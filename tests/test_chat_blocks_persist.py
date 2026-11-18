"""W10/P1-5：trade-json 结构化块落库，并能回放给前端与下一轮 AI。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _init(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    from trade import database

    database.init_db()


def test_blocks_persist_and_reach_next_turn(tmp_path, monkeypatch):
    """块存 extra1；列表/历史上下文都能读到。"""
    _init(tmp_path, monkeypatch)
    from trade import chat_memory, company

    co = company.create(name="Blocks Co", slug="blocks-co")
    blocks = {
        "facts": [{"label": "价格", "value": "USD 1.0"}],
        "draft": {"lang": "zh", "subject": "报价草稿", "body": "Dear buyer"},
        "next_actions": [{"label": "生成PI", "action": "gen_pi"}],
    }
    conv = chat_memory.save_with_context(
        company_id=co["id"], query="报个价", response="已报价",
        blocks=blocks,
    )
    assert conv["id"]

    rows = chat_memory.list_by_company(co["id"], limit=10)
    assert rows[0]["extra1"]["trade_blocks"] == blocks

    recent = chat_memory.get_recent(co["id"], limit=5)
    assert recent[0]["extra1"]["trade_blocks"] == blocks

    from trade.helpers import _get_history_block

    block, _ = _get_history_block(co["id"], 1000)
    assert "assistant blocks:" in block
    assert "价格=USD 1.0" in block
    assert "报价草稿" in block
    assert "生成PI" in block


def test_blocks_default_empty(tmp_path, monkeypatch):
    """没有块时不写 extra1，保持旧行形态。"""
    _init(tmp_path, monkeypatch)
    from trade import chat_memory, company

    co = company.create(name="No Blocks Co", slug="no-blocks-co")
    conv = chat_memory.save_with_context(
        company_id=co["id"], query="q", response="r",
    )
    assert conv["extra1"] == {}


def test_blocks_summary_is_bounded():
    """摘要压成一行并截断，避免把整段草稿塞进 prompt。"""
    from trade.helpers import _blocks_history_summary

    assert _blocks_history_summary(None) == ""
    assert _blocks_history_summary([1, 2]) == ""
    summary = _blocks_history_summary({
        "facts": [{"label": "a\nb", "value": "c"}],
        "draft": {"subject": "长" * 400},
        "next_actions": [{"label": "生成PI", "action": "gen_pi"}],
    })
    assert "\n" not in summary
    assert len(summary) <= 300
