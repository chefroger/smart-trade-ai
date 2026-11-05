"""副驾组装层测试：设置默认关闭、热键降级、UI 无发送、service 全链路。"""

from __future__ import annotations

import sys

from trade.copilot import hotkey as hotkey_mod
from trade.copilot import settings as settings_mod
from trade.copilot import ui as ui_mod
from trade.copilot.service import CopilotService
from trade.copilot.types import (
    CapturedWindow,
    CustomerContext,
    DialogMessage,
    DraftResult,
    ExtractedDialog,
    SourceRef,
)


class TestSettings:
    def test_defaults_are_off(self):
        s = settings_mod.CopilotSettings()
        assert s.enabled is False
        assert s.use_clipboard is False
        assert s.clipboard_max_chars == 3000
        assert s.consent_ok() is False

    def test_missing_or_broken_file_falls_back(self, tmp_path):
        assert settings_mod.load_settings(tmp_path / "nope.json").enabled is False
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        assert settings_mod.load_settings(bad).enabled is False

    def test_enabled_requires_consent(self):
        s = settings_mod.CopilotSettings(enabled=True, consent_version=0)
        assert s.sanitized().enabled is False
        s2 = settings_mod.CopilotSettings(
            enabled=True, consent_version=settings_mod.REQUIRED_CONSENT_VERSION
        )
        assert s2.sanitized().enabled is True

    def test_save_roundtrip(self, tmp_path):
        path = tmp_path / "copilot.json"
        s = settings_mod.CopilotSettings(
            consent_version=1, enabled=True, use_clipboard=True,
            clipboard_max_chars=500, refused_apps=["Acme Bank"],
        )
        assert settings_mod.save_settings(s, path) is True
        loaded = settings_mod.load_settings(path)
        assert loaded.enabled is True
        assert loaded.use_clipboard is True
        assert loaded.clipboard_max_chars == 500
        assert loaded.refused_apps == ["Acme Bank"]

    def test_bad_values_are_sanitized(self):
        s = settings_mod.CopilotSettings(
            clipboard_max_chars=-5, consent_version="x", refused_apps="oops"  # type: ignore[arg-type]
        ).sanitized()
        assert s.clipboard_max_chars == 3000
        assert s.consent_version == 0
        assert s.refused_apps == []


class TestHotkey:
    def test_parse_defaults(self):
        assert hotkey_mod.parse_hotkey("ctrl+shift+space") == (
            "<ctrl>", "<shift>", "<space>",
        )
        assert hotkey_mod.canonical_hotkey("Cmd+Shift+Space") == "cmd+shift+space"

    def test_invalid_spec(self):
        assert hotkey_mod.parse_hotkey("space") is None
        assert hotkey_mod.to_pynput_hotkey("space") is None

    def test_missing_dependency_degrades(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "pynput", None)
        calls = []
        listener = hotkey_mod.HotkeyListener(lambda: calls.append(1))
        ok, reason = listener.start()
        assert ok is False
        assert "pynput" in reason
        assert listener.running is False
        assert calls == []


class TestUiHtml:
    def test_has_copy_plus_close_and_no_send(self):
        html = ui_mod.render_panel_html(draft="hello")
        assert "复制草稿" in html
        # 未接线动作不渲染空壳按钮
        assert "换一种说法" not in html
        assert "打开 trade 深处理" not in html
        assert "data-action='close'" in html
        assert "发送" not in html
        assert html.count("<button") == 2

    def test_escapes_draft(self):
        html = ui_mod.render_panel_html(draft="<script>alert(1)</script>")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_sources_are_rendered(self):
        html = ui_mod.render_panel_html(
            draft="ok",
            sources=[SourceRef(label="报价单.xlsx", value="$3.50")],
        )
        assert "报价单.xlsx" in html
        assert "$3.50" in html

    def test_loading_panel_has_no_empty_draft_or_actions(self):
        html = ui_mod.render_panel_html(status="正在识别…")
        assert "正在识别" in html
        assert "<textarea" not in html
        assert "data-action='copy'" not in html
        assert "data-action='regenerate'" not in html
        assert "data-action='deepen'" not in html
        assert "data-action='close'" in html
        assert html.count("<button") == 1


