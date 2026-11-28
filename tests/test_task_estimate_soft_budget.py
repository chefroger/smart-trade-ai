"""
M7 验收测试：长任务历史预估（skill_history_stats）、软 token 预算钩子（soft_budget）与 osint_jobs 透传。

所有测试数据均为虚构夹具，纯本地内存/临时库运行。
"""

from __future__ import annotations

import sqlite3

from trade.hermes_chat_memory_plugin import soft_budget
from trade.usage import (
    ensure_usage_schema,
    record_usage,
    resolve_soft_token_budget,
    skill_history_stats,
)


def _mem_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    ensure_usage_schema(conn)
    return conn


def test_skill_history_stats_under_threshold_has_no_fabricated_numbers():
    """0 条与 2 条历史记录均返回「暂无足够历史」，不编造任何默认数字。"""
    conn = _mem_db()
    s0 = skill_history_stats(conn, company_id=1, skill="b2b-osint")
    assert s0["has_history"] is False
    assert s0["count"] == 0
    assert s0["median_tokens"] is None
    assert "暂无足够历史" in s0["message"]

    for _ in range(2):
        record_usage(
            conn,
            company_id=1,
            skill="b2b-osint",
            model="deepseek-chat",
            prompt_tokens=100_000,
            completion_tokens=20_000,
            duration_ms=30_000,
        )
    s2 = skill_history_stats(conn, company_id=1, skill="b2b-osint")
    assert s2["has_history"] is False
    assert s2["count"] == 2
    assert s2["median_tokens"] is None
    assert "暂无足够历史" in s2["message"]


def test_skill_history_stats_median_and_company_isolation():
    """5 条与 10+ 条历史正确取最近 10 条中位数，且严格按 company_id 隔离。"""
    conn = _mem_db()
    # 公司 1 写入 5 条（token 合计分别为 10万/20万/30万/40万/50万，中位 30万）
    for idx in range(1, 6):
        record_usage(
            conn,
            company_id=1,
            skill="b2b-osint",
            model="deepseek-chat",
            prompt_tokens=idx * 90_000,
            completion_tokens=idx * 10_000,
            duration_ms=idx * 10_000,
        )
    # 公司 2 写入超大值，不得污染公司 1
    for _ in range(5):
        record_usage(
            conn,
            company_id=2,
            skill="b2b-osint",
            model="deepseek-chat",
            prompt_tokens=9_000_000,
            completion_tokens=1_000_000,
            duration_ms=999_000,
        )

    s5 = skill_history_stats(conn, company_id=1, skill="b2b-osint")
    assert s5["has_history"] is True
    assert s5["count"] == 5
    assert s5["median_tokens"] == 300_000
    assert s5["median_duration_ms"] == 30_000
    assert "最近 5 次" in s5["message"]
    assert "按本机历史，仅供参考" in s5["message"]

    # 再为公司 1 写入 10 条 100_000 token（总计 15 条，最近 10 条中位应为 100_000）
    for _ in range(10):
        record_usage(
            conn,
            company_id=1,
            skill="b2b-osint",
            model="deepseek-chat",
            prompt_tokens=80_000,
            completion_tokens=20_000,
            duration_ms=15_000,
        )
    s10 = skill_history_stats(conn, company_id=1, skill="b2b-osint", n=10)
    assert s10["count"] == 10
    assert s10["median_tokens"] == 100_000
    assert s10["median_duration_ms"] == 15_000


def test_resolve_soft_token_budget_modes():
    """auto=2x 中位数；历史不足 3 次返回 None；0 表示关闭；正整数直接生效。"""
    conn = _mem_db()
    assert resolve_soft_token_budget(conn, 1, "b2b-osint", env_value="auto") is None
    assert resolve_soft_token_budget(conn, 1, "b2b-osint", env_value="0") is None
    assert resolve_soft_token_budget(conn, 1, "b2b-osint", env_value="50000") == 50_000

    for _ in range(3):
        record_usage(
            conn,
            company_id=1,
            skill="b2b-osint",
            model="deepseek-chat",
            prompt_tokens=100_000,
            completion_tokens=20_000,
        )
    assert resolve_soft_token_budget(conn, 1, "b2b-osint", env_value="auto") == 240_000
    assert resolve_soft_token_budget(conn, 1, "b2b-osint", env_value="0") is None


