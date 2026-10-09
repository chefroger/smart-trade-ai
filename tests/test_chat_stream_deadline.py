"""SSE 兜底超时必须下发 error 事件 —— 不能无声结束。

## 历史 bug

超时分支原先走 `_emit_threadsafe("error", ...)` 后立刻 `break`。而
`_emit_threadsafe` 是 `loop.call_soon_threadsafe(...)`，回调要在**下一轮事件循环**
才执行 —— 可 `_event_stream` 马上 break 并进 finally，那条 error 永远进不了队列，
更不会有人 yield 它。

结果：运行超过 30 分钟的任务（网站诊断、大型文档分析）在前端只显示
「⚠️ Agent 未返回有效回复」—— 用户既不知道是超时、也不知道任务已被中止。

修法：超时分支直接 `yield _sse("error", ...)`，不绕队列。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class _SlowAgent:
    """正常返回的 agent —— 超时判定与它的快慢无关（首个循环就检查 deadline）。"""

    def __init__(self):
        self.tool_start_callback = None
        self.tool_complete_callback = None

    def chat(self, query):  # noqa: ARG002
        return "本应永远到不了的回复"

    def run_conversation(self, query, task_id=None):  # noqa: ARG002
        return {"final_response": "本应永远到不了的回复"}


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
    return co.create(name="Deadline Co", slug="deadline-co")


async def _collect(company: dict) -> str:
    import trade.api.chat as chat
    from trade.api.models import ChatRequest

    # 让 deadline 立刻过期（负数 = 已超时）
    with patch.object(chat, "_STREAM_DEADLINE_SECONDS", -1.0), \
         patch.object(chat, "create_agent", return_value=_SlowAgent()), \
         patch.object(chat, "build_query", return_value=("Q", "H")), \
         patch.object(chat.chat_memory, "save_with_context", return_value={"id": 1}), \
         patch("trade.license.check_license", return_value=(True, "")):
        resp = await chat.trade_chat_stream(
            ChatRequest(query="做个网站诊断"), company["id"]
        )
        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk if isinstance(chunk, str) else chunk.decode("utf-8", "replace"))
        return "".join(chunks)


class TestDeadlineEmitsError:
    async def test_timeout_event_is_delivered(self, company):
        body = await _collect(company)

        assert "event: error" in body, (
            "超时事件没有下发 —— 用户只会看到「未返回有效回复」"
            f"\n实际流内容：{body!r}"
        )

    async def test_timeout_message_mentions_the_limit(self, company):
        body = await _collect(company)

        assert "30 分钟" in body or "30分钟" in body, f"超时文案缺失：{body!r}"

    async def test_stream_still_carries_done(self, company):
        """即便超时，`done` 仍要在（前端据此判断流正常收尾）。"""
        body = await _collect(company)

        assert "event: done" in body
