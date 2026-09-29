"""bootstrap._adjust_sys_path 的 Hermes checkout 解析测试。

历史 bug：函数把 `HERMES_HOME` 本身当成 Hermes checkout 插进 sys.path。但
HERMES_HOME 是**数据根目录**（~/.hermes），checkout 在其下的 `hermes-agent/`。
而 `~/.local/bin/trade` 包装脚本恰好 `export HERMES_HOME=/Users/.../.hermes`，
于是插进去的是数据根目录（里面没有 hermes_cli）。

这个缺陷长期被掩盖：venv 的 site-packages 里另有一份 hermes-agent 兜底。
2026-09-28 清理掉那份冗余副本后，聊天立刻报「AI Agent 模块未加载」。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade import bootstrap


def _make_checkout(root: Path) -> Path:
    """在 root 下造一个含 hermes_cli 包的假 checkout。"""
    pkg = root / "hermes_cli"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text('__version__ = "0.21.4"\n', encoding="utf-8")
    return root


@pytest.fixture
def isolated(monkeypatch):
    """隔离 sys.path 与 sys.modules，避免测试互相污染。"""
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.delitem(sys.modules, "hermes_cli", raising=False)
    return monkeypatch


class TestHermesCheckoutResolution:
    """HERMES_HOME 指向数据根目录时，必须解析到其下的 hermes-agent。"""

    def test_resolves_nested_checkout_when_hermes_home_is_data_root(self, isolated, tmp_path):
        """HERMES_HOME=~/.hermes（数据根）→ 应插入 ~/.hermes/hermes-agent。"""
        data_root = tmp_path / "hermes"
        data_root.mkdir()
        checkout = _make_checkout(data_root / "hermes-agent")
        isolated.setenv("HERMES_HOME", str(data_root))

        bootstrap._adjust_sys_path()

        # 只断言路径，不调用 find_spec/import —— CI 会屏蔽 Hermes 顶层模块，
        # 任何触发导入系统的调用在那里都会抛 ImportError（本用例曾因此在 ci_sim 下挂）
        assert (checkout / "hermes_cli" / "__init__.py").is_file(), "假 checkout 未造好"
        assert str(checkout) in sys.path, f"未插入 checkout：{sys.path[:3]}"
        assert str(data_root) not in sys.path, "数据根目录不该被当成 checkout 插入"
        # 关键不变量：checkout 必须排在 site-packages 之前 —— 否则同名包会遮蔽它
        # （这正是 site-packages 里那份 0.18.0 长期顶替 checkout 的机制）
        site_indexes = [i for i, p in enumerate(sys.path) if p.endswith("site-packages")]
        if site_indexes:
            assert sys.path.index(str(checkout)) < min(site_indexes), \
                "checkout 排在 site-packages 之后，会被同名包遮蔽"

    def test_accepts_hermes_home_pointing_at_checkout_itself(self, isolated, tmp_path):
        """HERMES_HOME 直接就指向 checkout（其下有 hermes_cli）时按原样使用。"""
        checkout = _make_checkout(tmp_path / "checkout")
        isolated.setenv("HERMES_HOME", str(checkout))

        bootstrap._adjust_sys_path()

        assert str(checkout) in sys.path

    def _make_default_checkout(self, isolated, tmp_path) -> Path:
        """按**平台约定**造一个「默认位置」的假 checkout 并返回它。

        生产代码在 Windows 走 %LOCALAPPDATA%\\hermes\\hermes-agent，
        POSIX 走 ~/.hermes/hermes-agent —— 测试必须跟着平台走，
        否则会写成 Unix 专用（本用例曾在 CI 的 windows 任务上挂过）。
        """
        if os.name == "nt":
            base = tmp_path / "localappdata"
            isolated.setenv("LOCALAPPDATA", str(base))
            return _make_checkout(base / "hermes" / "hermes-agent")
        fake_home = tmp_path / "home"
        isolated.setattr(Path, "home", classmethod(lambda cls: fake_home))
        return _make_checkout(fake_home / ".hermes" / "hermes-agent")

    def _make_default_probe_fail(self, isolated, tmp_path) -> None:
        """让「平台默认位置」探测落空，隔离真实机器上的 ~/.hermes。"""
        if os.name == "nt":
            isolated.setenv("LOCALAPPDATA", str(tmp_path / "empty-localappdata"))
        else:
            isolated.setattr(Path, "home", classmethod(lambda cls: tmp_path / "nohome"))

    def test_does_not_insert_data_root_without_checkout(self, isolated, tmp_path):
        """HERMES_HOME 里没有 checkout 时，绝不能把该目录本身当 checkout 插入。"""
        data_root = tmp_path / "hermes"
        data_root.mkdir()  # 空目录：既非 checkout 也没有 hermes-agent/
        isolated.setenv("HERMES_HOME", str(data_root))
        self._make_default_probe_fail(isolated, tmp_path)

        bootstrap._adjust_sys_path()

        assert str(data_root) not in sys.path, "数据根目录被误当 checkout 插入"

    def test_falls_back_to_default_location_when_hermes_home_lacks_checkout(self, isolated, tmp_path):
        """HERMES_HOME 下没有 checkout 时，回退到平台默认路径。"""
        data_root = tmp_path / "hermes"
        data_root.mkdir()
        isolated.setenv("HERMES_HOME", str(data_root))
        checkout = self._make_default_checkout(isolated, tmp_path)

        bootstrap._adjust_sys_path()

        assert str(checkout) in sys.path, f"未回退到默认位置：{sys.path[:3]}"

    def test_unset_hermes_home_uses_default_location(self, isolated, tmp_path):
        """回归护栏：HERMES_HOME 未设置时仍走平台默认路径。"""
        isolated.delenv("HERMES_HOME", raising=False)
        checkout = self._make_default_checkout(isolated, tmp_path)

        bootstrap._adjust_sys_path()

        assert str(checkout) in sys.path
