"""
OSINT 模块测试 — 各层检测功能 + orchestrator 编排。

测试 WHOIS/DNS MX/制裁名单/技术栈/LinkedIn 的独立功能和集成。

**全部离线**（2026-10-13 起）：传输层统一在 `_osint_stays_offline` fixture 里
换成桩（WHOIS socket / DNS MX / 制裁下载 / 官网抓取），断言打的是**解析与判定
逻辑**，不再是"真实端点今天通不通"。此前这套测试会真下载 OFAC 名单
（实测单用例 108s）、真连 WHOIS 服务器，套件耗时在 2~7 分钟之间随网络抖动，
墙内跑还可能大面积 skip。需要"真实端点还活着"的验证由 `trade doctor` 承担
（它本来就做端到端验活）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade.osint import (
    check_sanctions,
    compute_risk_score,
    detect_tech_stack,
    domain_whois,
    generate_recommendations,
    linkedin_company_verify,
    verify_corporate_email,
)

# ── 离线传输桩 ──────────────────────────────────────────────────────────────

# 一份真实形态的 WHOIS 响应（Verisign .com 格式），供解析逻辑用
_FAKE_WHOIS_COM = """\
   Domain Name: EXAMPLE.COM
   Registry Domain ID: 2336799_DOMAIN_COM-VRSN
   Registrar WHOIS Server: whois.iana.org
   Registrar: RESERVED-Internet Assigned Numbers Authority
   Creation Date: 1995-08-14T04:00:00Z
   Registry Expiry Date: 2026-08-13T04:00:00Z
   Name Server: A.IANA-SERVERS.NET
   Name Server: B.IANA-SERVERS.NET
   Domain Status: clientDeleteProhibited
