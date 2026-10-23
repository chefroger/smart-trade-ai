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

from contextlib import contextmanager
from contextvars import ContextVar

_current_company_id: ContextVar[int | None] = ContextVar(
    "trade_agent_company_id", default=None
)


def current_company_id() -> int | None:
    """当前 agent 调用绑定的公司 id（未绑定 → None）。"""
    return _current_company_id.get()


@contextmanager
def bind_company(company_id: int | None):
    """把 company_id 绑定到当前上下文，退出时恢复（线程池复用不会串值）。"""
    token = _current_company_id.set(company_id)
    try:
        yield
    finally:
        _current_company_id.reset(token)
