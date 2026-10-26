"""
Trade AI Assistant — 聊天记忆 / 对话记录。

存储 Agent 会话期间的查询、回复以及读取的文件。
可选地将对话轮次保留到 Hindsight 长期记忆（需要 hindsight-client 包和 API 密钥）。

所有操作均通过 company_id 隔离，实现多租户数据隔离。
"""

import json
import logging
from datetime import datetime

from trade.database import get_connection

logger = logging.getLogger(__name__)

# 对话清理节流：每家公司每天最多运行一次，避免每次保存都扫描全表
_last_purge_date: dict[int, str] = {}


def purge_old_conversations(company_id: int, days: int = 365, min_total: int = 30000) -> int:
    """删除指定公司 N 天前的对话记录，返回删除行数。

    仅在总对话数超过 min_total 时才执行清理——避免对小数据集的过度裁剪。
    每家公司独立清理，不影响其他公司的数据保留策略。
    """
    conn = get_connection()
    try:
        # 先检查总量，小于阈值不清理
        total = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE company_id = ?",
            (company_id,),
        ).fetchone()[0]
        if total < min_total:
            return 0

        cur = conn.execute(
            "DELETE FROM conversations "
            "WHERE company_id = ? AND created_at < datetime('now', 'localtime', ?)",
            (company_id, f"-{days} days"),
        )
        conn.commit()
        deleted = cur.rowcount
        if deleted:
            logger.info("Purged %d conversations older than %d days for company %d",
                        deleted, days, company_id)
        return deleted
    finally:
        conn.close()


def save(
    company_id: int,
    query: str,
    response: str = "",
    library_id: int | None = None,
    files_read: list[dict] | None = None,
    context: str = "",
    skill: str = "",
    customer_id: int | None = None,
) -> dict:
    """保存一条对话记录，作用域限定到指定公司。返回新插入的行，以字典形式呈现。

    skill 参数记录本次查询匹配到的技能名（存入 extra3），供质量统计按技能聚合评分。
    customer_id 记录这条对话属于哪个客户（None = 未关联客户），历史注入按它过滤。
    """
    if company_id is None:
        raise ValueError("company_id is required for conversation isolation")
    conn = get_connection()
    try:
        # extra3 记录匹配到的 skill（空则不写，保持旧行为兼容）
        extra3 = json.dumps({"skill": skill}, ensure_ascii=False) if skill else "{}"
        cur = conn.execute(
            "INSERT INTO conversations "
            "(company_id, customer_id, library_id, query, response, files_read, context, extra3) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                company_id,
                customer_id,
                library_id,
                query,
                response,
                json.dumps(files_read or [], ensure_ascii=False),
                context,
                extra3,
            ),
        )
        new_id = cur.lastrowid
        conn.commit()  # 先确保数据落库，再 SELECT
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (new_id,)
        ).fetchone()
        if row is not None:
            return _row_to_dict(row)
        # 极端兜底：返回最小可用字典（字段类型与 _row_to_dict 输出一致）
        return {
            "id": new_id, "company_id": company_id, "customer_id": customer_id,
            "library_id": library_id, "query": query, "response": response,
            "files_read": files_read or [], "created_at": None, "context": context,
            "extra1": {}, "extra2": {}, "extra3": {},
        }
    finally:
        conn.close()


def list_by_context(
    company_id: int, context: str, limit: int = 50
) -> list[dict]:
    """返回指定公司内某个上下文（如 daily/lead/platform）最近的对话记录。

    同时包含 context 为空字符串的旧记录，兼容升级前的历史数据。
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE company_id = ? "
            "AND (context = ? OR context = '') "
            "ORDER BY id DESC LIMIT ?",
            (company_id, context, limit),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def list_by_company(company_id: int, limit: int = 50) -> list[dict]:
    """返回指定公司最近的对话记录，按最新在前排序。"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE company_id = ? ORDER BY id DESC LIMIT ?",
            (company_id, limit),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def list_by_library(
    company_id: int, library_id: int, limit: int = 50
) -> list[dict]:
    """返回指定公司内某个资料库最近的对话记录，按最新在前排序。"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE company_id = ? AND library_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (company_id, library_id, limit),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get(company_id: int, conversation_id: int) -> dict | None:
    """根据 ID 获取单条对话记录，作用域限定到公司。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ? AND company_id = ?",
            (conversation_id, company_id),
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def update_response(company_id: int, conversation_id: int, response: str) -> dict | None:
    """更新一条对话记录的回复字段。"""
    conn = get_connection()
    try:
        n = conn.execute(
            "UPDATE conversations SET response = ? WHERE id = ? AND company_id = ?",
            (response, conversation_id, company_id),
        ).rowcount
        conn.commit()
        if n == 0:
            # 没有行被更新，说明指定 ID 的记录不存在或不属于该公司
            return None
        return get(company_id, conversation_id)
    finally:
        conn.close()


