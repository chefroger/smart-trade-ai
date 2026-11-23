"""工单 P0-C：OSINT 路由命中后，交付前必须有制裁结论。

背景：2026-11-23 审计 P0-3 —— 人名说法匹配不到技能时走普通提示，OSINT
协议与制裁层整层不跑；即使路由命中了，模型也可能不写制裁段落。
交付前代码兜底：能补就跑本地制裁库，补不了就明确写「未执行（原因）」。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade.api import chat  # noqa: E402
from trade.partial_report import CompletedToolTracker  # noqa: E402


class TestTargetExtraction:
    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("Matthew Busel 是谁", "Matthew Busel"),
            ("查一下MatthewBusel这个人的资料", "MatthewBusel"),
            ("查查张伟这个人", "张伟"),
            ("王建国是谁", "王建国"),
            ("company:Acme Trading 有没有被制裁", "Acme Trading"),
            ("Can you check who owns acme-trading.com?", "acme-trading.com"),
            ("联系 bob@acme.com 查一下", "bob@acme.com"),
        ],
    )
    def test_extracts_screening_target(self, query, expected):
        assert chat._osint_target_from_query(query) == expected

    def test_empty_query_returns_none(self):
        assert chat._osint_target_from_query("   ") is None


class TestEnsureSection:
    def test_appends_when_osint_tool_not_used(self, monkeypatch):
        monkeypatch.setattr(
            chat, "_sanctions_fallback_text",
            lambda query: "制裁名单筛查：未命中（哨兵）",
        )
        tools = CompletedToolTracker()

        out = chat._ensure_sanctions_section(
            query="Jane Doe 是谁", response="她是采购负责人。", skill="b2b-osint", tools=tools,
        )

        assert "【制裁名单筛查】" in out
        assert "未命中（哨兵）" in out
        assert out.startswith("她是采购负责人。")

    def test_skips_when_tool_used_and_section_present(self, monkeypatch):
        monkeypatch.setattr(
            chat, "_sanctions_fallback_text",
            lambda query: "不应调用",
        )
        tools = CompletedToolTracker()
        tools.on_complete("osint_job_start", {"target": "acme.com"}, "{}")

        out = chat._ensure_sanctions_section(
            query="查一下 acme.com",
            response="制裁名单：未命中。",
            skill="b2b-osint",
            tools=tools,
        )

        assert out == "制裁名单：未命中。"

    def test_appends_when_tool_used_but_answer_omits_sanctions(self, monkeypatch):
        monkeypatch.setattr(
            chat, "_sanctions_fallback_text",
            lambda query: "制裁名单筛查：未命中（哨兵）",
        )
        tools = CompletedToolTracker()
        tools.on_complete("osint_job_start", {"target": "acme.com"}, "{}")

        out = chat._ensure_sanctions_section(
            query="查一下 acme.com", response="公司成立 2020 年。",
            skill="b2b-osint", tools=tools,
        )

        assert "【制裁名单筛查】" in out

    def test_other_skills_untouched(self, monkeypatch):
        monkeypatch.setattr(chat, "_sanctions_fallback_text", lambda q: "不应调用")
        out = chat._ensure_sanctions_section(
            query="写一封开发信", response="正文", skill="b2b-cold-outreach",
            tools=CompletedToolTracker(),
        )
        assert out == "正文"


class TestFallbackText:
    def _patch_check(self, monkeypatch, result: dict):
        import trade.osint.sanctions as sanctions

        monkeypatch.setattr(sanctions, "check_sanctions", lambda name, country=None: result)

    def test_degraded_says_not_executed(self, monkeypatch):
        self._patch_check(monkeypatch, {
            "hits": [], "is_sanctioned": False,
            "coverage": {"degraded": True, "total_entries": 0, "lists": {}},
        })
        text = chat._sanctions_fallback_text("Jane Doe 是谁")
        assert "未执行" in text and "不构成" in text

    def test_miss_reports_lists_and_stale(self, monkeypatch):
        self._patch_check(monkeypatch, {
            "hits": [], "is_sanctioned": False,
            "coverage": {
                "degraded": False, "total_entries": 1200,
                "lists": {
                    "OFAC": {"label": "OFAC SDN", "stale": True, "stale_hours": 80},
                    "UN": {"label": "UN", "stale": False},
                },
            },
        })
        text = chat._sanctions_fallback_text("Jane Doe 是谁")
        assert "未命中" in text and "2 份名单" in text and "1200" in text
        assert "OFAC SDN 过期 80 小时" in text

    def test_sanctioned_is_marked(self, monkeypatch):
        self._patch_check(monkeypatch, {
            "hits": [{"list_label": "OFAC SDN", "matched_value": "ACME CORP"}],
            "is_sanctioned": True,
            "coverage": {"degraded": False, "total_entries": 10, "lists": {"OFAC": {}}},
        })
        text = chat._sanctions_fallback_text("Acme Corp 有没有被制裁")
        assert "命中" in text and "ACME CORP" in text


# ── 端点集成：同步路径确实把兜底写进回答与历史 ─────────────────────────────


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
    return co.create(name="Delivery Co", slug="delivery-co")


class _Agent:
    def __init__(self, answer: str):
        self.answer = answer
        self.tool_start_callback = None
        self.tool_complete_callback = None

    def chat(self, query):  # noqa: ARG002
        return self.answer

    def run_conversation(self, query, task_id=None):  # noqa: ARG002
        return {"final_response": self.chat(query)}


@pytest.mark.asyncio
async def test_sync_route_appends_sanctions_section(company, monkeypatch):
    from trade.api.models import ChatRequest

    monkeypatch.setattr(
        chat, "_sanctions_fallback_text",
        lambda query: "制裁名单筛查：未命中（哨兵）",
    )
    saved: list[dict] = []
    with patch.object(chat, "build_query", return_value=("Q", "## 当前技能：b2b-osint")), \
         patch.object(chat, "create_agent", side_effect=lambda **kw: _Agent("她是采购负责人。")), \
         patch.object(chat.chat_memory, "save_with_context",
                      side_effect=lambda **kw: saved.append(kw) or {"id": 1}), \
         patch("trade.license.check_license", return_value=(True, "")):
        result = await chat.trade_chat(ChatRequest(query="Jane Doe 是谁"), company["id"])

    assert "【制裁名单筛查】" in result["response"]
    assert "未命中（哨兵）" in result["response"]
    assert saved and "未命中（哨兵）" in saved[0]["response"]


@pytest.mark.asyncio
async def test_stream_route_appends_sanctions_section(company, monkeypatch):
    """流式端点同样要在交付前补制裁段。"""
    from trade.api.models import ChatRequest

    monkeypatch.setattr(
        chat, "_sanctions_fallback_text",
        lambda query: "制裁名单筛查：未命中（哨兵）",
    )
    saved: list[dict] = []
    with patch.object(chat, "build_query", return_value=("Q", "## 当前技能：b2b-osint")), \
         patch.object(chat, "create_agent", side_effect=lambda **kw: _Agent("她是采购负责人。")), \
         patch.object(chat.chat_memory, "save_with_context",
                      side_effect=lambda **kw: saved.append(kw) or {"id": 2}), \
         patch("trade.license.check_license", return_value=(True, "")):
        resp = await chat.trade_chat_stream(
            ChatRequest(query="Jane Doe 是谁"), company["id"]
        )
        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk if isinstance(chunk, str) else chunk.decode("utf-8", "replace"))
    body = "".join(chunks)

    assert "【制裁名单筛查】" in body and "未命中（哨兵）" in body
    assert saved and "未命中（哨兵）" in saved[0]["response"]


def test_question_sentences_are_not_used_as_target(monkeypatch):
    """W2：疑问/指代句不能被整句当成筛查目标。"""
    for query in ("这个买家是不是骗子", "帮我查下这个客户靠谱吗"):
        assert chat._osint_target_from_query(query) is None
        text = chat._sanctions_fallback_text(query)
        assert "未执行" in text and "无法从问题中确定筛查对象" in text


def test_bare_targets_still_screened(monkeypatch):
    monkeypatch.setattr(
        "trade.osint.sanctions.check_sanctions",
        lambda name, country=None: {
            "hits": [], "is_sanctioned": False,
            "coverage": {"degraded": False, "total_entries": 10, "lists": {"OFAC": {}}},
        },
    )
    for query in ("天津赛得", "Huawei"):
        assert chat._osint_target_from_query(query) == query
        assert "未命中" in chat._sanctions_fallback_text(query)
