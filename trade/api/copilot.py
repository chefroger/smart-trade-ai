"""聊天副驾设置 API。

读写设置，并在开启/关闭时拉起/结束**独立的副驾进程**（热键 + 托盘 + 悬浮窗）。
副驾进程独立于 Trade 服务：启动失败只返回原因，不影响 Trade 本身。
默认关闭：未同意隐私说明不能开启；关闭状态下不会 spawn 任何进程。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
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
# spawn 后短等：子进程常因未同意/缺依赖秒退，不能只凭 Popen 成功就报「运行中」。
_SPAWN_SETTLE_SECONDS = 0.6
_STOP_WAIT_SECONDS = 3.0


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


def _error_path() -> Path:
    return _runtime_dir() / "copilot.last_error"


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


def _read_last_error() -> str:
    try:
        return _error_path().read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _write_last_error(reason: str) -> None:
    try:
        _runtime_dir().mkdir(parents=True, exist_ok=True)
        _error_path().write_text(reason or "", encoding="utf-8")
    except Exception:
        pass


def _clear_last_error() -> None:
    try:
        _error_path().unlink(missing_ok=True)
    except Exception:
        pass


def _runtime_status() -> dict:
    pid = _read_pid()
    running = _pid_alive(pid)
    status: dict = {"running": running, "pid": pid if running else None}
    # 上次启动失败原因（成功启动后清掉），设置页重开仍能看见。
    if not running:
        err = _read_last_error()
        if err:
            status["error"] = err
    return status


def _clear_pid_file() -> None:
    try:
        _pid_path().unlink(missing_ok=True)
    except Exception:
        pass


def _ensure_copilot_running(company_id: int, *, restart: bool = False) -> tuple[bool, str]:
    """确保副驾独立进程在跑。

    restart=True 时先停再起（保存设置后热键/公司/剪贴板才能生效）。
    启动后短等确认进程仍存活；秒退只返回原因，不假装成功。
    """
    if restart and _runtime_status()["running"]:
        _stop_copilot()
    elif _runtime_status()["running"]:
        return True, ""
    if not company_id:
        return False, "未选择公司，副驾无法启动。"
    log_path = _runtime_dir() / "copilot.log"
    log_handle = None
    try:
        _runtime_dir().mkdir(parents=True, exist_ok=True)
        # 故意不 with-close：子进程继承句柄后父进程关掉会让 Windows 丢日志。
        log_handle = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
        kwargs: dict = {
            "stdin": subprocess.DEVNULL,
            "stdout": log_handle,
            "stderr": log_handle,
            "env": os.environ.copy(),
        }
        if os.name == "nt":
            kwargs["creationflags"] = _WINDOWS_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
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
        time.sleep(_SPAWN_SETTLE_SECONDS)
        if proc.poll() is not None:
            _clear_pid_file()
            reason = (
                f"副驾进程启动后立即退出（退出码 {proc.returncode}）。"
                f"请查看日志：{log_path}"
            )
            _write_last_error(reason)
            return False, reason
        if not _pid_alive(proc.pid):
            _clear_pid_file()
            reason = f"副驾进程未保持运行。请查看日志：{log_path}"
            _write_last_error(reason)
            return False, reason
        _clear_last_error()
        return True, ""
    except Exception as exc:
        _clear_pid_file()
        reason = f"启动副驾进程失败：{exc}"
        _write_last_error(reason)
        return False, reason
    finally:
        # 父进程侧关掉写端；子进程已继承的 FD 仍可用（Unix/Windows 继承后独立）。
        if log_handle is not None:
            try:
                log_handle.close()
            except Exception:
                pass


def _stop_copilot() -> None:
    pid = _read_pid()
    if pid and _pid_alive(pid):
        try:
            import psutil

            proc = psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(timeout=_STOP_WAIT_SECONDS)
            except Exception:
                proc.kill()
        except Exception:
            try:
                os.kill(pid, 15)
            except OSError:
                pass
            # 无 psutil 时再短等，避免紧接着 restart 撞上未退出的旧进程。
            deadline = time.monotonic() + _STOP_WAIT_SECONDS
            while time.monotonic() < deadline and _pid_alive(pid):
                time.sleep(0.1)
    _clear_pid_file()


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
    开启状态下每次保存都重启副驾，保证热键/公司/剪贴板改动生效。
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
        ok, reason = _ensure_copilot_running(cid, restart=True)
        runtime = {"running": ok, "pid": _read_pid() or None}
        if not ok:
            runtime["error"] = reason
    else:
        _stop_copilot()
        _clear_last_error()
    return {**_payload(current), "runtime": runtime}
