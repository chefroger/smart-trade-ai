"""
Smart Trade AI — Token / 费用台账（优化路线 P1-6）。

用户用的是按量付费模型（DeepSeek 等），但现在没有任何用量统计。
本模块提供极轻量的本地台账：每次 LLM 调用记一笔，支持按天/按 skill
汇总费用。数据存在 trade.db 的 usage_ledger 表，随库备份走。

费率说明：
- PRICE_PER_1MUSD 是"示例费率"，按 2026 年公开价格填写，调用方可通过
  record_usage(price_override=...) 或环境变量覆盖；
- 环境变量覆盖格式：TRADE_PRICE_<MODEL>="in,out"，如
  TRADE_PRICE_DEEPSEEK_CHAT="0.27,1.10"（单位：美元/1M tokens）；
- 模型名归一化：小写、去空格，便于匹配。

注意：token 数以 SDK 返回的 usage 为准；流式场景下调用方需自行累计。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time

logger = logging.getLogger(__name__)

# 每公司每日 token 额度（输入+输出合计），只用于侧栏提示，不拦截聊天。
# 默认 2000 万：实测一次网站诊断约 340 万，200 万会一句就标红（2026-10-26）。
# 环境变量 TRADE_DAILY_TOKEN_LIMIT 覆盖，设为 0（或负数）表示不限。
DEFAULT_DAILY_TOKEN_LIMIT = 20_000_000

# ── 示例费率（美元 / 1M tokens）：(输入, 输出) ─────────────────────────────
#  ⚠️ 请按实际账单定期校准；未知模型默认按 (0, 0) 计（只记 token 不记费用）。
PRICE_PER_1MUSD: dict[str, tuple[float, float]] = {
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    "deepseek-flash": (0.10, 0.40),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "claude-3-5-haiku": (0.80, 4.00),
}

# 兜底建表。正常路径由 trade/database.py 的 SCHEMA_SQL 建 —— 那份是**权威定义**；
# 这里只为「直接调用本模块、库尚未初始化」的场景兜底，两份必须保持一致。
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS usage_ledger (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                REAL    NOT NULL,
    company_id        INTEGER NOT NULL DEFAULT 0,
    skill             TEXT    NOT NULL DEFAULT '',
    provider          TEXT    NOT NULL DEFAULT '',
    model             TEXT    NOT NULL DEFAULT '',
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd          REAL    NOT NULL DEFAULT 0,
    extra1            TEXT    NOT NULL DEFAULT '',
    extra2            TEXT    NOT NULL DEFAULT '',
    extra3            TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage_ledger(ts);
CREATE INDEX IF NOT EXISTS idx_usage_skill ON usage_ledger(skill);
"""


def _norm_model(model: str) -> str:
    return (model or "").strip().lower().replace(" ", "-").replace("_", "-")


def get_price(model: str) -> tuple[float, float]:
    """返回 (输入价, 输出价) 美元/1M。环境变量优先。"""
    key = _norm_model(model)
    env_key = "TRADE_PRICE_" + key.upper().replace("-", "_")
    env_val = os.environ.get(env_key, "").strip()
    if env_val:
        try:
            inp, outp = env_val.split(",")
            return float(inp), float(outp)
        except ValueError:
            logger.warning("费率环境变量格式错误 %s=%r，应为 in,out", env_key, env_val)
    return PRICE_PER_1MUSD.get(key, (0.0, 0.0))


