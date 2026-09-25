"""Trade 启动时补齐文档解析依赖的测试。"""

from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade import bootstrap


def _block_imports(monkeypatch, *names):
    """让指定模块的导入失败。"""
    for name in names:
        monkeypatch.setitem(sys.modules, name, None)


def test_all_document_deps_present(monkeypatch):
    """依赖齐全时不报告缺失。"""
    _block_imports(monkeypatch)
    monkeypatch.setattr(bootstrap, "_importable", lambda name: True)

    assert bootstrap._document_deps_missing() == []


def test_missing_anydoc_is_reported(monkeypatch):
    """缺少 PDF 解析依赖时要报出来。"""
    monkeypatch.setattr(bootstrap, "_importable", lambda name: name != "anydoc")

    missing = bootstrap._document_deps_missing()

    assert [spec for _mod, spec in missing] == ["firecrawl-anydoc==0.2.4"]


def test_missing_pypdfium_is_reported(monkeypatch):
    """缺少分页探测依赖时也要报出来。"""
    monkeypatch.setattr(bootstrap, "_importable", lambda name: name != "pypdfium2")

    missing = bootstrap._document_deps_missing()

    assert [spec for _mod, spec in missing] == ["pypdfium2>=4.30.0,<6.0"]


def test_install_prefers_hermes_lazy_deps_for_anydoc(monkeypatch):
    """anydoc 走 Hermes 自己的安装机制，保持与其 pyproject 一致。"""
    calls = []
    lazy = types.ModuleType("tools.lazy_deps")
    lazy.ensure = lambda feature, prompt=True: calls.append(("lazy", feature))
    monkeypatch.setitem(sys.modules, "tools.lazy_deps", lazy)
    monkeypatch.setattr(bootstrap, "_importable", lambda name: name != "anydoc")
    monkeypatch.setattr(bootstrap, "_pip_install", lambda specs: calls.append(("pip", tuple(specs))))

    bootstrap._install_document_deps()

    assert ("lazy", "tool.doc_extract") in calls
    assert ("pip", ("pypdfium2>=4.30.0,<6.0",)) not in calls


def test_install_uses_pip_for_pypdfium(monkeypatch):
    """pypdfium2 不是 Hermes 的懒加载项，直接用 pip 安装。"""
    calls = []
    monkeypatch.setattr(bootstrap, "_importable", lambda name: name != "pypdfium2")
    monkeypatch.setattr(bootstrap, "_pip_install", lambda specs: calls.append(tuple(specs)))

    bootstrap._install_document_deps()

    assert calls == [("pypdfium2>=4.30.0,<6.0",)]


def test_install_failure_does_not_raise(monkeypatch):
    """安装失败不能让启动崩溃。"""
    def _boom(_specs):
        raise RuntimeError("network down")

    monkeypatch.setattr(bootstrap, "_importable", lambda name: False)
    monkeypatch.setattr(bootstrap, "_pip_install", _boom)
    monkeypatch.setitem(sys.modules, "tools.lazy_deps", None)

    bootstrap._install_document_deps()
