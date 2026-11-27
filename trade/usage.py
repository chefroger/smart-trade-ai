"""
Smart Trade AI — Token / 费用台账（优化路线 P1-6 + 工单 #3/#8 缓存三档与高峰闲时计价）。

用户用的是按量付费模型（DeepSeek 等），本模块提供极轻量的本地台账：
每次 LLM 调用记一笔，区分缓存命中 / 缓存未命中 / 输出三档价格，以及高峰 / 闲时窗口。
数据存在 trade.db 的 usage_ledger 表，随库备份走。

费率说明：
- 默认价格与时段规则存放在同目录 `trade/pricing.toml`（含官方来源 URL 与查阅日期）；
- 可通过环境变量 `TRADE_PRICING_FILE` 指定自定义 TOML；
- 可通过环境变量 `TRADE_PRICE_<MODEL>` 覆盖单模型价格：
  - 两段格式 `"in,out"`（命中与未命中均按 `in` 计）；
  - 三段格式 `"hit,miss,out"`（单位：美元 / 1M tokens）；
- 模型名归一化：小写、去空格，便于匹配。

注意：费用为本地估算，实际以服务商（如 DeepSeek）账单为准；token 数以 SDK 返回的 usage 为准。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
import tomllib
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 每公司每日 token 额度（输入+输出合计），只用于侧栏提示，不拦截聊天。
# 默认 2000 万：实测一次网站诊断约 340 万，200 万会一句就标红（2026-10-26）。
# 环境变量 TRADE_DAILY_TOKEN_LIMIT 覆盖，设为 0（或负数）表示不限。
DEFAULT_DAILY_TOKEN_LIMIT = 20_000_000

# 缺缓存字段时的行标记（存于 extra1）
NO_CACHE_DATA_TAG = "no_cache_data"

# 默认配置文件路径
_DEFAULT_PRICING_PATH = Path(__file__).resolve().parent / "pricing.toml"

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
    cache_hit_tokens  INTEGER NOT NULL DEFAULT 0,
    cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
    price_window      TEXT    NOT NULL DEFAULT '',
    currency          TEXT    NOT NULL DEFAULT 'USD',
    cost_usd          REAL    NOT NULL DEFAULT 0,
    extra1            TEXT    NOT NULL DEFAULT '',
    extra2            TEXT    NOT NULL DEFAULT '',
    extra3            TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage_ledger(ts);
CREATE INDEX IF NOT EXISTS idx_usage_skill ON usage_ledger(skill);
"""


# ==============================================================================
# 价格配置加载与时段判定
# ==============================================================================


def _norm_model(model: str) -> str:
    """将模型名归一化为小写连字符形式，便于查表和匹配环境变量。"""
    return (model or "").strip().lower().replace(" ", "-").replace("_", "-")


def load_pricing_config(path: Path | None = None) -> dict[str, Any]:
    """加载价格与时段配置（优先 TRADE_PRICING_FILE，其次内置 trade/pricing.toml）。"""
    env_file = os.environ.get("TRADE_PRICING_FILE", "").strip()
    target = path or (Path(env_file) if env_file else _DEFAULT_PRICING_PATH)
    try:
        return tomllib.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — 配置缺失/损坏时降级为空配置，不阻断记账
        logger.warning("读取价格配置失败（%s）：%s", target, exc)
        return {}


