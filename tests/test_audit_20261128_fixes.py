"""2026-11-28 审计修复回归测试（P2-4 / P2-5 / P2-6 / P2-9 / P2-10）。"""

from __future__ import annotations

import asyncio

import pytest

from trade.osint.orchestrator import _failure_layer, osint_full_check, retry_single_source
from trade.osint.sources import registries_misc, usernames
from trade.osint.sources.base import TargetContext


def test_p2_5_large_buyer_email_not_skipped_as_platform(monkeypatch):
    """P2-5：buyer@walmart.com 作为邮箱目标时，不按 b2b_marketplace 跳过自有域名层。"""
    called = {"whois": False}

    def _fake_whois(dom: str):
        called["whois"] = True
        return {"domain": dom, "registered": True, "days_old": 5000}

    monkeypatch.setattr("trade.osint.orchestrator.domain_whois", _fake_whois)
    monkeypatch.setattr(
        "trade.osint.orchestrator.email_intel.email_background_check",
        lambda _t: {"checked_count": 1, "found_count": 0, "results": []},
    )
    monkeypatch.setattr(
        "trade.osint.orchestrator.verify_corporate_email",
        lambda _t: {"is_corporate": True, "is_personal": False, "mx_found": True, "risk_flags": []},
    )
    monkeypatch.setattr("trade.osint.orchestrator.sources_enabled", lambda: False)

    rep = asyncio.run(
        osint_full_check(
            "buyer@walmart.com",
            include_tech_stack=False,
            include_sanctions=False,
            include_linkedin=False,
        )
    )
    assert called["whois"] is True
    assert rep["layers"]["domain_intel"].get("registered") is True
    assert rep["layers"]["domain_intel"].get("status") != "not_applicable"


def test_p2_6_registries_misc_and_usernames_all_errors_return_error(monkeypatch):
    """P2-6：registries_misc 与 usernames 全部上游报错时返回 error 而非 miss。"""
    ctx_co = TargetContext(target="Acme Corp", target_type="company", company_name="Acme Corp")

    def _boom_fetch(*_a, **_kw):
        raise ConnectionError("upstream unreachable")

    res_reg = registries_misc.run(ctx_co, fetch=_boom_fetch)
    assert res_reg.status == "error"
    assert res_reg.error_code == "network"
    assert res_reg.retryable is True

    monkeypatch.setattr(
        usernames,
        "_load_sites",
        lambda: [{"name": "GitHub", "uri_check": "https://example.invalid/{account}", "e_code": 200}],
    )
    ctx_u = TargetContext(target="alice", target_type="person", username="alice")
    res_u = usernames.run(ctx_u, fetch=_boom_fetch)
    assert res_u.status == "error"
    assert res_u.error_code == "network"


def test_p2_9_failure_layer_unknown_exception_not_network():
    """P2-9：非网络类程序异常（如 TypeError）归为 unknown / retryable=False，不误报网络错误。"""
    stub = _failure_layer("rdap", "error", detail="bad operand type", exc=TypeError("bad operand"))
    assert stub["error_code"] == "unknown"
    assert stub["retryable"] is False
    assert "网络" not in stub["error"]


def test_p2_4_retry_single_source_runs_target_source_and_rejects_unknown(monkeypatch):
    """P2-4：retry_single_source 可单独重跑指定层，未知 source 抛 ValueError。"""
    monkeypatch.setattr(
        "trade.osint.orchestrator.domain_whois",
        lambda dom: {"domain": dom, "registered": True, "days_old": 1200},
    )
    events: list[dict] = []
    res = asyncio.run(retry_single_source("acme.example-corp.org", "domain_intel", on_event=events.append))
    assert res["registered"] is True
    assert any(e.get("event") == "source_start" and e.get("source") == "domain_intel" for e in events)
    assert any(e.get("event") == "source_done" and e.get("source") == "domain_intel" for e in events)

    with pytest.raises(ValueError, match="unknown source"):
        asyncio.run(retry_single_source("acme.example-corp.org", "nonexistent_source"))


