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
    """设置文件落在临时 TRADE_HOME，不碰真实 ~/.trade。"""
    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
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
            update_copilot_settings(CopilotSettingsPayload(enabled=True))
        assert exc.value.status_code == 400
        assert load_settings().enabled is False

    def test_enable_with_consent_persists(self):
        payload = update_copilot_settings(
            CopilotSettingsPayload(enabled=True, consent_version=1)
        )
        assert payload["settings"]["enabled"] is True
        assert load_settings().enabled is True

    def test_saving_does_not_start_anything(self, monkeypatch):
        """设置 API 只写文件；不得 import/启动 service、hotkey、ui。"""
        import trade.api.copilot as api_mod

        for name in ("service", "hotkey", "ui"):
            assert name not in vars(api_mod), "设置 API 不得加载副驾运行模块"

        payload = update_copilot_settings(
            CopilotSettingsPayload(consent_version=1, use_clipboard=True)
        )
        assert payload["settings"]["use_clipboard"] is True


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
