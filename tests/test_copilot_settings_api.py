"""副驾设置 API 与设置弹窗回归（默认关闭 / 同意门禁）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

import trade.api.copilot as api_mod
from trade.api.copilot import (
    CopilotSettingsPayload,
    get_copilot_settings,
    update_copilot_settings,
)
from trade.copilot.settings import load_settings

ROOT = Path(__file__).resolve().parent.parent
# 真实实现留底：个别用例要测 spawn settle，需临时撤掉下方成功桩。
_REAL_ENSURE_COPILOT = api_mod._ensure_copilot_running
_REAL_STOP_COPILOT = api_mod._stop_copilot


@pytest.fixture(autouse=True)
def _isolated_settings_home(tmp_path, monkeypatch):
    """设置文件落在临时 TRADE_HOME；不真的拉起副驾进程。"""
    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    monkeypatch.setattr(
        api_mod, "_ensure_copilot_running", lambda cid, restart=False: (True, "")
    )
    monkeypatch.setattr(api_mod, "_stop_copilot", lambda: None)
    yield


class TestCopilotSettingsApi:
    def test_get_defaults_off(self):
        payload = get_copilot_settings()
        assert payload["settings"]["enabled"] is False
        assert payload["settings"]["use_clipboard"] is False
        assert payload["settings"]["clipboard_max_chars"] == 3000
        assert payload["required_consent_version"] >= 1

    def test_enable_without_consent_is_rejected(self):
        with pytest.raises(HTTPException) as exc:
            update_copilot_settings(
                CopilotSettingsPayload(enabled=True), cid=1
            )
        assert exc.value.status_code == 400
        assert load_settings().enabled is False

    def test_enable_with_consent_persists(self):
        payload = update_copilot_settings(
            CopilotSettingsPayload(enabled=True, consent_version=1), cid=1
        )
        assert payload["settings"]["enabled"] is True
        assert payload["runtime"]["running"] is True
        assert load_settings().enabled is True

    def test_enable_starts_and_disable_stops_process(self, monkeypatch):
        import trade.api.copilot as api_mod

        calls = []

        def _ensure(cid, *, restart=False):
            calls.append(("start", cid, restart))
            return True, ""

        monkeypatch.setattr(api_mod, "_ensure_copilot_running", _ensure)
        monkeypatch.setattr(
            api_mod, "_stop_copilot", lambda: calls.append(("stop",))
        )
        update_copilot_settings(
            CopilotSettingsPayload(enabled=True, consent_version=1), cid=7
        )
        update_copilot_settings(CopilotSettingsPayload(enabled=False), cid=7)
        assert calls == [("start", 7, False), ("stop",)]

    def test_resave_while_enabled_restarts_process(self, monkeypatch):
        """开启状态下再保存必须 restart，否则热键/公司改动不生效。"""
        import trade.api.copilot as api_mod

        calls = []

        def _ensure(cid, *, restart=False):
            calls.append((cid, restart))
            return True, ""

        monkeypatch.setattr(api_mod, "_ensure_copilot_running", _ensure)
        update_copilot_settings(
            CopilotSettingsPayload(enabled=True, consent_version=1), cid=3
        )
        update_copilot_settings(
            CopilotSettingsPayload(hotkey="ctrl+shift+a"), cid=3
        )
        # 首次开启只需启动；第二次热键变了才重启。
        assert calls == [(3, False), (3, True)]

    def test_irrelevant_field_does_not_restart(self, monkeypatch):
        """纯文案/未接线字段变化不应重启副驾（正在生成时会被打断）。"""
        import trade.api.copilot as api_mod

        calls = []

        def _ensure(cid, *, restart=False):
            calls.append(restart)
            return True, ""

        monkeypatch.setattr(api_mod, "_ensure_copilot_running", _ensure)
        update_copilot_settings(
            CopilotSettingsPayload(enabled=True, consent_version=1), cid=1
        )
        update_copilot_settings(
            CopilotSettingsPayload(write_memory=True), cid=1
        )
        assert calls == [False, False]

    def test_write_memory_is_forced_off(self):
        payload = update_copilot_settings(
            CopilotSettingsPayload(consent_version=1, write_memory=True), cid=1
        )
        assert payload["settings"]["write_memory"] is False

    def test_stop_skips_foreign_pid(self, monkeypatch, tmp_path):
        """PID 文件指向非副驾进程时不得误杀。"""
        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        monkeypatch.setattr(api_mod, "_stop_copilot", _REAL_STOP_COPILOT)
        api_mod._pid_path().parent.mkdir(parents=True, exist_ok=True)
        api_mod._pid_path().write_text("4242", encoding="utf-8")
        monkeypatch.setattr(api_mod, "_pid_alive", lambda pid: True)
        monkeypatch.setattr(api_mod, "_pid_is_copilot", lambda pid: False)
        killed = []
        monkeypatch.setattr(api_mod.os, "kill", lambda pid, sig: killed.append(pid))

        api_mod._stop_copilot()
        assert killed == []
        assert not api_mod._pid_path().exists()

    def test_save_without_enabling_does_not_spawn(self, monkeypatch):
        import trade.api.copilot as api_mod

        spawned = []

        def _ensure(cid, *, restart=False):
            spawned.append(cid)
            return True, ""

        monkeypatch.setattr(api_mod, "_ensure_copilot_running", _ensure)
        payload = update_copilot_settings(
            CopilotSettingsPayload(consent_version=1, use_clipboard=True), cid=1
        )
        assert payload["settings"]["use_clipboard"] is True
        assert spawned == []


class TestCopilotSettingsUi:
    def _modal(self) -> str:
        html = (ROOT / "static" / "trade_chat.html").read_text(encoding="utf-8")
        start = html.index('id="copilot-settings-modal"')
        end = html.index("<!-- Company Modal -->", start)
        return html[start:end]

    def test_modal_has_consent_and_switch(self):
        modal = self._modal()
        assert 'id="copilot-consent"' in modal
        assert 'id="copilot-enabled"' in modal
        assert "隐私说明版本" in modal

    def test_modal_has_no_send_wording(self):
        modal = self._modal()
        assert "发送" not in modal

    def test_privacy_copy_is_provider_neutral(self):
        modal = self._modal()
        assert "视觉模型" in modal
        assert "对话模型" in modal
        assert "剪贴板文本" in modal
        assert "只发给 DeepSeek" not in modal

    def test_write_memory_checkbox_hidden_until_wired(self):
        modal = self._modal()
        assert "copilot-write-memory" not in modal

    def test_js_functions_exist(self):
        js = (ROOT / "static" / "trade_chat.js").read_text(encoding="utf-8")
        assert "function showCopilotSettings()" in js
        assert "function saveCopilotSettings()" in js
        assert "function onCopilotConsentChange()" in js

    def test_api_paths_use_trade_prefix(self):
        """api() 直接用传入路径；漏掉 /api/trade 会 404（2026-11-05 实测）。"""
        js = (ROOT / "static" / "trade_chat.js").read_text(encoding="utf-8")
        assert "/api/trade/copilot/settings" in js
        assert "'/copilot/settings'" not in js


class TestCopilotMainGate:
    def test_exits_when_not_enabled(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        from trade.copilot_main import main

        assert main([]) == 2

    def test_bootstrap_dispatches_copilot(self):
        src = (ROOT / "trade" / "bootstrap.py").read_text(encoding="utf-8")
        assert '"copilot"' in src
        assert "copilot_main" in src

    def test_main_sets_trade_host_and_yolo_before_hermes(self):
        src = (ROOT / "trade" / "copilot_main.py").read_text(encoding="utf-8")
        assert 'TRADE_HOST' in src
        assert 'HERMES_YOLO_MODE' in src
        assert "set_dismiss_handler" in src
        assert src.index('TRADE_HOST') < src.index(
            "from trade.bootstrap import prepare_hermes_import_paths"
        )


class TestCopilotSpawnSettle:
    def test_immediate_exit_is_not_reported_running(self, monkeypatch, tmp_path):
        """Popen 成功但子进程秒退 → 不得报 running=True。"""
        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        # 撤掉 autouse 成功桩，测真实 settle。
        monkeypatch.setattr(api_mod, "_ensure_copilot_running", _REAL_ENSURE_COPILOT)
        monkeypatch.setattr(api_mod, "_SPAWN_SETTLE_SECONDS", 0.05)

        class FakeProc:
            pid = 4242
            returncode = 2

            def poll(self):
                return self.returncode

        monkeypatch.setattr(
            api_mod.subprocess, "Popen", lambda *a, **k: FakeProc()
        )
        ok, reason = api_mod._ensure_copilot_running(1)
        assert ok is False
        assert "立即退出" in reason
        assert api_mod._runtime_status()["running"] is False
        assert "立即退出" in (api_mod._runtime_status().get("error") or "")
