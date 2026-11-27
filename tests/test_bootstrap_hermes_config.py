"""
Bootstrap 修改 Hermes config.yaml 的安全与幂等测试（工单 #1）。

覆盖五种配置形态（有缩进列表、无缩进列表、行内列表、空值、无 plugins 段）
两轮连续启动流程，验证：
  - YAML 始终合法可解析
  - chat-memory 仅出现一次，第二轮完全幂等
  - 用户注释、其他键顺序与值不被破坏
  - background_review 先写、chat-memory 后写的顺序同样安全
  - 已损坏 YAML 不写盘且只告警一次
"""

from __future__ import annotations

import pytest
import yaml

from trade import bootstrap


def _run_startup_sequence() -> None:
    """按启动顺序连续调用 chat-memory 启用与 background_review 关闭。"""
    bootstrap.ensure_chat_memory_plugin_enabled()
    bootstrap.ensure_background_review_disabled()


@pytest.mark.parametrize(
    "case_name,initial_yaml",
    [
        (
            "indented_list",
            "# 用户自定义注释\n"
            "model: deepseek-flash\n"
            "plugins:\n"
            "  enabled:\n"
            "    - foo\n"
            "other_key: keep_me\n",
        ),
        (
            "indentless_list_without_target",
            "# 无缩进块序列（PyYAML safe_dump 默认形态）\n"
            "model: deepseek-flash\n"
            "plugins:\n"
            "  enabled:\n"
            "  - foo\n"
            "other_key: keep_me\n",
        ),
        (
            "indentless_list_with_target",
            "# 已有无缩进 chat-memory，不得重复插入\n"
            "model: deepseek-flash\n"
            "plugins:\n"
            "  enabled:\n"
            "  - chat-memory\n"
            "other_key: keep_me\n",
        ),
        (
            "inline_list",
            "# 行内列表\n"
            "model: deepseek-flash\n"
            "plugins:\n"
            "  enabled: [foo, bar]\n"
            "other_key: keep_me\n",
        ),
        (
            "empty_enabled",
            "# 空值列表\n"
            "model: deepseek-flash\n"
            "plugins:\n"
            "  enabled:\n"
            "other_key: keep_me\n",
        ),
        (
            "no_plugins_section",
            "# 无 plugins 段\n"
            "model: deepseek-flash\n"
            "other_key: keep_me\n",
        ),
    ],
)
def test_five_yaml_forms_idempotent_two_rounds(
    tmp_path, monkeypatch, case_name, initial_yaml
):
    """五种配置形态连续跑两遍启动流程：合法、去重、幂等、保留注释与他键。"""
    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir(parents=True, exist_ok=True)
    cfg = hermes_home / "config.yaml"
    cfg.write_text(initial_yaml, encoding="utf-8")

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    bootstrap._CORRUPT_CONFIG_WARNED.clear()

    # 第一轮启动
    _run_startup_sequence()
    after_round1 = cfg.read_text(encoding="utf-8")
    data1 = yaml.safe_load(after_round1)
    assert isinstance(data1, dict), case_name
    assert data1["model"] == "deepseek-flash"
    assert data1["other_key"] == "keep_me"
    assert data1["plugins"]["enabled"].count("chat-memory") == 1
    assert data1["auxiliary"]["background_review"]["enabled"] is False
    # 保留用户注释
    assert initial_yaml.splitlines()[0] in after_round1

    # 第二轮启动：完全幂等，不修改文件内容
    _run_startup_sequence()
    after_round2 = cfg.read_text(encoding="utf-8")
    assert after_round2 == after_round1


def test_background_review_first_then_chat_memory(tmp_path, monkeypatch):
    """先调 background_review 再调 chat-memory（历史上曾触发 safe_dump + 写坏）。"""
    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir(parents=True, exist_ok=True)
    cfg = hermes_home / "config.yaml"
    cfg.write_text(
        "# 保留注释\n"
        "auxiliary:\n"
        "  background_review:\n"
        "    enabled: true  # 旧配置开启\n"
        "plugins:\n"
        "  enabled:\n"
        "  - foo\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    bootstrap._CORRUPT_CONFIG_WARNED.clear()

    assert bootstrap.ensure_background_review_disabled() is True
    bootstrap.ensure_chat_memory_plugin_enabled()

    text = cfg.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert data["auxiliary"]["background_review"]["enabled"] is False
    assert data["plugins"]["enabled"] == ["foo", "chat-memory"]
    assert "# 保留注释" in text


def test_corrupt_yaml_never_overwritten_and_warns_once(tmp_path, monkeypatch, capsys):
    """输入已是损坏 YAML 时绝不写盘，且只提示一次并给出 .bak 路径。"""
    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir(parents=True, exist_ok=True)
    cfg = hermes_home / "config.yaml"
    corrupt_content = "plugins:\n  enabled:\n    - chat-memory\n  - chat-memory\n"
    cfg.write_text(corrupt_content, encoding="utf-8")

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    bootstrap._CORRUPT_CONFIG_WARNED.clear()

    _run_startup_sequence()
    _run_startup_sequence()

    # 原文件一个字节都不改
    assert cfg.read_text(encoding="utf-8") == corrupt_content
    out = capsys.readouterr().out
    assert out.count("YAML 语法错误") == 1
    assert ".bak" in out
