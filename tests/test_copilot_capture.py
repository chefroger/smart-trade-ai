"""聊天副驾 capture 测试（平台无关部分 + 平台桩）。

覆盖任务书 §7 的自动化项：
    - 剪贴板通道判定（对话特征、指纹新鲜度）
    - 剪贴板保存/恢复（铁律 5）
    - 级联顺序与降级（剪贴板 → 截图 → 结构化报错）
真机截图/权限验证在交付记录里单独做，这里不触碰真实屏幕。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from trade.copilot import capture as capture_mod
from trade.copilot.platform_base import WindowCapture

DIALOG = "John: What is your MOQ?\nMe: 500 pcs."


class FakePlatform:
    """平台适配模块的桩：记录调用次数，返回预设结果。"""

    def __init__(self, *, available: bool = True, reason: str = "",
                 window: WindowCapture | None = None):
        self._available = available
        self._reason = reason
        self._window = window or WindowCapture(
            image_png=b"\x89PNG-fake", app_name="WeChat", window_title="John",
        )
        self.calls = 0

    def available(self) -> tuple[bool, str]:
        return self._available, self._reason

    def capture_active_window(self) -> WindowCapture:
        self.calls += 1
        return self._window


@pytest.fixture(autouse=True)
def _reset_clipboard_state():
    capture_mod.reset_clipboard_freshness()
    yield
    capture_mod.reset_clipboard_freshness()


# ── 对话文本判定 ────────────────────────────────────────────────────────────


class TestLooksLikeConversation:
    @pytest.mark.parametrize("text", [
        DIALOG,
        "[10/23/26, 10:23:45 AM] John: What is your MOQ?",
        "客户：有货吗？\n我：有的，500 起订",
        "From: John Smith\nSubject: RFQ for valves\n\nPlease quote.",
        "10:23\nJohn\nWhat is your MOQ?",
    ])
    def test_accepts_dialog_shapes(self, text):
        assert capture_mod.looks_like_conversation(text) is True

    @pytest.mark.parametrize("text", [
        "",
        "hi",
        "Please send me the price list",
        "def main():\n    print(1)",
        "SELECT * FROM customers WHERE id = 1",
    ])
    def test_rejects_non_dialog(self, text):
        assert capture_mod.looks_like_conversation(text) is False


# ── 新鲜度：内容指纹自上次采用以来变过 ──────────────────────────────────────


class TestClipboardFreshness:
    def test_first_claim_is_fresh(self):
        assert capture_mod.claim_fresh_clipboard(DIALOG) is True

    def test_same_content_twice_is_stale(self):
        assert capture_mod.claim_fresh_clipboard(DIALOG) is True
        assert capture_mod.claim_fresh_clipboard(DIALOG) is False

    def test_changed_content_is_fresh(self):
        assert capture_mod.claim_fresh_clipboard(DIALOG) is True
        assert capture_mod.claim_fresh_clipboard(DIALOG + "\nJohn: hello?") is True

    def test_whitespace_difference_is_same_fingerprint(self):
        assert capture_mod.claim_fresh_clipboard("a b\nc") is True
        assert capture_mod.claim_fresh_clipboard("a   b\tc") is False

    def test_reset_clears_baseline(self):
        assert capture_mod.claim_fresh_clipboard(DIALOG) is True
        capture_mod.reset_clipboard_freshness()
        assert capture_mod.claim_fresh_clipboard(DIALOG) is True


# ── 剪贴板保存/恢复（铁律 5）──────────────────────────────────────────────


class TestClipboardPreserved:
    def test_restores_original_after_temporary_write(self, monkeypatch):
        class FakeClipboard:
            def __init__(self):
                self.text = "original"
                self.copies: list[str] = []

            def paste(self):
                return self.text

            def copy(self, value):
                self.text = value
                self.copies.append(value)

        fake = FakeClipboard()
        monkeypatch.setattr(capture_mod, "_import_pyperclip", lambda: fake)

        with capture_mod.clipboard_preserved():
            fake.copy("changed")

        assert fake.copies[-1] == "original"
        assert fake.text == "original"


# ── 级联与降级 ──────────────────────────────────────────────────────────────


class TestCaptureCascade:
    def test_clipboard_dialog_wins_without_screenshot(self, monkeypatch):
        monkeypatch.setattr(capture_mod, "read_clipboard", lambda: DIALOG)
        platform = FakePlatform()
        result = capture_mod.capture_conversation(platform=platform)

        assert result.ok
        assert result.channel == "clipboard"
        assert result.text == DIALOG
        assert result.has_image() is False
        assert platform.calls == 0

    def test_repeated_clipboard_falls_back_to_screenshot(self, monkeypatch):
        monkeypatch.setattr(capture_mod, "read_clipboard", lambda: DIALOG)
        platform = FakePlatform()

        first = capture_mod.capture_conversation(platform=platform)
        second = capture_mod.capture_conversation(platform=platform)

        assert first.channel == "clipboard"
        assert second.channel == "screenshot"
        assert second.ok
        assert second.has_image()
        assert second.app_name == "WeChat"
        assert platform.calls == 1

    def test_non_dialog_clipboard_falls_back_to_screenshot(self, monkeypatch):
        monkeypatch.setattr(capture_mod, "read_clipboard", lambda: "def f(): pass")
        platform = FakePlatform()
        result = capture_mod.capture_conversation(platform=platform)

        assert result.channel == "screenshot"
        assert result.ok
        assert platform.calls == 1

    def test_clipboard_can_be_disabled(self, monkeypatch):
        monkeypatch.setattr(capture_mod, "read_clipboard", lambda: DIALOG)
        platform = FakePlatform()
        result = capture_mod.capture_conversation(
            platform=platform, use_clipboard=False
        )
        assert result.channel == "screenshot"
        assert platform.calls == 1

    def test_screenshot_is_base64_data_url(self, monkeypatch):
        monkeypatch.setattr(capture_mod, "read_clipboard", lambda: "")
        platform = FakePlatform(window=WindowCapture(
            image_png=b"png-bytes", app_name="WhatsApp", window_title="Ana",
        ))
        result = capture_mod.capture_conversation(platform=platform)
        assert result.image_data_url.startswith("data:image/png;base64,")
        assert result.app_name == "WhatsApp"
        assert result.window_title == "Ana"

    def test_missing_dependency_is_structured_error(self, monkeypatch):
        monkeypatch.setattr(capture_mod, "read_clipboard", lambda: "")
        platform = FakePlatform(
            available=False, reason="缺少依赖 pyobjc-framework-Quartz",
        )
        result = capture_mod.capture_conversation(platform=platform)

        assert not result.ok
        assert result.error_kind == "missing_dependency"
        assert "Quartz" in result.error
        assert platform.calls == 0

    def test_permission_denied_is_structured_error(self, monkeypatch):
        monkeypatch.setattr(capture_mod, "read_clipboard", lambda: "")
        platform = FakePlatform(window=WindowCapture(
            app_name="WeChat", window_title="John",
            error="没有屏幕录制权限", error_kind="permission",
        ))
        result = capture_mod.capture_conversation(platform=platform)

        assert not result.ok
        assert result.error_kind == "permission"
        assert result.app_name == "WeChat"

    def test_unsupported_platform(self, monkeypatch):
        monkeypatch.setattr(capture_mod, "read_clipboard", lambda: "")
        monkeypatch.setattr(capture_mod, "load_platform", lambda: None)
        result = capture_mod.capture_conversation()

        assert not result.ok
        assert result.error_kind == "unsupported_platform"


def test_capture_module_contains_no_platform_api():
    """共享调度层不许直接 import 平台 API（平台实现必须隔离在两个 platform_*.py）。"""
    source = Path(capture_mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("import Quartz", "import mss", "ctypes.windll"):
        assert forbidden not in source, forbidden


# ── macOS：CGImage → PNG（真 Quartz，不碰屏幕）──────────────────────────────


@pytest.mark.skipif(
    __import__("sys").platform != "darwin", reason="仅 macOS 有 Quartz"
)
def test_cgimage_to_png_round_trip():
    platform_darwin = pytest.importorskip("trade.copilot.platform_darwin")
    quartz = platform_darwin._quartz()
    if quartz is None:
        pytest.skip("pyobjc-framework-Quartz 未安装")

    colorspace = quartz.CGColorSpaceCreateDeviceRGB()
    context = quartz.CGBitmapContextCreate(
        None, 4, 4, 8, 16, colorspace, quartz.kCGImageAlphaPremultipliedLast,
    )
    image = quartz.CGBitmapContextCreateImage(context)
    png = platform_darwin._cgimage_to_png(quartz, image)

    assert png.startswith(b"\x89PNG\r\n\x1a\n"), "必须得到可用的 PNG 字节"


def test_darwin_permission_guide_shape():
    platform_darwin = pytest.importorskip("trade.copilot.platform_darwin")
    guide = platform_darwin.permission_guide()
    assert "screen_recording" in guide
    entry = guide["screen_recording"]
    assert set(entry) == {"granted", "reason", "settings_url"}
    assert entry["settings_url"].startswith("x-apple.systempreferences:")


# ── 权限引导（UI 只调用这两个封装，不直接碰平台模块）────────────────────────


def test_permission_guide_passthrough(monkeypatch):
    fake = SimpleNamespace(
        permission_guide=lambda: {"screen_recording": {"granted": False}},
    )
    monkeypatch.setattr(capture_mod, "load_platform", lambda: fake)
    assert capture_mod.permission_guide()["screen_recording"]["granted"] is False


def test_request_permission_passthrough(monkeypatch):
    fake = SimpleNamespace(request_screen_recording_permission=lambda: True)
    monkeypatch.setattr(capture_mod, "load_platform", lambda: fake)
    assert capture_mod.request_screen_recording_permission() is True


def test_permission_wrappers_without_platform(monkeypatch):
    monkeypatch.setattr(capture_mod, "load_platform", lambda: None)
    assert capture_mod.permission_guide() == {}
    assert capture_mod.request_screen_recording_permission() is False
