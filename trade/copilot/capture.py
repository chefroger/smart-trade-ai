"""capture —— 触发式读取当前对话（平台无关的调度层）。

## 读取级联（任务书 §3）

    ① 剪贴板：内容像对话 + 自上次采用以来发生过变化 → 直接用文本
    ② 截图：取当前活动窗口（Windows PrintWindow→mss；macOS Quartz 按窗口 ID）

平台 API 全部在 `platform_win32.py` / `platform_darwin.py` 里；本模块只做
判定、调度与 base64 编码，能在任何平台单测。

## 剪贴板新鲜度为什么是"指纹变化"而不是"30 秒"

任务书原文要求"30 秒内更新过"，但 macOS 的批准依赖里没有 AppKit，
`pyperclip` 也拿不到剪贴板的变更时间/计数（Windows 同样只有序号、没有时间戳）。
Lau 于 2026-10-23 拍板 A 方案：把"30 秒内更新过"落成**内容指纹自上次采用以来
变过**——同样的内容再次触发时不再采用（视为陈旧），改为走截图。代价是首次触发
无法判断内容新旧，只能靠文本特征兜底；好处是不引入后台轮询（铁律 2）与额外依赖。

## 铁律

- 触发式：本模块不启动任何线程/定时器，只在被调用时读一次。
- 截图不落盘：只返回 base64 data URL，所有中间字节都在内存里。
- 剪贴板无损：读操作不改剪贴板；`clipboard_preserved()` 供将来任何临时写入使用。
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import sys
import threading
import time
from contextlib import contextmanager

from trade.copilot.platform_base import WindowCapture
from trade.copilot.types import CapturedWindow

_log = logging.getLogger(__name__)

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

    首次调用没有基线，按"新鲜"处理（Lau 2026-10-23 拍板的 A 方案）。
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


@contextmanager
def clipboard_preserved():
    """临时改写剪贴板时保存并恢复用户原内容（铁律 5）。

    当前读取路径不会写剪贴板，所以这里不需要包住 `read_clipboard()`；
    它是给任何"临时占用剪贴板"的操作准备的（测试见 tests/test_copilot_capture.py）。
    """
    module = _import_pyperclip()
    original: str | None = None
    if module is not None:
        try:
            original = module.paste()
        except Exception:
            original = None
    try:
        yield
    finally:
        if module is not None and original is not None:
            try:
                module.copy(original)
            except Exception as exc:
                _log.warning("恢复剪贴板失败：%s", exc)


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


def capture_conversation(
    *,
    platform=None,
    use_clipboard: bool = True,
) -> CapturedWindow:
    """执行一次触发式读取（剪贴板优先，失败回退截图）。

    Args:
        platform: 平台适配模块（测试注入用；None = 按 `sys.platform` 自动加载）。
        use_clipboard: 是否尝试剪贴板通道（设置里可关）。

    Returns:
        CapturedWindow。成功时 `channel` + (`text` 或 `image_data_url`) 有值；
        失败时 `error` / `error_kind` 有值，**不返回空成功**。
    """
    started = time.monotonic()

    if use_clipboard:
        text = read_clipboard()
        if text and looks_like_conversation(text) and claim_fresh_clipboard(text):
            return CapturedWindow(
                channel="clipboard",
                text=text,
                elapsed_ms=_elapsed_ms(started),
            )

    module = platform if platform is not None else load_platform()
    if module is None:
        return _failure(
            "当前平台不支持副驾截图（仅 Windows / macOS）。",
            "unsupported_platform",
            started,
        )

    available, reason = module.available()
    if not available:
        return _failure(reason, "missing_dependency", started)

    window: WindowCapture = module.capture_active_window()
    if not window.ok:
        return _failure(
            window.error or "读取当前窗口失败。",
            window.error_kind or "capture_failed",
            started,
            app_name=window.app_name,
            window_title=window.window_title,
        )

    return CapturedWindow(
        app_name=window.app_name,
        window_title=window.window_title,
        channel="screenshot",
        image_data_url=_png_data_url(window.image_png),
        elapsed_ms=_elapsed_ms(started),
    )


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
) -> CapturedWindow:
    return CapturedWindow(
        app_name=app_name,
        window_title=window_title,
        channel="screenshot",
        elapsed_ms=_elapsed_ms(started),
        error=error,
        error_kind=error_kind,
    )
