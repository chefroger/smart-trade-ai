"""Windows 平台适配：当前活动窗口 + 窗口截图。

截图策略（任务书 §3）：优先 `PrintWindow`（能拿到被遮挡窗口的内容），
失败或得到全黑位图时回退 `mss` 抓取窗口所在屏幕区域。

只读：不注入按键、不发消息、不落盘（守卫测试见 tests/test_copilot_guard.py）。
所有 Win32 调用都用 ctypes，`pywin32` 不是必需依赖。
注意：`mss` 是截图路径的必需依赖 —— PrintWindow 抓到的位图也由 `mss.tools`
编码成 PNG，回退路径同样用它抓屏；缺 mss 时截图整体不可用（副驾降级）。
"""

from __future__ import annotations

import ctypes
import logging
import ntpath
import sys
from ctypes import wintypes

from trade.copilot.platform_base import WindowCapture

_log = logging.getLogger(__name__)

_PW_RENDERFULLCONTENT = 0x00000002
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)


class _BITMAPINFOHEADER(ctypes.Structure):
    """GetDIBits 需要的位图头（32bpp BGRA，top-down）。"""

    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


_dll_cache: tuple | None = None


def _dlls():
    """加载 (user32, gdi32, kernel32) 并设置 64 位句柄签名（结果缓存在模块内）。

    **必须显式设置 restype**：ctypes 默认把返回值当 `c_int`（32 位），而
    HWND / HDC / HBITMAP / HANDLE 在 64 位 Windows 上是指针宽度 —— 句柄值
    一旦超过 2^31 就会被截断成负数，后续 PrintWindow/GetDIBits 全部拿到坏句柄。
    """
    global _dll_cache
    if _dll_cache is not None:
        return _dll_cache
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    kernel32 = ctypes.windll.kernel32
    _configure_win32(user32, gdi32, kernel32)
    _dll_cache = (user32, gdi32, kernel32)
    return _dll_cache


def _configure_win32(user32, gdi32, kernel32) -> None:
    """给所有涉及句柄的函数标注类型；单项失败只记日志，不影响其余调用。"""
    signatures = {
        # (dll, 函数名): (restype, argtypes)
        (user32, "GetForegroundWindow"): (wintypes.HWND, []),
        (user32, "IsWindowVisible"): (wintypes.BOOL, [wintypes.HWND]),
        (user32, "IsIconic"): (wintypes.BOOL, [wintypes.HWND]),
        (user32, "GetWindowTextLengthW"): (
            ctypes.c_int, [wintypes.HWND],
        ),
        (user32, "GetWindowTextW"): (
            ctypes.c_int, [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int],
        ),
        (user32, "GetWindowRect"): (
            wintypes.BOOL, [wintypes.HWND, ctypes.POINTER(wintypes.RECT)],
        ),
        (user32, "GetWindowThreadProcessId"): (
            wintypes.DWORD, [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)],
        ),
        (user32, "GetWindowDC"): (wintypes.HDC, [wintypes.HWND]),
        (user32, "ReleaseDC"): (
            ctypes.c_int, [wintypes.HWND, wintypes.HDC],
        ),
        (user32, "PrintWindow"): (
            wintypes.BOOL, [wintypes.HWND, wintypes.HDC, wintypes.UINT],
        ),
        (gdi32, "CreateCompatibleDC"): (wintypes.HDC, [wintypes.HDC]),
        (gdi32, "CreateCompatibleBitmap"): (
            wintypes.HBITMAP, [wintypes.HDC, ctypes.c_int, ctypes.c_int],
        ),
        (gdi32, "SelectObject"): (
            wintypes.HGDIOBJ, [wintypes.HDC, wintypes.HGDIOBJ],
        ),
        (gdi32, "DeleteObject"): (wintypes.BOOL, [wintypes.HGDIOBJ]),
        (gdi32, "DeleteDC"): (wintypes.BOOL, [wintypes.HDC]),
        (gdi32, "GetDIBits"): (
            ctypes.c_int,
            [
                wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
            ],
        ),
        (kernel32, "OpenProcess"): (
            wintypes.HANDLE, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD],
        ),
        (kernel32, "QueryFullProcessImageNameW"): (
            wintypes.BOOL,
            [
                wintypes.HANDLE, wintypes.DWORD,
                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
            ],
        ),
        (kernel32, "CloseHandle"): (wintypes.BOOL, [wintypes.HANDLE]),
    }
    for (dll, name), (restype, argtypes) in signatures.items():
        try:
            function = getattr(dll, name)
            function.restype = restype
            function.argtypes = argtypes
        except Exception as exc:
            _log.debug("设置 %s 签名失败：%s", name, exc)