def delete(company_id: int, conversation_id: int) -> bool:
    """删除一条对话记录，作用域限定到公司。"""
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM conversations WHERE id = ? AND company_id = ?",
            (conversation_id, company_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def add_rating(
    company_id: int,
    conversation_id: int,
    rating: int,
    feedback: str = "",
) -> dict | None:
    """为对话记录添加评分（1-5）和可选的文字反馈。

    使用 json_set 原子 UPDATE 避免读-改-写竞态条件。
    返回更新后的行字典，找不到记录时返回 None。
    """
    rated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE conversations SET extra2 = json_set("
            "  COALESCE(NULLIF(extra2, ''), '{}'),"
            "  '$.rating', ?, '$.feedback', ?, '$.rated_at', ?"
            ") WHERE id = ? AND company_id = ?",
            (rating, feedback, rated_at, conversation_id, company_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
        return get(company_id, conversation_id)
    finally:
        conn.close()


# ── 质量统计（rating 闭环） ──────────────────────────────────────────

# 低分阈值：rating ≤ 2 视为"需要关注的回复"（前端 👍=4 / 👎=2）
_LOW_RATING_THRESHOLD = 2


def get_quality_stats(company_id: int, days: int = 30) -> dict:
    """聚合指定公司近 N 天的对话评分，用于发现需要优化的技能/场景。

    只统计窗口期内已评分的记录（extra2.rating 非空）。分组维度：
      - by_skill:   按对话匹配到的技能（extra3.skill）聚合
      - by_context: 按聊天入口场景（daily/lead/osint 等）聚合
    两组均按「低分优先、其次均分升序」排序，方便直接看到最需要关注的项。

    days 会被收窄到 1-365，防止异常参数导致全表扫描或空窗口。
    """
    if company_id is None:
        raise ValueError("company_id is required for conversation isolation")
    days = max(1, min(int(days), 365))
    window = f"-{days} days"

    # 公共过滤条件：窗口内 + extra2 是合法 JSON 且已有评分
    # （json_valid 保护历史脏数据，避免 json_extract 抛 malformed JSON 错误）
    _WHERE = (
        "WHERE company_id = ? AND created_at >= datetime('now', 'localtime', ?) "
        "AND json_valid(extra2) AND json_extract(extra2, '$.rating') IS NOT NULL"
    )
    _AGG = (
        "COUNT(*) AS rated, "
        "ROUND(AVG(json_extract(extra2, '$.rating')), 2) AS avg_rating, "
        "SUM(CASE WHEN json_extract(extra2, '$.rating') <= ? THEN 1 ELSE 0 END) AS low_count"
    )
    _ORDER = "ORDER BY low_count DESC, avg_rating ASC"

    conn = get_connection()
    try:
        # 总体：已评分数 / 均分 / 低分数
        total_row = conn.execute(
            f"SELECT {_AGG} FROM conversations {_WHERE}",
            (_LOW_RATING_THRESHOLD, company_id, window),
        ).fetchone()
        total_rated = total_row["rated"] or 0

        # 按技能聚合：extra3 缺失/非法时归入「未匹配技能」，不丢行
        by_skill = conn.execute(
            "SELECT COALESCE(NULLIF(json_extract("
            "  CASE WHEN json_valid(extra3) THEN extra3 ELSE '{}' END, '$.skill'), ''), "
            "  '(未匹配技能)') AS grp, "
            f"{_AGG} FROM conversations {_WHERE} "
            f"GROUP BY grp {_ORDER}",
            (_LOW_RATING_THRESHOLD, company_id, window),
        ).fetchall()

        # 按聊天入口聚合
        by_context = conn.execute(
            "SELECT COALESCE(NULLIF(context, ''), '(未指定)') AS grp, "
            f"{_AGG} FROM conversations {_WHERE} "
            f"GROUP BY grp {_ORDER}",
            (_LOW_RATING_THRESHOLD, company_id, window),
        ).fetchall()

        return {
            "days": days,
            "total_rated": total_rated,
            "avg_rating": total_row["avg_rating"],
            "low_count": total_row["low_count"] or 0,
            "by_skill": [
                {"skill": r["grp"], "rated": r["rated"],
                 "avg_rating": r["avg_rating"], "low_count": r["low_count"] or 0}
                for r in by_skill
            ],
            "by_context": [
                {"context": r["grp"], "rated": r["rated"],
                 "avg_rating": r["avg_rating"], "low_count": r["low_count"] or 0}
                for r in by_context
            ],
        }
    finally:
        conn.close()


# ── Hindsight 集成 ───────────────────────────────────────────────────

def save_with_context(
    company_id: int | None,
    query: str,
    response: str = "",
    library_id: int | None = None,
    files_read: list[dict] | None = None,
    *,
    library_name: str = "",
    customer_name: str = "",
    customer_id: int | None = None,
    retain_to_memory: bool = True,
    context: str = "",
    skill: str = "",
) -> dict:
    """保存一条对话记录到 SQLite，并可选择同步到 Hindsight 长期记忆。

    这是 B2B 对话日志记录推荐使用的入口函数。
    skill 记录本次匹配到的技能名，供质量统计（get_quality_stats）按技能聚合评分。
    customer_id 供后续按客户过滤历史。
    """
    result = save(
        company_id, query, response, library_id, files_read,
        context=context, skill=skill, customer_id=customer_id,
    )
    # 试用期价值小结：每保存一轮对话记一次「处理询盘」（旁路统计，失败不影响保存）
    try:
        from trade.trial_usage import KIND_INQUIRY, record_event

        record_event(KIND_INQUIRY, company_id)
    except Exception:
        pass

    if retain_to_memory:
        # 只有当调用方要求保留到记忆时才执行，避免不必要的 I/O
        try:
            from trade import company as _company
            from trade.memory import retain_conversation, retain_to_hermes_memory

            # Hindsight 记忆（需要 API 密钥 —— 即发即忘，失败不影响主流程）
            try:
                retained = retain_conversation(
                    query=query,
                    response=response,
                    library_name=library_name,
                    customer_name=customer_name,
                    company_id=company_id,
                )
                if retained:
                    # 成功保留日志后记录调试信息，便于排查记忆同步问题
                    logger.debug("Conversation %d retained to Hindsight", result["id"])
            except Exception as exc:
                logger.debug("Hindsight retain skipped: %s", exc)

            # Hermes 原生记忆（始终可用 —— 即发即忘，失败不影响主流程）
            try:
                company_name = ""
                if company_id:
                    # 根据公司 ID 查询公司名称，用于在记忆上下文中标识来源
                    co = _company.get(company_id)
                    if co:
                        company_name = co.get("name", "")
                retain_to_hermes_memory(
                    query=query,
                    response=response,
                    company_name=company_name,
                    library_name=library_name,
                    customer_name=customer_name,
                )
            except Exception as exc:
                logger.debug("Hermes memory retain skipped: %s", exc)

        except ImportError:
            pass  # trade.memory 模块未安装，跳过记忆保留
        except Exception as exc:
            logger.debug("Memory retain skipped: %s", exc)

    # 每天运行一次对话清理（每家公司独立节流），删除 365 天前的旧记录（仅当总量超过 30000 条时触发）
    if company_id:
        global _last_purge_date
        from datetime import date as _date
        _today = _date.today().isoformat()
        if _last_purge_date.get(company_id) != _today:
            _last_purge_date[company_id] = _today
            try:
                purge_old_conversations(company_id, days=365, min_total=30000)
            except Exception:
                logger.debug("Conversation purge skipped", exc_info=True)

    return result


def recall_context(query: str, *, bank_id: str = "trade") -> str:
    """搜索 Hindsight 长期记忆以获取相关的历史对话记录。

    可按公司隔离（传入 bank_id="trade-company-{id}"）。

    如果 Hindsight 不可用或未找到匹配结果，则返回空字符串。
    """
    try:
        from trade.memory import recall

        result = recall(query, bank_id=bank_id)
        return result or ""
    except ImportError:
        return ""
    except Exception:
        return ""


# ── 辅助函数 ──────────────────────────────────────────────────────────


def get_recent(
    company_id: int, limit: int = 20, customer_id: int | None = None
) -> list[dict]:
    """获取最近的 N 条对话记录，用于上下文注入。

    customer_id 给定时只取该客户的对话；**未选客户时只取未归属对话**
    （`customer_id IS NULL`）—— 否则默认聊天会把全公司最近 20 条塞进 prompt，
    给 A 客户的回答看到 B 客户的价格/承诺（2026-10-23/25 审计）。
    返回时反转以确保上下文按时间正序排列。
    """
    clauses = ["company_id = ?", "query IS NOT NULL"]
    params: list = [company_id]
    if customer_id is not None:
        clauses.append("customer_id = ?")
        params.append(customer_id)
    else:
        clauses.append("customer_id IS NULL")
    params.append(limit)

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, company_id, customer_id, library_id, query, response, "
            "files_read, created_at "
            f"FROM conversations WHERE {' AND '.join(clauses)} "
            "ORDER BY id DESC LIMIT ?",
            params,
        ).fetchall()
        # 反转排序，使得最早的在最前，适合作为对话上下文输入给 LLM
        return [_row_to_dict(r) for r in reversed(rows)]
    finally:
        conn.close()


# ── search_history 时间范围边界计算 ──────────────────────────────────
# 抽成查表是为了**让以后加新枚举只是加一行**（否则又写漏一档——这就是这条 review 的根因）。
# 所有区间都是**左闭右开**（含 start、不含隐含 end），与 created_at 的字符串字典序语义一致。
# 区间端点都是 00:00:00 本地时间，与 created_at 同源；this_* 含"现在"，last_* 不含"现在"。
#
# 时区口径：与 save_with_context 一致（datetime('now', 'localtime')）。所有计算都在
# Python 进程的本地时区完成，**不**做时区归一化——这是 trade 现有口径，保持一致。
#
# "本周"基准：Monday=weekday(0)。"上周"= 本周一 00:00 减 7 天。注意这是中国大陆
# 出口场景的默认（贸易员认知的"上周一→本周一"）；如果哪天产品决定改"周日=一周第一天"，
# 改这里 8 个 lambda 即可——**是改一处而不是改 8 处 if**。
import datetime as _dt
from collections.abc import Callable

# 区间计算器的签名：吃一个 now，吐该区间的**起点**（或 None = 不过滤）
_BoundaryFn = Callable[[_dt.datetime], "_dt.datetime | None"]


def _start_of_day(dt: _dt.datetime) -> _dt.datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _start_of_week(dt: _dt.datetime) -> _dt.datetime:
    return _start_of_day(dt - _dt.timedelta(days=dt.weekday()))


def _start_of_month(dt: _dt.datetime) -> _dt.datetime:
    return _start_of_day(dt.replace(day=1))


def _start_of_year(dt: _dt.datetime) -> _dt.datetime:
    return _start_of_day(dt.replace(month=1, day=1))


def _subtract_one_month(dt: _dt.datetime) -> _dt.datetime:
    """回退一个月。year-1/12 用于 1 月的特殊情况（stdlib 没有直接的 -1 month）。

    ⚠️ **要求 day 落在每个月都存在**（即 ≤28，实践中就是月初）。
    对 3/31 这类日期 `replace(month=2)` 会直接 ValueError（2 月没有 31 号）——
    这是 2026-10-16 实测踩到的月末崩溃。调用方如果传的是"当前时刻"，必须先用
    `_start_of_month()` 归一。
    """
    if dt.month == 1:
        return dt.replace(year=dt.year - 1, month=12)
    return dt.replace(month=dt.month - 1)


def _subtract_one_week(dt: _dt.datetime) -> _dt.datetime:
    return dt - _dt.timedelta(days=7)


def _subtract_one_year(dt: _dt.datetime) -> _dt.datetime:
    return dt.replace(year=dt.year - 1)


# 区间计算器：每个 lambda 接受 now，返回对应区间的**起点**（左闭右开的 start）。
# 返回 None 表示"无时间过滤"（= all）。
#
# **区间口径**：
#   - 含"现在"的：today / this_week / this_month / this_year
#   - 不含"现在"的（前一周期完整窗口）：yesterday / last_week / last_month / last_year
# 这与 chat-memory 的 augment_prompt 表严格一致。
_BOUNDARY_COMPUTERS: dict[str, "_BoundaryFn"] = {
    "today":      lambda now: _start_of_day(now),
    # yesterday 是"昨天那一整天"，不含今天 00:00 之后；用 end 关键字显式表达上界
    "yesterday":  lambda now: _start_of_day(now - _dt.timedelta(days=1)),
    "this_week":  lambda now: _start_of_week(now),
    "last_week":  lambda now: _subtract_one_week(_start_of_week(now)),
    "this_month": lambda now: _start_of_month(now),
    "last_month": lambda now: _subtract_one_month(_start_of_month(now)),
    "this_year":  lambda now: _start_of_year(now),
    "last_year":  lambda now: _subtract_one_year(_start_of_year(now)),
    "all":        lambda now: None,
}

# 对应"不含现在"的枚举，需要上界 end（与 start 一起把区间夹出来）。
# 结构：start_computer / end_computer —— end 是个"开区间右端"，不参与等号。
_BOUNDARY_END_COMPUTERS: dict[str, "_BoundaryFn"] = {
    "yesterday":  lambda now: _start_of_day(now),
    "last_week":  lambda now: _start_of_week(now),
    "last_month": lambda now: _start_of_month(now),
    "last_year":  lambda now: _start_of_year(now),
}


# 工具暴露的合法枚举：search_history 接受这些值，其它一律视为 "all"（fail-safe —— 与
# 旧实现的"else: start = None"行为一致）。新加枚举**只需**改这里 + _BOUNDARY_COMPUTERS + 测试，
# 不用动 SQL。
_VALID_TIME_RANGES = frozenset(_BOUNDARY_COMPUTERS.keys())


def search_history(
    company_id: int,
    time_range: str = "all",
    limit: int = 20,
    *,
    recent_days: int | None = None,
    recent_months: int | None = None,
    customer_id: int | None = None,
    unattributed_only: bool = False,
) -> list[dict]:
    """按时间范围查询历史对话记录（供 LLM 工具调用使用）。

    Args:
        company_id: 作用域，限定到公司
        time_range: "today" | "yesterday" | "this_week" | "last_week"
                  | "this_month" | "last_month" | "this_year" | "last_year" | "all"
                  （未知值 → 等同 "all"；fail-safe）
        recent_days: 若非 None，按"过去 N 天（含今天）"过滤。**优先于 time_range**。
                          用来表达"上周三"等不能精确落到枚举的情况。
        recent_months: 同 recent_days，按"过去 N 个月（含本月）"。**优先于 time_range**。
        limit: 最大返回行数

    Returns:
        字典列表，包含 id, query, response, created_at。
    """
    # recent_days / recent_months 优先于 time_range：它们解决"上上周/上个月初/上周三"等
    # 枚举表达不了的相对区间。schema 里标为可选（与 time_range 互斥，靠 augment_prompt 约束）。
    import datetime as _dt

    conn = get_connection()
    try:
        if recent_days is not None and recent_days > 0:
            # **含今天**所有数据：start = (N-1) 天前的 00:00。
            # 例如 N=1 → start = 今天 00:00（仅今天的对话，**不等于 yesterday** —— yesterday
            # 不含今天）；N=2 → start = 昨天 00:00（今天 + 昨天）；N=7 → 过去 7 整天。
            #
            # 这与 time_range=today 起点同，但 recent_days 解决枚举表达不了的相对区间
            # （"上上周三" = 14；"前 7 天" = 7）。
            start = _start_of_day(_dt.datetime.now() - _dt.timedelta(days=recent_days - 1))
        elif recent_months is not None and recent_months > 0:
            # 含本月：start = (N-1) 个月前的月初。
            # **必须先归一到月初再逐月回退**：直接拿"当前时刻"回退，在 3/31、5/31、
            # 7/31 这类日子会 ValueError（2/4/6 月没有 31 号）—— 2026-10-16 实测到的
            # 月末崩溃（handler 会兜成 tool_error，但"前几个月"每年有几天是坏的）。
            # 月初一定在每个月的存在，回退才安全；结果与"先回退再取月初"等价。
            cursor = _start_of_month(_dt.datetime.now())
            for _ in range(recent_months - 1):
                cursor = _subtract_one_month(cursor)
            start = cursor
        else:
            computer = _BOUNDARY_COMPUTERS.get(time_range)
            if computer is None:
                # 未知枚举 → 当 "all" 处理（与旧实现的"else: start = None"行为一致，
                # fail-safe：宁可返回更多结果，也不要因 schema 漂移抛 KeyError）
                computer = _BOUNDARY_COMPUTERS["all"]
            start = computer(_dt.datetime.now())

        # "不含现在"的枚举（yesterday / last_*）：有 end 上界（开区间右端）
        end_computer = _BOUNDARY_END_COMPUTERS.get(time_range)
        end = end_computer(_dt.datetime.now()) if end_computer else None

        if start is None and end is None:
            # DESC + LIMIT 才是"最近 N 条"；ASC 会返回公司最早的 N 条（审计 P1）。
            clauses = ["company_id = ?"]
            params = [company_id]
            if customer_id is not None:
                clauses.append("customer_id = ?")
                params.append(customer_id)
            elif unattributed_only:
                clauses.append("customer_id IS NULL")
            params.append(limit)
            rows = conn.execute(
                "SELECT id, company_id, customer_id, library_id, query, response, "
                "files_read, created_at "
                f"FROM conversations WHERE {' AND '.join(clauses)} "
                "ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        else:
            # start / end 都不空 → start <= created_at < end；任一为空 → 该侧不限制
            clauses = ["company_id = ?"]
            params: list = [company_id]
            if customer_id is not None:
                clauses.append("customer_id = ?")
                params.append(customer_id)
            elif unattributed_only:
                clauses.append("customer_id IS NULL")
            if start is not None:
                clauses.append("created_at >= ?")
                params.append(start.strftime("%Y-%m-%d %H:%M:%S"))
            if end is not None:
                clauses.append("created_at < ?")
                params.append(end.strftime("%Y-%m-%d %H:%M:%S"))
            params.append(limit)
            rows = conn.execute(
                f"SELECT id, company_id, customer_id, library_id, query, response, "
                f"files_read, created_at "
                f"FROM conversations WHERE {' AND '.join(clauses)} "
                f"ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()

        # 对外仍按时间正序返回（调用方逐个拼进上下文），但取的是最近 N 条
        return [_row_to_dict(r) for r in reversed(rows)]
    finally:
        conn.close()


def _row_to_dict(row) -> dict:
    """将 SQLite 行对象转换为字典，同时将 files_read JSON 字段反序列化。"""
    result = {
        "id": row["id"],
        "company_id": row["company_id"],
        "customer_id": row["customer_id"] if "customer_id" in row.keys() else None,
        "library_id": row["library_id"],
        "query": row["query"],
        "response": row["response"],
        "files_read": json.loads(row["files_read"]) if row["files_read"] else [],
        "created_at": row["created_at"],
        "context": row["context"] if "context" in row.keys() else "",
    }
    # 安全解析 extra 列 — 仅当列存在于结果集中时才处理（get_recent 等函数不 SELECT 这些列）
    _row_keys = row.keys()
    for col in ("extra1", "extra2", "extra3"):
        if col not in _row_keys:
            continue
        try:
            raw = row[col] if row[col] else "{}"
            result[col] = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (json.JSONDecodeError, TypeError, KeyError, IndexError):
            result[col] = {}
    return result


# ── CLI 冒烟测试 ───────────────────────────────────────────────────────

if __name__ == "__main__":
    from trade.database import init_db

    init_db()

    conv = save(
        company_id=1,
        library_id=None,
        query="去年营收怎么样？",
        response="根据2024年度销售额数据...",
        files_read=[{"file": "2024_report.xlsx", "pages": [1, 2]}],
    )
    print("Saved:", json.dumps(conv, indent=2, ensure_ascii=False))

    recent = list_by_company(1, 5)
    print(f"\nRecent for company 1 ({len(recent)}):")
    for c in recent:
        print(f"  [{c['id']}] {c['query'][:40]}...")

    delete(1, conv["id"])
    print("\nCleaned up test conversation.")
