"""按请求拦截"已由缓存覆盖"的文件读取（pre_tool_call 钩子）。

为什么需要硬拦截：只靠提示词告诉 agent"别重读"不可靠；带 read_file 工具时
它仍可能读，缓存就白省了。这里按 `task_id` 维护本次可跳过路径集合，
命中即返回 block 指令（Hermes 的 pre_tool_call 支持，YOLO 模式也不会跳过）。

**不按工具名白名单**：Hermes 的工具表是动态的（MCP/插件/委托），枚举不完。
改为扫描本次调用的所有字符串参数：只要出现本次跳过的文件路径就拦截，
因此 `terminal` 的 `cat`、`execute_code` 的 `open()`、`search_files` 的
`path`、`delegate_task` 的嵌套任务参数都能覆盖。

已知残余（本模块不解决）：相对路径/变量/脚本间接引用、目录级搜索、
子 agent 自己发现路径后用自己的 task_id 读取。只拦字面路径，任何异常放行。

只在 Trade 进程内生效（TRADE_HOST=1）；用户单独跑 hermes 时注册表为空，
钩子直接放行，不改变其行为。
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path

_MESSAGE = "该文件本次已由缓存提取覆盖（仅用于概览/定位），请勿重复读取。"

# Windows 风格绝对路径（C:\... 或 C:/...）：在 POSIX 宿主上 Path 会当成相对路径，
# 但它对 agent 来说仍然是绝对路径，必须当作绝对路径处理。
_WIN_ABS_RE = re.compile(r"^[A-Za-z]:[\\/]")

# 只返回目录项/元数据、不返回文件内容的工具：路径命中也不拦（避免误伤）。
_NON_CONTENT_TOOLS = frozenset({"list_dir"})

_lock = threading.Lock()
_skips: dict[str, frozenset[str]] = {}


def _resolve(path: str) -> str:
    try:
        return str(Path(path).resolve())
    except (OSError, TypeError, ValueError):
        return ""


def _norm(text) -> str:
    """把路径字面量归一到可比较的形式（needle 与 haystack 必须同样处理）。

    同一个文件在不同写法下不是同一串字符：
    - Windows 下 repr() 会把反斜杠写成两个（'C:\\\\Users\\\\x'）
    - 命令里可能混用正斜杠
    - Windows 文件名大小写不敏感
    所以比较前先把分隔符统一、重复分隔符折叠，Windows 下再统一小写。
    """
    out = str(text).replace("\\", "/")
    while "//" in out:
        out = out.replace("//", "/")
    if os.name == "nt":
        out = out.lower()
    return out


def _is_absolute(path: Path, text: str) -> bool:
    """绝对路径判定。

    反斜杠写法（Windows 风格）在 POSIX 宿主上 `is_absolute()` 为假，
    但归一后仍是绝对路径，必须按绝对路径处理。
    """
    try:
        if path.is_absolute():
            return True
    except OSError:
        pass
    return _norm(text).startswith("/")


def _variants(raw) -> set[str]:
    """同一路径的几种字面写法（resolved / 原绝对路径 / macOS /private 形式）。"""
    text = str(raw)
    if os.name != "nt" and _WIN_ABS_RE.match(text):
        # Windows 风格绝对路径：在 POSIX 宿主上 resolve 只会拼上 cwd，没有意义，
        # 只保留原字面量（归一后即 c:/... 形式）。
        return {_norm(text)}
    try:
        path = Path(text).expanduser()
        resolved = str(path.resolve())
    except (OSError, TypeError, ValueError):
        return set()
    values = {resolved}
    if _is_absolute(path, text):
        values.add(str(path))
    # macOS 下 /var/... 与 /private/var/... 指向同一文件；命令里可能写任一种。
    if resolved.startswith("/private/"):
        values.add(resolved[len("/private"):])
    return {_norm(v) for v in values}


def register(task_id: str, paths) -> None:
    """登记本次请求可跳过的文件（绝对路径集合）。"""
    key = str(task_id or "").strip()
    if not key:
        return
    values: set[str] = set()
    for raw in paths or ():
        values.update(_variants(raw))
    with _lock:
        _skips[key] = frozenset(values)


def release(task_id: str) -> None:
    """请求结束必须释放，避免长驻进程内累积。"""
    with _lock:
        _skips.pop(str(task_id or "").strip(), None)


def is_skipped(task_id: str, path: str) -> bool:
    key = str(task_id or "").strip()
    if not key:
        return False
    target = _norm(_resolve(path))
    if not target:
        return False
    with _lock:
        return target in _skips.get(key, frozenset())


def _iter_strings(value):
    """递归取出参数里的所有字符串（dict/list/tuple/set 嵌套）。"""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _iter_strings(item)


def _mentions_skipped(args, needles: frozenset[str]) -> bool:
    if not needles:
        return False
    for text in _iter_strings(args):
        norm_text = _norm(text)
        for needle in needles:
            norm_needle = _norm(needle)
            if norm_needle and norm_needle in norm_text:
                return True
    return False


def on_pre_tool_call(tool_name: str = "", args=None, task_id: str = "", **_kw) -> dict | None:
    """Hermes pre_tool_call 入口；任何异常都放行（不能把聊天锁死）。"""
    try:
        # 只在 Trade 进程内生效；用户单独跑 hermes 时不受影响。
        if os.environ.get("TRADE_HOST", "").strip() != "1":
            return None
        if args is None or tool_name in _NON_CONTENT_TOOLS:
            return None
        key = str(task_id or "").strip()
        if not key:
            return None
        with _lock:
            needles = _skips.get(key, frozenset())
        if _mentions_skipped(args, needles):
            return {"action": "block", "message": _MESSAGE}
        return None
    except Exception:
        return None
