"""聊天副驾设置 API。

读写设置，并在开启/关闭时拉起/结束**独立的副驾进程**（热键 + 托盘 + 悬浮窗）。
副驾进程独立于 Trade 服务：启动失败只返回原因，不影响 Trade 本身。
默认关闭：未同意隐私说明不能开启；关闭状态下不会 spawn 任何进程。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from trade.api.deps import require_company
from trade.copilot.settings import (
    REQUIRED_CONSENT_VERSION,
    CopilotSettings,
    default_settings_path,
    load_settings,
    save_settings,
)

router = APIRouter(tags=["copilot"])

_WINDOWS_NEW_PROCESS_GROUP = 0x00000200


class CopilotSettingsPayload(BaseModel):
    enabled: bool | None = None
    consent_version: int | None = None
    use_clipboard: bool | None = None
    clipboard_max_chars: int | None = Field(default=None, ge=0)
    refused_apps: list[str] | None = None
    hotkey: str | None = None
    write_memory: bool | None = None


def _runtime_dir() -> Path:
    return default_settings_path().parent


def _pid_path() -> Path:
    return _runtime_dir() / "copilot.pid"


def _read_pid() -> int:
    try:
        return int(_pid_path().read_text(encoding="utf-8").strip())
    except Exception:
        return 0


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import psutil

        return bool(psutil.pid_exists(pid))
    except Exception:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _runtime_status() -> dict:
    pid = _read_pid()
    running = _pid_alive(pid)
    return {"running": running, "pid": pid if running else None}


def _ensure_copilot_running(company_id: int) -> tuple[bool, str]:
    """确保副驾独立进程在跑；已在跑则直接成功。失败只返回原因。"""
    if _runtime_status()["running"]:
        return True, ""
    if not company_id:
        return False, "未选择公司，副驾无法启动。"
    log_path = _runtime_dir() / "copilot.log"
    try:
        _runtime_dir().mkdir(parents=True, exist_ok=True)
        kwargs = {
            "stdin": subprocess.DEVNULL,
            "env": os.environ.copy(),
        }
        if os.name == "nt":
            kwargs["creationflags"] = _WINDOWS_NEW_PROCESS_GROUP
            kwargs["stdout"] = subprocess.DEVNULL
            kwargs["stderr"] = subprocess.DEVNULL
        else:
            kwargs["start_new_session"] = True
        with open(log_path, "a", encoding="utf-8") as log:
            if os.name != "nt":
                kwargs["stdout"] = log
                kwargs["stderr"] = log
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "trade.copilot_main",
                    "--company-id",
                    str(company_id),
                ],
                **kwargs,
            )
        _pid_path().write_text(str(proc.pid), encoding="utf-8")
        return True, ""
    except Exception as exc:
        return False, f"启动副驾进程失败：{exc}"


def _stop_copilot() -> None:
    pid = _read_pid()
    if pid and _pid_alive(pid):
        try:
            import psutil

            proc = psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except Exception:
                proc.kill()
        except Exception:
            try:
                os.kill(pid, 15)
            except OSError:
                pass
    try:
        _pid_path().unlink(missing_ok=True)
    except Exception:
        pass


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
        "runtime": _runtime_status(),
    }


@router.get("/copilot/settings")
def get_copilot_settings():
    """读取副驾设置与进程状态（默认全关）。"""
    return _payload(load_settings())


@router.put("/copilot/settings")
def update_copilot_settings(
    body: CopilotSettingsPayload,
    cid: int = Depends(require_company),
):
    """更新副驾设置；开启时后台拉起独立副驾进程，关闭时结束它。

    开启必须先同意隐私说明（400）。进程启动失败**不影响设置保存**，
    只在 runtime.error 里返回原因（Trade 主功能不受影响）。
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

    runtime: dict = {"running": False, "pid": None}
    if current.enabled:
        ok, reason = _ensure_copilot_running(cid)
        runtime = {"running": ok, "pid": _read_pid() or None}
        if not ok:
            runtime["error"] = reason
    else:
        _stop_copilot()
    return {**_payload(current), "runtime": runtime}
