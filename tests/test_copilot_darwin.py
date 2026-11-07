"""macOS 截图模块：前台是 Trade 时的拒绝路径（mock Quartz，不碰真实屏幕）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pw = pytest.importorskip("trade.copilot.platform_darwin")


def _fake_quartz(pid: int, owner: str = "Trade"):
    """只提供 _frontmost_window / capture_active_window 用到的常量与方法。

    用 SimpleNamespace 而不是 class：Quartz 常量是 mixedCase，class 作用域会触发 N815。
    """
    window = {
        "layer": 0,
        "pid": pid,
        "onscreen": True,
        "owner": owner,
        "bounds": {"Width": 800, "Height": 600},
        "num": 42,
        "title": owner,
    }
    return SimpleNamespace(
        kCGWindowLayer="layer",
        kCGWindowOwnerPID="pid",
        kCGWindowIsOnscreen="onscreen",
        kCGWindowOwnerName="owner",
        kCGWindowBounds="bounds",
        kCGWindowNumber="num",
        kCGWindowName="title",
        kCGWindowListOptionOnScreenOnly=1,
        kCGWindowListExcludeDesktopElements=2,
        kCGNullWindowID=0,
        kCGWindowListOptionIncludingWindow=8,
        kCGWindowImageBoundsIgnoreFraming=16,
        kCGWindowImageShouldBeOpaque=32,
        CGRectNull=object(),
        CGWindowListCreateImage=lambda *_args, **_kwargs: None,
        CGWindowListCopyWindowInfo=lambda *_args: [window],
    )


def _patch(monkeypatch, pid: int, owner: str = "Trade") -> None:
    monkeypatch.setattr(pw, "_quartz", lambda: _fake_quartz(pid, owner))
    monkeypatch.setattr(pw, "screen_recording_granted", lambda: True)


def test_trade_foreground_is_rejected(monkeypatch):
    """前台是 Trade 进程 → 明确拒绝，不去读后面的窗口。"""
    _patch(monkeypatch, 4242)
    monkeypatch.setattr(pw, "own_window_pids", lambda: {4242})
    result = pw.capture_active_window()
    assert not result.ok
    assert result.error_kind == "host_frontmost"
    assert "Trade" in result.error


def test_other_app_is_not_rejected(monkeypatch):
    """别的应用照常走截图路径（这里只验证没被误判成 Trade）。"""
    _patch(monkeypatch, 9999, owner="WeChat")
    monkeypatch.setattr(pw, "own_window_pids", lambda: {4242})
    result = pw.capture_active_window()
    assert result.error_kind != "host_frontmost"