def available() -> tuple[bool, str]:
    """Windows 上 Win32 API 随系统可用。

    注意：截图**整体**依赖 mss —— PrintWindow 抓到的位图由 mss.tools 编码成
    PNG，回退路径也用它抓屏。缺 mss 时截图不可用（副驾降级，不影响主功能）。
    """
    if sys.platform != "win32":
        return False, "Windows 截图模块只能在 Windows 上使用。"
    try:
        _dlls()
    except Exception as exc:
        return False, f"Win32 API 不可用：{exc}"
    try:
        import mss  # noqa: F401 —— 仅探测依赖可用性
    except Exception:
        return False, "缺少依赖 mss，副驾截图不可用。"
    return True, ""


def permission_guide() -> dict:
    """Windows 没有屏幕录制授权；返回空结构，UI 统一处理。"""
    return {}


def capture_active_window() -> WindowCapture:
    """截取当前前台窗口（内存 PNG + 应用名 + 标题）。"""
    user32, gdi32, kernel32 = _dlls()
    _apply_per_monitor_dpi_awareness(user32)

    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return WindowCapture(error="没有找到前台窗口。", error_kind="no_window")

    title = _window_title(user32, hwnd)
    app_name = _process_name(user32, kernel32, hwnd)

    if not user32.IsWindowVisible(hwnd):
        return WindowCapture(
            app_name=app_name, window_title=title,
            error="前台窗口不可见。", error_kind="no_window",
        )
    if user32.IsIconic(hwnd):
        return WindowCapture(
            app_name=app_name, window_title=title,
            error="前台窗口已最小化，无法读取。请先还原窗口。",
            error_kind="minimized",
        )

    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return WindowCapture(
            app_name=app_name, window_title=title,
            error="读取窗口尺寸失败。", error_kind="capture_failed",
        )
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width <= 0 or height <= 0:
        return WindowCapture(
            app_name=app_name, window_title=title,
            error="窗口尺寸无效。", error_kind="capture_failed",
        )

    image_png = _print_window_png(user32, gdi32, hwnd, width, height)
    if not image_png:
        # PrintWindow 对部分应用（GPU 渲染/受保护窗口）返回黑图 → 回退抓屏
        image_png = _grab_region_png(rect)
    if not image_png:
        return WindowCapture(
            app_name=app_name, window_title=title,
            error="窗口截图失败（PrintWindow 与屏幕抓取都不可用）。",
            error_kind="capture_failed",
        )

    return WindowCapture(
        image_png=image_png, app_name=app_name, window_title=title,
    )


# ── 内部实现 ────────────────────────────────────────────────────────────────

def _apply_per_monitor_dpi_awareness(user32) -> None:
    """让 GetWindowRect 返回物理像素（只影响当前线程，不改主程序 UI 缩放）。"""
    try:
        user32.SetThreadDpiAwarenessContext(
            _DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        )
    except Exception:
        pass


