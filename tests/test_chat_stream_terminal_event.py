"""/chat/stream 必须以**终止事件**收场 —— 否则前端只能显示一句没有原因的话。

## 为什么需要这个约束（客户机实测，2026-10-08）

客户做「公司网站诊断」时前端只显示 `⚠️ Agent 未返回有效回复`。真实原因是
Hermes 的 `hermes_bootstrap.py` 把 server.py 重新 exec 到它自带的 store python
（那里没有 trade 包），子进程 ModuleNotFoundError 退出，父进程 `raise RelaunchExit(1)`。

`RelaunchExit` 继承 **SystemExit**，属 BaseException 而非 Exception，于是：

1. `trade/api/chat.py` 的重试循环里 `except Exception` 抓不到它 → agent 线程死亡
   （`Future exception was never retrieved`）；
2. `_event_stream` 在队列等待超时后只判断 `agent_task.done()` 就 break，
   **从不取 `agent_task.exception()`** → 异常被彻底吞掉；
3. `finally` 只补发 `done`，而前端 `trade_chat.js` 的 switch 没有 `done` 分支；
4. 前端 `responseText` 为空，落到兜底文案 —— 网络断、agent 崩、被丢弃，
   三类完全不同的问题长得一模一样。

前三条都是本文件要钉住的契约：**无论 agent 怎么失败，流里必须有一个终止事件
（`response` 或 `error`）说清原因。**
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class _AgentRaising:
    """模拟客户的真实故障：agent 一被调用就抛 BaseException。

    用 SystemExit 是因为 Hermes 的 `RelaunchExit` 就是它的子类 —— 这正是
    `except Exception` 抓不到的原因。用普通 Exception 测不出这个缺陷。
    """

    def __init__(self, exc: BaseException):
        self._exc = exc
        self.tool_start_callback = None
        self.tool_complete_callback = None

    def chat(self, query):  # noqa: ARG002
        raise self._exc

    def run_conversation(self, query, task_id=None):  # noqa: ARG002
        raise self._exc


@pytest.fixture
def company(monkeypatch, tmp_path):
    """临时库 + 一家公司（建目录的过程照 document_rules 那套 harness）。"""
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
    return co.create(name="SSE Co", slug="sse-co")


async def _collect_stream(company: dict, exc: BaseException) -> str:
    """驱动真实的 trade_chat_stream，把 SSE 响应体收成一个字符串。"""
    import trade.api.chat as chat
    from trade.api.models import ChatRequest

    with patch.object(chat, "create_agent", return_value=_AgentRaising(exc)), \
         patch.object(chat, "build_query", return_value=("Q", "H")), \
         patch.object(chat.chat_memory, "save_with_context", return_value={"id": 1}), \
         patch("trade.license.check_license", return_value=(True, "")):
        resp = await chat.trade_chat_stream(
            ChatRequest(query="帮我做一下公司网站诊断"), company["id"]
        )
        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk if isinstance(chunk, str) else chunk.decode("utf-8", "replace"))
        return "".join(chunks)


class TestStreamEndsWithTerminalEvent:
    """agent 以 BaseException 结束时，必须下发 error 事件。"""

    async def test_base_exception_produces_error_event(self, company):
        body = await _collect_stream(company, SystemExit(1))

        assert "event: error" in body, (
            "agent 以 SystemExit(1) 结束时流里没有 error 事件 —— "
            "前端只能显示「⚠️ Agent 未返回有效回复」，真实原因被吞掉。"
            f"\n实际流内容：{body!r}"
        )

    async def test_error_event_names_the_exception_type(self, company):
        """错误信息要带上异常类型，否则等于没说。"""
        body = await _collect_stream(company, SystemExit(1))

        assert "SystemExit" in body, f"错误事件未标明异常类型：{body!r}"

    async def test_not_retried(self, company):
        """BaseException 不是瞬时故障，不该进重试循环（重试只会拖时间）。

        断言方式：整个过程必须很快返回。若进了重试循环，会 sleep 1+2 秒。
        """
        import time

        start = time.time()
        await _collect_stream(company, SystemExit(1))
        elapsed = time.time() - start

        assert elapsed < 1.5, f"疑似进入了重试循环（耗时 {elapsed:.1f}s）"

    async def test_stream_always_carries_done(self, company):
        """无论成败，`done` 都要在（前端的流结束判据）。"""
        body = await _collect_stream(company, SystemExit(1))

        assert "event: done" in body
