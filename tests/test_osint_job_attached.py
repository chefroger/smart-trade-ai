"""工单 §4-B1：osint_job_start 完成后必须补发 job_attached。

前端靠这条事件把 task 面板挂进聊天流；靠解析被截断的 result_preview 不可靠。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def company(monkeypatch, tmp_path):
    """临时库 + 一家公司（与 test_chat_stream_terminal_event 同一套 harness）。"""
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
    return co.create(name="Attach Co", slug="attach-co")


class _AgentEmittingJobStart:
    """agent.chat 里直接回调一次 osint_job_start 的完成事件。"""

    def __init__(self):
        self.tool_start_callback = None
        self.tool_complete_callback = None

    def chat(self, query):  # noqa: ARG002
        self.tool_complete_callback(
            "tc-1", "osint_job_start", {"target": "acme.com"},
            json.dumps({"job_id": 42, "status": "queued", "reused": False, "target": "acme.com"}),
        )
        return "已启动后台背调。"

    def run_conversation(self, query, task_id=None):  # noqa: ARG002
        return self.chat(query)


async def _collect(company: dict) -> str:
    import trade.api.chat as chat
    from trade.api.models import ChatRequest

    def _make_agent(**kwargs):
        agent = _AgentEmittingJobStart()
        agent.tool_start_callback = kwargs.get("tool_start_callback")
        agent.tool_complete_callback = kwargs.get("tool_complete_callback")
        return agent

    with patch.object(chat, "create_agent", side_effect=_make_agent), \
         patch.object(chat, "build_query", return_value=("Q", "H")), \
         patch.object(chat.chat_memory, "save_with_context", return_value={"id": 1}), \
         patch("trade.license.check_license", return_value=(True, "")):
        resp = await chat.trade_chat_stream(ChatRequest(query="查一下 acme.com"), company["id"])
        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk if isinstance(chunk, str) else chunk.decode("utf-8", "replace"))
        return "".join(chunks)


class TestJobAttached:
    async def test_stream_emits_job_attached_with_job_id(self, company):
        body = await _collect(company)
        assert "event: job_attached" in body, f"流里没有 job_attached：{body!r}"
        assert '"job_id": 42' in body
        assert '"target": "acme.com"' in body

    def test_parse_rejects_non_plugin_payloads(self):
        from trade.api.chat import _parse_osint_job_attachment

        assert _parse_osint_job_attachment('{"job_id": 3, "target": "x"}') == {
            "job_id": 3, "target": "x",
        }
        assert _parse_osint_job_attachment('{"job_id": 0}') is None
        assert _parse_osint_job_attachment('{"job_id": true}') is None
        assert _parse_osint_job_attachment("not json") is None
        assert _parse_osint_job_attachment({"job_id": 5, "target": "y"}) == {
            "job_id": 5, "target": "y",
        }
