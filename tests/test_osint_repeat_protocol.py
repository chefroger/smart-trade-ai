"""OSINT 技能连续调用时必须**每次都注入完整协议**。

## 为什么

`build_query` 有一个「连续同 skill 走简短提示」的省 token 机制：第二次触发同一技能时，
只发一句「继续使用 X 技能，规则同上一次。」而不是完整 injection_prompt（~1500-3000 字）。

这套机制对**能看见历史**的技能成立 —— 模型能从对话历史里读到上一次的规则。
但 OSINT 类技能**不注入历史**（`build_query` 里 `if matched_name not in _OSINT_SKILL_NAMES`
才取 history_block，理由是「每次背调目标是独立的」）。

于是第二次背调时：
  - system hint 只有一句「规则同上一次」
  - 而「上一次」对模型不可见（没有历史）
  → **b2b-osint 的三阶段协议、溯源铁律整块丢失**，AI 自由发挥：不查 WHOIS、
    不查制裁名单、不给来源 URL。用户看到的是「第一次很专业，后面明显敷衍」。

`augmented_query` 那条路径已经给 OSINT 加了豁免（helpers.py:484），但
`skill_system_hint` 这条没有 —— 本文件钉住它。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 从 injection_prompt 里取的稳定标记（协议正文的开头）
PROTOCOL_MARKER = "Strategic Intelligence Architect"


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
    return co.create(name="Osint Co", slug="osint-co")


OSINT_QUERY = "帮我做一下客户背景调查（OSINT），目标是 example.com"


def _hint(company, last_skill):
    import trade.helpers as helpers

    _prompt, hint = helpers.build_query(
        company["id"], None, OSINT_QUERY, last_skill_name=last_skill
    )
    return hint or ""


class TestOsintAlwaysGetsFullProtocol:
    def test_first_call_has_protocol(self, company):
        """前置条件：首次调用本来就注入完整协议。"""
        assert PROTOCOL_MARKER in _hint(company, None)

    def test_second_call_still_has_protocol(self, company):
        """第二次连续背调也必须拿到完整协议。

        因为 OSINT 不注入历史 ——「规则同上一次」里的「上一次」模型根本看不到。
        """
        hint = _hint(company, "b2b-osint")

        assert PROTOCOL_MARKER in hint, (
            "第二次背调丢失了完整协议（只剩「规则同上一次」，而 OSINT 不看历史）—— "
            "agent 会退化为自由发挥：不查 WHOIS/制裁名单、不给来源"
        )

    def test_second_call_is_not_the_short_hint(self, company):
        """明确断言：不得走那句短路文案。"""
        hint = _hint(company, "b2b-osint")

        assert "规则同上一次" not in hint, "OSINT 走了简短提示分支（协议丢失）"
