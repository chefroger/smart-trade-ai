"""
测试全局配置 — 必须在任何 trade 模块 import 之前执行。

设置 TRADE_HOME 环境变量，防止 _setup_work_directory 和 _get_trade_home 触碰真实桌面。
"""
import os
import tempfile

import pytest

# 在第 0 步：在所有 import 之前设置 TRADE_HOME
# 这样 trade.company 模块级别的 TRADE_HOME 常量就会指向临时路径
if "TRADE_HOME" not in os.environ:
    os.environ["TRADE_HOME"] = tempfile.mkdtemp(prefix="trade-test-")

# 同样必须在 import 之前设置 HERMES_HOME：cron / license / skill_router / memory
# 都在 import 期按它解析目录，且 treat 会**写入** ~/.hermes（skills、memories/MEMORY.md）。
# 不隔离的后果真实发生过：测试里的 install_skills() 覆盖了真实的 ~/.hermes/skills。
if "HERMES_HOME" not in os.environ:
    os.environ["HERMES_HOME"] = tempfile.mkdtemp(prefix="trade-test-hermes-")


@pytest.fixture(autouse=True)
def _isolate_process_globals():
    """快照/清空测试会改动的进程级全局状态。

    涉及两类：
    1. trade.api.deps 的 session token 与公司绑定 —— 测试里 set_session_token() 后
       不会自动复位，后续用例会跑在「锁已被打开」的污染状态里（快照后恢复）。
    2. trade.api.chat 的限流计数器与 skill 缓存 —— 每个测试都用全新的临时库，
       公司 id 都从 1 开始，于是不同测试文件的请求会累加到同一把限流计数器上，
       达到 20 次/分钟即抛 429（清空，让每个用例从干净的窗口开始）。

    注意：这里用 sys.modules 查询而**不是** import —— 在 fixture 里 import
    trade.api.deps 会让它被提前加载、改变其它测试的模块导入顺序
    （曾因此打乱一组依赖真实 DB 的用例）。
    """
    import sys as _sys

    deps = _sys.modules.get("trade.api.deps")
    chat = _sys.modules.get("trade.api.chat")
    # 未加载的模块不碰：保持「fixture 不引入额外 import」这条原则
    _deps_state = (
        (deps._SESSION_TOKEN, dict(deps._ACTIVE_COMPANY)) if deps is not None else None
    )

    yield

    if _deps_state is not None:
        token, bindings = _deps_state
        deps._SESSION_TOKEN = token
        deps._ACTIVE_COMPANY.clear()
        deps._ACTIVE_COMPANY.update(bindings)
    if chat is not None:
        chat._chat_timestamps.clear()
        chat._last_skill_per_company.clear()
