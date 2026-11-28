"""
Trade AI Assistant — 长任务软 token 预算钩子（M7，Hermes pre_tool_call）。

设计原则（桌面端「随时可用」优先）：
  - 默认策略 `auto`（历史中位数的 2 倍；历史不足 3 次时不设上限）；`0` 表示关闭。
  - 无确认弹窗、不拦截聊天本身、绝不在未交付任何结果时终止任务。
  - 达到软预算后，仅对新增检索类工具返回 block 提示，引导模型基于已有材料提前收尾，
    并在报告开头写明「因达到本次预算提前收尾，未完成：...」，用户可随时点「继续补查」。
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field

# 触发软预算后不再新发起的检索类工具（写作/落库/格式化等收尾工具不受限制）
RETRIEVAL_TOOLS: frozenset[str] = frozenset({
    "web_search",
    "web_extract",
    "web_crawl",
    "browser_navigate",
    "osint_job_start",
    "supplier_quote_search",
    "search_files",
})

_lock = threading.Lock()


@dataclass
class _BudgetState:
    """单个任务的软预算实时状态。"""

    limit_tokens: int
    skill: str = ""
    consumed_tokens: int = 0
    tripped: bool = False
    unfinished_tools: list[str] = field(default_factory=list)


_budgets: dict[str, _BudgetState] = {}


def register(task_id: str, limit_tokens: int | None, *, skill: str = "") -> None:
    """为指定 task_id 登记本次软 token 预算；limit_tokens 为 None 或 <=0 时不设上限。"""
    key = str(task_id or "").strip()
    if not key or limit_tokens is None or int(limit_tokens) <= 0:
        return
    with _lock:
        _budgets[key] = _BudgetState(limit_tokens=int(limit_tokens), skill=str(skill or ""))


def add_tokens(task_id: str, tokens: int) -> bool:
    """累加本次任务已消耗 token 数；返回当前是否已达到或超过软预算。"""
    key = str(task_id or "").strip()
    if not key:
        return False
    with _lock:
        st = _budgets.get(key)
        if st is None:
            return False
        st.consumed_tokens += max(0, int(tokens or 0))
        if st.consumed_tokens >= st.limit_tokens:
            st.tripped = True
        return st.tripped


def get_state(task_id: str) -> dict | None:
    """返回指定 task_id 的软预算状态快照（供测试与收尾文案使用）。"""
    key = str(task_id or "").strip()
    if not key:
        return None
    with _lock:
        st = _budgets.get(key)
        if st is None:
            return None
        return {
            "limit_tokens": st.limit_tokens,
            "skill": st.skill,
            "consumed_tokens": st.consumed_tokens,
            "tripped": st.tripped,
            "unfinished_tools": list(st.unfinished_tools),
        }


def format_wrapup_notice(task_id: str) -> str:
    """生成提前收尾说明（未触发软预算时返回空串）。"""
    snap = get_state(task_id)
    if not snap or not snap["tripped"]:
        return ""
    unfinished = "、".join(snap["unfinished_tools"]) if snap["unfinished_tools"] else "后续扩展检索"
    return f"因达到本次预算提前收尾，未完成：{unfinished}。如需更深入核查，可点击「继续补查」。"


def release(task_id: str) -> None:
    """任务结束时释放内存状态，避免长驻进程累积。"""
    with _lock:
        _budgets.pop(str(task_id or "").strip(), None)


def on_pre_tool_call(tool_name: str = "", args=None, task_id: str = "", **_kw) -> dict | None:
    """Hermes pre_tool_call 钩子：超软预算时拦截新的检索类工具调用，引导优雅收尾。"""
    try:
        # 只在 Trade 进程内生效；用户单独跑 Hermes 时零影响
        if os.environ.get("TRADE_HOST", "").strip() != "1":
            return None
        key = str(task_id or "").strip()
        if not key or tool_name not in RETRIEVAL_TOOLS:
            return None
        with _lock:
            st = _budgets.get(key)
            if st is None or st.consumed_tokens < st.limit_tokens:
                return None
            st.tripped = True
            if tool_name not in st.unfinished_tools:
                st.unfinished_tools.append(tool_name)
            unfinished = "、".join(st.unfinished_tools)
        return {
            "action": "block",
            "message": (
                f"本次任务已达软预算上限（{st.limit_tokens} token），请停止新增检索并基于已有材料收尾。"
                f"请在报告开头写明「因达到本次预算提前收尾，未完成：{unfinished}」，并交付完整的部分结果。"
            ),
        }
    except Exception:  # noqa: BLE001 —— 任何异常放行，绝不拖垮任务
        return None
