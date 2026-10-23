"""平台适配层的公共契约（仅 capture 用）。

共享模块（`capture.py`）只 import 这里的数据结构，**不 import 任何平台 API**。
平台实现（`platform_win32.py` / `platform_darwin.py`）各自返回 `WindowCapture`：

    available() -> (bool, reason)      依赖是否齐全（缺依赖只降级，不崩）
    capture_active_window() -> WindowCapture
    permission_guide() -> dict          权限状态 + 系统设置直达链接（macOS 用）

截图只在内存里流转：这里只带 PNG 字节，不提供任何落盘方法（铁律 6）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WindowCapture:
    """一次窗口截图的平台返回值（成功或失败都用这个结构）。"""

    # PNG 字节（内存中；失败时为空）
    image_png: bytes = b""
    # 窗口所属应用名（如 "WeChat" / "chrome.exe"）
    app_name: str = ""
    # 窗口标题
    window_title: str = ""
    # 失败原因（成功时为空）
    error: str = ""
    # "permission" / "no_window" / "minimized" / "capture_failed"
    error_kind: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.image_png) and not self.error