def _service(**overrides):
    defaults = {
        "company_id": 1,
        "settings": settings_mod.CopilotSettings(consent_version=1, enabled=True),
        "capture_fn": lambda **kw: CapturedWindow(
            channel="clipboard", text="客户: What is your MOQ?"
        ),
        "extract_fn": lambda captured: ExtractedDialog(
            contact="Acme",
            messages=[DialogMessage(who="customer", text="What is your MOQ?")],
            confidence=0.9,
        ),
        "build_context_fn": lambda extracted: CustomerContext(
            matched=True, new_contact=False, customer_name="Acme"
        ),
        "draft_fn": lambda text, ctx: DraftResult(
            draft="500 pcs.", summary_zh="起订量 500",
            sources=[SourceRef(label="产品库", value="500")],
        ),
    }
    defaults.update(overrides)
    return CopilotService(**defaults)


class TestService:
    async def test_disabled_does_nothing(self):
        svc = _service(settings=settings_mod.CopilotSettings())
        event = await svc.trigger()
        assert event.ok is False
        assert "未开启" in event.error

    def test_enable_requires_consent(self, tmp_path):
        svc = _service(settings_path=tmp_path / "s.json")
        svc.settings = settings_mod.CopilotSettings()
        ok, reason = svc.enable()
        assert ok is False
        assert "隐私说明" in reason
        assert svc.enabled is False

    def test_enable_starts_hotkey(self, tmp_path):
        started = []

        class FakeHotkey:
            def start(self):
                started.append("start")
                return True, ""

            def stop(self):
                started.append("stop")

        svc = _service(
            settings_path=tmp_path / "s.json",
            hotkey_factory=lambda cb: FakeHotkey(),
        )
        ok, _ = svc.enable()
        assert ok is True and svc.enabled is True
        assert started == ["start"]
        svc.pause()
        assert svc.paused is True
        svc.resume()
        svc.disable()
        assert svc.enabled is False
        assert started[-1] == "stop"

    async def test_full_flow(self):
        shown = []

        class FakeUi:
            def show_result(self, **kwargs):
                shown.append(kwargs)

        svc = _service(ui=FakeUi())
        event = await svc.trigger()
        assert event.ok is True
        assert event.draft.draft == "500 pcs."
        assert shown and shown[0]["draft"] == "500 pcs."

    async def test_capture_failure_stops(self):
        calls = []
        svc = _service(
            capture_fn=lambda **kw: CapturedWindow(error="没有权限", error_kind="permission"),
            extract_fn=lambda captured: calls.append("extract"),
        )
        event = await svc.trigger()
        assert event.stage == "capture"
        assert calls == []

    async def test_confirmation_skips_draft(self):
        drafted = []
        svc = _service(
            build_context_fn=lambda extracted: CustomerContext(
                needs_confirmation=True, confirmation_question="你是说 Li 吗？"
            ),
            draft_fn=lambda text, ctx: drafted.append(1),
        )
        event = await svc.trigger()
        assert event.stage == "confirm"
        assert "Li" in event.confirmation
        assert drafted == []

    async def test_paused_stops(self):
        svc = _service()
        svc.pause()
        event = await svc.trigger()
        assert event.ok is False
        assert "暂停" in event.error


class TestTray:
    def test_missing_dependency_degrades(self, monkeypatch):
        import sys as _sys

        from trade.copilot import tray as tray_mod

        monkeypatch.setitem(_sys.modules, "pystray", None)
        ok, reason = tray_mod.available()
        assert ok is False and "pystray" in reason
        icon = tray_mod.TrayIcon(
            on_toggle=lambda: None, on_pause=lambda: None, on_quit=lambda: None
        )
        ok, _ = icon.start()
        assert ok is False and icon.running is False

    def test_service_start_and_stop_tray(self):
        calls = []

        class FakeTray:
            def start(self):
                calls.append("start")
                return True, ""

            def stop(self):
                calls.append("stop")

        svc = _service(tray_factory=lambda: FakeTray())
        assert svc.start_tray() == (True, "")
        assert svc.start_tray() == (True, "")
        svc.stop_tray()
        assert calls == ["start", "stop"]


