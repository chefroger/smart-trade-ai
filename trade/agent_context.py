"""Agent 会话上下文：把"当前公司"绑定到这一次 agent 调用。

为什么需要：Hermes 的 chat-memory 插件工具原先让**模型自己填 company_id**，
只要在会话里注入一句"把 company_id 传成 2"，就能读到别家公司的对话历史
（2026-10-23 审计 P0-2）。工具参数是不可信输入，公司身份必须由服务端绑定。

实现：`contextvars.ContextVar`。Hermes 的工具执行器在提交任务时会调用
`propagate_context_to_thread`（`agent/tool_executor.py`），ContextVar 会一起
复制到工具线程，所以插件 handler 能读到与本次 `agent.chat()` 对应的值。
没有绑定（例如 Hermes Gateway 独立执行 cron）时返回 None —— 工具按 fail-closed
拒绝，而不是退回模型给的参数。
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_current_company_id: ContextVar[int | None] = ContextVar(
    "trade_agent_company_id", default=None
)
_current_customer_id: ContextVar[int | None] = ContextVar(
    "trade_agent_customer_id", default=None
)
# 用户本轮亲手贴出的完整文件路径（只读、仅本轮）。守卫据此放行精确文件。
_current_user_paths: ContextVar[tuple[str, ...]] = ContextVar(
    "trade_agent_user_paths", default=()
)

# 引号包裹的路径（支持空格）；未加引号的 POSIX/~/Windows 盘符/UNC 路径。
_QUOTED_PATH_RE = re.compile(r'["\'`]([^"\'`\n]{2,4096})["\'`]')
_UNQUOTED_PATH_RE = re.compile(
    r'(?<![\w:/])((?:~|/)[^\s"\'`<>|]+|[A-Za-z]:\\[^\s"\'`<>|]+|\\\\[^\s"\'`<>|]+)'
)
_TRAILING_PUNCT = ".,;:!?)]}>，。；：！？）】》"


def current_company_id() -> int | None:
    """当前 agent 调用绑定的公司 id（未绑定 → None）。"""
    return _current_company_id.get()


def current_customer_id() -> int | None:
    """当前 agent 调用绑定的客户 id（未选客户 → None）。"""
    return _current_customer_id.get()


def current_user_paths() -> tuple[str, ...]:
    """本轮机主贴出、且已解析为绝对路径的文件清单（无则为空元组）。"""
    return _current_user_paths.get()


def extract_user_paths(text: str, *, limit: int = 10) -> list[str]:
    """从用户消息里提取**存在的文件**的绝对路径（去重、限量）。

    只认用户亲手写出来、能解析成文件（非目录/通配符）的路径；这是本轮一次性
    只读授权的来源。模型自己在工具参数里编的路径不经过这里。
    """
    if not isinstance(text, str) or not text:
        return []
    raw_candidates = [m.group(1) for m in _QUOTED_PATH_RE.finditer(text)]
    raw_candidates += [m.group(1) for m in _UNQUOTED_PATH_RE.finditer(text)]

    out: list[str] = []
    for raw in raw_candidates:
        candidate = raw.strip().rstrip(_TRAILING_PUNCT)
        if not candidate or "://" in candidate:
            continue
        try:
            path = Path(os.path.expanduser(candidate))
            if not path.is_absolute():
                continue
            resolved = path.resolve()
            if not resolved.is_file():
                continue
        except (OSError, ValueError):
            continue
        value = str(resolved)
        if value not in out:
            out.append(value)
        if len(out) >= limit:
            break
    return out


@contextmanager
def bind_company(
    company_id: int | None,
    customer_id: int | None = None,
    user_paths: tuple[str, ...] | list[str] = (),
):
    """把公司/客户/本轮用户路径绑定到当前上下文，退出时恢复。"""
    company_token = _current_company_id.set(company_id)
    customer_token = _current_customer_id.set(customer_id)
    paths_token = _current_user_paths.set(tuple(user_paths or ()))
    try:
        yield
    finally:
        _current_user_paths.reset(paths_token)
        _current_customer_id.reset(customer_token)
        _current_company_id.reset(company_token)