"""

# 一份含明显技术栈特征页面的 HTML（Shopify 免费建站 + 可用作企业级判断的对照）
_FAKE_SITE_HTML = (
    "<html><head><title>Demo Shop</title>"
    '<script src="https://cdn.shopify.com/s/files/1/xxx.js"></script>'
    "</head><body>hello</body></html>"
)


class _FakeHTTPResponse:
    """urllib.urlopen 的最小替身（headers.get + read + 上下文管理）。"""

    def __init__(self, body: str, server: str = "nginx"):
        self._body = body.encode("utf-8")
        self.headers = {"Server": server}

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _osint_stays_offline(monkeypatch):
    """把 OSINT 的四个传输层统一换成桩 —— 整套测试不打真网络。

    - WHOIS socket → 返回一份真实形态的响应文本（考解析，不考网络）
    - DNS MX 查询 → 固定返回"有 MX"（考企业邮箱判定，不考 DNS）
    - 制裁名单下载 → 拦掉下载，走内置 fallback 名单（考匹配与降级披露）
    - 官网抓取（公司名解析）→ 未显式注入 fetcher 时返回 None

    被拦的都是**传输**；各层的解析/判定/评分逻辑仍然是真代码。
    """
    import trade.osint.email_verify as _email
    import trade.osint.orchestrator as _orch
    import trade.osint.sanctions.loader as _loader
    import trade.osint.whois as _whois
    from trade import email_intel as _intel

    monkeypatch.setattr(_whois, "_query_whois_server", lambda domain, server, port=43, timeout=10: _FAKE_WHOIS_COM)
    monkeypatch.setattr(_email, "_query_mx_records", lambda domain: (["mx1.example.com"], True, None))
    monkeypatch.setattr(_loader, "http_get", lambda url, timeout=30: None)  # 触发内置 fallback
    # Layer 1 邮箱注册检测走 holehe 子进程（真探测 120+ 站点，一个 orchestrator 用例 8~10s）
    monkeypatch.setattr(_intel, "email_background_check", _fake_email_background_check)

    # 进程级内存缓存/健康度放的是上一次（可能联网）加载的结果 → 清掉，保证走桩路径
    _loader._sanctions_cache.clear()
    _loader._sanctions_meta.clear()

    real_resolve = _orch._resolve_entity_name

    def _resolve(domain, **kw):
        # 显式注入 fetcher 的测试（TestEntityNameResolution）拿到真实实现
        if "fetcher" in kw:
            return real_resolve(domain, **kw)
        return None

    monkeypatch.setattr(_orch, "_resolve_entity_name", _resolve)


def _fake_email_background_check(email: str) -> dict:
    """email_intel.email_background_check 的桩（结构照真实返回，见其模块 docstring）。"""
    return {
        "email": email,
        "checked_count": 3,
        "found_count": 1,
        "found_sites_count": 1,
        "rate_limited_count": 0,
        "results": [
            {
                "site": "github.com",
                "site_display": "GitHub",
                "exists": True,
                "rate_limited": False,
                "email_recovery": None,
                "phone_number": None,
                "profile_url": "https://github.com/demo",
                "created_date": None,
                "others": {},
            }
        ],
        "social_profiles": {"github": "https://github.com/demo"},
        "error": None,
    }

# ── Layer 2: WHOIS ──────────────────────────────────────────────────────────


class TestWHOIS:
    """测试 WHOIS 域名查询。"""

    def test_known_domain_example_com(self):
        """example.com 的 WHOIS 响应应被解析为「已注册」（传输层用桩，见文件顶部）。"""
        result = domain_whois("example.com")
        assert result.get("error") is None, f"解析桩数据不应报错: {result.get('error')}"
        assert result["registered"] is True
        assert result["domain"] == "example.com"
        # 桩里带了 Creation Date → 年龄分类应被算出来（考解析链，不只考"有返回"）
        assert result["days_old"] is not None and result["days_old"] > 3650
        assert result["age_category"] == "old"

    def test_www_prefix_stripped(self):
        """www. 前缀应被自动去除。"""
        result = domain_whois("www.example.com")
        assert result["domain"] == "example.com"

    def test_https_prefix_stripped(self):
        """https:// 前缀应被自动去除。"""
        result = domain_whois("https://example.com")
        assert result["domain"] == "example.com"

    def test_invalid_domain(self):
        """无效域名返回错误。"""
        result = domain_whois("not-a-domain")
        assert result["registered"] is False
        assert result.get("error") is not None

    def test_empty_string(self):
        """空字符串返回错误。"""
        result = domain_whois("")
        assert result["registered"] is False

    def test_result_has_all_fields(self):
        """返回结果应包含所有定义字段。"""
        result = domain_whois("example.com")
        expected_fields = {
            "domain", "registered", "registrar", "creation_date",
            "expiry_date", "days_old", "age_category", "dns_servers",
            "registrant_name", "whois_server", "status", "error",
        }
        assert expected_fields.issubset(result.keys()), \
            f"Missing fields: {expected_fields - result.keys()}"

    def test_google_com_too(self):
        """google.com 应返回已注册。"""
        result = domain_whois("google.com")
        assert result["registered"] is True


# ── Layer 3: Corporate Email Verification ───────────────────────────────────


class TestEmailVerification:
    """测试企业邮箱验证。"""

    def test_personal_email_gmail(self):
        """@gmail.com 应被识别为个人邮箱。"""
        result = verify_corporate_email("user@gmail.com")
        assert result["is_personal"] is True
        assert result["is_corporate"] is False
        assert result["risk_flag"] is True
        assert "个人邮箱" in str(result["risk_flags"])

    def test_personal_email_qq(self):
        """@qq.com 应被识别为个人邮箱。"""
        result = verify_corporate_email("12345@qq.com")
        assert result["is_personal"] is True
        assert result["risk_flag"] is True

    def test_corporate_email_example(self):
        """企业域名邮箱应识别为企业邮箱。"""
        result = verify_corporate_email("john@example.com")
        assert result["is_personal"] is False
        assert result["is_corporate"] is True

    def test_domain_matching(self):
        """提供 website 时应验证域名一致性。"""
        result = verify_corporate_email("john@example.com", website="https://example.com")
        assert result["domain_match"] is True

    def test_domain_mismatch(self):
        """邮箱域名与网站不一致时应标记。"""
        result = verify_corporate_email("john@other.com", website="https://example.com")
        assert result["domain_match"] is False

    def test_invalid_email_format(self):
        """无效邮箱格式返回错误提示。"""
        result = verify_corporate_email("not-an-email")
        assert result["suggestion"] == "邮箱格式无效"

    def test_mx_records_attempted(self):
        """企业邮箱应尝试查询 MX 记录。DNS 查询可能因网络失败。"""
        result = verify_corporate_email("admin@google.com")
        # 传输层桩固定返回"有 MX" → 断言判定结果（而不是"有没有返回"）
        assert result["mx_found"] is True
        assert result["mx_servers"] == ["mx1.example.com"]

    def test_result_has_all_fields(self):
        """返回结果应包含所有定义字段。"""
        result = verify_corporate_email("test@company.com")
        expected_fields = {
            "email", "domain", "is_personal", "is_corporate",
            "risk_flag", "domain_match", "mx_found", "mx_servers",
            "risk_flags", "suggestion",
        }
        assert expected_fields.issubset(result.keys())


