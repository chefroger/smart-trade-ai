"""
M1 验收测试：公共平台域名与网址分类器、OSINT 跳过平台自有域名层、classify_urls 插件工具。

所有测试域名/公司名均为虚构夹具，不触网、不写库。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from trade.hermes_chat_memory_plugin.tools import handle_classify_urls
from trade.osint.domain_class import (
    classify_domain_or_url,
    classify_urls_batch,
)
from trade.osint.orchestrator import osint_full_check
from trade.osint.sources.base import SourceResult

# ==============================================================================
# 1. 域名与网址分类器：参数化正例与反例
# ==============================================================================


@pytest.mark.parametrize(
    ("raw", "expected_category"),
    [
        # reserved（复用 PR #27 is_reserved_domain）
        ("example.com", "reserved"),
        ("https://sub.example.sa/about", "reserved"),
        ("foo.test", "reserved"),
        ("demo.invalid", "reserved"),
        ("localhost", "reserved"),
        # free_mail
        ("foo@gmail.com", "free_mail"),
        ("buyer@qq.com", "free_mail"),
        ("sales@outlook.com", "free_mail"),
        # b2b_marketplace
        ("https://abc.en.alibaba.com/", "b2b_marketplace"),
        ("https://www.made-in-china.com/showroom/fictional-lamp/", "b2b_marketplace"),
        ("https://detail.1688.com/offer/123456.html", "b2b_marketplace"),
        # trade_data
        ("https://www.importyeti.com/company/fictional-buyer", "trade_data"),
        ("https://panjiva.com/Fictional-Corp/12345", "trade_data"),
        # directory
        ("https://www.yellowpages.com/ny/fictional-hardware", "directory"),
        ("https://www.crunchbase.com/organization/fictional-co", "directory"),
        # research_press
        ("https://www.statista.com/statistics/123/led-market", "research_press"),
        ("https://www.prnewswire.com/news-releases/fictional.html", "research_press"),
        # recruitment_page（独立招聘站 + 企业站招聘路径 + LinkedIn 招聘路径）
        ("https://www.indeed.com/cmp/Fictional", "recruitment_page"),
        ("https://fictional-buyer.de/careers", "recruitment_page"),
        ("https://www.linkedin.com/jobs/view/123456", "recruitment_page"),
        # social_content
        ("https://www.linkedin.com/posts/fictional-user_activity-123", "social_content"),
        ("https://www.instagram.com/reel/abc123/", "social_content"),
        ("https://www.reddit.com/r/lighting/comments/xyz", "social_content"),
        ("facebook.com", "social_content"),
        # site_builder_subdomain
        ("https://fictionalshop.wixsite.com/home", "site_builder_subdomain"),
        ("https://fictionalblog.blogspot.com/", "site_builder_subdomain"),
        ("https://fictional-store.myshopify.com/", "site_builder_subdomain"),
        # 反例：不可误判的真实独立域名 & LinkedIn 公司主页
        ("notalibaba.com", "normal"),
        ("https://www.linkedin.com/company/fictional-industrial-gmbh/", "normal"),
        ("myexample.sa", "normal"),
        ("sales@acme-tools.de", "normal"),
        ("acme-tools.de", "normal"),
    ],
)
def test_classify_domain_or_url_matrix(raw: str, expected_category: str):
    """覆盖全部 10 类标签的正例及易误判反例。"""
    res = classify_domain_or_url(raw)
    assert res["category"] == expected_category
    assert res["reason"]


def test_inferred_store_name_from_platform_urls():
    """平台店铺 URL 应准确推断出候选店铺名，忽略 www/en 等通用子域前缀。"""
    ali = classify_domain_or_url("https://abc.en.alibaba.com/")
    assert ali["category"] == "b2b_marketplace"
    assert ali["inferred_store_name"] == "abc"

    mic = classify_domain_or_url("https://www.made-in-china.com/showroom/fictional-led/")
    assert mic["category"] == "b2b_marketplace"
    assert mic["inferred_store_name"] == "fictional-led"

    shopify = classify_domain_or_url("https://nordic-lamps.myshopify.com/")
    assert shopify["category"] == "site_builder_subdomain"
    assert shopify["inferred_store_name"] == "nordic-lamps"


def test_corrupt_toml_falls_back_to_builtin_lists(tmp_path):
    """清单文件损坏时安全回退内置清单，不抛异常、不阻断背调。"""
    bad_toml = tmp_path / "broken.toml"
    bad_toml.write_text("[[[not valid toml ==", encoding="utf-8")

    res = classify_domain_or_url("foo@gmail.com", builtin_path=bad_toml, override_path=bad_toml)
    assert res["category"] == "free_mail"


def test_user_override_add_and_remove(tmp_path):
    """用户覆盖文件支持 [add] 追加与 [remove] 移除条目。"""
    override = tmp_path / "platform_domains.toml"
    override.write_text(
        '[add]\ndirectory = ["custom-yellow.fictional"]\n'
        '[remove]\nb2b_marketplace = ["kompass.com"]\n',
        encoding="utf-8",
    )

    assert classify_domain_or_url("https://custom-yellow.fictional/a", override_path=override)["category"] == "directory"
    assert classify_domain_or_url("https://www.kompass.com/c/x", override_path=override)["category"] == "normal"


# ==============================================================================
# 2. OSINT 编排：公共邮箱 & 平台店铺跳过自有域名层，独立域名回归正常
# ==============================================================================


def _clean_sanctions_stub(name: str) -> dict:
    """无命中的本地制裁筛查桩（覆盖率完整，非降级）。"""
    return {
        "hits": [],
        "is_sanctioned": False,
        "risk_level": "none",
        "coverage": {"degraded": False, "total_entries": 1000, "lists": {"ofac": 1000}},
        "suggestion": "未命中制裁名单",
    }


@pytest.mark.asyncio
async def test_osint_free_mail_skips_domain_layers_and_runs_email_verify():
    """foo@gmail.com：零 WHOIS/技术栈/RDAP/CT/Wayback/pDNS 请求，状态为 not_applicable，邮箱验证仍执行。"""
    whois_mock = MagicMock()
    tech_mock = MagicMock()
    verify_mock = MagicMock(return_value={
        "email": "foo@gmail.com",
        "domain": "gmail.com",
        "is_personal": True,
        "is_corporate": False,
        "mx_found": True,
        "risk_flags": ["使用个人邮箱域名"],
    })
    holehe_mock = MagicMock(return_value={"checked_count": 10, "found_count": 0, "results": []})
    called_sources: list[str] = []

    def _fake_public_run(module, ctx, fetcher):
        called_sources.append(module.NAME)
        return SourceResult(source=module.NAME, status="miss").to_dict()

    with (
        patch("trade.osint.orchestrator.domain_whois", whois_mock),
        patch("trade.osint.orchestrator.detect_tech_stack", tech_mock),
        patch("trade.osint.orchestrator.verify_corporate_email", verify_mock),
        patch("trade.osint.orchestrator.email_intel.email_background_check", holehe_mock),
        patch("trade.osint.orchestrator.check_sanctions", side_effect=_clean_sanctions_stub),
        patch("trade.osint.orchestrator._run_public_source", side_effect=_fake_public_run),
    ):
        report = await osint_full_check("foo@gmail.com")

    # 域名类层零调用
    whois_mock.assert_not_called()
    tech_mock.assert_not_called()
    for dom_src in ("rdap", "ct", "wayback", "pdns"):
        assert dom_src not in called_sources
        assert report["sources"][dom_src]["status"] == "not_applicable"
        assert "公共邮箱" in report["sources"][dom_src]["reason"]

    # 邮箱验证层与注册检测仍执行
    verify_mock.assert_called_once_with("foo@gmail.com")
    holehe_mock.assert_called_once_with("foo@gmail.com")

    # 层状态、首屏说明、评级（不可给绿色 low）
    assert report["layers"]["domain_intel"]["status"] == "not_applicable"
    assert "公共邮箱" in report["layers"]["domain_intel"]["reason"]
    assert report["layers"]["tech_stack"]["status"] == "not_applicable"
    assert "目标使用公共平台域名" in report["platform_domain_notice"]
    assert report["overall_rating"] == "limited"
    assert report["overall_score"] is None


@pytest.mark.asyncio
async def test_osint_marketplace_store_url_infers_store_name():
    """https://abc.en.alibaba.com/：跳过域名类层，推断店铺名 abc 并交给公司名类来源。"""
    whois_mock = MagicMock()
    tech_mock = MagicMock()
    seen_company_names: list[str | None] = []

    def _fake_public_run(module, ctx, fetcher):
        seen_company_names.append(ctx.company_name)
        return SourceResult(source=module.NAME, status="miss").to_dict()

    with (
        patch("trade.osint.orchestrator.domain_whois", whois_mock),
        patch("trade.osint.orchestrator.detect_tech_stack", tech_mock),
        patch("trade.osint.orchestrator.check_sanctions", side_effect=_clean_sanctions_stub),
        patch("trade.osint.orchestrator._run_public_source", side_effect=_fake_public_run),
    ):
        report = await osint_full_check("https://abc.en.alibaba.com/")

    whois_mock.assert_not_called()
    tech_mock.assert_not_called()
    assert report["layers"]["domain_intel"]["status"] == "not_applicable"
    assert report["sources"]["rdap"]["status"] == "not_applicable"
    assert report["inferred_store_name"] == "abc"
    assert "推断店铺名 abc（推断自店铺地址）" in report["inferred_store_note"]
    assert "abc" in seen_company_names
    assert report["overall_rating"] == "limited"


