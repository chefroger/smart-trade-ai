"""用量台账接线与每日 token 上限（审计 P1-16）。

审计要求：`record_usage` 从未被聊天链路调用，额度防线只有"每分钟 20 次"。
这里锁定：

1. 每次 agent 调用（含失败/中断的那次尝试）都把 token 记进 usage_ledger；
2. 每公司每日默认 2000 万 token 额度，只用于界面提示，超限**不拦聊天**；
3. `TRADE_DAILY_TOKEN_LIMIT=0` 表示不限；
4. 额度状态由 `/usage/today` 暴露给前端（used / limit / exceeded）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def company(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    import trade.database as _db

    monkeypatch.setattr(_db, "_get_db_path", lambda: tmp_path / "trade.db")
    from trade.database import init_db

    init_db()

    import trade.company as co

    def _setup(name, slug, suggested_name=""):
        wd = tmp_path / (suggested_name or name)
        wd.mkdir(parents=True, exist_ok=True)
        for cat, _ in co._WORK_DIR_CATEGORIES:
            (wd / cat).mkdir(parents=True, exist_ok=True)
        return wd, True

    monkeypatch.setattr(co, "_setup_work_directory", _setup)
    return co.create(name="Quota Co", slug="quota-co")


def _insert_usage(company_id: int, prompt: int, completion: int, *, ts_ago: float = 0.0):
    """直接写一行台账（绕过业务代码，专门造"今天已用 X"的状态）。"""
    import time

    from trade.database import get_connection

    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO usage_ledger (ts, company_id, skill, provider, model, "
            "prompt_tokens, completion_tokens, cost_usd) VALUES (?,?,?,?,?,?,?,?)",
            (time.time() - ts_ago, company_id, "test", "p", "m", prompt, completion, 0.0),
        )
        conn.commit()
    finally:
        conn.close()


class _CountingAgent:
    """带 Hermes 会话计数字段的替身 agent。"""

    def __init__(self, prompt=100, completion=20):
        self.session_prompt_tokens = prompt
        self.session_completion_tokens = completion
        self.provider = "deepseek"
        self.model = "deepseek-chat"
        self.interrupted = False

    def chat(self, query):  # noqa: ARG002
        return "好的，这是回复。"

    def run_conversation(self, query, task_id=None):  # noqa: ARG002
        return {"final_response": self.chat(query)}

    def hard_interrupt(self, message=None):  # noqa: ARG002
        self.interrupted = True


class TestDailyLimitConfig:
    def test_default_is_twenty_million(self, monkeypatch):
        monkeypatch.delenv("TRADE_DAILY_TOKEN_LIMIT", raising=False)
        import trade.usage as usage

        assert usage.daily_token_limit() == 20_000_000

    def test_env_override_and_disable(self, monkeypatch):
        import trade.usage as usage

        monkeypatch.setenv("TRADE_DAILY_TOKEN_LIMIT", "5000")
        assert usage.daily_token_limit() == 5000

        monkeypatch.setenv("TRADE_DAILY_TOKEN_LIMIT", "0")
        assert usage.daily_token_limit() == 0

    def test_invalid_env_falls_back_to_default(self, monkeypatch):
        import trade.usage as usage

        monkeypatch.setenv("TRADE_DAILY_TOKEN_LIMIT", "abc")
        assert usage.daily_token_limit() == 20_000_000


class TestTokensToday:
    def test_sums_today_only(self, company):
        import trade.usage as usage
        from trade.database import get_connection

        _insert_usage(company["id"], 100, 20)
        _insert_usage(company["id"], 200, 30)
        # 昨天的那笔不计入
        _insert_usage(company["id"], 9999, 9999, ts_ago=2 * 86400)
        # 别家公司的也不计入
        _insert_usage(company["id"] + 1000, 500, 500)

        conn = get_connection()
        try:
            assert usage.tokens_today(conn, company["id"]) == 350
        finally:
            conn.close()

    def test_record_agent_usage_writes_row(self, company):
        import trade.usage as usage

        agent = _CountingAgent(prompt=1000, completion=250)
        cost = usage.record_agent_usage(
            agent, company_id=company["id"], skill="b2b-osint",
        )

        assert cost > 0, "已知模型应算出费用"
        from trade.database import get_connection

        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT company_id, skill, provider, model, prompt_tokens, "
                "completion_tokens FROM usage_ledger WHERE company_id = ?",
                (company["id"],),
            ).fetchone()
        finally:
            conn.close()
        assert tuple(row) == (company["id"], "b2b-osint", "deepseek",
                              "deepseek-chat", 1000, 250)

    def test_agent_without_counters_records_nothing(self, company):
        import trade.usage as usage

        class _Bare:
            def chat(self, q):  # noqa: ARG002
                return "ok"

        assert usage.record_agent_usage(_Bare(), company_id=company["id"]) == 0.0
        from trade.database import get_connection

        conn = get_connection()
        try:
            n = conn.execute("SELECT COUNT(*) FROM usage_ledger").fetchone()[0]
        finally:
            conn.close()
        assert n == 0


class TestChatBudgetIsAdvisoryOnly:
    """用户 2026-10-26 决定：额度只做提示，不拦截聊天。"""

    @pytest.mark.asyncio
    async def test_over_limit_still_answers(self, company):
        import trade.api.chat as chat
        from trade.api.models import ChatRequest

        _insert_usage(company["id"], 20_000_000, 1)

        with patch.object(chat, "create_agent", return_value=_CountingAgent()), \
             patch.object(chat, "build_query", return_value=("Q", "H")), \
             patch.object(chat.chat_memory, "save_with_context", return_value={"id": 1}), \
             patch("trade.license.check_license", return_value=(True, "")):
            result = await chat.trade_chat(ChatRequest(query="你好"), company["id"])

        assert result["response"] == "好的，这是回复。"

    def test_usage_today_endpoint_reports_exceeded(self, company):
        import trade.api.chat as chat

        _insert_usage(company["id"], 20_100_000, 0)
        data = chat.usage_today(company["id"])

        assert data["used"] == 20_100_000
        assert data["limit"] == 20_000_000
        assert data["exceeded"] is True

    def test_usage_today_endpoint_shows_used_when_unlimited(self, company, monkeypatch):
        import trade.api.chat as chat

        monkeypatch.setenv("TRADE_DAILY_TOKEN_LIMIT", "0")
        _insert_usage(company["id"], 1234, 66)
        data = chat.usage_today(company["id"])

        assert data["used"] == 1300
        assert data["limit"] == 0
        assert data["exceeded"] is False

    @pytest.mark.asyncio
    async def test_unlimited_env_still_answers(self, company, monkeypatch):
        import trade.api.chat as chat
        from trade.api.models import ChatRequest

        monkeypatch.setenv("TRADE_DAILY_TOKEN_LIMIT", "0")
        _insert_usage(company["id"], 9_000_000, 1)

        with patch.object(chat, "create_agent", return_value=_CountingAgent()), \
             patch.object(chat, "build_query", return_value=("Q", "H")), \
             patch.object(chat.chat_memory, "save_with_context", return_value={"id": 1}), \
             patch("trade.license.check_license", return_value=(True, "")):
            result = await chat.trade_chat(ChatRequest(query="你好"), company["id"])

        assert result["response"] == "好的，这是回复。"

    @pytest.mark.asyncio
    async def test_successful_chat_records_usage(self, company):
        import trade.api.chat as chat
        from trade.api.models import ChatRequest

        with patch.object(chat, "create_agent", return_value=_CountingAgent(prompt=800, completion=150)), \
             patch.object(chat, "build_query", return_value=("Q", "H")), \
             patch.object(chat.chat_memory, "save_with_context", return_value={"id": 1}), \
             patch("trade.license.check_license", return_value=(True, "")):
            await chat.trade_chat(ChatRequest(query="你好"), company["id"])

        import trade.usage as usage
        from trade.database import get_connection

        conn = get_connection()
        try:
            assert usage.tokens_today(conn, company["id"]) == 950
        finally:
            conn.close()

    @pytest.mark.asyncio
    async def test_failed_attempt_is_still_recorded(self, company):
        """失败的重试同样烧 token —— 漏记会让日额度形同虚设。"""

        class _Failing(_CountingAgent):
            def chat(self, query):  # noqa: ARG002
                raise RuntimeError("provider exploded")

        import trade.api.chat as chat
        from trade.api.models import ChatRequest

        with patch.object(chat, "create_agent", return_value=_Failing(prompt=400, completion=0)), \
             patch.object(chat, "build_query", return_value=("Q", "H")), \
             patch.object(chat, "chat_memory") as fake_mem, \
             patch.object(chat, "time") as fake_time, \
             patch("trade.license.check_license", return_value=(True, "")):
            fake_time.time.return_value = 0
            fake_time.sleep = lambda *_: None
            fake_time.time_ns = lambda: 0
            await chat.trade_chat(ChatRequest(query="你好"), company["id"])

        fake_mem.save_with_context.assert_not_called()

        import trade.usage as usage
        from trade.database import get_connection

        conn = get_connection()
        try:
            # 3 次尝试（1 + 2 重试）各 400
            assert usage.tokens_today(conn, company["id"]) == 1200
        finally:
            conn.close()
