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
