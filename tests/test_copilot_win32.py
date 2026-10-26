"""Windows 截图模块单测（mock user32/gdi32/kernel32，不需要 Windows）。

复审 P2-2 要求：PrintWindow 黑图回退、最小化、无窗口、进程名四条至少要有
mock 测试锁定；审计又补了一条 64 位句柄签名（restype 默认 c_int 会截断）。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

import pytest

from trade.copilot import platform_win32 as pw


class FakeFunction:
    """可调用 + 可赋 restype/argtypes 的假 Win32 函数。"""

    def __init__(self, impl=None, value=None):
        self._impl = impl
        self._value = value
        self.restype = None
        self.argtypes = None

    def __call__(self, *args):
        if self._impl is not None:
            return self._impl(*args)
        return self._value


class FakeDLL:
    def __init__(self, **functions):
        for name, function in functions.items():
            setattr(self, name, function)


def _user32(**overrides):
    functions = {
        "GetForegroundWindow": FakeFunction(value=1234),
        "SetThreadDpiAwarenessContext": FakeFunction(value=1),
        # 默认 z 序：目标窗口就在最前（未被遮挡）
        "GetTopWindow": FakeFunction(value=1234),
        "GetWindow": FakeFunction(value=0),
        "GetWindowTextLengthW": FakeFunction(value=6),
        "GetWindowTextW": FakeFunction(
            impl=lambda hwnd, buffer, size: _write_text(buffer, "WeChat")
        ),
        "IsWindowVisible": FakeFunction(value=1),
        "IsIconic": FakeFunction(value=0),
        "GetWindowRect": FakeFunction(impl=_fill_rect(100, 60)),
        "GetWindowThreadProcessId": FakeFunction(impl=_fill_pid(4242)),
        "GetWindowDC": FakeFunction(value=10),
        "ReleaseDC": FakeFunction(value=1),
        "PrintWindow": FakeFunction(value=1),
    }
    functions.update(overrides)
    return FakeDLL(**functions)


def _gdi32(**overrides):
    functions = {
        "CreateCompatibleDC": FakeFunction(value=20),
        "CreateCompatibleBitmap": FakeFunction(value=30),
        "SelectObject": FakeFunction(value=40),
        "DeleteObject": FakeFunction(value=1),
        "DeleteDC": FakeFunction(value=1),
        # 不写任何像素 → 全零位图，模拟 GPU 渲染窗口的"黑图"
        "GetDIBits": FakeFunction(impl=lambda hdc, hbm, start, lines, buf, info, fmt: lines),
    }
    functions.update(overrides)
    return FakeDLL(**functions)


def _kernel32(**overrides):
    functions = {
        "OpenProcess": FakeFunction(value=0),
        "QueryFullProcessImageNameW": FakeFunction(value=0),
        "CloseHandle": FakeFunction(value=1),
    }
    functions.update(overrides)
    return FakeDLL(**functions)


def _write_text(buffer, text):
    buffer.value = text
    return len(text)


def _fill_rect(width, height):
    def impl(hwnd, rect_ref):
        rect = rect_ref._obj
        rect.left, rect.top = 0, 0
        rect.right, rect.bottom = width, height
        return 1
    return impl


def _fill_pid(pid):
    def impl(hwnd, pid_ref):
        pid_ref._obj.value = pid
        return 1
    return impl


def _patch_dlls(monkeypatch, user32=None, gdi32=None, kernel32=None):
    triple = (user32 or _user32(), gdi32 or _gdi32(), kernel32 or _kernel32())
    monkeypatch.setattr(pw, "_dlls", lambda: triple)
    return triple


# ── 错误分支 ────────────────────────────────────────────────────────────────


def test_no_foreground_window(monkeypatch):
    _patch_dlls(monkeypatch, user32=_user32(GetForegroundWindow=FakeFunction(value=0)))
    result = pw.capture_active_window()
    assert not result.ok
    assert result.error_kind == "no_window"


def test_minimized_window_is_reported_not_captured(monkeypatch):
    _patch_dlls(monkeypatch, user32=_user32(IsIconic=FakeFunction(value=1)))
    result = pw.capture_active_window()
    assert not result.ok
    assert result.error_kind == "minimized"
    assert "最小化" in result.error
    assert result.window_title == "WeChat"


def test_invisible_window(monkeypatch):
    _patch_dlls(monkeypatch, user32=_user32(IsWindowVisible=FakeFunction(value=0)))
    result = pw.capture_active_window()
    assert not result.ok
    assert result.error_kind == "no_window"


# ── 截图路径 ────────────────────────────────────────────────────────────────


def test_black_printwindow_falls_back_to_mss(monkeypatch):
    """PrintWindow 成功但位图全黑 → 必须回退屏幕抓取，而不是返回黑图。"""
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(
        pw, "_grab_region_png",
        lambda rect: calls.append((rect.right, rect.bottom)) or b"PNG-GRAB",
    )
    _patch_dlls(monkeypatch)

    result = pw.capture_active_window()

    assert result.ok
    assert result.image_png == b"PNG-GRAB"
    assert calls == [(100, 60)], "回退必须按窗口矩形抓屏"


def test_printwindow_bitmap_is_encoded_when_not_black(monkeypatch):
    """非黑位图走 PrintWindow 编码路径，不触发 mss 回退。"""
    from unittest import mock

    monkeypatch.setattr(pw, "_bgra_to_png", lambda raw, w, h: b"PNG-DIB")
    monkeypatch.setattr(
        pw, "_grab_region_png", mock.Mock(side_effect=AssertionError("不该回退"))
    )
    # GetDIBits 写入非零像素
    gdi = _gdi32(GetDIBits=FakeFunction(
        impl=lambda hdc, hbm, start, lines, buf, info, fmt: _fill_bytes(buf, lines)
    ))
    _patch_dlls(monkeypatch, gdi32=gdi)

    result = pw.capture_active_window()

    assert result.ok
    assert result.image_png == b"PNG-DIB"


def _fill_bytes(buffer, height):
    buffer.raw = b"\x40" * len(buffer)
    return height


def test_both_paths_failing_is_structured_error(monkeypatch):
    monkeypatch.setattr(pw, "_grab_region_png", lambda rect: b"")
    _patch_dlls(monkeypatch)
    result = pw.capture_active_window()
    assert not result.ok
    assert result.error_kind == "capture_failed"


# ── 进程名 ──────────────────────────────────────────────────────────────────


def test_process_name_from_window_handle(monkeypatch):
    def query(handle, flags, buffer, size_ref):
        buffer.value = r"C:\Program Files\Tencent\WeChat.exe"
        size_ref._obj.value = len(buffer.value)
        return 1

    kernel = _kernel32(
        OpenProcess=FakeFunction(value=777),
        QueryFullProcessImageNameW=FakeFunction(impl=query),
    )
    _patch_dlls(monkeypatch, kernel32=kernel)
    monkeypatch.setattr(pw, "_print_window_png", lambda *a: b"PNG")
    result = pw.capture_active_window()
    assert result.app_name == "WeChat.exe"


def test_process_name_empty_when_open_fails(monkeypatch):
    _patch_dlls(monkeypatch)
    monkeypatch.setattr(pw, "_print_window_png", lambda *a: b"PNG")
    assert pw.capture_active_window().app_name == ""


# ── 64 位句柄签名 ───────────────────────────────────────────────────────────


def test_configure_sets_pointer_sized_restypes(monkeypatch):
    """审计 P3-③：句柄默认 restype=c_int 会被截断，必须显式标成指针宽度。"""
    user32, gdi32, kernel32 = _user32(), _gdi32(), _kernel32()
    pw._configure_win32(user32, gdi32, kernel32)

    assert user32.GetForegroundWindow.restype is wintypes.HWND
    assert user32.GetWindowDC.restype is wintypes.HDC
    assert gdi32.CreateCompatibleDC.restype is wintypes.HDC
    assert gdi32.CreateCompatibleBitmap.restype is wintypes.HBITMAP
    assert gdi32.SelectObject.restype is wintypes.HGDIOBJ
    assert kernel32.OpenProcess.restype is wintypes.HANDLE
    assert wintypes.HWND is ctypes.c_void_p
    # DPI 上下文也是指针宽度：不声明会把 -4 塞进 32 位 int（审计 P2-15）
    assert user32.SetThreadDpiAwarenessContext.argtypes == [ctypes.c_void_p]


def test_configure_tolerates_missing_functions():
    """老系统缺某个函数时只跳过该项，不许整体抛错。"""
    pw._configure_win32(FakeDLL(), FakeDLL(), FakeDLL())


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_available_off_windows(monkeypatch, platform):
    monkeypatch.setattr(pw.sys, "platform", platform)
    ok, reason = pw.available()
    assert ok is False
    assert "Windows" in reason


class TestCoveredWindowPrivacy:
    """P1-6：PrintWindow 失败时若窗口被遮挡，不能抓屏幕（会把遮挡物发给视觉模型）。"""

    def _user_with_zorder(self, blocker_rect):
        def rect_for(hwnd, rect_ref):
            rect = rect_ref._obj
            if hwnd == 999:
                rect.left, rect.top, rect.right, rect.bottom = blocker_rect
            else:
                rect.left, rect.top, rect.right, rect.bottom = 0, 0, 100, 60
            return 1

        def next_window(hwnd, flag):
            return 1234 if hwnd == 999 else 0

        return _user32(
            GetTopWindow=FakeFunction(value=999),
            GetWindow=FakeFunction(impl=next_window),
            IsWindowVisible=FakeFunction(value=1),
            GetWindowRect=FakeFunction(impl=rect_for),
        )

    def test_covered_window_refuses_screen_grab(self, monkeypatch):
        grabs: list = []
        monkeypatch.setattr(
            pw, "_grab_region_png",
            lambda rect: grabs.append(rect) or b"PNG-SHOULD-NOT-HAPPEN",
        )
        monkeypatch.setattr(pw, "_print_window_png", lambda *a: b"")
        _patch_dlls(monkeypatch, user32=self._user_with_zorder((10, 10, 110, 70)))

        result = pw.capture_active_window()

        assert not result.ok
        assert result.error_kind == "capture_failed"
        assert "遮挡" in result.error
        assert grabs == [], "被遮挡时绝不能抓屏幕"

    def test_uncovered_window_falls_back(self, monkeypatch):
        grabs: list = []
        monkeypatch.setattr(
            pw, "_grab_region_png",
            lambda rect: grabs.append(rect) or b"PNG-GRAB",
        )
        monkeypatch.setattr(pw, "_print_window_png", lambda *a: b"")
        _patch_dlls(monkeypatch, user32=self._user_with_zorder((200, 200, 300, 300)))

        result = pw.capture_active_window()

        assert result.ok
        assert result.image_png == b"PNG-GRAB"
        assert len(grabs) == 1
