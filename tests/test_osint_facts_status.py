"""
M8 验收测试：背调事实库支持 status（found / not_found / failed）、3 天复用提示、迁移兼容与跨公司隔离。

所有测试目标均为虚构夹具，纯本地临时 SQLite 运行。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import patch

from trade import database as db_mod
from trade import osint_facts
from trade.agent_context import bind_company
from trade.hermes_chat_memory_plugin.tools import (
    handle_osint_fact_save,
    handle_osint_job_start,
)


def _init_temp_db(tmp_path, monkeypatch):
    """初始化隔离临时数据库并创建两家虚构测试公司。"""
    db_path = tmp_path / "trade.db"
    monkeypatch.setattr(db_mod, "_get_db_path", lambda: db_path)
    db_mod.init_db()
    conn = db_mod.get_connection()
    try:
        conn.execute("INSERT INTO companies (id, name, slug) VALUES (1, 'Fictional A', 'fictional-a')")
        conn.execute("INSERT INTO companies (id, name, slug) VALUES (2, 'Fictional B', 'fictional-b')")
        conn.commit()
    finally:
        conn.close()
    return db_path


def test_not_found_fact_saved_reused_within_ttl_and_isolated_by_company(tmp_path, monkeypatch):
    """记一条 not_found → 3 天内返回给模型；跨公司隔离；超过 3 天自动失效。"""
    _init_temp_db(tmp_path, monkeypatch)

    row = osint_facts.save_fact(
        1,
        "Fictional Buyer GmbH",
        "注册资本",
        "",
        source_url="https://fictional-dir.invalid/buyer",
        source_name="公开工商库",
        status="not_found",
    )
    assert row is not None
    assert row["status"] == "not_found"
    assert row["value"] == ""
    assert row["verified"] == 0

    # known_facts 语义不变：只返回已核实 found
    assert osint_facts.known_facts(1, "Fictional Buyer GmbH") == {}
    assert osint_facts.unverified_facts(1, "Fictional Buyer GmbH") == {}

    # 3 天内 not_found_facts 可见
    nf = osint_facts.not_found_facts(1, "Fictional Buyer GmbH", max_age_days=3)
    assert "注册资本" in nf
    assert nf["注册资本"]["label"] == "已查询未检索到"
    assert nf["注册资本"]["sources"][0]["name"] == "公开工商库"

    # 跨公司不可见
    assert osint_facts.not_found_facts(2, "Fictional Buyer GmbH") == {}

    # 模拟 5 天后：超过默认 3 天 TTL 不再提示沿用
    future = datetime.now() + timedelta(days=5)
    assert osint_facts.not_found_facts(1, "Fictional Buyer GmbH", max_age_days=3, now=future) == {}


def test_not_found_then_found_prefers_found_and_preserves_history(tmp_path, monkeypatch):
    """同一字段先 not_found 后 found：known_facts 显示 found、not_found_facts 不再列出，历史行保留。"""
    _init_temp_db(tmp_path, monkeypatch)

    osint_facts.save_fact(
        1,
        "Fictional Alpha Ltd",
        "法定代表人",
        "",
        source_name="来源A",
        status="not_found",
    )
    osint_facts.save_fact(
        1,
        "Fictional Alpha Ltd",
        "法定代表人",
        "Jane Doe",
        source_url="https://fictional-reg.invalid/alpha",
        source_name="来源B",
        verified=True,
        status="found",
    )

    known = osint_facts.known_facts(1, "Fictional Alpha Ltd")
    assert known["法定代表人"]["values"] == ["Jane Doe"]
    assert osint_facts.not_found_facts(1, "Fictional Alpha Ltd") == {}

    # 原始表里两条历史均保留
    all_rows = osint_facts.list_facts(1, "Fictional Alpha Ltd")
    assert {r["status"] for r in all_rows} == {"not_found", "found"}


def test_osint_job_start_tool_returns_not_found_facts(tmp_path, monkeypatch):
    """osint_fact_save 记 not_found 后，再次 osint_job_start 返回的上下文包含 not_found_facts 与复用提示。"""
    _init_temp_db(tmp_path, monkeypatch)

    with bind_company(1):
        saved = json.loads(handle_osint_fact_save({
            "target": "Fictional Beta Corp",
            "field": "注册资本",
            "status": "not_found",
            "source_name": "公开登记库",
        }))
        assert saved["saved"] is True
        assert saved["fact"]["status"] == "not_found"

        with (
            patch("trade.osint_jobs.create_job", return_value=({"id": 99, "status": "queued"}, False)),
            patch("trade.osint_jobs.start_job"),
        ):
            started = json.loads(handle_osint_job_start({"target": "Fictional Beta Corp"}))

    assert "注册资本" in started["not_found_facts"]
    assert "如需重查" in started["not_found_hint"]
