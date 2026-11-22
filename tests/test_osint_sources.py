"""P2-1 / P2-2：目标类型、公开来源（RDAP/CT/Wayback/GitHub）与 CLI 渲染。

夹具是真实响应的快照（tensorust.com / Mattbusel，2026-11-22 抓取）。
全部离线：来源通过注入的 fetcher 读取夹具。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade.osint import cli  # noqa: E402
from trade.osint.orchestrator import (  # noqa: E402
    _detect_target_type,
    _resolve_entity_name,
    _split_type_prefix,
    osint_full_check,
)
from trade.osint.sources import (  # noqa: E402
    TargetContext,
    ct,
    edgar,
    gdelt,
    github,
    gleif,
    gravatar,
    pdns,
    rdap,
    registries_misc,
    source_applies,
    sources_enabled,
    us_states,
    usernames,
    vies,
    wayback,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "osint" / "sources"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def fake_fetch(url: str, timeout: int = 15, **_kw):
    """按 URL 返回夹具；未知 URL 返回 None（模拟无数据）。"""
    if "rdap.org/domain" in url:
        return _read("rdap_domain.json")
    if "certspotter" in url:
        return _read("ct_certspotter.json")
    if "web.archive.org/cdx" in url:
        return _read("wayback_cdx.json")
    if "api.github.com/search/users" in url:
        return _read("github_search.json")
    if "api.github.com/users/" in url:
        login = url.rstrip("/").rsplit("/", 1)[-1]
        if login == "Mattbusel":
            return _read("github_user.json")
        return json.dumps({"login": login})
    if "api.hackertarget.com" in url:
        return _read("pdns_hackertarget.txt") if "cloudflare.com" in url else ""
    if "api.gleif.org" in url:
        return _read("gleif_search.json") if "Apple" in url else json.dumps({"data": []})
    if "data.ny.gov" in url:
        return _read("us_ny.json") if "TENSORUST" in url.upper() else "[]"
    if "data.colorado.gov" in url:
        return _read("us_co.json") if "GOOGLE" in url.upper() else "[]"
    if "efts.sec.gov" in url:
        if "Apple" in url:
            return _read("edgar.json")
        return json.dumps({"hits": {"hits": [], "total": {"value": 0}}})
    if "gdeltproject.org" in url:
        return _read("gdelt_artlist.json") if "tensorust" in url.lower() else json.dumps({"articles": []})
    if "vies/rest-api" in url:
        return _read("vies.json")
    if "api.gravatar.com" in url:
        return _read("gravatar_profile.json")
    if "recherche-entreprises.api.gouv.fr" in url:
        return _read("fr_search.json")
    if "data.brreg.no" in url:
        return _read("no_search.json")
    if "brasilapi.com.br" in url:
        return _read("br_cnpj.json")
    return None


def ctx(**overrides) -> TargetContext:
    base = TargetContext(
        target="tensorust.com",
        target_type="domain",
        domain="tensorust.com",
        company_name="Tensorust",
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


# ── P2-1：目标类型 ──────────────────────────────────────────────────────────


class TestTargetType:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("John Smith", "person"),
            ("Matthew Charles Vladislav Busel", "person"),
            ("张三", "person"),
            ("ACME Corporation", "company"),
            ("Doha Pearl Contracting W.L.L.", "company"),
            ("Microsoft", "company"),
            ("华为技术有限公司", "company"),
            ("tensorust.com", "domain"),
            ("a@b.com", "email"),
            ("https://x.com/a", "url"),
        ],
    )
    def test_detection(self, value, expected):
        assert _detect_target_type(value) == expected

    def test_explicit_prefixes(self):
        assert _split_type_prefix('person: Matthew Busel') == ("Matthew Busel", "person")
        assert _split_type_prefix("company:ACME Trading") == ("ACME Trading", "company")
        assert _split_type_prefix("ACME") == ("ACME", None)

    def test_title_split_on_colon(self):
        html = "<html><head><title>Tensorust: the money is in the join</title></head></html>"
        assert _resolve_entity_name("tensorust.com", fetcher=lambda *a, **k: html) == "Tensorust"


# ── P2-2：每个来源的成功 / 空 / 错误 ────────────────────────────────────────


class TestRdap:
    def test_success(self):
        result = rdap.run(ctx(), fetch=fake_fetch)
        assert result.status == "hit"
        assert result.data["creation_date"].startswith("2026-10-15")
        assert result.data["registrar"]
        assert any("注册时间" in fact["text"] for fact in result.facts)
        assert result.facts[0]["url"] == "https://rdap.org/domain/tensorust.com"

    def test_empty(self):
        result = rdap.run(ctx(), fetch=lambda *a, **k: "{}")
        assert result.status == "miss"

    def test_error(self):
        def _boom(*_a, **_k):
            raise OSError("connection reset")

        result = rdap.run(ctx(), fetch=_boom)
        assert result.status == "error" and "RDAP" in result.error

    def test_no_domain_is_skipped(self):
        assert rdap.run(ctx(domain=None), fetch=fake_fetch).status == "skipped"


class TestCt:
    def test_success_lists_subdomains(self):
        result = ct.run(ctx(), fetch=fake_fetch)
        assert result.status == "hit"
        assert "shop" in result.data["subdomains"]
        assert "tollbit" in result.data["subdomains"]
        assert result.data["earliest"].startswith("2026-10-15")
        assert any("证书" in fact["text"] for fact in result.facts)

    def test_empty(self):
        result = ct.run(ctx(), fetch=lambda *a, **k: "[]")
        assert result.status == "miss"

    def test_error(self):
        def _boom(*_a, **_k):
            raise TimeoutError("timed out")

        result = ct.run(ctx(), fetch=_boom)
        assert result.status == "error"


class TestWayback:
    def test_success_first_snapshot(self):
        result = wayback.run(ctx(), fetch=fake_fetch)
        assert result.status == "hit"
        assert result.data["first_snapshot"] == "20261015081506"
        assert "2026-10-15" in result.facts[0]["text"]
        assert result.facts[0]["url"].startswith("https://web.archive.org/web/")

    def test_empty(self):
        result = wayback.run(ctx(), fetch=lambda *a, **k: '[["urlkey"]]')
        assert result.status == "miss"

    def test_error(self):
        def _boom(*_a, **_k):
            raise OSError("blocked")

        result = wayback.run(ctx(), fetch=_boom)
        assert result.status == "error"


class TestGithub:
    def test_search_picks_profile_with_matching_domain(self):
        result = github.run(ctx(), fetch=fake_fetch)
        assert result.status == "hit"
        assert result.data["login"] == "Mattbusel"
        text = result.facts[0]["text"]
        assert "Matthew Charles Vladislav Busel" in text
        assert "New York" in text
        assert "2024-09-27" in text

    def test_direct_username(self):
        result = github.run(
            ctx(target_type="person", domain=None, github_username="Mattbusel"),
            fetch=fake_fetch,
        )
        assert result.status == "hit"
        assert result.data["login"] == "Mattbusel"

    def test_same_name_without_evidence_is_not_used(self):
        """只有同名、没有域名/公司吻合 → 不采用（防止挂错人）。"""
        search = json.dumps({"total_count": 1, "items": [{"login": "random"}]})

        def _fetch(url, timeout=15, **_k):
            if "search/users" in url:
                return search
            return json.dumps({"login": "random", "name": "Random Person"})

        result = github.run(ctx(domain="acme.com", company_name="ACME"), fetch=_fetch)
        assert result.status == "miss"
        assert "未采用" in result.error

    def test_error(self):
        def _boom(*_a, **_k):
            raise OSError("api down")

        result = github.run(ctx(), fetch=_boom)
        assert result.status == "error"


class TestPdns:
    def test_success(self):
        result = pdns.run(ctx(domain="cloudflare.com"), fetch=fake_fetch)
        assert result.status == "hit"
        assert any("abuse.cloudflare.com" in name for name in result.data["subdomains"])

    def test_quota_error_text_is_not_a_hit(self):
        result = pdns.run(
            ctx(domain="cloudflare.com"),
            fetch=lambda *a, **k: "API count exceeded - Increase Quota with Membership",
        )
        assert result.status == "miss"

    def test_no_domain_is_skipped(self):
        assert pdns.run(ctx(domain=None), fetch=fake_fetch).status == "skipped"


class TestGleif:
    def test_success(self):
        result = gleif.run(
            ctx(company_name="Apple", domain=None, target_type="company"),
            fetch=fake_fetch,
        )
        assert result.status == "hit"
        assert result.data["lei"]
        assert "APPLE TREE" in result.facts[0]["text"]

    def test_non_matching_result_is_not_used(self):
        result = gleif.run(
            ctx(company_name="Tensorust", domain=None, target_type="company"),
            fetch=fake_fetch,
        )
        assert result.status == "miss"

    def test_person_is_skipped(self):
        result = gleif.run(
            ctx(company_name=None, domain=None, person_name="John Smith", target_type="person"),
            fetch=fake_fetch,
        )
        assert result.status == "skipped"


class TestVies:
    def test_valid_vat(self):
        result = vies.run(
            ctx(target="IE6388047V", domain=None, target_type="company"),
            fetch=fake_fetch,
        )
        assert result.status == "hit"
        assert result.data["valid"] is True
        assert "GOOGLE IRELAND" in result.facts[0]["text"]

    def test_invalid_vat_is_still_a_finding(self):
        result = vies.run(
            ctx(target="IE6388047V", domain=None, target_type="company"),
            fetch=lambda *a, **k: json.dumps({"isValid": False, "userError": "INVALID"}),
        )
        assert result.status == "hit"
        assert result.data["valid"] is False
        assert "无效" in result.facts[0]["text"]

    def test_no_vat_is_skipped(self):
        assert vies.run(ctx(), fetch=fake_fetch).status == "skipped"
        assert source_applies("vies", ctx()) is False
        assert source_applies("vies", ctx(target="IE6388047V")) is True


class TestUsStates:
    def test_ny_registration_and_address_type(self):
        result = us_states.run(
            ctx(company_name="TENSORUST LLC", domain=None, target_type="company"),
            fetch=fake_fetch,
        )
        assert result.status == "hit"
        joined = " ".join(fact["text"] for fact in result.facts)
        assert "DOS ID 8120331" in joined
        assert "Westchester" in joined
        assert "非经营地证明" in joined

    def test_co_registration(self):
        result = us_states.run(
            ctx(company_name="Google", domain=None, target_type="company"),
            fetch=fake_fetch,
        )
        assert result.status == "hit"
        joined = " ".join(fact["text"] for fact in result.facts)
        assert "科罗拉多州登记" in joined and "20198008646" in joined

    def test_person_is_skipped(self):
        result = us_states.run(
            ctx(company_name=None, domain=None, person_name="John Smith", target_type="person"),
            fetch=fake_fetch,
        )
        assert result.status == "skipped"


class TestEdgar:
    def test_success(self):
        result = edgar.run(
            ctx(company_name="Apple", domain=None, target_type="company"),
            fetch=fake_fetch,
        )
        assert result.status == "hit"
        assert "10-K" in result.facts[0]["text"]

    def test_empty(self):
        result = edgar.run(
            ctx(company_name="Tensorust", domain=None, target_type="company"),
            fetch=fake_fetch,
        )
        assert result.status == "miss"

    def test_person_is_skipped(self):
        result = edgar.run(
            ctx(company_name=None, domain=None, person_name="John Smith", target_type="person"),
            fetch=fake_fetch,
        )
        assert result.status == "skipped"


class TestGdelt:
    def test_success(self):
        result = gdelt.run(ctx(), fetch=fake_fetch)
        assert result.status == "hit"
        assert "Tensorust" in result.facts[0]["text"]
        assert result.facts[0]["url"].startswith("https://")

    def test_error_is_reported(self):
        def _boom(*_a, **_k):
            raise OSError("HTTP Error 429: Too Many Requests")

        result = gdelt.run(ctx(), fetch=_boom)
        assert result.status == "error"
        assert "429" in result.error

    def test_empty(self):
        result = gdelt.run(ctx(), fetch=lambda *a, **k: json.dumps({"articles": []}))
        assert result.status == "miss"


class TestGravatar:
    def test_success(self):
        result = gravatar.run(
            ctx(email="matt@tensorust.com", domain=None, target_type="email"),
            fetch=fake_fetch,
        )
        assert result.status == "hit"
        assert "Matt Example" in result.facts[0]["text"]
        assert result.facts[0]["url"].startswith("https://gravatar.com/")

    def test_no_profile_is_miss(self):
        def _404(*_a, **_k):
            raise OSError("HTTP Error 404: Not Found")

        assert gravatar.run(
            ctx(email="nobody@example.com", domain=None, target_type="email"),
            fetch=_404,
        ).status == "miss"

    def test_no_email_is_skipped(self):
        assert gravatar.run(ctx(), fetch=fake_fetch).status == "skipped"


class TestRegistriesMisc:
    def test_fr_registration(self):
        result = registries_misc.run(
            ctx(company_name="Airbus", domain=None, target_type="company"),
            fetch=fake_fetch,
        )
        assert result.status == "hit"
        joined = " ".join(fact["text"] for fact in result.facts)
        assert "法国登记" in joined and "383474814" in joined

    def test_no_registration(self):
        result = registries_misc.run(
            ctx(company_name="Equinor", domain=None, target_type="company"),
            fetch=fake_fetch,
        )
        assert result.status == "hit"
        joined = " ".join(fact["text"] for fact in result.facts)
        assert "挪威登记" in joined and "923609016" in joined

    def test_br_cnpj(self):
        result = registries_misc.run(
            ctx(target="33.000.167/0001-01", company_name=None, domain=None, target_type="company"),
            fetch=fake_fetch,
        )
        assert result.status == "hit"
        joined = " ".join(fact["text"] for fact in result.facts)
        assert "巴西登记" in joined and "PETROBRAS" in joined

    def test_person_is_skipped(self):
        result = registries_misc.run(
            ctx(company_name=None, domain=None, person_name="John Smith", target_type="person"),
            fetch=fake_fetch,
        )
        assert result.status == "skipped"


class TestUsernames:
    def test_found_public_profiles(self, monkeypatch):
        monkeypatch.setattr(usernames, "_load_sites", lambda: [
            {"name": "GitHub", "uri_check": "https://github.com/{account}", "e_string": "profile"},
            {"name": "Reddit", "uri_check": "https://reddit.com/user/{account}", "e_string": "u/"},
        ])

        def _fetch(url, timeout=4, **_k):
            return "profile u/Mattbusel" if "github.com" in url else None

        result = usernames.run(ctx(username="Mattbusel"), fetch=_fetch)
        assert result.status == "hit"
        assert "GitHub" in result.facts[0]["text"]
        assert result.data["checked"] == 2

    def test_miss_when_no_profiles(self, monkeypatch):
        monkeypatch.setattr(usernames, "_load_sites", lambda: [
            {"name": "GitHub", "uri_check": "https://github.com/{account}", "e_string": "profile"},
        ])
        result = usernames.run(ctx(username="nobody"), fetch=lambda *a, **k: None)
        assert result.status == "miss"

    def test_no_username_is_skipped(self):
        assert usernames.run(ctx(), fetch=fake_fetch).status == "skipped"
        assert source_applies("usernames", ctx()) is False
        assert source_applies("usernames", ctx(username="matt")) is True


class TestUsernameExtraction:
    def test_from_profile_url(self):
        from trade.osint.orchestrator import _extract_username, _split_username_prefix

        assert _extract_username("https://github.com/Mattbusel", "url") == "Mattbusel"
        assert _extract_username("https://www.linkedin.com/in/matthewbusel/", "url") == "matthewbusel"
        assert _extract_username("matt@tensorust.com", "email") == "matt"
        assert _split_username_prefix("username:Mattbusel") == ("Mattbusel", "Mattbusel")


class TestSwitch:
    def test_sources_can_be_disabled(self, monkeypatch):
        monkeypatch.setenv("TRADE_OSINT_SOURCES", "off")
        assert sources_enabled() is False

    def test_applicability(self):
        assert source_applies("rdap", ctx(domain=None)) is False
        assert source_applies("rdap", ctx()) is True
        assert source_applies("gleif", ctx(target_type="person")) is False
        assert source_applies("github", ctx(target_type="person")) is True


# ── 编排与 CLI 渲染 ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_orchestrator_collects_sources_and_rdap_fills_whois(monkeypatch):
    """WHOIS 失败时 RDAP 补位；⑦ 来源事实齐全且都带 URL。"""
    import trade.osint.orchestrator as orch

    monkeypatch.setenv("TRADE_OSINT_SOURCES", "on")
    monkeypatch.setattr(
        orch, "domain_whois",
        lambda domain: {"domain": domain, "registered": False,
                        "error": "WHOIS 服务器无响应"},
    )
    events: list[dict] = []
    report = await osint_full_check(
        "tensorust.com",
        include_sanctions=False,
        include_tech_stack=False,
        include_linkedin=False,
        source_fetcher=fake_fetch,
        on_event=events.append,
    )

    # RDAP 补位：WHOIS 失败不再把域名判成未核验
    di = report["layers"]["domain_intel"]
    assert di["error"] is None
    assert di["via"] == "rdap"
    assert di["creation_date"].startswith("2026-10-15")
    assert di["age_category"] == "new"
    assert "domain_age_new" in report["flags"]

    sources = report["sources"]
    assert sources["rdap"]["status"] == "hit"
    assert sources["ct"]["status"] == "hit"
    assert sources["wayback"]["status"] == "hit"
    assert sources["github"]["status"] == "hit"
    assert "shop" in sources["ct"]["data"]["subdomains"]
    assert any("Matthew Charles Vladislav Busel" in f["text"]
               for f in sources["github"]["facts"])
    # 第二批：州登记与新闻
    assert sources["us_states"]["status"] == "hit"
    assert "DOS ID 8120331" in " ".join(f["text"] for f in sources["us_states"]["facts"])
    assert sources["gdelt"]["status"] == "hit"

    started = {e["source"] for e in events if e["event"] == "source_start"}
    done = {e["source"] for e in events if e["event"] == "source_done"}
    assert {"rdap", "ct", "wayback", "github"} <= started
    assert done == started

    text = cli.format_report(report)
    assert "⑦ 公开来源" in text
    assert "[RDAP 域名注册] 注册时间：2026-10-15" in text
    assert "tollbit" in text
    assert "Matthew Charles Vladislav Busel" in text


@pytest.mark.asyncio
async def test_slow_source_times_out_without_blocking_others(monkeypatch):
    import trade.osint.orchestrator as orch

    monkeypatch.setenv("TRADE_OSINT_SOURCES", "on")
    monkeypatch.setitem(orch._LAYER_TIMEOUTS, "rdap", 0.05)

    def _fetch(url, timeout=15, **_k):
        if "rdap.org/domain" in url:
            time.sleep(0.5)
            return _read("rdap_domain.json")
        return fake_fetch(url, timeout)

    report = await osint_full_check(
        "tensorust.com",
        include_sanctions=False,
        include_tech_stack=False,
        include_linkedin=False,
        budget=5.0,
        source_fetcher=_fetch,
    )
    assert report["sources"]["rdap"]["status"] == "timeout"
    assert report["sources"]["ct"]["status"] == "hit"