def _window_title(user32, hwnd) -> str:
    length = int(user32.GetWindowTextLengthW(hwnd))
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _process_name(user32, kernel32, hwnd) -> str:
    """取窗口所属进程的可执行文件名（拿不到就返回空串）。"""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    handle = kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value
    )
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(
            handle, 0, buffer, ctypes.byref(size)
        ):
            # 显式用 ntpath：Windows 路径的反斜杠在 POSIX 上 os.path 不认，
            # 这样 mock 测试在任何平台上结果一致。
            return ntpath.basename(buffer.value)
    except Exception:
        pass
    finally:
        kernel32.CloseHandle(handle)
    return ""


def _print_window_png(user32, gdi32, hwnd, width: int, height: int) -> bytes:
    """PrintWindow → 32bpp DIB → PNG；失败返回空字节。"""
    hdc_window = user32.GetWindowDC(hwnd)
    if not hdc_window:
        return b""
    hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
    bitmap = gdi32.CreateCompatibleBitmap(hdc_window, width, height)
    if not hdc_mem or not bitmap:
        _release_dc(user32, gdi32, hwnd, hdc_window, hdc_mem, bitmap)
        return b""

    old_object = gdi32.SelectObject(hdc_mem, bitmap)
    try:
        if not user32.PrintWindow(hwnd, hdc_mem, _PW_RENDERFULLCONTENT):
            return b""

        # GetDIBits 要求位图不在 DC 中
        gdi32.SelectObject(hdc_mem, old_object)

        header = _BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        header.biWidth = width
        header.biHeight = -height  # 负数 = top-down，省一次翻转
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0  # BI_RGB

        buffer = ctypes.create_string_buffer(width * height * 4)
        copied = gdi32.GetDIBits(
            hdc_mem, bitmap, 0, height, buffer,
            ctypes.byref(header), 0,
        )
        if copied != height:
            return b""
        raw = buffer.raw
        if not any(raw):
            # 全黑图：常见于 GPU 渲染窗口，交给 mss 回退
            return b""
        return _bgra_to_png(raw, width, height)
    finally:
        # PrintWindow 失败时位图仍在 DC 里 —— 先恢复旧对象，DeleteObject 才有效
        try:
            if hdc_mem and old_object:
                gdi32.SelectObject(hdc_mem, old_object)
        except Exception:
            pass
        _release_dc(user32, gdi32, hwnd, hdc_window, hdc_mem, bitmap)


def _release_dc(user32, gdi32, hwnd, hdc_window, hdc_mem, bitmap) -> None:
    try:
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if hdc_mem:
            gdi32.DeleteDC(hdc_mem)
        if hdc_window:
            user32.ReleaseDC(hwnd, hdc_window)
    except Exception:
        pass


def _bgra_to_png(raw: bytes, width: int, height: int) -> bytes:
    """BGRA → RGB 后交给 mss 的纯 Python PNG 编码器（不依赖 Pillow）。"""
    try:
        import mss.tools  # type: ignore
    except Exception as exc:
        _log.debug("mss 不可用：%s", exc)
        return b""
    pixels = bytearray(width * height * 3)
    # 步长切片在 C 层完成，比逐像素循环快一个数量级
    pixels[0::3] = raw[2::4]
    pixels[1::3] = raw[1::4]
    pixels[2::3] = raw[0::4]
    try:
        return mss.tools.to_png(bytes(pixels), (width, height))
    except Exception as exc:
        _log.warning("PNG 编码失败：%s", exc)
        return b""


def _grab_region_png(rect) -> bytes:
    """mss 回退：抓窗口所在的屏幕区域（窗口被遮挡时会抓到上层内容）。"""
    try:
        import mss
        import mss.tools  # type: ignore
    except Exception as exc:
        _log.debug("mss 不可用：%s", exc)
        return b""
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width <= 0 or height <= 0:
        return b""
    try:
        with mss.mss() as sct:
            shot = sct.grab({
                "left": int(rect.left),
                "top": int(rect.top),
                "width": width,
                "height": height,
            })
            return mss.tools.to_png(shot.rgb, shot.size)
    except Exception as exc:
        _log.warning("屏幕区域抓取失败：%s", exc)
        return b""
