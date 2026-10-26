"""同步聊天超时后必须真正叫停 agent，且失败文案不落库（审计 P1-21）。

`asyncio.wait_for(loop.run_in_executor(...))` 超时只是放弃等待 —— Future 取消
停不掉线程，`agent.chat()` 里的工具调用会继续跑、继续烧 token。这里锁定：

1. 超时后调用 Hermes 的跨线程中断（interrupt/hard_interrupt）；
2. 超时后迟到的结果不再重试、不再当成功回复；
3. 失败兜底文案（超时/异常/空响应）不写入聊天历史。
"""

from __future__ import annotations

import asyncio
import sys
import threading
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
    return co.create(name="Timeout Co", slug="timeout-co")


class TestAbortRunningAgent:
    """中断的调用顺序与失败兜底：中断是上游内部 API，不能假设一定可用。"""

    def test_prefers_hard_interrupt(self):
        import trade.api.chat as chat

        calls = []

        class _Agent:
            def hard_interrupt(self, message=None):
                calls.append(("hard", message))

            def interrupt(self, *a, **k):  # 不应被调用
                calls.append(("soft", a, k))

        chat._abort_running_agent(_Agent())

        assert calls == [("hard", "trade: request timed out")]

    def test_falls_back_to_interrupt_without_hard_interrupt(self):
        import trade.api.chat as chat

        calls = []

        class _OldAgent:
            def interrupt(self, message=None, *, hard_cancel=False):
                calls.append((message, hard_cancel))

        chat._abort_running_agent(_OldAgent())

        assert calls == [("trade: request timed out", True)]

    def test_falls_back_to_positional_interrupt(self):
        import trade.api.chat as chat

        calls = []

        class _AncientAgent:
            def interrupt(self, message=None):
                calls.append(message)

        chat._abort_running_agent(_AncientAgent())

        assert calls == ["trade: request timed out"]

    def test_interrupt_failure_is_swallowed(self):
        import trade.api.chat as chat

        class _Broken:
            def hard_interrupt(self, *a, **k):
                raise RuntimeError("upstream broke")

        chat._abort_running_agent(_Broken())  # 不得抛

    def test_none_agent_is_noop(self):
        import trade.api.chat as chat

        chat._abort_running_agent(None)


class _BlockingAgent:
    """chat() 一直阻塞，直到 hard_interrupt() 放行 —— 模拟被中断的工具调用。"""

    def __init__(self, release: threading.Event, interrupted: threading.Event,
                 exc: Exception | None = None):
        self.release = release
        self.interrupted = interrupted
        self.exc = exc

    def hard_interrupt(self, message=None):
        self.interrupted.set()
        self.release.set()

    def chat(self, query):  # noqa: ARG002
        # 最多 2 秒：即使中断没送达，测试也不会挂死
        self.release.wait(2.0)
        if self.exc is not None:
            raise self.exc
        return "超时之后才返回的结果"

    def run_conversation(self, query, task_id=None):  # noqa: ARG002
        return {"final_response": self.chat(query)}


class TestSyncTimeoutAbortsAgent:
    @pytest.mark.asyncio
    async def test_timeout_interrupts_and_skips_save(self, company):
        import trade.api.chat as chat
        from trade.api.models import ChatRequest

        release = threading.Event()
        interrupted = threading.Event()
        agent = _BlockingAgent(release, interrupted)
        saved = []

        with patch.object(chat, "create_agent", return_value=agent), \
             patch.object(chat, "build_query", return_value=("Q", "H")), \
             patch.object(chat, "chat_memory") as fake_mem, \
             patch.object(chat, "_SYNC_TIMEOUT_SECONDS", 0.05), \
             patch("trade.license.check_license", return_value=(True, "")):
            fake_mem.save_with_context.side_effect = lambda **k: saved.append(k) or {"id": 1}
            result = await chat.trade_chat(ChatRequest(query="你好"), company["id"])

        assert "自动中止" in result["response"]
        assert result["conversation"] is None
        assert interrupted.is_set(), "超时后必须调用 Hermes 的中断接口"
        assert saved == [], "超时兜底文案不得写入聊天历史"

        # 让被中断的 worker 收尾，确认迟到结果也不会触发落库
        for _ in range(50):
            if release.is_set():
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        assert saved == [], "超时后迟到的结果不得再写入历史"

    @pytest.mark.asyncio
    async def test_interrupt_failure_still_returns_timeout_response(self, company):
        """中断接口炸了，超时响应也不能变成 500。"""
        import trade.api.chat as chat
        from trade.api.models import ChatRequest

        release = threading.Event()
        interrupted = threading.Event()

        class _BrokenAgent(_BlockingAgent):
            def hard_interrupt(self, message=None):
                interrupted.set()
                raise RuntimeError("upstream broke")

        agent = _BrokenAgent(release, interrupted)

        with patch.object(chat, "create_agent", return_value=agent), \
             patch.object(chat, "build_query", return_value=("Q", "H")), \
             patch.object(chat, "chat_memory") as fake_mem, \
             patch.object(chat, "_SYNC_TIMEOUT_SECONDS", 0.05), \
             patch("trade.license.check_license", return_value=(True, "")):
            result = await chat.trade_chat(ChatRequest(query="你好"), company["id"])

        assert "自动中止" in result["response"]
        fake_mem.save_with_context.assert_not_called()
        release.set()  # 放行 worker，避免测试结束时线程仍在等
