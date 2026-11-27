"""P8 回归测试：长报告输出预算（max_tokens）与 finish_reason=length 截断提示。"""

from __future__ import annotations

import types


def test_long_report_skill_sets_max_tokens_override(monkeypatch):
    """b2b-osint 等长报告技能在 deepseek 上也应注入较高 max_tokens 预算。"""
    from trade import helpers

    monkeypatch.delenv("TRADE_LONG_REPORT_MAX_TOKENS", raising=False)
    ov = helpers._consistency_request_overrides("b2b-osint", "deepseek")
    assert ov is not None
    assert ov["max_tokens"] == 8192

    # 环境变量可覆盖
    monkeypatch.setenv("TRADE_LONG_REPORT_MAX_TOKENS", "12000")
    ov2 = helpers._consistency_request_overrides("b2b-osint", "deepseek")
    assert ov2 is not None
    assert ov2["max_tokens"] == 12000

    # 普通创作类非长报告不强加 max_tokens
    ov3 = helpers._consistency_request_overrides("b2b-cold-outreach", "deepseek")
    assert ov3 is None


def test_detect_length_truncated_helper():
    """finish_reason='length' 时能正确识别并标记 truncated。"""
    from trade.api.chat import _is_length_truncated

    assert _is_length_truncated(None) is False
    assert _is_length_truncated(types.SimpleNamespace(last_finish_reason="stop")) is False
    assert _is_length_truncated(types.SimpleNamespace(last_finish_reason="length")) is True
    assert _is_length_truncated(types.SimpleNamespace(_last_finish_reason="LENGTH")) is True