class TestReadingIndicator:
    async def test_status_sequence_on_success(self):
        statuses = []

        class FakeUi:
            def show_status(self, text):
                statuses.append(text)

            def show_result(self, **kwargs):
                statuses.append("result")

        svc = _service(ui=FakeUi())
        event = await svc.trigger()
        assert event.ok is True
        assert statuses[:3] == ["正在读取…", "正在识别…", "正在生成草稿…"]
        assert statuses[-1] == "result"

    async def test_error_is_shown(self):
        shown = []

        class FakeUi:
            def show_error(self, text):
                shown.append(text)

        svc = _service(
            ui=FakeUi(),
            capture_fn=lambda **kw: CapturedWindow(
                error="该应用在拒读名单内，未读取。", error_kind="refused"
            ),
        )
        event = await svc.trigger()
        assert event.stage == "capture"
        assert shown == ["该应用在拒读名单内，未读取。"]

    async def test_no_customer_message_shows_error(self):
        shown = []

        class FakeUi:
            def show_status(self, text):
                pass

            def show_error(self, text):
                shown.append(text)

        svc = _service(
            ui=FakeUi(),
            extract_fn=lambda captured: ExtractedDialog(
                messages=[DialogMessage(who="me", text="我刚发的")],
            ),
        )
        event = await svc.trigger()
        assert event.stage == "extract"
        assert "没有识别到客户消息" in event.error
        assert shown == ["没有识别到客户消息。"]


class TestHotkeyToggle:
    async def test_close_when_popup_visible(self):
        hidden = []

        class FakeUi:
            def is_visible(self):
                return True

            def hide(self):
                hidden.append(True)

        calls = []
        svc = _service(
            ui=FakeUi(),
            capture_fn=lambda **kw: calls.append(1) or CapturedWindow(text="x"),
        )
        event = await svc.trigger()
        assert event.ok is True
        assert event.stage == "closed"
        assert hidden == [True]
        assert calls == [], "弹窗已存在时不应再次读取"

    async def test_close_cancels_in_flight_run(self):
        import asyncio
        import threading

        gate = threading.Event()
        hidden = []

        class FakeUi:
            def __init__(self):
                self.visible = False

            def is_visible(self):
                return self.visible

            def show_status(self, text):
                self.visible = True

            def hide(self):
                self.visible = False
                hidden.append(True)

            def show_result(self, **kwargs):
                raise AssertionError("取消后不应再弹结果")

        def slow_capture(**kwargs):
            gate.wait(2)
            return CapturedWindow(text="客户: hi")

        ui = FakeUi()
        svc = _service(ui=ui, capture_fn=slow_capture)
        task = asyncio.create_task(svc.trigger())
        await asyncio.sleep(0.05)  # 让第一轮进入 capture 并显示"正在读取"
        second = await svc.trigger()  # 第二次按键：关闭
        assert second.stage == "closed"
        gate.set()
        first = await task
        assert first.stage == "cancelled"
        assert hidden == [True]

    async def test_dismiss_cancels_in_flight_like_hotkey(self):
        """× 关闭必须取消在途任务，否则生成完会再把窗口弹回来。"""
        import asyncio
        import threading

        gate = threading.Event()

        class FakeUi:
            def __init__(self):
                self.visible = False

            def is_visible(self):
                return self.visible

            def show_status(self, text):
                self.visible = True

            def hide(self):
                self.visible = False

            def show_result(self, **kwargs):
                raise AssertionError("dismiss 后不应再弹结果")

        def slow_capture(**kwargs):
            gate.wait(2)
            return CapturedWindow(text="客户: hi")

        ui = FakeUi()
        svc = _service(ui=ui, capture_fn=slow_capture)
        task = asyncio.create_task(svc.trigger())
        await asyncio.sleep(0.05)
        svc.dismiss()
        gate.set()
        first = await task
        assert first.stage == "cancelled"


class TestCopyButton:
    def test_error_panel_has_no_actions(self):
        html = ui_mod.render_panel_html(status="无法连接到模型服务")
        assert "无法连接到模型服务" in html
        assert "复制草稿" not in html
        assert "<textarea" not in html

    def test_copy_returns_clear_error_for_empty_text(self):
        bridge = ui_mod._Bridge()
        result = bridge.action("copy", "   ")
        assert result["ok"] is False
        assert "没有草稿" in result["error"]

    def test_copy_writes_clipboard_when_clicked(self, monkeypatch):
        import sys
        from types import ModuleType

        copied = []
        fake = ModuleType("pyperclip")
        fake.copy = lambda text: copied.append(text)
        monkeypatch.setitem(sys.modules, "pyperclip", fake)

        result = ui_mod._Bridge().action("copy", "hello")
        assert result["ok"] is True
        assert copied == ["hello"]

    def test_unwired_button_reports_not_connected(self):
        result = ui_mod._Bridge().action("regenerate", "hello")
        assert result["ok"] is False
        assert "尚未接入" in result["error"]

    def test_close_calls_callback(self):
        closed = []
        bridge = ui_mod._Bridge(on_close=lambda: closed.append(True))
        result = bridge.action("close")
        assert result["ok"] is True
        assert closed == [True]