def pricing_freshness_info(
    *, today: date | None = None, config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """返回价格配置的核对日期、已过天数与是否超过 stale_days（供 doctor 提醒）。"""
    cfg = config if config is not None else load_pricing_config()
    meta = cfg.get("meta") if isinstance(cfg.get("meta"), dict) else {}
    verified_str = str(meta.get("verified_at") or "").strip()
    stale_days = int(meta.get("stale_days") or 90)
    source_url = str(meta.get("source_url") or "").strip()
    ref_day = today or date.today()
    age_days: int | None = None
    is_stale = False
    if verified_str:
        try:
            verified_day = date.fromisoformat(verified_str)
            age_days = (ref_day - verified_day).days
            is_stale = age_days > stale_days
        except ValueError:
            age_days = None
    return {
        "verified_at": verified_str,
        "age_days": age_days,
        "stale_days": stale_days,
        "is_stale": is_stale,
        "source_url": source_url,
    }


def resolve_price_window(
    model: str,
    *,
    ts: float | None = None,
    config: dict[str, Any] | None = None,
    holidays: set[str] | list[str] | None = None,
) -> str:
    """判定指定模型在时间 ts 处于 peak / offpeak / ''（不分时段）。

    按配置中的 window_group（如 deepseek）在 UTC 时间下判断：
    - 当日位于 holidays 列表 → offpeak；
    - UTC 星期不在 peak_weekdays（如周六/周日）→ offpeak；
    - UTC 小时落入任意左闭右开区间 [start, end) → peak，否则 offpeak。
    """
    cfg = config if config is not None else load_pricing_config()
    models_cfg = cfg.get("models") if isinstance(cfg.get("models"), dict) else {}
    m_cfg = models_cfg.get(_norm_model(model))
    # 未知模型或未配置分时段组时返回空串
    if not isinstance(m_cfg, dict) or not m_cfg.get("window_group"):
        return ""
    group_name = str(m_cfg["window_group"])
    windows_cfg = cfg.get("windows") if isinstance(cfg.get("windows"), dict) else {}
    w_cfg = windows_cfg.get(group_name)
    if not isinstance(w_cfg, dict):
        return ""

    dt_utc = datetime.fromtimestamp(ts if ts is not None else time.time(), tz=UTC)
    day_str = dt_utc.date().isoformat()
    holiday_set = set(holidays) if holidays is not None else set(w_cfg.get("holidays") or [])
    # 配置的法定节假日全天按闲时计价
    if day_str in holiday_set:
        return "offpeak"

    peak_weekdays = set(w_cfg.get("peak_weekdays") or [])
    # 非工作日（如周六、周日）全天按闲时计价
    if dt_utc.weekday() not in peak_weekdays:
        return "offpeak"

    hour = dt_utc.hour
    for rng in w_cfg.get("peak_utc_ranges") or []:
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            start_h, end_h = int(rng[0]), int(rng[1])
            # 左闭右开：[start_h, end_h)
            if start_h <= hour < end_h:
                return "peak"
    return "offpeak"


def get_tiered_price(
    model: str,
    *,
    window: str = "",
    config: dict[str, Any] | None = None,
) -> tuple[float, float, float]:
    """返回 (缓存命中输入价, 缓存未命中输入价, 输出价) 美元 / 1M tokens。

    优先级：环境变量 TRADE_PRICE_<MODEL> > 配置文件（按 peak/offpeak） > (0, 0, 0)。
    """
    key = _norm_model(model)
    env_key = "TRADE_PRICE_" + key.upper().replace("-", "_")
    env_val = os.environ.get(env_key, "").strip()
    # 环境变量显式覆盖优先
    if env_val:
        parts = [p.strip() for p in env_val.split(",")]
        try:
            if len(parts) == 2:
                inp, outp = float(parts[0]), float(parts[1])
                return inp, inp, outp
            if len(parts) == 3:
                return float(parts[0]), float(parts[1]), float(parts[2])
        except ValueError:
            pass
        logger.warning(
            "费率环境变量格式错误 %s=%r，应为 in,out 或 hit,miss,out", env_key, env_val
        )

    cfg = config if config is not None else load_pricing_config()
    models_cfg = cfg.get("models") if isinstance(cfg.get("models"), dict) else {}
    m_cfg = models_cfg.get(key)
    if not isinstance(m_cfg, dict):
        return 0.0, 0.0, 0.0

    # 分时段模型按 window 选择对应价格子表（默认回落 peak 避免低估）
    if window and isinstance(m_cfg.get(window), dict):
        tier = m_cfg[window]
    elif isinstance(m_cfg.get("peak"), dict):
        tier = m_cfg["peak"]
    else:
        tier = m_cfg

    hit_p = float(tier.get("cache_hit", tier.get("cache_miss", 0.0)) or 0.0)
    miss_p = float(tier.get("cache_miss", 0.0) or 0.0)
    out_p = float(tier.get("output", 0.0) or 0.0)
    return hit_p, miss_p, out_p


def get_price(model: str) -> tuple[float, float]:
    """兼容旧接口：返回 (未命中输入价, 输出价) 美元 / 1M tokens。"""
    _hit, miss, out = get_tiered_price(model)
    return miss, out


# ==============================================================================
# Provider 响应 / Agent 用量字段统一映射
# ==============================================================================


def _read_field(obj: Any, name: str) -> Any:
    """兼容 dict 与对象属性读取。"""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _to_nonneg_int(val: Any) -> int:
    """将任意数值安全转为非负整数。"""
    if val is None or isinstance(val, bool):
        return 0
    try:
        return max(0, int(val))
    except (TypeError, ValueError):
        return 0


def extract_usage_tokens(usage_obj: Any) -> dict[str, Any]:
    """统一解析 OpenAI / DeepSeek / Hermes 等不同 provider 的 usage 对象。

    Returns:
        {
            "prompt_tokens": int,       # 输入总量（命中 + 未命中）
            "completion_tokens": int,   # 输出总量
            "cache_hit_tokens": int,    # 缓存命中输入
            "cache_miss_tokens": int,   # 缓存未命中输入
            "has_cache_data": bool,     # 是否显式提供了缓存明细字段
        }
    """
    if usage_obj is None:
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cache_hit_tokens": 0,
            "cache_miss_tokens": 0,
            "has_cache_data": False,
        }

    raw_prompt = _read_field(usage_obj, "prompt_tokens")
    if raw_prompt is None:
        raw_prompt = _read_field(usage_obj, "input_tokens")
    prompt = _to_nonneg_int(raw_prompt)

    raw_comp = _read_field(usage_obj, "completion_tokens")
    if raw_comp is None:
        raw_comp = _read_field(usage_obj, "output_tokens")
    completion = _to_nonneg_int(raw_comp)

    # 依次检查 DeepSeek 原生字段、Hermes 归一化字段、OpenAI prompt_tokens_details
    raw_hit = _read_field(usage_obj, "prompt_cache_hit_tokens")
    if raw_hit is None:
        raw_hit = _read_field(usage_obj, "cache_read_tokens")
    if raw_hit is None:
        details = _read_field(usage_obj, "prompt_tokens_details")
        if details is not None:
            raw_hit = _read_field(details, "cached_tokens")

    raw_miss = _read_field(usage_obj, "prompt_cache_miss_tokens")
    has_cache_data = (raw_hit is not None) or (raw_miss is not None)

    if has_cache_data:
        hit = _to_nonneg_int(raw_hit)
        if raw_miss is not None:
            miss = _to_nonneg_int(raw_miss)
            # 若输入总量未提供但给了 hit + miss，则反推总量
            if prompt == 0 and (hit + miss) > 0:
                prompt = hit + miss
        else:
            miss = max(0, prompt - hit)
        # 防止异常数据导致命中超过总输入
        if prompt > 0 and hit > prompt:
            hit = prompt
            miss = 0
    else:
        # 缺失缓存字段时全部按未命中计，调用方会在账本行打标记
        hit = 0
        miss = prompt

    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cache_hit_tokens": hit,
        "cache_miss_tokens": miss,
        "has_cache_data": has_cache_data,
    }


