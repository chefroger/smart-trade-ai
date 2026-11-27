"""U1 / U3 / U4 回归测试。"""

from __future__ import annotations

import yaml


def test_u3_prompt_forbids_customer_email_in_signature():
    """U3：系统提示词必须明确禁止把客户邮箱写进发件人落款。"""
    from trade import prompt

    assert "NEVER put the customer's/recipient's email" in prompt.TRADE_JSON_BLOCKS_HINT


def test_u4_ensure_background_review_disabled_sets_false_and_respects_opt_in(monkeypatch, tmp_path):
    """U4：默认关闭 auxiliary.background_review.enabled；设置环境变量时跳过。"""
    from trade import bootstrap

    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir()
    cfg = hermes_home / "config.yaml"
    cfg.write_text(
        "model:\n  provider: deepseek\nauxiliary:\n  background_review:\n    enabled: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("trade.post_install.skills._get_hermes_home", lambda: hermes_home)

    # 显式允许自改写时不改动
    monkeypatch.setenv("TRADE_ALLOW_SKILL_SELF_IMPROVE", "1")
    assert bootstrap.ensure_background_review_disabled() is False
    assert yaml.safe_load(cfg.read_text(encoding="utf-8"))["auxiliary"]["background_review"]["enabled"] is True

    # 默认行为：关闭 background_review 并留 .bak
    monkeypatch.delenv("TRADE_ALLOW_SKILL_SELF_IMPROVE", raising=False)
    assert bootstrap.ensure_background_review_disabled() is True
    parsed = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert parsed["auxiliary"]["background_review"]["enabled"] is False
    assert (hermes_home / "config.yaml.bak").is_file()

    # 幂等：再次调用返回 False
    assert bootstrap.ensure_background_review_disabled() is False
