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
            ("Jane Doe 是谁", "Jane Doe"),
            ("查一下JaneDoe这个人的资料", "JaneDoe"),
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

    @pytest.mark.parametrize(
        ("query", "expected_target", "expected_reason"),
        [
            # S2 专名优先：没有查询意图词时也要取出拉丁专名
            ("能不能和 Rosneft 做生意", "Rosneft", ""),
            ("帮我背调 Rosneft", "Rosneft", ""),
            ("和 Huawei 合作有风险吗", "Huawei", ""),
            # S2 中文目标：剥掉疑问/动词后剩下的中文串
            ("背调一下华为", "华为", "cjk"),
            ("帮我查一下华为", "华为", "cjk"),
            ("海康威视", "海康威视", "cjk"),
            ("华为有没有被制裁", "华为", "cjk"),
            ("帮我看看天津赛得", "天津赛得", "cjk"),
            ("天津赛得", "天津赛得", "cjk"),
            # 指代/疑问句取不到对象
            ("这个买家是不是骗子", None, "ambiguous"),
            ("帮我查下这个客户靠谱吗", None, "ambiguous"),
        ],
    )
    def test_target_info_marks_cjk_and_ambiguous(self, query, expected_target, expected_reason):
        assert chat._osint_target_info(query) == (expected_target, expected_reason)


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
    # 英文裸名照常给「未命中」
    assert chat._osint_target_from_query("Huawei") == "Huawei"
    assert "未命中" in chat._sanctions_fallback_text("Huawei")
    # S2：中文裸名能取到目标、也真的查过了，但英文名单无法比对 → 不写「未命中」
    assert chat._osint_target_from_query("天津赛得") == "天津赛得"
    text = chat._sanctions_fallback_text("天津赛得")
    assert "未执行" in text and "中文名称无法比对" in text
    assert "未命中" not in text


class TestS2ChineseAndQuestionFallback:
    """S2 验收表：中文目标 → 未执行（中文名）；专名优先 → 命中。"""

    def _no_hit_complete(self, monkeypatch):
        monkeypatch.setattr(
            "trade.osint.sanctions.check_sanctions",
            lambda name, country=None: {
                "hits": [], "is_sanctioned": False,
                "coverage": {"degraded": False, "total_entries": 10, "lists": {"OFAC": {}}},
            },
        )

    def _confirmed_hit(self, monkeypatch, value="ROSNEFT"):
        monkeypatch.setattr(
            "trade.osint.sanctions.check_sanctions",
            lambda name, country=None: {
                "hits": [{"list_label": "OFAC SDN", "matched_value": value,
                          "confirmation": "confirmed"}],
                "is_sanctioned": True,
                "coverage": {"degraded": False, "total_entries": 10, "lists": {"OFAC": {}}},
            },
        )

    @pytest.mark.parametrize(
        "query",
        [
            "背调一下华为",
            "帮我查一下华为",
            "海康威视",
            "华为有没有被制裁",
            "帮我看看天津赛得",
            "天津赛得",
        ],
    )
    def test_cjk_targets_without_hits_are_not_executed(self, monkeypatch, query):
        self._no_hit_complete(monkeypatch)
        text = chat._sanctions_fallback_text(query)
        assert "未执行" in text and "中文名称无法比对" in text
        assert "未命中" not in text

    @pytest.mark.parametrize(
        "query",
        [
            "能不能和 Rosneft 做生意",
            "帮我背调 Rosneft",
            "和 Huawei 合作有风险吗",
        ],
    )
    def test_latin_proper_name_is_screened(self, monkeypatch, query):
        self._confirmed_hit(monkeypatch)
        text = chat._sanctions_fallback_text(query)
        assert "⚠️ 命中" in text
        assert "ROSNEFT" in text

    def test_pronoun_questions_stay_not_executed(self, monkeypatch):
        self._no_hit_complete(monkeypatch)
        for query in ("这个买家是不是骗子", "帮我查下这个客户靠谱吗"):
            text = chat._sanctions_fallback_text(query)
            assert "未执行" in text and "无法从问题中确定筛查对象" in text


def test_verb_prefix_is_stripped_but_pronouns_still_blocked():
    """O-新2：剥掉查询动词后取目标；指代/疑问句仍不猜。"""
    assert chat._osint_target_from_query("帮我查一下华为") == "华为"
    assert chat._osint_target_from_query("查一下 Huawei") == "Huawei"
    assert chat._osint_target_from_query("帮我查下这个客户靠谱吗") is None
    assert chat._osint_target_from_query("这个买家是不是骗子") is None


class TestO26EnglishQuestionTargets:
    """O-新26：英文问句不能再把 Is/Can/Does/Was/Check 混进目标。"""

    def _complete(self, monkeypatch):
        monkeypatch.setattr(
            "trade.osint.sanctions.check_sanctions",
            lambda name, country=None: {
                "hits": [], "is_sanctioned": False,
                "coverage": {"degraded": False, "total_entries": 10, "lists": {"OFAC": {}}},
            },
        )

    @pytest.mark.parametrize("query", [
        "Is Huawei sanctioned?",
        "Can Huawei be sanctioned?",
        "Does Huawei have sanctions?",
        "Was Huawei sanctioned?",
        "Check Huawei for sanctions",
    ])
    def test_english_questions_use_bare_target(self, monkeypatch, query):
        self._complete(monkeypatch)
        assert chat._osint_target_info(query) == ("Huawei", "")
        text = chat._sanctions_fallback_text(query)
        # 现在比对的是 Huawei 本身：可以如实写未命中，但不能再出现 "Is Huawei"
        assert "Is Huawei" not in text and "Can Huawei" not in text
        assert "未命中" in text

    def test_chinese_cases_unchanged(self):
        assert chat._osint_target_info("帮我查一下华为有没有被制裁") == ("华为", "cjk")
        assert chat._osint_target_info("这个买家是不是骗子") == (None, "ambiguous")


def test_o29_known_limitation_multi_target_not_split(monkeypatch):
    """O-新29 已知局限：多目标不拆分，但方向安全（不会给假绿字）。"""
    monkeypatch.setattr(
        "trade.osint.sanctions.check_sanctions",
        lambda name, country=None: {
            "hits": [], "is_sanctioned": False,
            "coverage": {"degraded": False, "total_entries": 10, "lists": {"OFAC": {}}},
        },
    )
    # 现状：整串当一个中文目标（「和」不拆，避免误伤和记黄埔这类名称）
    assert chat._osint_target_info("华为和中兴有没有被制裁") == ("华为和中兴", "cjk")
    text = chat._sanctions_fallback_text("华为和中兴有没有被制裁")
    assert "未执行" in text and "中文名称无法比对" in text
    assert "未命中" not in text
