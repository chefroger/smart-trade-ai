"""聊天副驾托盘/菜单栏图标（pystray 惰性加载）。

- 依赖缺失时 `start()` 只返回原因，调用方降级为设置页按钮，不影响 Trade。
- 托盘只提供三个动作：开启/关闭副驾、暂停/恢复、退出托盘。
- **默认不创建**：只有调用方显式 `start()` 才会出现图标。
- 点击图标不得弹出终端窗口（pystray 在 macOS/Windows 均为原生托盘）。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

_log = logging.getLogger(__name__)


def available() -> tuple[bool, str]:
    try:
        import pystray  # noqa: F401
    except Exception as exc:
        return False, f"缺少依赖 pystray，托盘不可用（可用设置页控制）：{exc}"
    return True, ""


def _icon_image():
    """生成一个简单的托盘图标（pystray 依赖 Pillow）。"""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (64, 64), (24, 24, 27))
    draw = ImageDraw.Draw(image)
    draw.ellipse((12, 12, 52, 52), fill=(90, 160, 255))
    draw.rectangle((26, 26, 38, 38), fill=(24, 24, 27))
    return image


class TrayIcon:
    """托盘图标；`start()` 在后台线程运行，`stop()` 安全退出。"""

    def __init__(
        self,
        *,
        on_toggle: Callable[[], None],
        on_pause: Callable[[], None],
        on_quit: Callable[[], None],
        is_enabled: Callable[[], bool] = lambda: False,
        is_paused: Callable[[], bool] = lambda: False,
    ) -> None:
        self.on_toggle = on_toggle
        self.on_pause = on_pause
        self.on_quit = on_quit
        self.is_enabled = is_enabled
        self.is_paused = is_paused
        self._icon = None
        self._thread = None
        self.error = ""

    @property
    def running(self) -> bool:
        return self._icon is not None

    def start(self) -> tuple[bool, str]:
        if self._icon is not None:
            return True, ""
        ok, reason = available()
        if not ok:
            self.error = reason
            return False, reason
        try:
            import pystray

            menu = pystray.Menu(
                pystray.MenuItem(self._toggle_label, self._toggle),
                pystray.MenuItem(self._pause_label, self._pause),
                pystray.MenuItem("退出托盘", self._quit),
            )
            icon = pystray.Icon("trade-copilot", _icon_image(), "聊天副驾", menu)
            thread = threading.Thread(target=icon.run, daemon=True)
            thread.start()
        except Exception as exc:
            self.error = f"托盘启动失败：{exc}"
            _log.warning(self.error)
            return False, self.error
        self._icon = icon
        self._thread = thread
        return True, ""

    def stop(self) -> None:
        icon, self._icon = self._icon, None
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass

    def _toggle_label(self, _item=None) -> str:
        return "关闭副驾" if self.is_enabled() else "开启副驾"

    def _pause_label(self, _item=None) -> str:
        return "恢复" if self.is_paused() else "暂停"

    def _toggle(self, _icon=None, _item=None) -> None:
        self._safe(self.on_toggle)

    def _pause(self, _icon=None, _item=None) -> None:
        self._safe(self.on_pause)

    def _quit(self, _icon=None, _item=None) -> None:
        self._safe(self.on_quit)
        self.stop()

    @staticmethod
    def _safe(fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception:
            _log.exception("托盘菜单回调失败")
