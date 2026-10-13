"""trade.usage 模块测试（sqlite :memory:，无外部依赖）。"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trade import usage  # noqa: E402


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    yield c
    c.close()


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
    assert s["by_skill"][0]["skill"] == "b2b-osint"
    assert s["by_model"][0]["model"] == "deepseek-chat"


def test_unknown_model_zero_cost(conn):
    cost = usage.record_usage(conn, model="some-future-model", prompt_tokens=100, completion_tokens=100)
    assert cost == 0.0
    s = usage.summary(conn)
    assert s["total_tokens"] == 200


def test_price_env_override(conn, monkeypatch):
    monkeypatch.setenv("TRADE_PRICE_DEEPSEEK_CHAT", "1.0,2.0")
    cost = usage.record_usage(conn, model="deepseek-chat", prompt_tokens=1_000_000, completion_tokens=0)
    assert cost == pytest.approx(1.0)


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
    usage.record_usage(conn, skill="b2b-osint", model="deepseek-chat", prompt_tokens=10)
    text = usage.format_summary_text(usage.summary(conn))
    assert "b2b-osint" in text
    assert "近 7 天" in text


def test_record_never_raises(conn):
    conn.close()  # 已关闭的连接
    assert usage.record_usage(conn, skill="x") == 0.0
