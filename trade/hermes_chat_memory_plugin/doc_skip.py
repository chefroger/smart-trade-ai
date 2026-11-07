"""按请求拦截"已由缓存覆盖"的文件读取（pre_tool_call 钩子）。

为什么需要硬拦截：只靠提示词告诉 agent"别重读"不可靠；带 read_file 工具时
它仍可能读，缓存就白省了。这里按 `task_id` 维护本次可跳过路径集合，
命中即返回 block 指令（Hermes 的 pre_tool_call 支持，YOLO 模式也不会跳过）。

只在 Trade 进程内生效（TRADE_HOST=1）；用户单独跑 hermes 时注册表为空，
钩子直接放行，不改变其行为。
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

_READ_TOOLS = frozenset({"read_file"})
_MESSAGE = "该文件本次已由缓存提取覆盖（仅用于概览/定位），请勿重复读取。"

_lock = threading.Lock()
_skips: dict[str, frozenset[str]] = {}


def _resolve(path: str) -> str:
    try:
        return str(Path(path).resolve())
    except (OSError, TypeError, ValueError):
        return ""


def register(task_id: str, paths) -> None:
    """登记本次请求可跳过的文件（绝对路径集合）。"""
    key = str(task_id or "").strip()
    if not key:
        return
    resolved = frozenset(filter(None, (_resolve(str(p)) for p in paths or ())))
    with _lock:
        _skips[key] = resolved


def release(task_id: str) -> None:
    """请求结束必须释放，避免长驻进程内累积。"""
    with _lock:
        _skips.pop(str(task_id or "").strip(), None)


def is_skipped(task_id: str, path: str) -> bool:
    key = str(task_id or "").strip()
    if not key:
        return False
    target = _resolve(path)
    if not target:
        return False
    with _lock:
        return target in _skips.get(key, frozenset())


def on_pre_tool_call(tool_name: str = "", args=None, task_id: str = "", **_kw) -> dict | None:
    """Hermes pre_tool_call 入口；任何异常都放行（不能把聊天锁死）。"""
    try:
        if os.environ.get("TRADE_HOST", "").strip() != "1":
            return None
        if tool_name not in _READ_TOOLS or not isinstance(args, dict):
            return None
        path = args.get("path")
        if not path or not is_skipped(task_id, str(path)):
            return None
        return {"action": "block", "message": _MESSAGE}
    except Exception:
        return None
