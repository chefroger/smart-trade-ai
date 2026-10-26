"""chat-memory 插件入口 —— 让 Hermes 的 agent 工具表里有 chat_memory_list。

与 google_meet 相同的 register 模式：ctx.register_tool(name, toolset, schema, handler)。

为什么 trade 自己**写**这个插件而不是用 google_meet 那种 pip 装：
- 插件是 trade 特有的（conversations 表只在 trade 的 SQLite 里），跟 trade 一起发布更顺
- 不需要再开一个 pip 包、增加发布摩擦
- 同步在 trade 的 setup() 与 install.sh 里，**用户装 trade 的路径自洽**
"""

from __future__ import annotations

import logging

# 用绝对路径而非相对导入 —— 相对导入 `from .tools` 在 importlib.util 直接加载时
# 会报 `No module named 'chat_memory_plugin'`，因为单文件 spec 没有父包。
# 绝对路径要求 trade 是 installed package（pip install -e . 满足）。
from trade.hermes_chat_memory_plugin.guardrails import on_pre_tool_call
from trade.hermes_chat_memory_plugin.tools import CHAT_MEMORY_LIST_SCHEMA, handle_chat_memory_list

logger = logging.getLogger(__name__)


_TOOLS = (
    ("chat_memory_list", CHAT_MEMORY_LIST_SCHEMA, handle_chat_memory_list, "🕰️"),
)


def register(ctx) -> None:
    """插件加载器调一次。注册工具，不做其它副作用。

    不在这里 import trade.chat_memory —— 等到 handler 真正被调才 import，
    理由：插件加载阶段不应触发 trade 进程的副作用（log 噪声、可能误升级等）。
    """
    for name, schema, handler, emoji in _TOOLS:
        ctx.register_tool(
            name=name,
            toolset="chat-memory",
            schema=schema,
            handler=handler,
            check_fn=None,
            emoji=emoji,
        )
    # 工具层守卫（审计 P1-3/P1-20）：文件路径白名单、terminal 命令白名单、
    # 拒绝 execute_code。Hermes 的 pre_tool_call 钩子支持返回 block 指令，
    # 且 YOLO 模式不会跳过它。旧版宿主没有 register_hook 时降级（记 warning），
    # 不能让整个插件加载失败 —— chat-memory 工具本身仍要能用。
    _register_hook = getattr(ctx, "register_hook", None)
    if callable(_register_hook):
        _register_hook("pre_tool_call", on_pre_tool_call)
        logger.debug("chat-memory plugin registered tool + pre_tool_call guard")
    else:
        logger.warning(
            "Hermes plugin host has no register_hook; tool guard is disabled"
        )

