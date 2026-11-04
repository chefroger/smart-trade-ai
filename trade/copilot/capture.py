"""capture —— 触发式读取当前对话（平台无关的调度层）。

## 读取级联（任务书 §3）

    ① 剪贴板：内容像对话 + 自上次采用以来发生过变化 → 直接用文本
    ② 截图：取当前活动窗口（Windows PrintWindow→mss；macOS Quartz 按窗口 ID）

平台 API 全部在 `platform_win32.py` / `platform_darwin.py` 里；本模块只做
判定、调度与 base64 编码，能在任何平台单测。

## 剪贴板新鲜度为什么是"指纹变化"而不是"30 秒"

任务书原文要求"30 秒内更新过"，但 macOS 的批准依赖里没有 AppKit，
`pyperclip` 也拿不到剪贴板的变更时间/计数（Windows 同样只有序号、没有时间戳）。
按任务书 §3 修订口径（2026-10-23 裁定）：把"30 秒内更新过"落成**内容指纹自
上次采用以来变过**——同样的内容再次触发时不再采用（视为陈旧），改为走截图。
首次触发没有基线按新鲜处理（否则第一次就撞权限墙）；代价是无法判断内容新旧，
由对话特征判定 + 草稿人工确认兜住。好处是不引入后台轮询（铁律 2）与额外依赖。

## 铁律

- 触发式：本模块不启动任何线程/定时器，只在被调用时读一次。
- 截图不落盘：只返回 base64 data URL，所有中间字节都在内存里。
- 剪贴板无损：副驾只读剪贴板，代码里没有写剪贴板的路径（"复制草稿"是 UI 行为）。
- 剪贴板通道默认关，且单次发送有字符上限（默认 3000，超限改走截图）。
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import sys
import threading
import time

from trade.copilot.platform_base import WindowCapture
from trade.copilot.types import CapturedWindow

_log = logging.getLogger(__name__)

# 剪贴板单次发送上限：一屏聊天通常远短于此，防误发长合同等无关内容。
DEFAULT_CLIPBOARD_MAX_CHARS = 3000
CLIPBOARD_TOO_LONG_NOTICE = "剪贴板内容过长，已改为读取屏幕"

# 拒读名单：内置类别只写通用条目，不按国家/具体银行写死。
# 用户自定义条目由调用方通过 `refused_apps` 传入。
_REFUSED_APP_PATTERNS = (
    # 密码管理器
    "1password", "bitwarden", "lastpass", "dashlane", "keeper",
    "keepass", "enpass", "password manager", "密码管理",
    # 网银 / 支付
    "bank", "banking", "网银", "银行", "alipay", "支付宝",
    "paypal", "wallet", "支付",
)


def is_refused_app(app_name: str, extra: tuple[str, ...] | list[str] = ()) -> bool:
    """前台应用是否命中拒读名单（纯函数，便于测试）。

    匹配规则：应用标识的小写子串命中任一内置/自定义条目。宁可误拒（用户
    切回聊天窗口即可），也不把密码管理器/网银内容送进模型。
    """
    name = (app_name or "").strip().lower()
    if not name:
        return False
    patterns = tuple(str(x).strip().lower() for x in extra if str(x).strip())
    return any(p in name for p in (*_REFUSED_APP_PATTERNS, *patterns))


def _default_clipboard_max_chars() -> int:
    """剪贴板字符上限（设置可改；当前先支持环境变量）。"""
    raw = os.environ.get("TRADE_COPILOT_CLIPBOARD_MAX_CHARS", "").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_CLIPBOARD_MAX_CHARS
    return value if value > 0 else DEFAULT_CLIPBOARD_MAX_CHARS

# 对话文本特征（任务书 §3 "多行、含发言人/时间特征"）
_SPEAKER_RE = re.compile(
    r"(?im)^\s*(?:"
    r"(?:客户|对方|买家|卖家|我|我方|客服)\s*[:：]"
    r"|(?:customer|client|buyer|seller|me|you|them|support)\s*[:：]"
    r")"
)
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
_EMAIL_RE = re.compile(
    r"(?im)^\s*(?:from|sent|to|subject|date|发件人|收件人|发送时间|主题)\s*[:：]"
)

# 剪贴板新鲜度状态：内容指纹（进程内，仅在触发时更新）
_clipboard_lock = threading.Lock()
_last_clipboard_fingerprint: str | None = None


def looks_like_conversation(text: str) -> bool:
    """判断剪贴板文本是否像一段聊天/邮件对话（可测的纯函数）。

    采用条件：长度够 + 出现发言人/时间/邮件头特征之一。
    宁可漏判（退回截图），也不要把复制的一段代码/一段文章当成对话。
    """
    content = (text or "").strip()
    if len(content) < 10:
        return False
    has_speaker = bool(_SPEAKER_RE.search(content))
    has_time = bool(_TIME_RE.search(content))
    has_email = bool(_EMAIL_RE.search(content))
    if not (has_speaker or has_time or has_email):
        return False
    # 单行但有明确发言人/邮件头也算（"John: what is your MOQ?"）；
    # 单行只有时间（"10:23"）已经被长度条件挡掉。
    return True


def clipboard_fingerprint(text: str) -> str:
    """内容指纹：归一空白后取 SHA-256。"""
    normalized = re.sub(r"\s+", " ", text or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def claim_fresh_clipboard(text: str) -> bool:
    """内容自上次采用以来变过 → True 并记住；否则 False（视为陈旧）。

    口径（任务书 §3 修订版）：基线只在**采用**时更新；首次触发没有基线，
    按新鲜处理 —— 否则第一次就把用户推去撞 macOS 权限墙，第一体验直接毁掉。
    残余风险由对话特征判定 + 草稿人工确认兜住。
    """
    global _last_clipboard_fingerprint
    fingerprint = clipboard_fingerprint(text)
    with _clipboard_lock:
        if _last_clipboard_fingerprint == fingerprint:
            return False
        _last_clipboard_fingerprint = fingerprint
        return True


def reset_clipboard_freshness() -> None:
    """清空剪贴板基线（测试与"暂停/恢复"时用）。"""
    global _last_clipboard_fingerprint
    with _clipboard_lock:
        _last_clipboard_fingerprint = None


def _import_pyperclip():
    """懒加载剪贴板库；缺失时返回 None（副驾降级，不影响主功能）。"""
    try:
        import pyperclip  # type: ignore

        return pyperclip
    except Exception as exc:
        _log.debug("剪贴板依赖不可用：%s", exc)
        return None


def read_clipboard() -> str:
    """读当前剪贴板文本；依赖缺失/读取失败一律返回空串。"""
    module = _import_pyperclip()
    if module is None:
        return ""
    try:
        return module.paste() or ""
    except Exception as exc:
        _log.warning("读取剪贴板失败：%s", exc)
        return ""


def load_platform():
    """按运行平台加载适配模块；不支持的平台返回 None。"""
    if sys.platform == "win32":
        from trade.copilot import platform_win32 as module
    elif sys.platform == "darwin":
        from trade.copilot import platform_darwin as module
    else:
        return None
    return module


def permission_guide() -> dict:
    """权限状态 + 原因 + 系统设置直达链接（macOS 引导用；其他平台返回空）。"""
    module = load_platform()
    if module is None:
        return {}
    guide = getattr(module, "permission_guide", None)
    return guide() if callable(guide) else {}


def request_screen_recording_permission() -> bool:
    """请求屏幕录制权限（会弹一次系统对话框）——只应由引导按钮调用一次。"""
    module = load_platform()
    if module is None:
        return False
    request = getattr(module, "request_screen_recording_permission", None)
    return bool(request()) if callable(request) else False


def ensure_screen_permission() -> bool:
    """运行时权限引导：没有权限就弹系统对话框 / 自动拉起设置页（进程内只做一次）。

    Windows 不需要该权限 → True；macOS 由 platform_darwin 实现一次性引导。
    """
    module = load_platform()
    if module is None:
        return False
    ensure = getattr(module, "ensure_screen_recording_permission", None)
    if callable(ensure):
        return bool(ensure())
    return True


def capture_conversation(
    *,
    platform=None,
    use_clipboard: bool = False,
    max_clipboard_chars: int | None = None,
    refused_apps: tuple[str, ...] | list[str] = (),
) -> CapturedWindow:
    """执行一次触发式读取（剪贴板可选，失败回退截图）。

    Args:
        platform: 平台适配模块（测试注入用；None = 按 `sys.platform` 自动加载）。
        use_clipboard: 是否尝试剪贴板通道（任务书 §6：默认关）。
        max_clipboard_chars: 剪贴板单次发送上限（None = 默认 3000，可被环境变量覆盖）。
        refused_apps: 用户自定义拒读条目（内置类别见 `_REFUSED_APP_PATTERNS`）。

    Returns:
        CapturedWindow。成功时 `channel` + (`text` 或 `image_data_url`) 有值；
        失败时 `error` / `error_kind` 有值，**不返回空成功**。
    """
    started = time.monotonic()
    module = platform if platform is not None else load_platform()

    # 拒读名单必须在读剪贴板/截图之前判断：密码管理器、网银等前台应用一律不碰。
    app_name = ""
    if module is not None:
        try:
            getter = getattr(module, "active_app_name", None)
            app_name = str(getter() or "") if callable(getter) else ""
        except Exception as exc:
            _log.debug("读取前台应用失败：%s", exc)
            app_name = ""
        if is_refused_app(app_name, refused_apps):
            return _failure(
                "该应用在拒读名单内，未读取。",
                "refused",
                started,
                app_name=app_name,
            )

    notice = ""
    if use_clipboard:
        text = read_clipboard()
        limit = max_clipboard_chars or _default_clipboard_max_chars()
        if text and len(text) > limit:
            # 不截断、不发送，改走截图；提示由 UI 原样展示。
            notice = CLIPBOARD_TOO_LONG_NOTICE
        elif text and looks_like_conversation(text) and claim_fresh_clipboard(text):
            return CapturedWindow(
                app_name=app_name,
                channel="clipboard",
                text=text,
                elapsed_ms=_elapsed_ms(started),
            )

    if module is None:
        return _failure(
            "当前平台不支持副驾截图（仅 Windows / macOS）。",
            "unsupported_platform",
            started,
            notice=notice,
        )

    available, reason = module.available()
    if not available:
        return _failure(reason, "missing_dependency", started, notice=notice)

    window: WindowCapture = module.capture_active_window()
    if not window.ok:
        # 权限缺失时在**运行时**拉起引导（系统弹窗 + 设置页），而不是要求用户
        # 提前配置；进程内只做一次，避免反复骚扰（任务书 §3）。
        if window.error_kind == "permission":
            _trigger_permission_guide(module)
        return _failure(
            window.error or "读取当前窗口失败。",
            window.error_kind or "capture_failed",
            started,
            app_name=window.app_name,
            window_title=window.window_title,
            notice=notice,
        )

    return CapturedWindow(
        app_name=window.app_name,
        window_title=window.window_title,
        channel="screenshot",
        image_data_url=_png_data_url(window.image_png),
        elapsed_ms=_elapsed_ms(started),
        notice=notice,
    )


def _trigger_permission_guide(module) -> None:
    """尽量拉起平台的一次性权限引导；失败不影响错误返回。"""
    ensure = getattr(module, "ensure_screen_recording_permission", None)
    if not callable(ensure):
        return
    try:
        ensure()
    except Exception as exc:  # 引导失败不能盖住"没有权限"这个主错误
        _log.warning("拉起权限引导失败：%s", exc)


def _png_data_url(image_png: bytes) -> str:
    encoded = base64.b64encode(image_png).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _failure(
    error: str,
    error_kind: str,
    started: float,
    *,
    app_name: str = "",
    window_title: str = "",
    notice: str = "",
) -> CapturedWindow:
    return CapturedWindow(
        app_name=app_name,
        window_title=window_title,
        channel="screenshot",
        elapsed_ms=_elapsed_ms(started),
        error=error,
        error_kind=error_kind,
        notice=notice,
    )
