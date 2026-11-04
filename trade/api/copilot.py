"""聊天副驾设置 API（仅读写设置，不启动副驾）。

默认关闭：本模块只持久化用户设置，**不注册热键、不启动服务、不读取屏幕**。
副驾接入启动流程是单独一步；在此之前安装/使用 Trade 与副驾无关。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from trade.copilot.settings import (
    REQUIRED_CONSENT_VERSION,
    CopilotSettings,
    load_settings,
    save_settings,
)

router = APIRouter(tags=["copilot"])


class CopilotSettingsPayload(BaseModel):
    enabled: bool | None = None
    consent_version: int | None = None
    use_clipboard: bool | None = None
    clipboard_max_chars: int | None = Field(default=None, ge=0)
    refused_apps: list[str] | None = None
    hotkey: str | None = None
    write_memory: bool | None = None


def _availability() -> dict:
    """依赖可用性（只探测 import，不启动任何东西）。"""
    try:
        from trade.copilot.hotkey import pynput_available

        hotkey_ok, hotkey_reason = pynput_available()
    except Exception as exc:
        hotkey_ok, hotkey_reason = False, str(exc)
    try:
        from trade.copilot.ui import available as ui_available

        ui_ok, ui_reason = ui_available()
    except Exception as exc:
        ui_ok, ui_reason = False, str(exc)
    return {
        "hotkey": {"available": hotkey_ok, "reason": hotkey_reason},
        "ui": {"available": ui_ok, "reason": ui_reason},
    }


def _payload(settings: CopilotSettings) -> dict:
    return {
        "settings": settings.to_dict(),
        "required_consent_version": REQUIRED_CONSENT_VERSION,
        "availability": _availability(),
    }


@router.get("/copilot/settings")
def get_copilot_settings():
    """读取副驾设置（默认全关）。"""
    return _payload(load_settings())


@router.put("/copilot/settings")
def update_copilot_settings(body: CopilotSettingsPayload):
    """更新副驾设置。

    开启（enabled=true）必须先同意隐私说明（consent_version 达标），
    否则 400。这里**只写设置文件**，不会让副驾开始运行。
    """
    current = load_settings()
    data = body.model_dump(exclude_none=True)
    for key, value in data.items():
        setattr(current, key, value)
    current = current.sanitized()
    if data.get("enabled") and not current.consent_ok():
        raise HTTPException(status_code=400, detail="请先阅读并同意副驾隐私说明。")
    if not save_settings(current):
        raise HTTPException(status_code=500, detail="保存副驾设置失败。")
    return _payload(current)
