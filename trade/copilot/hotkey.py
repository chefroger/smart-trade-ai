"""聊天副驾全局热键（惰性加载，可降级）。

- 默认组合：macOS `cmd+shift+space`，Windows/Linux `ctrl+shift+space`。
- 依赖 `pynput`；**缺失/注册失败只返回原因**，调用方降级为"点悬浮按钮触发"，
  绝不让副驾或 Trade 主功能崩溃。
- 只有用户显式开启副驾后，service 才会调用 `start()`。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

from trade.copilot.settings import default_hotkey

_log = logging.getLogger(__name__)

_MODIFIERS = {
    "ctrl": "<ctrl>",
    "control": "<ctrl>",
    "shift": "<shift>",
    "alt": "<alt>",
    "option": "<alt>",
    "cmd": "<cmd>",
    "command": "<cmd>",
    "super": "<cmd>",
    "win": "<cmd>",
}
_SPECIAL_KEYS = {
    "space": "<space>",
    "enter": "<enter>",
    "return": "<enter>",
    "tab": "<tab>",
    "esc": "<esc>",
    "escape": "<esc>",
}


def parse_hotkey(spec: str) -> tuple[str, ...] | None:
    """把 `ctrl+shift+space` 解析成规范化的键序列；非法返回 None。"""
    parts = [p for p in re.split(r"[+\s]+", (spec or "").strip().lower()) if p]
    if len(parts) < 2:
        return None
    normalized: list[str] = []
    for part in parts:
        if part in _MODIFIERS:
            token = _MODIFIERS[part]
        elif part in _SPECIAL_KEYS:
            token = _SPECIAL_KEYS[part]
        elif len(part) == 1:
            token = part
        else:
            token = part
        if token not in normalized:
            normalized.append(token)
    # 至少一个修饰键 + 一个主键，且主键在最后
    if not any(t.startswith("<") and t not in _SPECIAL_KEYS.values() for t in normalized[:-1]):
        return None
    return tuple(normalized)


def canonical_hotkey(spec: str) -> str:
    """规范化展示用字符串（非法时原样返回）。"""
    parsed = parse_hotkey(spec)
    if not parsed:
        return spec
    return "+".join(t.strip("<>") for t in parsed)


def to_pynput_hotkey(spec: str) -> str | None:
    parsed = parse_hotkey(spec)
    if not parsed:
        return None
    return "+".join(parsed)


def pynput_available() -> tuple[bool, str]:
    try:
        import pynput  # noqa: F401
    except Exception as exc:
        return False, f"缺少依赖 pynput，全局热键不可用（可用悬浮按钮触发）：{exc}"
    return True, ""


class HotkeyListener:
    """全局热键监听器；`start()` 只在副驾开启后调用。"""

    def __init__(
        self,
        callback: Callable[[], None],
        spec: str | None = None,
    ) -> None:
        self.callback = callback
        self.spec = canonical_hotkey(spec or default_hotkey())
        self._listener = None
        self.error = ""

    @property
    def running(self) -> bool:
        return self._listener is not None

    def start(self) -> tuple[bool, str]:
        if self._listener is not None:
            return True, ""
        available, reason = pynput_available()
        if not available:
            self.error = reason
            return False, reason
        combo = to_pynput_hotkey(self.spec)
        if combo is None:
            self.error = f"热键格式无效：{self.spec}"
            return False, self.error
        try:
            from pynput import keyboard

            listener = keyboard.GlobalHotKeys({combo: self._fire})
            listener.daemon = True
            listener.start()
        except Exception as exc:
            self.error = f"注册全局热键失败（可能被占用）：{exc}"
            _log.warning(self.error)
            return False, self.error
        self._listener = listener
        self.error = ""
        return True, ""

    def stop(self) -> None:
        listener, self._listener = self._listener, None
        if listener is None:
            return
        try:
            listener.stop()
        except Exception as exc:
            _log.debug("停止热键监听失败：%s", exc)

    def _fire(self) -> None:
        """回调异常不能把监听线程带崩。"""
        try:
            self.callback()
        except Exception:
            _log.exception("副驾热键回调失败")
