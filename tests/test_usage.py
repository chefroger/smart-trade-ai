"""trade.usage 模块测试（sqlite :memory:，无外部依赖；覆盖工单 #3 与 #8）。"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trade import database as db_mod  # noqa: E402
from trade import (
    doctor,  # noqa: E402
    usage,  # noqa: E402
)


@pytest.fixture()
def conn():
    """隔离内存 SQLite 连接。"""
    c = sqlite3.connect(":memory:")
    yield c
    c.close()


def _utc_ts(year: int, month: int, day: int, hour: int, minute: int = 0) -> float:
    """构造指定 UTC 时刻的 Unix 时间戳。"""
    return datetime(year, month, day, hour, minute, tzinfo=UTC).timestamp()


def test_record_and_summary(conn):
    cost = usage.record_usage(
        conn, skill="b2b-osint", provider="deepseek", model="deepseek-chat",
        prompt_tokens=1_000_000, completion_tokens=1_000_000,
    )
    # (0.27 + 1.10) = 1.37
    assert cost == pytest.approx(1.37)
    s = usage.summary(conn, days=7)
    assert s["calls"] == 1
    assert s["total_tokens"] == 2_000_000
    assert s["total_cost_usd"] == pytest.approx(1.37)
    assert s["cost_note"] == "估算，以 DeepSeek 账单为准"
    assert s["by_skill"][0]["skill"] == "b2b-osint"
    assert s["by_model"][0]["model"] == "deepseek-chat"


def test_unknown_model_zero_cost(conn):
    cost = usage.record_usage(
        conn, model="some-future-model", prompt_tokens=100, completion_tokens=100
    )
    assert cost == 0.0
    s = usage.summary(conn)
    assert s["total_tokens"] == 200


def test_price_env_override(conn, monkeypatch):
    monkeypatch.setenv("TRADE_PRICE_DEEPSEEK_CHAT", "1.0,2.0")
    cost = usage.record_usage(
        conn, model="deepseek-chat", prompt_tokens=1_000_000, completion_tokens=0
    )
    assert cost == pytest.approx(1.0)

    # 三段覆盖：hit,miss,out
    monkeypatch.setenv("TRADE_PRICE_DEEPSEEK_FLASH", "0.01,0.50,1.00")
    cost2 = usage.record_usage(
        conn,
        model="deepseek-flash",
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
        cache_hit_tokens=900_000,
        cache_miss_tokens=100_000,
    )
    # 0.9*0.01 + 0.1*0.50 + 1.0*1.00 = 1.059
    assert cost2 == pytest.approx(1.059)


def test_price_override_param(conn):
    cost = usage.record_usage(
        conn, model="deepseek-chat", prompt_tokens=1_000_000,
        completion_tokens=1_000_000, price_override=(0.0, 0.0),
    )
    assert cost == 0.0


def test_summary_grouping(conn):
    usage.record_usage(conn, skill="a", model="deepseek-chat", prompt_tokens=100)
    usage.record_usage(conn, skill="a", model="deepseek-chat", prompt_tokens=100)
    usage.record_usage(conn, skill="b", model="gpt-4o-mini", prompt_tokens=100)
    s = usage.summary(conn)
    assert s["calls"] == 3
    assert len(s["by_skill"]) == 2
    assert len(s["by_model"]) == 2
    assert len(s["by_day"]) == 1


def test_format_summary_text(conn):
    usage.record_usage(
        conn, skill="b2b-osint", model="deepseek-flash",
        prompt_tokens=1000, cache_hit_tokens=800, cache_miss_tokens=200,
    )
    text = usage.format_summary_text(usage.summary(conn))
    assert "b2b-osint" in text
    assert "近 7 天" in text
    assert "80.0%" in text
    assert "估算，以 DeepSeek 账单为准" in text


def test_record_never_raises(conn):
    conn.close()  # 已关闭的连接
    assert usage.record_usage(conn, skill="x") == 0.0


# ==============================================================================
# 工单 #8：三档计价 + 高峰/闲时边界 + 缺字段 + 老库迁移 + Agent 采集 + 过期提醒
# ==============================================================================


def test_tiered_pricing_peak_and_offpeak(conn):
    """打桩 usage（命中 900、未命中 100、输出 50）分别在高峰与闲时记账，核对费用与列值。"""
    # 2026-11-27（周五）UTC 02:00 → 高峰
    peak_ts = _utc_ts(2026, 11, 27, 2, 0)
    # 2026-11-27（周五）UTC 13:00 → 闲时
    offpeak_ts = _utc_ts(2026, 11, 27, 13, 0)

    c_peak = usage.record_usage(
        conn,
        skill="b2b-osint",
        provider="deepseek",
        model="deepseek-flash",
        prompt_tokens=1000,
        completion_tokens=50,
        cache_hit_tokens=900,
        cache_miss_tokens=100,
        ts=peak_ts,
    )
    expected_peak = (900 / 1e6) * 0.006 + (100 / 1e6) * 0.30 + (50 / 1e6) * 1.20
    assert c_peak == pytest.approx(expected_peak)

    c_off = usage.record_usage(
        conn,
        skill="b2b-osint",
        provider="deepseek",
        model="deepseek-flash",
        prompt_tokens=1000,
        completion_tokens=50,
        cache_hit_tokens=900,
        cache_miss_tokens=100,
        ts=offpeak_ts,
    )
    expected_off = (900 / 1e6) * 0.003 + (100 / 1e6) * 0.15 + (50 / 1e6) * 0.60
    assert c_off == pytest.approx(expected_off)
    assert c_off == pytest.approx(c_peak / 2)

    rows = conn.execute(
        "SELECT cache_hit_tokens, cache_miss_tokens, price_window, extra1 FROM usage_ledger ORDER BY id"
    ).fetchall()
    assert rows == [
        (900, 100, "peak", ""),
        (900, 100, "offpeak", ""),
    ]


@pytest.mark.parametrize(
    "year,month,day,hour,minute,holidays,expected",
    [
        # 2026-11-27 是周五（工作日），验证全部 UTC 高峰/闲时边界
        (2026, 11, 27, 0, 59, None, "offpeak"),
        (2026, 11, 27, 1, 0, None, "peak"),
        (2026, 11, 27, 3, 59, None, "peak"),
        (2026, 11, 27, 4, 0, None, "offpeak"),
        (2026, 11, 27, 5, 59, None, "offpeak"),
        (2026, 11, 27, 6, 0, None, "peak"),
        (2026, 11, 27, 9, 59, None, "peak"),
        (2026, 11, 27, 10, 0, None, "offpeak"),
        # 2026-11-28 是周六 → 高峰小时段也是闲时
        (2026, 11, 28, 2, 0, None, "offpeak"),
        (2026, 11, 28, 7, 30, None, "offpeak"),
        # 工作日但配置为法定节假日 → 全天闲时
        (2026, 11, 27, 2, 0, ["2026-11-27"], "offpeak"),
    ],
)
def test_peak_offpeak_boundaries(year, month, day, hour, minute, holidays, expected):
    """覆盖 UTC 00:59/01:00/03:59/04:00/05:59/06:00/09:59/10:00、周六与配置节假日。"""
    ts = _utc_ts(year, month, day, hour, minute)
    assert usage.resolve_price_window("deepseek-flash", ts=ts, holidays=holidays) == expected


def test_missing_cache_fields_marked_and_billed_as_miss(conn):
    """未提供缓存字段时按全部未命中计价，且在 extra1 标出 no_cache_data。"""
    offpeak_ts = _utc_ts(2026, 11, 27, 13, 0)
    cost = usage.record_usage(
        conn,
        model="deepseek-flash",
        prompt_tokens=1000,
        completion_tokens=0,
        ts=offpeak_ts,
    )
    assert cost == pytest.approx((1000 / 1e6) * 0.15)
    row = conn.execute(
        "SELECT cache_hit_tokens, cache_miss_tokens, extra1 FROM usage_ledger"
    ).fetchone()
    assert row == (0, 1000, usage.NO_CACHE_DATA_TAG)


def test_usage_ledger_migration_preserves_old_rows_and_tokens_today(tmp_path, monkeypatch):
    """建旧结构 usage_ledger 表，执行迁移后新列存在、旧数据不丢、tokens_today 不变。"""
    db_path = tmp_path / "legacy_usage.db"
    conn = sqlite3.connect(str(db_path))
    now_ts = datetime.now().timestamp()
    conn.executescript(
        """
        CREATE TABLE usage_ledger (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            ts                REAL    NOT NULL,
            company_id        INTEGER NOT NULL DEFAULT 0,
            skill             TEXT    NOT NULL DEFAULT '',
            provider          TEXT    NOT NULL DEFAULT '',
            model             TEXT    NOT NULL DEFAULT '',
            prompt_tokens     INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd          REAL    NOT NULL DEFAULT 0,
            extra1            TEXT    NOT NULL DEFAULT '',
            extra2            TEXT    NOT NULL DEFAULT '',
            extra3            TEXT    NOT NULL DEFAULT ''
        );
        """
    )
    conn.execute(
        "INSERT INTO usage_ledger (ts, company_id, skill, model, prompt_tokens, completion_tokens, cost_usd) "
        "VALUES (?, 1, 'b2b-osint', 'deepseek-flash', 500, 100, 0.01)",
        (now_ts,),
    )
    conn.commit()

    db_mod._migrate_usage_ledger_pricing_v6(conn)
    conn.commit()

    cols = {r[1] for r in conn.execute("PRAGMA table_info(usage_ledger)").fetchall()}
    assert {"cache_hit_tokens", "cache_miss_tokens", "price_window", "currency"} <= cols
    assert usage.tokens_today(conn, 1) == 600
    old_row = conn.execute(
        "SELECT prompt_tokens, completion_tokens, cache_hit_tokens, price_window FROM usage_ledger"
    ).fetchone()
    assert old_row == (500, 100, 0, "")
    conn.close()


def test_record_agent_usage_reads_session_cache_read_tokens(tmp_path, monkeypatch):
    """桩 agent 提供 session_cache_read_tokens 时，正确写入 cache_hit_tokens 与 cache_miss_tokens。"""
    db_path = tmp_path / "agent_usage.db"
    monkeypatch.setattr(db_mod, "_get_db_path", lambda: db_path)
    db_mod.init_db()

    fake_agent = SimpleNamespace(
        provider="deepseek",
        model="deepseek-flash",
        session_prompt_tokens=10_000,
        session_completion_tokens=500,
        session_cache_read_tokens=9_000,
    )
    usage.record_agent_usage(fake_agent, company_id=7, skill="b2b-osint")

    conn = db_mod.get_connection()
    try:
        row = conn.execute(
            "SELECT company_id, skill, prompt_tokens, completion_tokens, "
            "cache_hit_tokens, cache_miss_tokens, extra1 FROM usage_ledger"
        ).fetchone()
        assert tuple(row) == (7, "b2b-osint", 10_000, 500, 9_000, 1_000, "")
    finally:
        conn.close()


def test_record_response_usage_handles_deepseek_and_missing(conn):
    """record_response_usage 正确解析 DeepSeek 缓存字段，无 usage 时记 0 不报错。"""
    fake_usage = SimpleNamespace(
        prompt_tokens=2000,
        completion_tokens=300,
        prompt_cache_hit_tokens=1800,
        prompt_cache_miss_tokens=200,
    )
    cost = usage.record_response_usage(
        fake_usage,
        skill="supplier-extract",
        provider="deepseek",
        model="deepseek-flash",
        company_id=3,
        conn=conn,
        ts=_utc_ts(2026, 11, 27, 13, 0),
    )
    assert cost > 0
    assert usage.tokens_today(conn, 3) == 2300
    row = conn.execute(
        "SELECT skill, cache_hit_tokens, cache_miss_tokens, price_window FROM usage_ledger"
    ).fetchone()
    assert row == ("supplier-extract", 1800, 200, "offpeak")

    # 模型未返回 usage 时记 0 不报错
    assert usage.record_response_usage(None, skill="supplier-extract", conn=conn) == 0.0


def test_doctor_pricing_freshness_warns_after_90_days(monkeypatch):
    """价格表核对超过 90 天时 doctor 返回非致命告警。"""
    # 未过期时返回未过期
    info_fresh = usage.pricing_freshness_info(today=date(2026, 12, 1))
    assert info_fresh["is_stale"] is False

    monkeypatch.setattr(
        usage,
        "pricing_freshness_info",
        lambda **kw: {
            "verified_at": "2026-01-01",
            "age_days": 120,
            "stale_days": 90,
            "is_stale": True,
            "source_url": "https://api-docs.deepseek.com/quick_start/pricing",
        },
    )
    res = doctor.check_pricing_freshness()
    assert len(res) == 1
    assert res[0].status == doctor.STATUS_WARN
    assert res[0].fatal is False
    assert "90" in res[0].detail
