"""chat-memory 插件的工具实现。

为何需要把 search_history 薄封装一次，而不是让 LLM 直接调 trade.chat_memory：
- 该模块期望在**trade 进程内**被 import（从 trade.chat_memory 路径）—— 在 Hermes 进程里
  import 是 Hermes 自己的 trade 安装副本（如果有），未必一致。
- 通过插件 __init__.py 把 trade 注入到 Hermes 进程的 sys.path 后再 import；这里是**接缝**。
"""

from __future__ import annotations

import traceback
from typing import Any


def _str(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


def _schema(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    """与 google_meet 同型的 schema 构造（plugins/AGENTS.md 约定的格式）。"""
    params: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        params["required"] = required
    return {"name": name, "description": description, "parameters": params}


# 枚举值与 trade.chat_memory.search_history 的 _BOUNDARY_COMPUTERS 一一对应。
# 增删时**两边同步**（测试钉住）。
_TIME_RANGES_DESCRIPTION = """\
时间范围枚举：
- today / this_week / this_month / this_year 含"现在"（含端点 start，不含结束）；
- yesterday / last_week / last_month / last_year 不含"现在"（前一周期完整窗口）；
- all 不限。
未知值服务端按 all 兜底（fail-safe —— 与 search_history 的旧行为一致）。
"""

_RECENT_DAYS_DESCRIPTION = (
    "可选。过去 N 天（含今天）的窗口，start = (now - (N-1) 天) 的 00:00。N=1 等价于 'yesterday'。"
    "用于表达枚举表里没有的相对区间（如 '上上周三' = 14）。"
    "**与 time_range 互斥**：若都给了本参数优先；建议在 augment_prompt 里告诉 LLM 不要同时给。"
)

_RECENT_MONTHS_DESCRIPTION = (
    "可选。过去 N 个月（含本月）。逐月回退，遇 1 月走 12/去年。用于 '前几个月' 这类模糊词。"
    "**与 time_range 互斥**。"
)


CHAT_MEMORY_LIST_SCHEMA = _schema(
    "chat_memory_list",
    "查 trade 用户的对话历史（SQLite，按 company_id 严格隔离）。"
    "**company_id 必填**——必须传用户在 system prompt 的 Trade Context 段里写明的那个数字，"
    "**不能**从用户消息推断，传错会读到其他公司的数据。"
    "时间范围默认 'all'；给具体枚举值能精确窗口；recent_days/recent_months 用来表达枚举外的相对区间。",
    {
        "company_id": {
            "type": "integer",
            "description": (
                "当前会话的公司 ID。从 system prompt 的 'Trade Context' 段读取；"
                "**不要**让用户输入这个值。传错会读到其他公司数据（严重 bug）。"
            ),
        },
        "time_range": {
            "type": "string",
            "enum": [
                "today", "yesterday",
                "this_week", "last_week",
                "this_month", "last_month",
                "this_year", "last_year",
                "all",
            ],
            "description": _TIME_RANGES_DESCRIPTION,
        },
        "recent_days": {
            "type": "integer",
            "minimum": 1,
            "description": _RECENT_DAYS_DESCRIPTION,
        },
        "recent_months": {
            "type": "integer",
            "minimum": 1,
            "description": _RECENT_MONTHS_DESCRIPTION,
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100,
            "default": 20,
            "description": "最大返回条数。默认 20。",
        },
    },
    required=["company_id"],
)


def handle_chat_memory_list(args: dict[str, Any], **_kw) -> str:
    """插件 handler 签名：handle(args, **_kw)。

    **_kw 来自 dispatcher 注入**（task_id/session_id 等），signatures 已被 Hermes
    用 inspect 过滤（plugins/AGENTS.md），所以"宽收"是安全的。
    """
    # company_id 缺失/类型错 → 绝不能静默用别的值（会读到错误公司数据，**最毒**）
    company_id = args.get("company_id")
    if not isinstance(company_id, int) or company_id <= 0:
        return _err(
            "company_id is required and must be a positive integer — "
            "read it from the system prompt's 'Trade Context' section, "
            "do not invent a value or read it from the user's message."
        )

    time_range = args.get("time_range") or "all"
    if not isinstance(time_range, str):
        return _err(f"time_range must be a string (got {type(time_range).__name__})")
    recent_days = args.get("recent_days")
    recent_months = args.get("recent_months")
    if recent_days is not None and not isinstance(recent_days, int):
        return _err(f"recent_days must be an integer or omitted (got {type(recent_days).__name__})")
    if recent_months is not None and not isinstance(recent_months, int):
        return _err(f"recent_months must be an integer or omitted (got {type(recent_months).__name__})")
    if recent_days is not None and recent_days <= 0:
        return _err("recent_days must be positive")
    if recent_months is not None and recent_months <= 0:
        return _err("recent_months must be positive")
    # recent_days 与 recent_months 互斥（schema 允许但只能用一个）
    if recent_days is not None and recent_months is not None:
        return _err("recent_days and recent_months are mutually exclusive — pass only one")

    try:
        limit = int(args.get("limit") or 20)
    except (TypeError, ValueError):
        return _err("limit must be an integer")
    if limit < 1 or limit > 100:
        return _err("limit must be between 1 and 100")

    try:
        from trade.chat_memory import search_history
    except ImportError as exc:
        return _err(
            f"trade package not importable from Hermes process: {exc}. "
            "This usually means the chat-memory plugin was loaded outside a Trade context — "
            "check that trade-bootstrap adds Trade to sys.path before Hermes loads plugins."
        )

    try:
        rows = search_history(
            company_id=company_id,
            time_range=time_range,
            limit=limit,
            recent_days=recent_days,
            recent_months=recent_months,
        )
    except Exception:
        # 异常不外抛（plugins/AGENTS.md: handler 失败返回 tool_error）—— 给 LLM 可读的错误
        # 而不是 Python traceback（traceback 里有 trade 内部路径，泄漏内部）
        return _err(f"search_history failed: {traceback.format_exc(limit=2)}")

    return _json({
        "company_id": company_id,
        "time_range": time_range,
        "recent_days": recent_days,
        "recent_months": recent_months,
        "count": len(rows),
        "rows": rows,
    })


def _json(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, default=str)


def _err(msg: str) -> str:
    return _json({"error": msg})