@pytest.mark.asyncio
async def test_osint_normal_corporate_domain_regression():
    """回归：sales@acme-tools.de 仍正常执行 WHOIS、技术栈与域名类公开来源。"""
    whois_mock = MagicMock(return_value={
        "domain": "acme-tools.de",
        "registered": True,
        "days_old": 2000,
        "age_category": "old",
        "error": None,
    })
    tech_mock = MagicMock(return_value={"technologies": ["nginx"], "is_free_platform": False})
    verify_mock = MagicMock(return_value={
        "email": "sales@acme-tools.de",
        "domain": "acme-tools.de",
        "is_personal": False,
        "is_corporate": True,
        "mx_found": True,
        "risk_flags": [],
    })
    holehe_mock = MagicMock(return_value={"checked_count": 10, "found_count": 1, "results": []})
    called_sources: list[str] = []

    def _fake_public_run(module, ctx, fetcher):
        called_sources.append(module.NAME)
        return SourceResult(source=module.NAME, status="miss").to_dict()

    with (
        patch("trade.osint.orchestrator.domain_whois", whois_mock),
        patch("trade.osint.orchestrator.detect_tech_stack", tech_mock),
        patch("trade.osint.orchestrator.verify_corporate_email", verify_mock),
        patch("trade.osint.orchestrator.email_intel.email_background_check", holehe_mock),
        patch("trade.osint.orchestrator.check_sanctions", side_effect=_clean_sanctions_stub),
        patch("trade.osint.orchestrator._run_public_source", side_effect=_fake_public_run),
    ):
        report = await osint_full_check("sales@acme-tools.de")

    whois_mock.assert_called_once_with("acme-tools.de")
    tech_mock.assert_called_once_with("https://acme-tools.de")
    assert "rdap" in called_sources
    assert "ct" in called_sources
    assert "platform_domain_notice" not in report
    assert report["overall_rating"] == "low"
    assert report["overall_score"] == 100