# ── Layer 4: Sanctions ──────────────────────────────────────────────────────


class TestSanctions:
    """测试制裁名单筛查。"""

    def test_clean_company(self):
        """普通公司名不应命中制裁名单。"""
        result = check_sanctions("ACME Corporation Ltd")
        assert result["is_sanctioned"] is False
        assert result["risk_level"] == "none"

    def test_known_sanctioned_entity(self):
        """已知制裁实体应被精确匹配。"""
        # AL-SHABAAB 在 UN fallback 列表中
        result = check_sanctions("AL-SHABAAB")
        assert result["is_sanctioned"] is True
        assert result["risk_level"] == "high"

    def test_result_has_all_fields(self):
        """返回结果应包含所有定义字段。"""
        result = check_sanctions("test query")
        expected_fields = {
            "query", "country", "hits", "is_sanctioned",
            "risk_level", "suggestion",
        }
        assert expected_fields.issubset(result.keys())

    def test_country_filter(self):
        """提供 country 参数应影响结果。"""
        result = check_sanctions("ACME", country="US")
        assert result["country"] == "US"


# ── Layer 5: Tech Stack ─────────────────────────────────────────────────────


class TestTechStack:
    """测试技术栈检测。"""

    def test_detect_known_site(self):
        """从响应 HTML 里检出技术栈（注入 opener，不打真网络）。

        断言从原来的「>= 0 个技术」（等于没断言）升级为：真的从 HTML 里认出
        Shopify、判定为免费建站平台 —— 这才是这个函数存在的意义。
        """
        result = detect_tech_stack(
            "https://demo-shop.example.com",
            opener=lambda req, timeout=15: _FakeHTTPResponse(_FAKE_SITE_HTML),
        )
        assert result["error"] is None
        assert result["ssl_valid"] is True
        assert "Shopify" in result["technologies"]
        assert result["is_free_platform"] is True
        assert result["server"] == "nginx"

    def test_http_error_is_reported_not_raised(self):
        """取页面失败 → error 字段有值、不抛异常（抓不到 ≠ 网站可疑）。"""
        def _boom(req, timeout=15):
            raise OSError("connection refused")

        result = detect_tech_stack("https://down.example.com", opener=_boom)
        assert result["error"] is not None
        assert result["is_enterprise"] is False  # 抓不到时不得给"企业级"加分

    def test_auto_https_prefix(self):
        """省略协议时自动补全 https://。"""
        result = detect_tech_stack(
            "example.com", opener=lambda req, timeout=15: _FakeHTTPResponse("<html></html>")
        )
        assert result["url"].startswith("https://")

    def test_error_handling(self):
        """不存在的域名应有 error 字段（注入抛错的 opener，不真做 DNS）。"""
        def _nxdomain(req, timeout=15):
            raise OSError("Name or service not known")

        result = detect_tech_stack("https://this-domain-does-not-exist-12345.com", opener=_nxdomain)
        assert "error" in result

    def test_result_has_all_fields(self):
        """返回结果应包含所有定义字段。"""
        result = detect_tech_stack("https://example.com")
        expected_fields = {
            "url", "technologies", "platforms", "is_free_platform",
            "is_enterprise", "ssl_valid", "server", "error",
        }
        assert expected_fields.issubset(result.keys())


