"""副驾设置 API 与设置弹窗回归（默认关闭 / 同意门禁）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from trade.api.copilot import (
    CopilotSettingsPayload,
    get_copilot_settings,
    update_copilot_settings,
)
from trade.copilot.settings import load_settings

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _isolated_settings_home(tmp_path, monkeypatch):
    """设置文件落在临时 TRADE_HOME；不真的拉起副驾进程。"""
    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    import trade.api.copilot as api_mod

    monkeypatch.setattr(api_mod, "_ensure_copilot_running", lambda cid: (True, ""))
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
        monkeypatch.setattr(
            api_mod, "_ensure_copilot_running",
            lambda cid: calls.append(("start", cid)) or (True, ""),
        )
        monkeypatch.setattr(
            api_mod, "_stop_copilot", lambda: calls.append(("stop",))
        )
        update_copilot_settings(
            CopilotSettingsPayload(enabled=True, consent_version=1), cid=7
        )
        update_copilot_settings(CopilotSettingsPayload(enabled=False), cid=7)
        assert calls == [("start", 7), ("stop",)]

    def test_save_without_enabling_does_not_spawn(self, monkeypatch):
        import trade.api.copilot as api_mod

        spawned = []
        monkeypatch.setattr(
            api_mod, "_ensure_copilot_running",
            lambda cid: spawned.append(cid) or (True, ""),
        )
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