# ==============================================================================
# Schema 兜底与记账
# ==============================================================================


def ensure_usage_schema(conn: sqlite3.Connection) -> None:
    """确保 usage_ledger 表及缓存/时段扩展列存在（幂等，兼容老库）。"""
    conn.executescript(SCHEMA_SQL)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(usage_ledger)").fetchall()}
    additions = [
        ("cache_hit_tokens", "INTEGER NOT NULL DEFAULT 0"),
        ("cache_miss_tokens", "INTEGER NOT NULL DEFAULT 0"),
        ("price_window", "TEXT NOT NULL DEFAULT ''"),
        ("currency", "TEXT NOT NULL DEFAULT 'USD'"),
    ]
    for col, col_def in additions:
        # 老库缺列时自动补齐
        if col not in cols:
            conn.execute(f"ALTER TABLE usage_ledger ADD COLUMN {col} {col_def}")
    conn.commit()


def record_usage(
    conn: sqlite3.Connection,
    *,
    skill: str = "",
    provider: str = "",
    model: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cache_hit_tokens: int | None = None,
    cache_miss_tokens: int | None = None,
    company_id: int = 0,
    price_override: tuple[float, float] | tuple[float, float, float] | None = None,
    ts: float | None = None,
    config: dict[str, Any] | None = None,
    holidays: set[str] | list[str] | None = None,
) -> float:
    """记一笔用量，按缓存命中 / 未命中 / 输出三档及高峰闲时计价，返回估算费用（美元）。

    失败永不抛错（只记日志）。
    """
    try:
        ensure_usage_schema(conn)
        now_ts = ts if ts is not None else time.time()
        prompt = max(0, int(prompt_tokens or 0))
        completion = max(0, int(completion_tokens or 0))

        # 判断是否显式提供了缓存明细；未提供时全部按未命中计并标记 extra1
        has_cache_data = (cache_hit_tokens is not None) or (cache_miss_tokens is not None)
        if has_cache_data:
            hit = max(0, int(cache_hit_tokens or 0))
            if cache_miss_tokens is not None:
                miss = max(0, int(cache_miss_tokens or 0))
                if prompt == 0 and (hit + miss) > 0:
                    prompt = hit + miss
            else:
                miss = max(0, prompt - hit)
            if prompt > 0 and hit > prompt:
                hit = prompt
                miss = 0
            extra1 = ""
        else:
            hit = 0
            miss = prompt
            extra1 = NO_CACHE_DATA_TAG

        cfg = config if config is not None else load_pricing_config()
        window = resolve_price_window(model, ts=now_ts, config=cfg, holidays=holidays)
        meta = cfg.get("meta") if isinstance(cfg.get("meta"), dict) else {}
        currency = str(meta.get("currency") or "USD")

        if price_override is not None:
            if len(price_override) == 3:
                phit, pmiss, pout = price_override
            else:
                phit, pmiss, pout = price_override[0], price_override[0], price_override[1]
        else:
            phit, pmiss, pout = get_tiered_price(model, window=window, config=cfg)

        cost = (
            (hit / 1_000_000) * phit
            + (miss / 1_000_000) * pmiss
            + (completion / 1_000_000) * pout
        )
        conn.execute(
            """INSERT INTO usage_ledger
               (ts, company_id, skill, provider, model,
                prompt_tokens, completion_tokens,
                cache_hit_tokens, cache_miss_tokens,
                price_window, currency, cost_usd, extra1)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now_ts,
                company_id,
                skill,
                provider,
                _norm_model(model),
                prompt,
                completion,
                hit,
                miss,
                window,
                currency,
                cost,
                extra1,
            ),
        )
        conn.commit()
        return cost
    except Exception as e:
        logger.warning("用量记录失败: %s", e)
        return 0.0


def record_response_usage(
    usage_obj: Any,
    *,
    skill: str = "",
    provider: str = "",
    model: str = "",
    company_id: int = 0,
    conn: sqlite3.Connection | None = None,
    ts: float | None = None,
) -> float:
    """将辅助 LLM 响应（如 doc_extract / supplier-extract）的 usage 写入台账。

    模型未返回 usage 或 token 全为 0 时记 0 且不报错；任何异常只打日志。
    """
    parsed = extract_usage_tokens(usage_obj)
    # 无有效 token 时直接返回 0
    if parsed["prompt_tokens"] <= 0 and parsed["completion_tokens"] <= 0:
        return 0.0

    own_conn = conn is None
    try:
        if own_conn:
            from trade.database import get_connection

            conn = get_connection()
        assert conn is not None
        return record_usage(
            conn,
            skill=skill,
            provider=provider,
            model=model,
            prompt_tokens=parsed["prompt_tokens"],
            completion_tokens=parsed["completion_tokens"],
            cache_hit_tokens=parsed["cache_hit_tokens"] if parsed["has_cache_data"] else None,
            cache_miss_tokens=parsed["cache_miss_tokens"] if parsed["has_cache_data"] else None,
            company_id=company_id,
            ts=ts,
        )
    except Exception as e:
        logger.warning("辅助模型用量记录失败（不影响主流程）: %s", e)
        return 0.0
    finally:
        if own_conn and conn is not None:
            conn.close()


def _day_start_ts() -> float:
    """本地时区今天 00:00 的时间戳（limits 按用户看到的一天算，不按 UTC）。"""
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
    """把一次 agent 调用的 token 用量（含缓存命中）记入台账，返回费用（美元）。

    Hermes 的 ``session_*`` 计数是该 agent 实例的累计值；Trade 每个请求新建
    agent，所以它天然等于本次请求的用量（重试各自新建 agent，各记一笔）。
    字段缺失（旧版 Hermes / 测试桩）时记 0 —— 记账是旁路，绝不能影响聊天。
    """
    prompt = _to_nonneg_int(getattr(agent, "session_prompt_tokens", 0))
    completion = _to_nonneg_int(getattr(agent, "session_completion_tokens", 0))
    has_cache_attr = hasattr(agent, "session_cache_read_tokens")
    cache_read = _to_nonneg_int(getattr(agent, "session_cache_read_tokens", 0)) if has_cache_attr else 0

    # 部分 provider 只填 session_input_tokens（扣掉缓存后的未命中输入）/ session_output_tokens
    if not prompt:
        raw_in = _to_nonneg_int(getattr(agent, "session_input_tokens", 0))
        prompt = raw_in + cache_read if (has_cache_attr and raw_in > 0) else raw_in
    if not completion:
        completion = _to_nonneg_int(getattr(agent, "session_output_tokens", 0))
    if prompt <= 0 and completion <= 0:
        return 0.0

    cache_hit: int | None = None
    cache_miss: int | None = None
    # Hermes 暴露了 session_cache_read_tokens 时，按命中 / 未命中拆分记账
    if has_cache_attr:
        cache_hit = min(cache_read, prompt)
        cache_miss = max(0, prompt - cache_hit)

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
                cache_hit_tokens=cache_hit,
                cache_miss_tokens=cache_miss,
                company_id=company_id,
            )
        finally:
            conn.close()
    except Exception as e:
        logger.warning("用量记录失败（不影响聊天）: %s", e)
        return 0.0


def summary(conn: sqlite3.Connection, days: int = 7) -> dict:
    """近 N 天汇总：总 token、缓存命中率、估算费用、按 skill / 按模型 / 按天拆分。"""
    ensure_usage_schema(conn)
    since = time.time() - days * 86400
    total = conn.execute(
        """SELECT COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0),
                  COALESCE(SUM(cache_hit_tokens),0), COALESCE(SUM(cache_miss_tokens),0),
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
    total_prompt = int(total[0])
    total_hit = int(total[2])
    total_miss = int(total[3])
    hit_rate = round(total_hit / total_prompt, 4) if total_prompt > 0 else 0.0
    return {
        "days": days,
        "total_tokens": int(total[0] + total[1]),
        "cache_hit_tokens": total_hit,
        "cache_miss_tokens": total_miss,
        "cache_hit_rate": hit_rate,
        "total_cost_usd": round(float(total[4]), 4),
        "cost_note": "估算，以 DeepSeek 账单为准",
        "calls": int(total[5]),
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
    """给前端/CLI 用的纯文本摘要（明确标注估算口径与缓存命中率）。"""
    hit_pct = float(s.get("cache_hit_rate") or 0.0) * 100
    note = s.get("cost_note") or "估算，以 DeepSeek 账单为准"
    lines = [
        f"近 {s['days']} 天：{s['calls']} 次调用，{s['total_tokens']} tokens"
        f"（缓存命中率 {hit_pct:.1f}%），"
        f"约 ${s['total_cost_usd']:.4f}（{note}）"
    ]
    if s["by_skill"]:
        lines.append("按 skill（费用倒序）：")
        for r in s["by_skill"][:10]:
            lines.append(f"  - {r['skill']}: {r['calls']} 次 / ${r['cost_usd']:.4f}")
    return "\n".join(lines)