# ── Layer 6: LinkedIn ───────────────────────────────────────────────────────


class TestLinkedInVerify:
    """测试 LinkedIn 公司页验证（browser_navigate 指令生成）。"""

    def test_returns_browser_navigate_steps(self):
        """不发起 HTTP 请求，只生成 browser_navigate 指令。"""
        result = linkedin_company_verify("acme.com", "ACME Corp")
        assert result["method"] == "browser_navigate"
        assert result["domain"] == "acme.com"
        assert result["company_name"] == "ACME Corp"
        assert len(result["steps"]) >= 2
        assert result["steps"][0]["action"] == "navigate"
        assert "linkedin.com" in result["steps"][0]["url"]
        assert "summary_instruction" in result

    def test_domain_cleanup(self):
        """域名清理：去掉协议和路径。"""
        result = linkedin_company_verify("https://www.example.com/path", "Test")
        assert result["domain"] == "example.com"

    def test_has_all_fields(self):
        """返回结果包含所有定义字段。"""
        result = linkedin_company_verify("example.com", "Example Corp")
        expected_fields = {"method", "domain", "company_name", "steps", "summary_instruction"}
        assert expected_fields.issubset(result.keys())


# ── Scoring ─────────────────────────────────────────────────────────────────


class TestRiskScoring:
    """测试风险评分计算。"""

    def test_no_flags_max_score(self):
        """无红旗 → 满分 100 / low risk。"""
        score, rating = compute_risk_score([])
        assert score == 100
        assert rating == "low"

    def test_personal_email_penalty(self):
        """个人邮箱 → 扣 30 分。"""
        score, rating = compute_risk_score(["personal_email_domain"])
        assert score == 70

    def test_sanctioned_kills_score(self):
        """制裁命中 → 扣 50 分。"""
        score, rating = compute_risk_score(["sanctioned"])
        assert score == 50
        assert rating == "medium"

    def test_multiple_flags_high_risk(self):
        """多个红旗 → high risk。"""
        score, rating = compute_risk_score([
            "personal_email_domain",  # -30
            "domain_age_new",         # -20
            "free_platform",          # -15
            "no_linkedin",            # -10
        ])
        assert score == 25
        assert rating == "high"

    def test_score_clamped_zero(self):
        """分数不低于 0。"""
        score, rating = compute_risk_score([
            "sanctioned", "sanctioned", "sanctioned", "personal_email_domain",
        ])
        assert score >= 0

    def test_score_clamped_100(self):
        """分数不高于 100。"""
        score, rating = compute_risk_score([])
        assert score <= 100


class TestRecommendations:
    """测试建议生成。"""

    def test_generates_recommendations(self):
        """应生成多条建议。"""
        report = {
            "layers": {
                "email_verification": {
                    "is_corporate": True, "domain": "example.com", "risk_flag": False,
                },
                "domain_intel": {
                    "age_category": "old", "days_old": 2000,
                },
                "tech_stack": {
                    "is_enterprise": True, "is_free_platform": False,
                },
                "sanctions": {"is_sanctioned": False, "hits": []},
                "linkedin": {"linkedin_found": True, "employee_count": "1000+"},
            },
        }
        recs = generate_recommendations(report)
        assert len(recs) >= 3

    def test_flag_recommendations(self):
        """红旗报告中应包含警告建议。"""
        report = {
            "layers": {
                "email_verification": {
                    "risk_flag": True, "domain": "gmail.com",
                },
                "domain_intel": {
                    "age_category": "new", "days_old": 30,
                },
                "tech_stack": None,
                "sanctions": {"is_sanctioned": False, "hits": []},
                "linkedin": {"linkedin_found": False},
            },
        }
        recs = generate_recommendations(report)
        warnings = [r for r in recs if r.startswith("⚠️")]
        assert len(warnings) >= 1


# ── Orchestrator (requires async) ───────────────────────────────────────────