# ==============================================================================
# 3. classify_urls 插件工具：纯函数（无公司上下文可用）、不删除条目、区分用途
# ==============================================================================


def test_classify_urls_tool_customer_and_supplier_purposes():
    """10 个混合网址：找客户时平台/目录折叠进其他来源且总数不变；找供应商时平台店铺正常展示。"""
    mixed_urls = [
        "https://fictional-buyer-1.de",
        "https://fictional-buyer-2.co.uk",
        "https://www.linkedin.com/company/fictional-buyer-3/",
        "https://abc.en.alibaba.com/",
        "https://www.made-in-china.com/showroom/fictional-factory/",
        "https://www.yellowpages.com/ny/fictional-dir",
        "https://www.statista.com/statistics/123",
        "https://www.importyeti.com/company/fictional",
        "https://fictional-buyer-1.de/careers",
        "https://www.instagram.com/reel/fictional123/",
    ]

    # 纯函数：无公司上下文也能正常调用
    raw_customer = handle_classify_urls({"urls": mixed_urls, "purpose": "customer"})
    cust = json.loads(raw_customer)
    assert cust["total"] == 10
    assert len(cust["items"]) == 10
    assert cust["primary_count"] == 3
    assert cust["other_count"] == 7
    assert all(item["collapsed"] is True for item in cust["other_sources"])
    assert all(item["collapsed"] is False for item in cust["primary"])

    # 找供应商：2 个 B2B 平台店铺标为「平台店铺」并留在主表正常展示
    raw_supplier = handle_classify_urls({"urls": mixed_urls, "purpose": "supplier"})
    sup = json.loads(raw_supplier)
    assert sup["total"] == 10
    assert sup["primary_count"] == 5
    assert sup["other_count"] == 5
    shop_items = [it for it in sup["primary"] if it["category"] == "b2b_marketplace"]
    assert len(shop_items) == 2
    assert all(it["label"] == "平台店铺" for it in shop_items)


def test_classify_urls_batch_handles_invalid_purpose_gracefully():
    """非法 purpose 回退 customer，不抛异常。"""
    res = classify_urls_batch(["https://abc.en.alibaba.com/"], purpose="unknown")
    assert res["purpose"] == "customer"
    assert res["other_count"] == 1