def ensure_usage_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def record_usage(
    conn: sqlite3.Connection,
    *,
    skill: str = "",
    provider: str = "",
    model: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    company_id: int = 0,
    price_override: tuple[float, float] | None = None,
) -> float:
    """记一笔用量，返回本次费用（美元）。失败永不抛错（只记日志）。"""
    try:
        ensure_usage_schema(conn)
        pin, pout = price_override if price_override else get_price(model)
        cost = (prompt_tokens / 1_000_000) * pin + (completion_tokens / 1_000_000) * pout
        conn.execute(
            """INSERT INTO usage_ledger
               (ts, company_id, skill, provider, model,
                prompt_tokens, completion_tokens, cost_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                time.time(), company_id, skill, provider, _norm_model(model),
                int(prompt_tokens), int(completion_tokens), cost,
            ),
        )
        conn.commit()
        return cost
    except Exception as e:
        logger.warning("用量记录失败: %s", e)
        return 0.0


def _day_start_ts() -> float:
    """本地时区今天 00:00 的时间戳（limits 按用户看到的一天算，不按 UTC）。"""
    from datetime import datetime

    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def daily_token_limit() -> int:
    """当前生效的每日 token 上限；0 = 不限。

    环境变量非法时退回默认值（而不是当成"不限"）—— 配置写错不能把防护关掉。
    """
    raw = os.environ.get("TRADE_DAILY_TOKEN_LIMIT", "").strip()
    if not raw:
        return DEFAULT_DAILY_TOKEN_LIMIT
    try:
        return max(0, int(float(raw)))
    except ValueError:
        logger.warning(
            "TRADE_DAILY_TOKEN_LIMIT=%r 不是数字，改用默认值 %d",
            raw, DEFAULT_DAILY_TOKEN_LIMIT,
        )
        return DEFAULT_DAILY_TOKEN_LIMIT


def tokens_today(conn: sqlite3.Connection, company_id: int) -> int:
    """某公司今天已用的 token 总数（输入+输出）。"""
    ensure_usage_schema(conn)
    row = conn.execute(
        """SELECT COALESCE(SUM(prompt_tokens + completion_tokens), 0)
           FROM usage_ledger WHERE company_id = ? AND ts >= ?""",
        (int(company_id), _day_start_ts()),
    ).fetchone()
    return int(row[0] or 0)


def daily_budget_state(company_id: int) -> tuple[int, int]:
    """返回 (今日已用, 上限)；上限 0 表示不限。

    额度只用于界面提示，不再拦截聊天（2026-10-26 用户决定）；读库失败返回
    (0, 上限) —— 展示 0 好过把整个请求打挂。
    """
    limit = daily_token_limit()
    try:
        from trade.database import get_connection

        conn = get_connection()
        try:
            return tokens_today(conn, company_id), limit
        finally:
            conn.close()
    except Exception as e:
        logger.warning("读取今日用量失败（界面显示 0）: %s", e)
        return 0, limit


def record_agent_usage(agent, *, company_id: int = 0, skill: str = "") -> float:
    """把一次 agent 调用的 token 用量记入台账，返回费用（美元）。

    Hermes 的 ``session_*`` 计数是该 agent 实例的累计值；Trade 每个请求新建
    agent，所以它天然等于本次请求的用量（重试各自新建 agent，各记一笔）。
    字段缺失（旧版 Hermes / 测试桩）时记 0 —— 记账是旁路，绝不能影响聊天。
    """
    prompt = int(getattr(agent, "session_prompt_tokens", 0) or 0)
    completion = int(getattr(agent, "session_completion_tokens", 0) or 0)
    # 部分 provider 只填 input/output 两列
    if not prompt:
        prompt = int(getattr(agent, "session_input_tokens", 0) or 0)
    if not completion:
        completion = int(getattr(agent, "session_output_tokens", 0) or 0)
    if prompt <= 0 and completion <= 0:
        return 0.0
    try:
        from trade.database import get_connection

        conn = get_connection()
        try:
            return record_usage(
                conn,
                skill=skill,
                provider=str(getattr(agent, "provider", "") or ""),
                model=str(getattr(agent, "model", "") or ""),
                prompt_tokens=prompt,
                completion_tokens=completion,
                company_id=company_id,
            )
        finally:
            conn.close()
    except Exception as e:
        logger.warning("用量记录失败（不影响聊天）: %s", e)
        return 0.0


def summary(conn: sqlite3.Connection, days: int = 7) -> dict:
    """近 N 天汇总：总 token、总费用、按 skill / 按模型 / 按天拆分。"""
    ensure_usage_schema(conn)
    since = time.time() - days * 86400
    total = conn.execute(
        """SELECT COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0),
                  COALESCE(SUM(cost_usd),0), COUNT(*)
           FROM usage_ledger WHERE ts >= ?""",
        (since,),
    ).fetchone()
    by_skill = conn.execute(
        """SELECT skill, SUM(prompt_tokens)+SUM(completion_tokens), SUM(cost_usd), COUNT(*)
           FROM usage_ledger WHERE ts >= ? GROUP BY skill ORDER BY 3 DESC""",
        (since,),
    ).fetchall()
    by_model = conn.execute(
        """SELECT model, SUM(prompt_tokens)+SUM(completion_tokens), SUM(cost_usd), COUNT(*)
           FROM usage_ledger WHERE ts >= ? GROUP BY model ORDER BY 3 DESC""",
        (since,),
    ).fetchall()
    by_day = conn.execute(
        """SELECT date(ts, 'unixepoch', 'localtime'),
                  SUM(prompt_tokens)+SUM(completion_tokens), SUM(cost_usd), COUNT(*)
           FROM usage_ledger WHERE ts >= ?
           GROUP BY date(ts, 'unixepoch', 'localtime') ORDER BY 1""",
        (since,),
    ).fetchall()
    return {
        "days": days,
        "total_tokens": int(total[0] + total[1]),
        "total_cost_usd": round(float(total[2]), 4),
        "calls": int(total[3]),
        "by_skill": [
            {"skill": r[0] or "(未分类)", "tokens": int(r[1]), "cost_usd": round(float(r[2]), 4), "calls": int(r[3])}
            for r in by_skill
        ],
        "by_model": [
            {"model": r[0] or "(未知)", "tokens": int(r[1]), "cost_usd": round(float(r[2]), 4), "calls": int(r[3])}
            for r in by_model
        ],
        "by_day": [
            {"day": r[0], "tokens": int(r[1]), "cost_usd": round(float(r[2]), 4), "calls": int(r[3])}
            for r in by_day
        ],
    }


def format_summary_text(s: dict) -> str:
    """给前端/CLI 用的纯文本摘要。"""
    lines = [
        f"近 {s['days']} 天：{s['calls']} 次调用，{s['total_tokens']} tokens，"
        f"约 ${s['total_cost_usd']:.4f}"
    ]
    if s["by_skill"]:
        lines.append("按 skill（费用倒序）：")
        for r in s["by_skill"][:10]:
            lines.append(f"  - {r['skill']}: {r['calls']} 次 / ${r['cost_usd']:.4f}")
    return "\n".join(lines)
