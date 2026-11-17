"""PR #11 审计修复的回归：XSS 数据源、缺列降级、画像校验、围栏解析。"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from trade import profile as profile_mod
from trade.chat_blocks import parse_trade_json_blocks
from trade.order import _is_missing_column


def test_currency_rejects_html_and_normalizes_case():
    from trade.api.orders import _clean_currency

    with pytest.raises(HTTPException) as exc:
        _clean_currency("<img src=x onerror=alert(1)>")
    assert exc.value.status_code == 400

    assert _clean_currency("usd") == "USD"
    assert _clean_currency("") is None


def test_missing_column_recognizes_both_sqlite_messages():
    assert _is_missing_column(Exception("no such column: incoterm"))
    assert _is_missing_column(
        Exception("table orders has no column named incoterm")
    )
    assert not _is_missing_column(Exception("database is locked"))


def test_profile_rejects_non_string_fields():
    with pytest.raises(profile_mod.ProfileError):
        profile_mod._as_str(123, "category")
    with pytest.raises(profile_mod.ProfileError):
        profile_mod._as_str(["喜好"], "content")
    assert profile_mod._as_str(None, "subject") == ""


def test_profile_ai_visible_flag_is_strict():
    assert profile_mod._as_flag("false", "ai_visible") == 0
    assert profile_mod._as_flag("true", "ai_visible") == 1
    assert profile_mod._as_flag(0, "ai_visible") == 0
    with pytest.raises(profile_mod.ProfileError):
        profile_mod._as_flag("yes", "ai_visible")


def test_profile_extract_limit_must_be_integer():
    with pytest.raises(profile_mod.ProfileError):
        profile_mod._as_int("abc", "limit", 20)
    assert profile_mod._as_int(None, "limit", 20) == 20


def test_gift_amount_rejects_inf_nan():
    kwargs = {
        "direction": "我方赠送",
        "item": "茶具",
        "currency": "EUR",
        "gift_date": "",
    }
    for bad in ("1e999", "inf", "NaN"):
        with pytest.raises(profile_mod.ProfileError):
            profile_mod._validate_gift_fields(approx_value=bad, **kwargs)


def test_trade_json_draft_with_triple_backticks_still_parses():
    text = (
        "正文\n```trade-json\n"
        '{"draft":{"lang":"en","subject":"s","body":"a ``` b"}}\n'
        "```"
    )
    clean, blocks = parse_trade_json_blocks(text)
    assert clean == "正文"
    assert blocks["draft"]["body"] == "a ``` b"


def test_trade_json_all_filtered_actions_keeps_original_text():
    text = (
        "Hi\n```trade-json\n"
        '{"next_actions":[{"label":"加待办","action":"add_todo"}]}\n'
        "```"
    )
    clean, blocks = parse_trade_json_blocks(text)
    assert blocks is None
    assert clean == text
