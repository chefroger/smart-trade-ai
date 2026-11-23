"""P0-5：任务中止时的「未完成报告」与「不重复执行工具」的重试。

验收场景：
  - 超时（同步 / 流式）但已跑过工具 → 历史里出现 partial 报告；
  - 空结果重试不再整轮重跑 → 工具不会被第二次执行。
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade.partial_report import (  # noqa: E402
    CompletedToolTracker,
    build_partial_report,
    build_summary_prompt,
)

# ── 纯函数层 ────────────────────────────────────────────────────────────────


def _tracker_with(*calls) -> CompletedToolTracker:
    tracker = CompletedToolTracker()
    for name, args, result in calls:
        tracker.on_complete(name, args, result)
    return tracker


class TestTracker:
    def test_counts_only_completed_calls(self):
        tracker = CompletedToolTracker()
        tracker.on_start("web_search", {"query": "acme"})
        assert tracker.has_completed() is False

        tracker.on_complete("web_search", {"query": "acme"}, "结果")
        assert tracker.has_completed() is True
        assert tracker.completed_count() == 1

    def test_preview_is_truncated(self):
        tracker = _tracker_with(("read_file", {"path": "/a.md"}, "x" * 5000))
        item = tracker.snapshot()[0]
        assert len(item["preview"]) <= 240

    def test_transcript_carries_results(self):
        tracker = _tracker_with(
            ("web_search", {"query": "acme supplier"}, "找到 3 条"),
            ("web_fetch", {"url": "https://acme.example"}, "页面正文"),
        )
        text = tracker.transcript()
        assert "网页搜索" in text and "acme supplier" in text
        assert "抓取网页" in text and "页面正文" in text


class TestPartialReport:
    def test_lists_checked_and_unchecked_channels(self):
        tracker = _tracker_with(
            ("web_search", {"query": "acme supplier"}, "找到 3 条"),
            ("read_file", {"path": "/docs/a.md"}, "内容"),
        )
        text = build_partial_report("超过 30 分钟自动中止", tracker)

        assert "⚠️ 未完成报告" in text
        assert "超过 30 分钟自动中止" in text
        assert "已查渠道" in text and "网页搜索" in text and "读取文件" in text
        assert "未查渠道" in text
        assert "不含推测" in text

    def test_no_tools_says_so_instead_of_faking_channels(self):
        tracker = CompletedToolTracker()
        text = build_partial_report("客户端断开或用户停止", tracker)
        assert "已查渠道：无" in text
        assert "未查渠道：全部" in text

    def test_summary_prompt_forbids_tool_calls(self):
        tracker = _tracker_with(("web_search", {"query": "acme"}, "找到 3 条"))
        prompt = build_summary_prompt("查一下 acme", tracker)
        assert "不要调用任何工具" in prompt
        assert "找到 3 条" in prompt
        assert "查一下 acme" in prompt


# ── 端点：环境 ──────────────────────────────────────────────────────────────


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
    return co.create(name="Partial Co", slug="partial-co")


class _ToolAgent:
    """跑两个工具后阻塞（模拟被超时中断的 Agent）。"""

    def __init__(self, release: threading.Event | None = None):
        self.release = release or threading.Event()
        self.tool_start_callback = None
        self.tool_complete_callback = None

    def _run_tools(self):
        if self.tool_start_callback:
            self.tool_start_callback("t1", "web_search", {"query": "acme supplier"})
            self.tool_start_callback("t2", "web_fetch", {"url": "https://acme.example"})
        if self.tool_complete_callback:
            self.tool_complete_callback(
                "t1", "web_search", {"query": "acme supplier"}, "找到 3 条结果",
            )
            self.tool_complete_callback(
                "t2", "web_fetch", {"url": "https://acme.example"}, "页面正文...",
            )

    def chat(self, query):  # noqa: ARG002
        self._run_tools()
        self.release.wait(2.0)
        return "太晚的回答"

    def run_conversation(self, query, task_id=None):  # noqa: ARG002
        return {"final_response": self.chat(query)}

    def hard_interrupt(self, *a, **k):  # noqa: ARG002
        self.release.set()


def _attach_callbacks(agent, kwargs):
    agent.tool_start_callback = kwargs.get("tool_start_callback")
    agent.tool_complete_callback = kwargs.get("tool_complete_callback")
    agent.enabled_toolsets = kwargs.get("enabled_toolsets")
    return agent


@pytest.mark.asyncio
async def test_sync_timeout_saves_partial_report(company):
    """同步超时但已跑过工具 → 响应是未完成报告，且 partial=True 落库。"""
    import trade.api.chat as chat
    from trade.api.models import ChatRequest

    agent = _ToolAgent()
    saved = []

    with patch.object(chat, "create_agent", side_effect=lambda **kw: _attach_callbacks(agent, kw)), \
         patch.object(chat, "build_query", return_value=("Q", "H")), \
         patch.object(chat, "_SYNC_TIMEOUT_SECONDS", 0.2), \
         patch.object(chat.chat_memory, "save_with_context",
                      side_effect=lambda **kw: saved.append(kw) or {"id": 7}), \
         patch("trade.license.check_license", return_value=(True, "")):
        result = await chat.trade_chat(ChatRequest(query="查一下 acme"), company["id"])

    assert result["partial"] is True
    assert "未完成报告" in result["response"]
    assert "已查渠道" in result["response"] and "网页搜索" in result["response"]
    assert len(saved) == 1
    assert saved[0]["partial"] is True
    assert saved[0]["retain_to_memory"] is False
    assert "未完成报告" in saved[0]["response"]


class _CountingAgent:
    """第一次返回空（但跑了 1 个工具），总结调用返回结论。"""

    def __init__(self, counter: list[int], summary: str = "基于已有结果的总结"):
        self.counter = counter
        self.summary = summary
        self.tool_complete_callback = None
        self.tool_start_callback = None
        self.enabled_toolsets = None

    def chat(self, query):
        if self.enabled_toolsets == []:
            # 总结调用：不带工具，只根据已有结果作答
            assert "已完成工具结果" in query
            return self.summary
        self.counter.append(1)
        if self.tool_complete_callback:
            self.tool_complete_callback(
                "t1", "web_search", {"query": "acme"}, "一次结果",
            )
        return ""


@pytest.mark.asyncio
async def test_empty_result_retry_does_not_rerun_tools(company):
    """空结果重试改为一次总结调用（工具禁用），工具只执行一次。"""
    import trade.api.chat as chat
    from trade.api.models import ChatRequest

    counter: list[int] = []
    summary_agent = _CountingAgent(counter)
    full_agent = _CountingAgent(counter)

    created = []

    def _factory(**kw):
        agent = summary_agent if kw.get("enabled_toolsets") == [] else full_agent
        created.append(agent)
        return _attach_callbacks(agent, kw)

    saved = []
    with patch.object(chat, "create_agent", side_effect=_factory), \
         patch.object(chat, "build_query", return_value=("Q", "H")), \
         patch.object(chat.chat_memory, "save_with_context",
                      side_effect=lambda **kw: saved.append(kw) or {"id": 1}), \
         patch("trade.license.check_license", return_value=(True, "")):
        result = await chat.trade_chat(ChatRequest(query="查一下 acme"), company["id"])

    assert result["response"] == "基于已有结果的总结"
    # 审计 P2-3：总结成功也是「凭部分结果整理的半成品」，必须标 partial
    assert result["partial"] is True
    assert len(counter) == 1, "工具被重复执行了"
    assert full_agent.enabled_toolsets != []
    assert summary_agent.enabled_toolsets == []
    assert len(saved) == 1
    assert saved[0]["partial"] is True
    assert saved[0]["retain_to_memory"] is False, "半成品总结不得进长期记忆"


@pytest.mark.asyncio
async def test_stream_summary_is_marked_partial(company):
    """流式：空响应后总结成功，response 事件带 partial 且落库 partial=True。"""
    import trade.api.chat as chat
    from trade.api.models import ChatRequest

    counter: list[int] = []
    summary_agent = _CountingAgent(counter)
    full_agent = _CountingAgent(counter)

    def _factory(**kw):
        return _attach_callbacks(
            summary_agent if kw.get("enabled_toolsets") == [] else full_agent, kw,
        )

    saved: list[dict] = []
    with patch.object(chat, "create_agent", side_effect=_factory), \
         patch.object(chat, "build_query", return_value=("Q", "H")), \
         patch.object(chat.chat_memory, "save_with_context",
                      side_effect=lambda **kw: saved.append(kw) or {"id": 9}), \
         patch("trade.license.check_license", return_value=(True, "")):
        resp = await chat.trade_chat_stream(
            ChatRequest(query="查一下 acme"), company["id"]
        )
        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk if isinstance(chunk, str) else chunk.decode("utf-8", "replace"))
    body = "".join(chunks)

    assert "基于已有结果的总结" in body
    assert '"partial": true' in body
    assert len(counter) == 1, "工具被重复执行了"
    assert len(saved) == 1
    assert saved[0]["partial"] is True
    assert saved[0]["retain_to_memory"] is False


class TestSyncRunBudget:
    """审计 P2-5：同步端点的预算必须小于外层 600s 超时。"""

    def test_default_is_capped_below_timeout(self):
        import trade.api.chat as chat

        assert chat._SYNC_TIMEOUT_SECONDS == 600.0
        assert chat._sync_run_budget() == 540

    def test_respects_lower_configured_budget(self, monkeypatch):
        import trade.api.chat as chat

        monkeypatch.setenv("TRADE_RUN_BUDGET_SECONDS", "300")
        assert chat._sync_run_budget() == 300

    def test_disabled_budget_stays_disabled(self, monkeypatch):
        import trade.api.chat as chat

        monkeypatch.setenv("TRADE_RUN_BUDGET_SECONDS", "0")
        assert chat._sync_run_budget() is None

    def test_short_timeout_keeps_positive_floor(self, monkeypatch):
        import trade.api.chat as chat

        monkeypatch.setattr(chat, "_SYNC_TIMEOUT_SECONDS", 120.0)
        assert chat._sync_run_budget() == 60


async def _collect_stream(company) -> tuple[str, list[dict]]:
    import trade.api.chat as chat
    from trade.api.models import ChatRequest

    saved: list[dict] = []
    with patch.object(chat, "_STREAM_DEADLINE_SECONDS", 0.2), \
         patch.object(chat, "create_agent", side_effect=lambda **kw: _attach_callbacks(_ToolAgent(), kw)), \
         patch.object(chat, "build_query", return_value=("Q", "H")), \
         patch.object(chat.chat_memory, "save_with_context",
                      side_effect=lambda **kw: saved.append(kw) or {"id": 3}), \
         patch("trade.license.check_license", return_value=(True, "")):
        resp = await chat.trade_chat_stream(
            ChatRequest(query="查一下 acme"), company["id"]
        )
        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk if isinstance(chunk, str) else chunk.decode("utf-8", "replace"))
    return "".join(chunks), saved


@pytest.mark.asyncio
async def test_stream_deadline_saves_partial_report(company):
    body, saved = await _collect_stream(company)

    assert "event: error" in body
    assert "未完成报告" in body and "已查渠道" in body
    assert "30 分钟" in body
    partial_saves = [s for s in saved if s.get("partial")]
    assert partial_saves, "流式超时后没有把未完成报告写进历史"
    assert "未完成报告" in partial_saves[0]["response"]
    # 迟到答案不得作为正常回答落库
    assert all(not s.get("partial") or "未完成报告" in s["response"] for s in saved)
    time.sleep(0.05)


class _ToolThenAnswerAgent:
    """跑一个工具后正常返回回答（模拟正常多步对话）。"""

    def __init__(self, answer: str = "这是最终回答"):
        self.answer = answer
        self.tool_start_callback = None
        self.tool_complete_callback = None
        self.enabled_toolsets = None

    def chat(self, query):  # noqa: ARG002
        if self.tool_complete_callback:
            self.tool_complete_callback("t1", "web_search", {"query": "acme"}, "结果")
        return self.answer

    def run_conversation(self, query, task_id=None):  # noqa: ARG002
        return {"final_response": self.chat(query)}


@pytest.mark.asyncio
async def test_stream_normal_answer_with_tools_saves_exactly_one(company):
    """审计 P1-1：跑过工具的正常回答只能写一条历史，不能多出「已中止」。"""
    import trade.api.chat as chat
    from trade.api.models import ChatRequest

    saved: list[dict] = []
    with patch.object(chat, "create_agent",
                      side_effect=lambda **kw: _attach_callbacks(_ToolThenAnswerAgent(), kw)), \
         patch.object(chat, "build_query", return_value=("Q", "H")), \
         patch.object(chat.chat_memory, "save_with_context",
                      side_effect=lambda **kw: saved.append(kw) or {"id": 5}), \
         patch("trade.license.check_license", return_value=(True, "")):
        resp = await chat.trade_chat_stream(
            ChatRequest(query="查一下 acme"), company["id"]
        )
        async for _ in resp.body_iterator:
            pass

    assert len(saved) == 1, f"写了 {len(saved)} 条历史：{[s['response'][:20] for s in saved]}"
    assert "未完成报告" not in saved[0]["response"]
    assert not saved[0]["partial"]


@pytest.mark.asyncio
async def test_stream_summary_race_never_writes_two_histories(company):
    """审计 P1-1：总结成功路径本机循环 200 次，每次只能写 1 条。"""
    import trade.api.chat as chat
    from trade.api.models import ChatRequest

    for i in range(200):
        counter: list[int] = []
        summary_agent = _CountingAgent(counter)
        full_agent = _CountingAgent(counter)

        # 默认参数把循环变量绑定进函数（ruff B023：闭包捕获循环变量会拿到最后一轮）
        def _factory(_summary=summary_agent, _full=full_agent, **kw):
            return _attach_callbacks(
                _summary if kw.get("enabled_toolsets") == [] else _full, kw,
            )

        saved: list[dict] = []

        def _save(_saved=saved, _id=i, **kw):
            _saved.append(kw)
            return {"id": _id}

        with patch.object(chat, "create_agent", side_effect=_factory), \
             patch.object(chat, "build_query", return_value=("Q", "H")), \
             patch.object(chat, "_check_chat_rate_limit", return_value=True), \
             patch.object(chat.chat_memory, "save_with_context", side_effect=_save), \
             patch("trade.license.check_license", return_value=(True, "")):
            resp = await chat.trade_chat_stream(
                ChatRequest(query="查一下 acme"), company["id"]
            )
            async for _ in resp.body_iterator:
                pass

        assert len(saved) == 1, (
            f"第 {i} 次写出了 {len(saved)} 条：{[s['response'][:24] for s in saved]}"
        )


class TestPartialReportEvidence:
    """工单 P1-G：未完成报告要带每个工具 1–2 行结果预览（隐私过滤）。"""

    def test_preview_included_for_each_tool(self):
        tracker = _tracker_with(
            ("web_search", {"query": "acme"}, "找到 3 条：Acme 官网、LinkedIn、年报"),
        )
        text = build_partial_report("客户端断开", tracker)
        assert "结果：找到 3 条" in text

    def test_preview_is_capped(self):
        tracker = _tracker_with(("web_fetch", {"url": "https://a"}, "长" * 1000))
        text = build_partial_report("超时", tracker)
        for line in text.splitlines():
            if line.strip().startswith("· 结果："):
                assert len(line) < 260, "单行预览超过 240 字"

    def test_family_and_gift_previews_are_hidden(self):
        tracker = _tracker_with(
            ("read_file", {"path": "/a.md"}, "重要日期：太太 Maria 生日"),
            ("web_fetch", {"url": "https://b"}, "客户索要：两瓶茅台"),
            ("web_search", {"query": "acme"}, "正常结果"),
        )
        text = build_partial_report("断开", tracker)
        assert "太太 Maria" not in text
        assert "茅台" not in text
        assert "[已按隐私规则隐藏]" in text
        assert "结果：正常结果" in text