def test_p3_15_platform_domain_linkedin_marked_not_applicable(monkeypatch):
    """P3-15：公共平台域名时 LinkedIn 层显式标 not_applicable，而非 None。"""
    monkeypatch.setattr(
        "trade.osint.orchestrator.email_intel.email_background_check",
        lambda _t: {"checked_count": 1, "found_count": 0, "results": []},
    )
    monkeypatch.setattr(
        "trade.osint.orchestrator.verify_corporate_email",
        lambda _t: {"is_corporate": False, "is_personal": True, "mx_found": True, "risk_flags": []},
    )
    monkeypatch.setattr("trade.osint.orchestrator.sources_enabled", lambda: False)

    rep = asyncio.run(
        osint_full_check(
            "someone@gmail.com",
            include_tech_stack=True,
            include_sanctions=False,
            include_linkedin=True,
        )
    )
    li = rep["layers"]["linkedin"]
    assert isinstance(li, dict) and li.get("status") == "not_applicable"


def test_p3_16_usage_summary_company_filter_and_unknown_model_count():
    """P3-16：summary 支持按 company_id 过滤，并在存在未知模型时提示未计价笔数。"""
    import sqlite3

    from trade.usage import ensure_usage_schema, format_summary_text, record_usage, summary

    conn = sqlite3.connect(":memory:")
    ensure_usage_schema(conn)
    record_usage(conn, company_id=1, skill="chat", model="deepseek-flash", prompt_tokens=1000, completion_tokens=200)
    record_usage(conn, company_id=1, skill="chat", model="unlisted-model-z", prompt_tokens=500, completion_tokens=100)
    record_usage(conn, company_id=2, skill="chat", model="deepseek-flash", prompt_tokens=9000, completion_tokens=900)

    s1 = summary(conn, days=7, company_id=1)
    assert s1["calls"] == 2
    assert s1["unknown_model_calls"] == 1
    txt = format_summary_text(s1)
    assert "含 1 笔未知模型未计价" in txt


def test_p3_18_doctor_l1_failure_with_proxy_continues_to_l2_l3(monkeypatch):
    """P3-18：配置了系统代理且 L1 裸 socket 失败时，继续执行 L2/L3 而不提前截断。"""
    from trade import doctor

    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    calls = {"l2": 0, "l3": 0}

    def _l2(*_a):
        calls["l2"] += 1
        return doctor.STATUS_OK, "L2 ok"

    def _l3(*_a):
        calls["l3"] += 1
        return True, "L3 ok"

    res = doctor.check_llm_layered(
        deep=True,
        config_loader=lambda: {
            "provider": "deepseek",
            "model": "deepseek-flash",
            "api_key": "sk-test-fake-key-12345678",
            "base_url": "https://api.deepseek.com/v1",
        },
        l1_prober=lambda _u: (False, "direct tcp refused"),
        l2_prober=_l2,
        l3_prober=_l3,
    )
    assert len(res) == 3
    assert calls["l2"] == 1 and calls["l3"] == 1
    assert "系统代理" in res[0].detail


def test_p3_19_write_xlsx_text_cell_sets_string_type():
    """P3-19：write_xlsx_text_cell 对 '=' 开头字符串设 data_type='s' 且不加字面撇号。"""
    from types import SimpleNamespace

    from trade.sheet_safe import write_xlsx_text_cell

    cell = SimpleNamespace(value=None, data_type="n")
    write_xlsx_text_cell(cell, "=SUM(A1:A2)")
    assert cell.value == "=SUM(A1:A2)"
    assert cell.data_type == "s"


def test_p3_20_osint_facts_not_found_empty_url_distinct_by_source_name(tmp_path, monkeypatch):
    """P3-20：not_found 行 source_url 为空时，不同 source_name 不互相覆盖。"""
    from trade import database as db_mod
    from trade import osint_facts

    db_path = tmp_path / "facts.db"
    monkeypatch.setattr(db_mod, "_get_db_path", lambda: db_path)
    db_mod.init_db()
    conn = db_mod.get_connection()
    try:
        conn.execute("INSERT INTO companies (id, name, slug) VALUES (1, 'Acme', 'acme')")
        conn.commit()
    finally:
        conn.close()

    r1 = osint_facts.save_fact(1, "acme.org", "registry", status="not_found", source_name="gleif")
    r2 = osint_facts.save_fact(1, "acme.org", "registry", status="not_found", source_name="vies")
    assert r1 is not None and r2 is not None
    assert r1["id"] != r2["id"]
    rows = osint_facts.list_facts(1, "acme.org")
    assert len(rows) == 2

