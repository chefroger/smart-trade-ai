"""当前请求的公司上下文（thread-local）。

## 为什么需要它

Trade 是**多公司**应用：同一个 SQLite、同一个 Hermes、同一个 agent，但每个公司
的数据必须严格隔离（客户、订单、文档、对话、长期记忆）。

聊天记忆（conversations 表）有 `company_id` 列，查询天然按公司过滤。但**长期记忆**
走的是 Hermes 的 MEMORY.md —— 那是一个**纯文本文件**，没有 company_id 列，
Hermes 把它**原样注入** system prompt（`agent/system_prompt.py:516` →
`memory_tool_store.py:618`），**零过滤**。

于是唯一的隔离手段是"条目里带 `[公司: XXX]` 标签，然后让模型自己看标签"——
这是**软防护**：模型漏写一次标签，那条事实就会在别家公司的对话里浮现。

## 这个模块解决什么

让"当前是哪个公司"成为**代码事实**，而不是模型需要正确传递的参数：

- Trade 在处理请求的线程里设置本模块的 thread-local（`set_current_company`）
- 需要写长期记忆时，插件工具从这里取 company_id —— **模型不参与、不可能传错**
- 标签由代码写进条目文本，模型只提供事实内容

## 为什么用 thread-local 而不是别的

- 插件 handler 由 Hermes 在 **agent 调用栈内**执行，而 agent 由 Trade 在
  `loop.run_in_executor(None, _call_agent)` 里跑（`trade/api/chat.py:233`）——
  同一个线程，所以 thread-local 读得到。
- 不用全局变量：多公司并发请求会互相覆盖（那正是要防的串户）。
- 不用"模型传参"：模型可能传错、漏传、或被诱导传成别的公司 —— 最毒的一类 bug
  （现有的 `chat_memory_list` 就是这个模式，schema 里特意写了「传错会读到其他
  公司数据（严重 bug）」）。
"""

from __future__ import annotations

import threading

_state = threading.local()


def set_current_company(company_id: int | None) -> None:
    """设置当前线程的公司 ID（None 表示清空）。

    在处理请求的入口调用；线程复用时**必须**每次都设（哪怕是 None），
    否则会读到上一个请求残留的公司。
    """
    _state.company_id = company_id


def get_current_company() -> int | None:
    """取当前线程的公司 ID；没有设置过则返回 None。"""
    return getattr(_state, "company_id", None)


def current_company_or_none() -> int | None:
    """别名，强调"可能没有"（读事实的调用方要处理 None）。"""
    return get_current_company()
