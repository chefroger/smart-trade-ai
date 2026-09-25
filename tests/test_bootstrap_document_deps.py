"""Trade 启动时补齐文档解析依赖的测试。

注意：CI 里不安装 Hermes（按项目设计用 mock），所以这些测试必须自己注册
``tools`` 父包，不能依赖本机是否装了 Hermes——否则本机通过、CI 失败。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade import bootstrap


def _fake_lazy_deps(calls):
    """构造假的 tools.lazy_deps 模块。"""
    module = types.ModuleType("tools.lazy_deps")
    module.is_available = lambda feature: False
    module.ensure = lambda feature, prompt=True: calls.append(("lazy", feature))
    return module


def _install_fake_tools(monkeypatch, lazy_module):
    """注册假的 ``tools`` 父包，让 ``from tools import lazy_deps`` 成功。"""
    package = types.ModuleType("tools")
    package.lazy_deps = lazy_module
    monkeypatch.setitem(sys.modules, "tools", package)
    monkeypatch.setitem(sys.modules, "tools.lazy_deps", lazy_module)


def _remove_tools(monkeypatch):
    """模拟没有安装 Hermes 的环境。"""
    monkeypatch.setitem(sys.modules, "tools", None)
    monkeypatch.setitem(sys.modules, "tools.lazy_deps", None)


def test_all_document_deps_present(monkeypatch):
    """依赖齐全时不报告缺失。"""
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
    _install_fake_tools(monkeypatch, _fake_lazy_deps(calls))
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


def test_install_falls_back_to_pip_without_hermes(monkeypatch):
    """没有 Hermes 时改用 pip 安装，不能因此崩溃。"""
    calls = []
    _remove_tools(monkeypatch)
    monkeypatch.setattr(bootstrap, "_importable", lambda name: name != "anydoc")
    monkeypatch.setattr(bootstrap, "_pip_install", lambda specs: calls.append(tuple(specs)))

    bootstrap._install_document_deps()

    assert calls == [("firecrawl-anydoc==0.2.4",)]


def test_install_failure_does_not_raise(monkeypatch):
    """安装失败不能让启动崩溃。"""
    def _boom(_specs):
        raise RuntimeError("network down")

    _remove_tools(monkeypatch)
    monkeypatch.setattr(bootstrap, "_importable", lambda name: False)
    monkeypatch.setattr(bootstrap, "_pip_install", _boom)

    bootstrap._install_document_deps()
