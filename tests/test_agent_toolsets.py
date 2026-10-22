"""Agent 默认 toolset 组合的回归测试 —— `vision` 必须在列。

## 为什么需要这个文件（实测踩出来的）

2026-09-29 用户让 Trade 识别界面截图，agent 没走视觉通道，而是自写 Swift 脚本调
macOS Apple Vision 框架 OCR（会话 20260929_084156_4120c8）。当时的成因判断错了一次：
我拿 `tools/vision_tools.py` 的 `check_vision_requirements()` 当依据，说「vision_analyze
可用」—— 但那个函数是工具的**能力门控**（`check_fn`），只在工具已经由 toolset 启用之后
才会被评估；决定工具在不在场的是 `enabled_toolsets`。

实测 `trade.helpers.create_agent()`（生产路径）解析出的工具表只有 20 个，**没有
`vision_analyze`**；把 `"vision"` 加进列表才变成 22 个并出现它。所以模型当时根本没有
看图工具 —— 自写 OCR 不是抗命，是没有别的路。

`vision` 缺失属历史遗留：`a4ae5d8` 引入这个列表时就没有，不是某次升级的回归。
"""

from __future__ import annotations

import pytest


class TestDefaultEnabledToolsets:
    """默认 toolset 组合的内容要求。"""

    def test_vision_toolset_is_enabled(self):
        """`vision` 必须在默认列表里 —— 否则 agent 完全没有看图能力。

        Hermes 的 `vision_analyze` 注册在 `toolset="vision"` 下
        （tools/vision_tools.py 的 registry.register），而 Trade 是**显式**传
        enabled_toolsets 的，不会继承 config.yaml 里的 toolsets。
        """
        from trade.helpers import DEFAULT_ENABLED_TOOLSETS

        assert "vision" in DEFAULT_ENABLED_TOOLSETS, (
            "默认 toolset 组合缺少 vision —— agent 将拿不到 vision_analyze，"
            "图片识别会退化为自建 OCR 或直接失败"
        )

    @pytest.mark.parametrize(
        "toolset",
        ["web", "search", "file", "terminal", "code_execution",
         "browser", "skills", "memory", "cronjob", "todo"],
    )
    def test_core_toolsets_retained(self, toolset):
        """原有的核心 toolset 一个都不能丢（这条改动只应做加法）。"""
        from trade.helpers import DEFAULT_ENABLED_TOOLSETS

        assert toolset in DEFAULT_ENABLED_TOOLSETS

    def test_no_duplicates(self):
        """列表不应有重复项（重复会让 Hermes 侧的解析做无谓功）。"""
        from trade.helpers import DEFAULT_ENABLED_TOOLSETS

        assert len(DEFAULT_ENABLED_TOOLSETS) == len(set(DEFAULT_ENABLED_TOOLSETS))

    def test_is_immutable_constant(self):
        """用不可变类型，避免被调用方就地改坏（原先是函数内的字面量）。"""
        from trade.helpers import DEFAULT_ENABLED_TOOLSETS

        assert not isinstance(DEFAULT_ENABLED_TOOLSETS, list)


class TestEnvOverride:
    """TRADE_ENABLED_TOOLSETS 仍然能整体覆盖默认组合。"""

    def test_env_override_replaces_defaults(self, monkeypatch):
        monkeypatch.setenv("TRADE_ENABLED_TOOLSETS", "web, file")
        from trade.helpers import resolve_enabled_toolsets

        assert resolve_enabled_toolsets() == ["web", "file"]

    def test_env_override_trims_and_drops_empties(self, monkeypatch):
        monkeypatch.setenv("TRADE_ENABLED_TOOLSETS", " web , file ,, ")
        from trade.helpers import resolve_enabled_toolsets

        assert resolve_enabled_toolsets() == ["web", "file"]

    def test_unset_env_returns_defaults(self, monkeypatch):
        """未设置环境变量时返回默认组合（含 vision）。"""
        monkeypatch.delenv("TRADE_ENABLED_TOOLSETS", raising=False)
        from trade.helpers import DEFAULT_ENABLED_TOOLSETS, resolve_enabled_toolsets

        resolved = resolve_enabled_toolsets()

        assert resolved == list(DEFAULT_ENABLED_TOOLSETS)
        assert "vision" in resolved

    def test_empty_env_falls_back_to_defaults(self, monkeypatch):
        """环境变量为空白串时按未设置处理。"""
        monkeypatch.setenv("TRADE_ENABLED_TOOLSETS", "   ")
        from trade.helpers import DEFAULT_ENABLED_TOOLSETS, resolve_enabled_toolsets

        assert resolve_enabled_toolsets() == list(DEFAULT_ENABLED_TOOLSETS)
