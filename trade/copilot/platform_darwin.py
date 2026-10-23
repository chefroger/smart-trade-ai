"""macOS 平台适配：当前活动窗口 + 按窗口 ID 截图 + 屏幕录制权限链路。

权限（任务书 §3，macOS 头等公民）：
    - 截图需要"屏幕录制"权限；用 `CGPreflightScreenCaptureAccess()` 只查询、
      不弹窗；`CGRequestScreenCaptureAccess()` 由 UI 的引导按钮显式调用一次。
    - 权限缺失时返回结构化错误（error_kind="permission"），由 service 降级为
      剪贴板通道或"点按钮触发"，**不影响 trade 主功能**。
    - `permission_guide()` 提供系统设置直达链接与原因文案（引导只出一次由 UI 控制）。

只读：不注入事件、不落盘。Quartz 懒加载，缺依赖只降级。
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys

from trade.copilot.platform_base import WindowCapture

_log = logging.getLogger(__name__)

# 系统设置 → 隐私与安全性 → 屏幕录制
_SCREEN_RECORDING_SETTINGS_URL = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
)

# 不应被当作"聊天窗口"的系统进程
_SYSTEM_OWNERS = frozenset({
    "Window Server", "Dock", "SystemUIServer", "Control Center",
    "Notification Center", "loginwindow",
})

_quartz_module = None


def _quartz():
    """懒加载 Quartz（pyobjc-framework-Quartz）；缺失返回 None。"""
    global _quartz_module
    if _quartz_module is not None:
        return _quartz_module
    try:
        import Quartz  # type: ignore

        _quartz_module = Quartz
        return Quartz
    except Exception as exc:
        _log.debug("Quartz 不可用：%s", exc)
        return None


def available() -> tuple[bool, str]:
    if sys.platform != "darwin":
        return False, "macOS 截图模块只能在 macOS 上使用。"
    quartz = _quartz()
    if quartz is None:
        return False, "缺少依赖 pyobjc-framework-Quartz，副驾截图不可用。"
    if not hasattr(quartz, "CGWindowListCreateImage"):
        return False, "当前 macOS 不再提供 CGWindowListCreateImage，截图通道不可用。"
    return True, ""


def screen_recording_granted() -> bool:
    """查询屏幕录制权限（不触发系统弹窗）。"""
    quartz = _quartz()
    if quartz is None:
        return False
    preflight = getattr(quartz, "CGPreflightScreenCaptureAccess", None)
    if preflight is None:
        # 旧版 macOS 没有 TCC 查询接口：按已授权处理（系统会在截图时自行弹窗）
        return True
    try:
        return bool(preflight())
    except Exception as exc:
        _log.warning("查询屏幕录制权限失败：%s", exc)
        return False


def request_screen_recording_permission() -> bool:
    """请求屏幕录制权限（会触发一次系统弹窗）——只应由 UI 引导按钮调用。"""
    quartz = _quartz()
    if quartz is None:
        return False
    request = getattr(quartz, "CGRequestScreenCaptureAccess", None)
    if request is None:
        return screen_recording_granted()
    try:
        return bool(request())
    except Exception as exc:
        _log.warning("请求屏幕录制权限失败：%s", exc)
        return False


def permission_guide() -> dict:
    """权限状态 + 原因 + 系统设置直达链接（UI 用来做一次性引导）。"""
    return {
        "screen_recording": {
            "granted": screen_recording_granted(),
            "reason": "副驾需要“屏幕录制”权限，才能在你按下热键时截取当前聊天窗口。",
            "settings_url": _SCREEN_RECORDING_SETTINGS_URL,
        },
    }


def capture_active_window() -> WindowCapture:
    """按窗口 ID 截取当前前台聊天窗口（内存 PNG）。"""
    quartz = _quartz()
    if quartz is None:
        return WindowCapture(
            error="缺少依赖 pyobjc-framework-Quartz，副驾截图不可用。",
            error_kind="missing_dependency",
        )
    if not screen_recording_granted():
        return WindowCapture(
            error="没有“屏幕录制”权限，无法截图。请在系统设置中授权后重试。",
            error_kind="permission",
        )
    if not hasattr(quartz, "CGWindowListCreateImage"):
        return WindowCapture(
            error="当前 macOS 不再提供窗口截图接口（CGWindowListCreateImage）。",
            error_kind="unsupported_os",
        )

    window_info = _frontmost_window(quartz)
    if window_info is None:
        return WindowCapture(
            error="没有找到可读取的前台窗口。", error_kind="no_window",
        )
    window_id, owner, title = window_info

    image = quartz.CGWindowListCreateImage(
        quartz.CGRectNull,
        quartz.kCGWindowListOptionIncludingWindow,
        window_id,
        quartz.kCGWindowImageBoundsIgnoreFraming
        | quartz.kCGWindowImageShouldBeOpaque,
    )
    if image is None:
        return WindowCapture(
            app_name=owner, window_title=title,
            error="窗口截图失败（可能窗口已关闭或无权限）。",
            error_kind="capture_failed",
        )

    image_png = _cgimage_to_png(quartz, image)
    if not image_png:
        return WindowCapture(
            app_name=owner, window_title=title,
            error="窗口图像编码失败。", error_kind="capture_failed",
        )
    return WindowCapture(image_png=image_png, app_name=owner, window_title=title)


# ── 内部实现 ────────────────────────────────────────────────────────────────

def _frontmost_window(quartz) -> tuple[int, str, str] | None:
    """窗口列表是前到后排序的：取第一个正常的应用窗口。

    排除：非 0 层（菜单栏/Dock/桌面）、自己的进程（副驾悬浮窗）、系统进程、
    过小的窗口（图标/工具提示）。bounds 的键在 PyObjC 里是字符串。
    """
    try:
        windows = quartz.CGWindowListCopyWindowInfo(
            quartz.kCGWindowListOptionOnScreenOnly
            | quartz.kCGWindowListExcludeDesktopElements,
            quartz.kCGNullWindowID,
        ) or []
    except Exception as exc:
        _log.warning("读取窗口列表失败：%s", exc)
        return None

    own_pid = os.getpid()
    for info in windows:
        try:
            if int(info.get(quartz.kCGWindowLayer, 1)) != 0:
                continue
            if int(info.get(quartz.kCGWindowOwnerPID, -1)) == own_pid:
                continue
            if not info.get(quartz.kCGWindowIsOnscreen, True):
                continue
            owner = str(info.get(quartz.kCGWindowOwnerName) or "")
            if not owner or owner in _SYSTEM_OWNERS:
                continue
            bounds = info.get(quartz.kCGWindowBounds) or {}
            width = float(bounds.get("Width") or 0)
            height = float(bounds.get("Height") or 0)
            if width < 120 or height < 80:
                continue
            window_id = info.get(quartz.kCGWindowNumber)
            if window_id is None:
                continue
            title = str(info.get(quartz.kCGWindowName) or "")
            return int(window_id), owner, title
        except Exception:
            continue
    return None


def _cgimage_to_png(quartz, image) -> bytes:
    """CGImage → PNG 字节（ImageIO 在内存中完成，不落盘）。"""
    create_dest = getattr(quartz, "CGImageDestinationCreateWithData", None)
    if create_dest is None:
        _log.warning("当前 PyObjC 没有 ImageIO 绑定，无法把 CGImage 编码成 PNG")
        return b""
    try:
        data = quartz.CFDataCreateMutable(None, 0)
        destination = create_dest(data, "public.png", 1, None)
        if not destination:
            return b""
        quartz.CGImageDestinationAddImage(destination, image, None)
        if not quartz.CGImageDestinationFinalize(destination):
            return b""
        length = int(quartz.CFDataGetLength(data))
        pointer = quartz.CFDataGetBytePtr(data)
        try:
            # PyObjC 把指针暴露成 objc.varlist：切片得到的是「单字节 bytes」
            # 组成的 tuple（不是 int），所以必须 join，不能直接 bytes()。
            return b"".join(pointer[:length])
        except TypeError:
            # 某些版本返回整数地址（ctypes.string_at 需要 c_void_p/int）
            return ctypes.string_at(pointer, length)
    except Exception as exc:
        _log.warning("CGImage 转 PNG 失败：%s", exc)
        return b""
