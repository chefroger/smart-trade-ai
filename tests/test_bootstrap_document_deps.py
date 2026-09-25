"""Trade 启动时补齐 Hermes 文档解析依赖的测试。"""

from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade import bootstrap


def _fake_lazy_deps(available: bool, calls: list):
    """构造一个假的 tools.lazy_deps 模块。"""
    module = types.ModuleType("tools.lazy_deps")

    def is_available(feature):
        return available

    def ensure(feature, *, prompt=True):
        calls.append((feature, prompt))

    module.is_available = is_available
    module.ensure = ensure
    return module


def test_missing_document_deps_are_reported(monkeypatch):
    """依赖缺失时应被检测出来。"""
    fake = _fake_lazy_deps(available=False, calls=[])
    monkeypatch.setitem(sys.modules, "tools.lazy_deps", fake)

    assert bootstrap._document_deps_missing() is True


def test_present_document_deps_are_not_reported(monkeypatch):
    """依赖已安装时不报告缺失。"""
    fake = _fake_lazy_deps(available=True, calls=[])
    monkeypatch.setitem(sys.modules, "tools.lazy_deps", fake)

    assert bootstrap._document_deps_missing() is False


def test_install_document_deps_forces_non_interactive_install(monkeypatch):
    """安装必须强制且非交互，避免启动时等人输入。"""
    calls = []
    fake = _fake_lazy_deps(available=False, calls=calls)
    monkeypatch.setitem(sys.modules, "tools.lazy_deps", fake)

    bootstrap._install_document_deps()

    assert calls == [("tool.doc_extract", False)]


def test_install_failure_does_not_raise(monkeypatch):
    """安装失败不能让启动崩溃。"""
    module = types.ModuleType("tools.lazy_deps")

    def ensure(feature, *, prompt=True):
        raise RuntimeError("network down")

    module.is_available = lambda feature: False
    module.ensure = ensure
    monkeypatch.setitem(sys.modules, "tools.lazy_deps", module)

    bootstrap._install_document_deps()