class TestOrchestrator:
    """测试 osint_full_check 编排器。"""

    @pytest.mark.asyncio
    async def test_email_full_check(self):
        """对邮箱执行完整尽职调查。"""
        from trade.osint import osint_full_check
        result = await osint_full_check(
            "test@example.com",
            include_sanctions=True,
            include_tech_stack=False,
            include_linkedin=False,
        )
        assert result["target"] == "test@example.com"
        assert result["target_type"] == "email"
        assert "layers" in result
        assert "domain_intel" in result["layers"]
        assert "email_verification" in result["layers"]
        assert "recommendations" in result

    @pytest.mark.asyncio
    async def test_domain_full_check(self):
        """对域名执行完整尽职调查。"""
        from trade.osint import osint_full_check
        result = await osint_full_check(
            "example.com",
            include_sanctions=False,
            include_tech_stack=False,
            include_linkedin=False,
        )
        assert result["target_type"] == "domain"
        assert result["layers"]["email_registration"] is None

    @pytest.mark.asyncio
    async def test_company_name_full_check(self):
        """对公司名执行完整尽职调查。"""
        from trade.osint import osint_full_check
        result = await osint_full_check(
            "Microsoft Corporation",
            include_sanctions=True,
            include_tech_stack=False,
            include_linkedin=False,
        )
        assert result["target_type"] == "company"
        assert "sanctions" in result["layers"]

    @pytest.mark.asyncio
    async def test_risk_score_computed(self):
        """orchestrator 应计算综合风险评分。"""
        from trade.osint import osint_full_check
        result = await osint_full_check(
            "test@example.com",
            include_sanctions=True,
            include_tech_stack=False,
            include_linkedin=False,
        )
        assert "overall_score" in result
        assert "overall_rating" in result
        assert result["overall_score"] >= 0
        assert result["overall_score"] <= 100


# ── Target Type Detection ───────────────────────────────────────────────────


class TestTargetDetection:
    """测试 target 类型自动识别。"""

    def test_email_detection(self):
        """含 @ 的应识别为 email。"""
        from trade.osint.orchestrator import _detect_target_type
        assert _detect_target_type("john@example.com") == "email"

    def test_url_detection(self):
        """含 https:// 的应识别为 url。"""
        from trade.osint.orchestrator import _detect_target_type
        assert _detect_target_type("https://example.com") == "url"

    def test_domain_detection(self):
        """example.com 应识别为 domain。"""
        from trade.osint.orchestrator import _detect_target_type
        assert _detect_target_type("example.com") == "domain"

    def test_company_detection(self):
        """纯公司名应识别为 company。"""
        from trade.osint.orchestrator import _detect_target_type
        assert _detect_target_type("Microsoft Corp") == "company"


# ── SSRF 防护测试 ───────────────────────────────────────────────────────