def test_soft_budget_hook_blocks_retrieval_only_after_limit_and_generates_wrapup(monkeypatch):
    """达到软预算后只拦截检索类工具并引导优雅收尾；预算为 0/未超限时完全放行。"""
    monkeypatch.setenv("TRADE_HOST", "1")
    tid = "task-m7-test-1"
    soft_budget.release(tid)

    # 未登记（相当于预算为 0）：完全放行
    assert soft_budget.on_pre_tool_call("web_search", {"q": "a"}, task_id=tid) is None

    # 登记小预算 1000 token
    soft_budget.register(tid, 1000, skill="b2b-osint")
    try:
        assert soft_budget.add_tokens(tid, 600) is False
        assert soft_budget.on_pre_tool_call("web_search", {"q": "a"}, task_id=tid) is None

        # 超过软预算
        assert soft_budget.add_tokens(tid, 500) is True
        # 检索类工具被温和拦截并要求基于已有材料收尾
        blocked = soft_budget.on_pre_tool_call("web_search", {"q": "b"}, task_id=tid)
        assert blocked is not None
        assert blocked["action"] == "block"
        assert "因达到本次预算提前收尾" in blocked["message"]

        # 非检索类收尾工具（如落库/写报告）完全放行，保证绝不返回空报告
        assert soft_budget.on_pre_tool_call("osint_fact_save", {}, task_id=tid) is None

        notice = soft_budget.format_wrapup_notice(tid)
        assert "因达到本次预算提前收尾" in notice
        assert "web_search" in notice
        assert "继续补查" in notice
    finally:
        soft_budget.release(tid)


def test_soft_budget_live_token_reader_and_window_and_pricing_aliases(monkeypatch):
    """验证实时 token_reader 触发拦截、窗口标签不误标高峰价、以及官方别名与未知模型标记。"""
    from datetime import UTC, datetime

    from trade.usage import UNKNOWN_MODEL_TAG, get_tiered_price

    monkeypatch.setenv("TRADE_HOST", "1")
    tid = "task-m7-live-reader"
    live = {"tokens": 200}
    soft_budget.register(tid, 1000, skill="b2b-osint", token_reader=lambda: live["tokens"])
    try:
        assert soft_budget.on_pre_tool_call("web_search", {"q": "a"}, task_id=tid) is None
        live["tokens"] = 1200
        blocked = soft_budget.on_pre_tool_call("web_search", {"q": "b"}, task_id=tid)
        assert blocked is not None and blocked["action"] == "block"
    finally:
        soft_budget.release(tid)

    # 别名与前缀归一化
    assert get_tiered_price("deepseek-v4-flash", window="peak") == get_tiered_price(
        "deepseek-flash", window="peak"
    )
    assert get_tiered_price("deepseek/deepseek-flash", window="offpeak") == get_tiered_price(
        "deepseek-flash", window="offpeak"
    )

    # 周六闲时：deepseek-flash 正确标「闲时价」，deepseek-chat 不误标「当前为高峰价」
    sat_ts = datetime(2026, 11, 28, 3, 0, tzinfo=UTC).timestamp()
    conn = _mem_db()
    for _ in range(3):
        record_usage(
            conn,
            company_id=1,
            skill="b2b-osint",
            model="deepseek-flash",
            prompt_tokens=100_000,
            completion_tokens=20_000,
            duration_ms=25_000,
            ts=sat_ts,
        )
    st_flash = skill_history_stats(conn, 1, "b2b-osint", ts=sat_ts)
    assert st_flash["price_window"] == "offpeak"
    assert "当前为闲时价" in st_flash["message"]
    assert "当前为高峰价" not in st_flash["message"]

    # 未知模型记账打 unknown_model 标记
    record_usage(
        conn,
        company_id=1,
        skill="chat",
        model="custom-unlisted-model-x",
        prompt_tokens=1000,
        completion_tokens=500,
    )
    row = conn.execute(
        "SELECT extra1 FROM usage_ledger WHERE model = 'custom-unlisted-model-x'"
    ).fetchone()
    assert row is not None and UNKNOWN_MODEL_TAG in str(row[0])
