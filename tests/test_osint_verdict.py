"""P0-2 评分 fail-closed：关键层没查成时不再输出「low / 100」。

工单 2026-11-21 的验收场景：tensorust.com 的「WHOIS 失败 + 制裁降级」
下，结论不能是 low。这里的测试全部离线：
  - assess_verification 的层状态判定（纯函数）
  - compute_verdict 的 fail-closed 汇总
  - orchestrator 端到端（传输层打桩）
  - CLI 的「—（未完成核验）」渲染
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade.osint import cli  # noqa: E402
from trade.osint.scoring import (  # noqa: E402
    assess_verification,
    compute_risk_score,
    compute_verdict,
    generate_recommendations,
)


@pytest.fixture(autouse=True)
def _no_public_sources(monkeypatch):
    """本文件只考 6 层与评分；公开来源走真实网络会拖慢且不稳定。"""
    monkeypatch.setenv("TRADE_OSINT_SOURCES", "off")


def _degraded_sanctions(total: int = 2) -> dict:
    """制裁层：名单从未成功下载（coverage.degraded = True）。"""
    return {
        "is_sanctioned": False,
        "risk_level": "none",
        "hits": [],
        "coverage": {"degraded": True, "total_entries": total},
    }


def _healthy_sanctions(total: int = 30000) -> dict:
    """制裁层：正常加载了真名单。"""
    return {
        "is_sanctioned": False,
        "risk_level": "none",
        "hits": [],
        "coverage": {"degraded": False, "total_entries": total},
    }


def _whois_ok() -> dict:
    return {
        "domain": "acme.com",
        "registered": True,
        "days_old": 4000,
        "age_category": "old",
        "error": None,
    }


# ── 层状态判定 ──────────────────────────────────────────────────────────────


class TestAssessVerification:
    def test_degraded_sanctions_is_blocking(self):
        out = assess_verification(
            {"sanctions": _degraded_sanctions(), "domain_intel": _whois_ok()},
            has_domain=True,
        )
        blocking = {u["layer"] for u in out if u["required"]}
        assert blocking == {"sanctions"}

    def test_whois_error_is_blocking(self):
        out = assess_verification(
            {"sanctions": _healthy_sanctions(),
             "domain_intel": {"error": "WHOIS 服务器无响应"}},
            has_domain=True,
        )
        blocking = {u["layer"] for u in out if u["required"]}
        assert blocking == {"domain_intel"}
        assert "WHOIS 服务器无响应" in next(
            u["reason"] for u in out if u["layer"] == "domain_intel"
        )

    def test_healthy_layers_produce_no_blocking(self):
        out = assess_verification(
            {"sanctions": _healthy_sanctions(), "domain_intel": _whois_ok()},
            has_domain=True,
        )
        assert [u for u in out if u["required"]] == []

    def test_disabled_sanctions_is_disclosed_not_blocking(self):
        out = assess_verification(
            {"sanctions": None, "domain_intel": _whois_ok()},
            has_domain=True,
            sanctions_requested=False,
        )
        entry = next(u for u in out if u["layer"] == "sanctions")
        assert entry["status"] == "skipped"
        assert entry["required"] is False
        assert [u for u in out if u["required"]] == []

    def test_company_without_domain_is_not_applicable(self):
        out = assess_verification(
            {"sanctions": _healthy_sanctions(),
             "domain_intel": {"skipped": True, "reason": "no domain"}},
            has_domain=False,
        )
        entry = next(u for u in out if u["layer"] == "domain_intel")
        assert entry["status"] == "not_applicable"
        assert entry["required"] is False

    def test_non_key_layer_errors_are_not_blocking(self):
        """holehe / 技术栈失败只披露，不推翻结论。"""
        out = assess_verification(
            {
                "sanctions": _healthy_sanctions(),
                "domain_intel": _whois_ok(),
                "email_registration": {"error": "holehe not installed"},
                "tech_stack": {"error": "抓取失败"},
            },
            has_domain=True,
        )
        assert [u for u in out if u["required"]] == []
        assert {u["layer"] for u in out} == {"email_registration", "tech_stack"}

    def test_missing_coverage_is_treated_as_degraded(self):
        """旧版/外部构造的报告没有 coverage —— 保守按降级处理。"""
        out = assess_verification(
            {"sanctions": {"is_sanctioned": False, "hits": []},
             "domain_intel": _whois_ok()},
            has_domain=True,
        )
        assert any(u["layer"] == "sanctions" and u["required"] for u in out)


# ── 结论汇总 ────────────────────────────────────────────────────────────────


class TestComputeVerdict:
    def test_incomplete_when_key_layer_missing(self):
        unverified = assess_verification(
            {"sanctions": _degraded_sanctions(2),
             "domain_intel": {"error": "超时"}},
            has_domain=True,
        )
        score, rating, provisional = compute_verdict([], unverified)
        assert rating == "incomplete"
        assert score is None, "未核验时不得输出数字结论"
        assert provisional == 100, "诊断分数仍保留原计算值"

    def test_clean_report_keeps_normal_rating(self):
        unverified = assess_verification(
            {"sanctions": _healthy_sanctions(), "domain_intel": _whois_ok()},
            has_domain=True,
        )
        score, rating, provisional = compute_verdict([], unverified)
        assert (score, rating, provisional) == (100, "low", 100)

    def test_confirmed_sanctions_hit_overrides_degradation(self):
        """命中制裁是确定结论，不能被「未完成」掩盖。"""
        unverified = assess_verification(
            {"sanctions": _degraded_sanctions(), "domain_intel": _whois_ok()},
            has_domain=True,
        )
        score, rating, _ = compute_verdict(["sanctioned"], unverified)
        assert rating == "high"
        assert score is not None

    def test_disabled_sanctions_does_not_block_rating(self):
        unverified = assess_verification(
            {"sanctions": None, "domain_intel": _whois_ok()},
            has_domain=True,
            sanctions_requested=False,
        )
        score, rating, _ = compute_verdict([], unverified)
        assert (score, rating) == (100, "low")


# ── 建议文案 ────────────────────────────────────────────────────────────────


class TestRecommendationsDisclose:
    def test_blocking_layers_named_in_verdict_sentence(self):
        layers = {
            "sanctions": _degraded_sanctions(),
            "domain_intel": {"error": "WHOIS 服务器无响应"},
        }
        report = {
            "layers": layers,
            "flags": [],
            "unverified": assess_verification(layers, has_domain=True),
        }
        recs = generate_recommendations(report)
        head = recs[0]
        assert "未完成核验" in head
        assert "制裁名单筛查" in head and "WHOIS 域名情报" in head
        assert "不代表低风险" in head

    def test_disabled_channel_marked_not_a_clean_bill(self):
        report = {
            "layers": {"sanctions": None, "domain_intel": _whois_ok()},
            "flags": [],
            "unverified": assess_verification(
                {"sanctions": None, "domain_intel": _whois_ok()},
                has_domain=True,
                sanctions_requested=False,
            ),
        }
        text = "\n".join(generate_recommendations(report))
        assert "本次未查" in text and "无风险" in text


# ── 端到端：tensorust.com 场景（工单验收）─────────────────────────────────


class TestOrchestratorFailClosed:
    @pytest.mark.asyncio
    async def test_whois_failure_plus_degraded_sanctions_is_not_low(self, monkeypatch):
        """WHOIS 失败 + 制裁降级 → incomplete，绝不是 low。"""
        import trade.osint.orchestrator as orch

        monkeypatch.setattr(
            orch, "domain_whois",
            lambda domain: {"domain": domain, "registered": False,
                            "error": "WHOIS 服务器无响应"},
        )
        monkeypatch.setattr(
            orch, "check_sanctions",
            lambda name, country=None: _degraded_sanctions(2),
        )
        monkeypatch.setattr(
            orch, "detect_tech_stack",
            lambda url: {"error": "抓取失败", "technologies": []},
        )
        monkeypatch.setattr(orch, "_resolve_entity_name", lambda domain, **kw: None)

        report = await orch.osint_full_check(
            "tensorust.com",
            include_sanctions=True,
            include_tech_stack=True,
            include_linkedin=False,
        )

        assert report["overall_rating"] == "incomplete"
        assert report["overall_score"] is None
        blocking = {u["layer"] for u in report["unverified"] if u["required"]}
        assert blocking == {"sanctions", "domain_intel"}
        assert any("未完成核验" in r for r in report["recommendations"])

    @pytest.mark.asyncio
    async def test_healthy_run_still_scores(self, monkeypatch):
        import trade.osint.orchestrator as orch

        monkeypatch.setattr(orch, "domain_whois", lambda domain: _whois_ok())
        monkeypatch.setattr(
            orch, "check_sanctions",
            lambda name, country=None: _healthy_sanctions(),
        )
        monkeypatch.setattr(
            orch, "detect_tech_stack",
            lambda url: {"technologies": ["nginx"], "is_free_platform": False,
                         "is_enterprise": True, "error": None},
        )
        monkeypatch.setattr(orch, "_resolve_entity_name", lambda domain, **kw: None)

        report = await orch.osint_full_check(
            "acme.com",
            include_sanctions=True,
            include_tech_stack=True,
            include_linkedin=False,
        )

        assert report["overall_rating"] == "low"
        assert report["overall_score"] == 100
        assert report["unverified"] == []

    @pytest.mark.asyncio
    async def test_sanctioned_hit_survives_degraded_source(self, monkeypatch):
        """命中制裁时即使 WHOIS 也失败，结论仍是 high 而不是 incomplete。"""
        import trade.osint.orchestrator as orch

        monkeypatch.setattr(
            orch, "domain_whois",
            lambda domain: {"domain": domain, "registered": False, "error": "超时"},
        )
        monkeypatch.setattr(
            orch, "check_sanctions",
            lambda name, country=None: {
                "is_sanctioned": True, "risk_level": "high", "hits": [],
                "coverage": {"degraded": True, "total_entries": 2},
            },
        )
        monkeypatch.setattr(orch, "_resolve_entity_name", lambda domain, **kw: None)

        report = await orch.osint_full_check(
            "acme.com", include_tech_stack=False, include_linkedin=False,
        )

        assert report["overall_rating"] == "high"
        assert report["overall_score"] is not None


# ── CLI 渲染 ────────────────────────────────────────────────────────────────


class TestCliShowsIncomplete:
    def _report(self, **overrides) -> dict:
        report = {
            "target": "tensorust.com",
            "target_type": "domain",
            "overall_score": None,
            "overall_rating": "incomplete",
            "provisional_score": 100,
            "flags": [],
            "layers": {"sanctions": _degraded_sanctions(),
                       "domain_intel": {"error": "WHOIS 服务器无响应"}},
            "unverified": assess_verification(
                {"sanctions": _degraded_sanctions(),
                 "domain_intel": {"error": "WHOIS 服务器无响应"}},
                has_domain=True,
            ),
            "recommendations": [],
        }
        report.update(overrides)
        return report

    def test_score_rendered_as_dash(self):
        text = cli.format_report(self._report())
        assert "—（未完成核验）" in text
        assert "/100" not in text.split("\n")[1]

    def test_unverified_layers_listed_in_header(self):
        text = cli.format_report(self._report())
        head = text.split("建议：")[0]
        assert "未核验：制裁名单筛查" in head
        assert "未核验：WHOIS 域名情报" in head


# 保持对纯函数原有语义的守卫：compute_risk_score 本身不变
def test_compute_risk_score_unchanged():
    assert compute_risk_score([]) == (100, "low")
    assert compute_risk_score(["sanctioned"]) == (50, "medium")


# ── 审计 P0-B：无核验时不给 low / 100 ─────────────────────────────────────


class TestLimitedRating:
    def test_person_without_domain_or_hits_is_limited(self):
        score, rating, provisional = compute_verdict(
            [], [], target_type="person", has_domain=False, public_hits=0,
        )
        assert score is None, "仅完成制裁筛查时不得输出数字结论"
        assert rating == "limited"
        assert provisional == 100

    def test_company_without_domain_or_hits_is_limited(self):
        _, rating, _ = compute_verdict(
            [], [], target_type="company", has_domain=False, public_hits=0,
        )
        assert rating == "limited"

    def test_public_hit_lifts_limited(self):
        score, rating, _ = compute_verdict(
            [], [], target_type="company", has_domain=False, public_hits=1,
        )
        assert (score, rating) == (100, "low")

    def test_domain_target_keeps_normal_scoring(self):
        score, rating, _ = compute_verdict(
            [], [], target_type="domain", has_domain=True, public_hits=0,
        )
        assert (score, rating) == (100, "low")

    def test_sanctioned_hit_beats_limited(self):
        score, rating, _ = compute_verdict(
            ["sanctioned"], [], target_type="person", has_domain=False, public_hits=0,
        )
        assert (score, rating) == (50, "high")

    def test_incomplete_takes_precedence(self):
        score, rating, _ = compute_verdict(
            [], [{"layer": "sanctions", "required": True, "reason": "degraded"}],
            target_type="person", has_domain=False, public_hits=0,
        )
        assert (score, rating) == (None, "incomplete")


class TestOrchestratorLimited:
    @pytest.mark.asyncio
    async def test_person_without_domain_gets_limited(self, monkeypatch):
        """制裁库完整、人名无域名、公开来源零命中 → limited，不是 low/100。"""
        import trade.osint.orchestrator as orch

        monkeypatch.setattr(
            orch, "check_sanctions",
            lambda name, country=None: _healthy_sanctions(),
        )
        monkeypatch.setattr(orch, "_resolve_entity_name", lambda domain, **kw: None)
        monkeypatch.setattr(orch, "PUBLIC_SOURCES", [])

        report = await orch.osint_full_check(
            "person:Jane Doe", include_tech_stack=False, include_linkedin=False,
        )

        assert report["overall_rating"] == "limited"
        assert report["overall_score"] is None
        assert report["provisional_score"] == 100
        assert "仅完成制裁筛查" in report["rating_note"]
        assert any("仅完成制裁筛查" in r for r in report["recommendations"])


class TestCliShowsLimited:
    def test_limited_renders_dash_and_note(self):
        report = {
            "target": "Jane Doe",
            "target_type": "person",
            "overall_score": None,
            "overall_rating": "limited",
            "provisional_score": 100,
            "rating_note": "仅完成制裁筛查：目标没有可查询域名，公开来源也没有命中",
            "flags": [],
            "layers": {"sanctions": _healthy_sanctions(), "domain_intel": {"skipped": True}},
            "unverified": [],
            "recommendations": ["⚠️ 本次仅完成制裁筛查"],
        }
        text = cli.format_report(report)

        assert "—（仅完成制裁筛查）" in text
        assert "仅完成制裁筛查" in text
        assert "/100" not in text.split("\n")[1]


class TestRegistryOnlyHits:
    """W3：只有登记类命中不能给 low/100。"""

    def test_public_hit_counts_split(self):
        from trade.osint.orchestrator import _public_hit_counts

        substantive, registry = _public_hit_counts({
            "us_states": {"status": "hit"},
            "vies": {"status": "hit"},
            "github": {"status": "hit"},
            "rdap": {"status": "miss"},
        })
        assert (substantive, registry) == (1, 2)

    @pytest.mark.asyncio
    async def test_registry_only_company_is_limited(self, monkeypatch):
        import trade.osint.orchestrator as orch
        from trade.osint.sources.base import SourceResult

        class _Registry:
            NAME = "us_states"

            @staticmethod
            def run(ctx, fetch=None):  # noqa: ARG004
                return SourceResult(
                    "us_states", "hit",
                    facts=[{"text": "纽约州登记：Tensorust LLC，成立 2026-10-30"}],
                )

        monkeypatch.setattr(orch, "PUBLIC_SOURCES", (_Registry(),))
        monkeypatch.setattr(orch, "sources_enabled", lambda: True)
        monkeypatch.setattr(
            orch, "check_sanctions",
            lambda name, country=None: _healthy_sanctions(),
        )
        monkeypatch.setattr(orch, "_resolve_entity_name", lambda domain, **kw: None)

        report = await orch.osint_full_check(
            "company:Tensorust LLC", include_tech_stack=False, include_linkedin=False,
        )

        assert report["overall_rating"] == "limited"
        assert report["overall_score"] is None
        assert "2026-10-30" in report["rating_note"]