class TestSSRFProtection:
    """测试 _is_private_host 和 http_get 的 SSRF 防护。"""

    def test_private_ip_blocked(self):
        """127.0.0.1 应被拦截。"""
        from trade.osint.constants import _is_private_host
        assert _is_private_host("127.0.0.1") is True

    def test_private_ip_192(self):
        """192.168.x.x 应被拦截。"""
        from trade.osint.constants import _is_private_host
        assert _is_private_host("192.168.1.1") is True

    def test_private_ip_10(self):
        """10.x.x.x 应被拦截。"""
        from trade.osint.constants import _is_private_host
        assert _is_private_host("10.0.0.1") is True

    def test_private_ip_172(self):
        """172.16.x.x 应被拦截。"""
        from trade.osint.constants import _is_private_host
        assert _is_private_host("172.16.0.1") is True

    def test_link_local_blocked(self):
        """169.254.x.x 应被拦截。"""
        from trade.osint.constants import _is_private_host
        assert _is_private_host("169.254.1.1") is True

    def test_multicast_blocked(self):
        """224.x.x.x 应被拦截。"""
        from trade.osint.constants import _is_private_host
        assert _is_private_host("224.0.0.1") is True

    def test_public_ip_allowed(self):
        """8.8.8.8 公网 IP 应放行。"""
        from trade.osint.constants import _is_private_host
        assert _is_private_host("8.8.8.8") is False

    def test_public_domain_allowed(self):
        """example.com 公网域名应放行。"""
        from trade.osint.constants import _is_private_host
        assert _is_private_host("example.com") is False

    def test_ofac_url_allowed(self):
        """制裁名单 URL（ofac.treasury.gov）应放行。"""
        from trade.osint.constants import _is_private_host
        assert _is_private_host("ofac.treasury.gov") is False

    def test_http_get_blocks_private(self):
        """http_get 访问内网地址应返回 None。"""
        from trade.osint.constants import http_get
        result = http_get("http://127.0.0.1/", timeout=3)
        assert result is None

    def test_http_get_blocks_localhost(self):
        """http_get 访问 localhost 应返回 None。"""
        from trade.osint.constants import http_get
        result = http_get("http://localhost/", timeout=3)
        assert result is None

    def test_tech_stack_reuses_shared_ssrf(self):
        """tech_stack 模块应复用 constants._is_private_host 而非重复实现。"""
        import trade.osint.tech_stack as ts
        # 不应有自己的 _BLOCKED_RANGES（说明复用了 constants 的共享实现）
        assert not hasattr(ts, "_BLOCKED_RANGES"), \
            "tech_stack should use _is_private_host from constants, not its own _BLOCKED_RANGES"
        # 应有 _is_private_host（从 constants 导入的共享函数）
        assert hasattr(ts, "_is_private_host"), \
            "tech_stack should import _is_private_host from constants"


class TestEntityNameResolution:
    """域名 → 公司名解析（制裁筛查的输入质量）。

    这一步会抓官网首页，**测试必须注入 fetcher**，不打真网络
    （曾因在 async 体里同步调用而拖慢整套测试，见 orchestrator 的 executor 注释）。
    """

    def test_title_main_part_is_used(self):
        from trade.osint.orchestrator import _resolve_entity_name

        html = "<html><head><title>ACME Corp | Official Site</title></head></html>"
        assert _resolve_entity_name("acme.com", fetcher=lambda url, timeout=15: html) == "ACME Corp"

    def test_too_short_title_is_rejected(self):
        from trade.osint.orchestrator import _resolve_entity_name

        assert _resolve_entity_name("x.com", fetcher=lambda url, timeout=15: "<title>ab</title>") is None

    def test_empty_response_or_no_domain_yields_none(self):
        from trade.osint.orchestrator import _resolve_entity_name

        empty = lambda url, timeout=15: ""  # noqa: E731 — 测试内联桩，保持简短
        assert _resolve_entity_name("acme.com", fetcher=empty) is None
        # 无域名时必须在发请求**之前**返回 —— 注入会抛的桩来证明它没被调用
        def _must_not_call(url, timeout=15):
            raise AssertionError("domain 为空却发了请求")

        assert _resolve_entity_name(None, fetcher=_must_not_call) is None
        assert _resolve_entity_name("", fetcher=_must_not_call) is None

    def test_fetcher_exception_is_swallowed(self):
        """取页面失败不能让整份报告崩 —— 回退 None。"""
        from trade.osint.orchestrator import _resolve_entity_name

        def _boom(url, timeout=15):
            raise OSError("网络炸了")

        assert _resolve_entity_name("acme.com", fetcher=_boom) is None


class TestIDNTargetDetection:
    """IDN（中文域名等）必须识别为 domain 而不是公司名（优化路线 P0-4）。"""

    def test_chinese_idn_is_domain(self):
        from trade.osint.orchestrator import _detect_target_type

        assert _detect_target_type("例子.中国") == "domain"

    def test_ascii_behaviour_unchanged(self):
        from trade.osint.orchestrator import _detect_target_type

        assert _detect_target_type("example.com") == "domain"
        assert _detect_target_type("北京科技有限公司") == "company"
        assert _detect_target_type("john@example.com") == "email"


# 注：离线桩统一在文件顶部的 `_osint_stays_offline` fixture 里定义
# （模块级 autouse，覆盖 WHOIS / DNS / 制裁下载 / 官网抓取四个传输层）。
