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
) -> dict:
    """保存一条对话记录，作用域限定到指定公司。返回新插入的行，以字典形式呈现。

    skill 参数记录本次查询匹配到的技能名（存入 extra3），供质量统计按技能聚合评分。
    """
    if company_id is None:
        raise ValueError("company_id is required for conversation isolation")
    conn = get_connection()
    try:
        # extra3 记录匹配到的 skill（空则不写，保持旧行为兼容）
        extra3 = json.dumps({"skill": skill}, ensure_ascii=False) if skill else "{}"
        cur = conn.execute(
            "INSERT INTO conversations (company_id, library_id, query, response, files_read, context, extra3) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                company_id,
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
            "id": new_id, "company_id": company_id,
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
    retain_to_memory: bool = True,
    context: str = "",
    skill: str = "",
) -> dict:
    """保存一条对话记录到 SQLite，并可选择同步到 Hindsight 长期记忆。

    这是 B2B 对话日志记录推荐使用的入口函数。
    skill 记录本次匹配到的技能名，供质量统计（get_quality_stats）按技能聚合评分。
    """
    result = save(company_id, query, response, library_id, files_read, context=context, skill=skill)

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


def get_recent(company_id: int, limit: int = 20) -> list[dict]:
    """获取最近的 N 条对话记录，用于上下文注入。

    返回字典列表，包含键：id, query, response, created_at。
    数据库查询按最新在前排序，返回时反转以确保上下文按时间正序排列。
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, company_id, library_id, query, response, files_read, created_at "
            "FROM conversations WHERE company_id = ? AND query IS NOT NULL "
            "ORDER BY id DESC LIMIT ?",
            (company_id, limit),
        ).fetchall()
        # 反转排序，使得最早的在最前，适合作为对话上下文输入给 LLM
        return [_row_to_dict(r) for r in reversed(rows)]
    finally:
        conn.close()


def search_history(
    company_id: int,
    time_range: str = "all",
    limit: int = 20,
) -> list[dict]:
    """按时间范围查询历史对话记录（供 LLM 工具调用使用）。

    Args:
        company_id: 作用域，限定到公司
        time_range: "today" | "this_week" | "this_month" | "all"
        limit: 最大返回行数

    Returns:
        字典列表，包含 id, query, response, created_at。
    """
    conn = get_connection()
    try:
        import datetime as _dt
        now = _dt.datetime.now()
        if time_range == "today":
            # 当天的 00:00:00 作为起始时间
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif time_range == "this_week":
            # 本周一 00:00:00 作为起始时间（周一 = weekday=0）
            start = now - _dt.timedelta(days=now.weekday())
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        elif time_range == "this_month":
            # 本月 1 号的 00:00:00 作为起始时间
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:  # "all"
            # 查询全部历史，不设时间过滤
            start = None

        if start:
            # 有时间范围限制，添加 created_at >= start 的过滤条件
            start_str = start.strftime("%Y-%m-%d %H:%M:%S")
            rows = conn.execute(
                "SELECT id, company_id, library_id, query, response, files_read, created_at "
                "FROM conversations WHERE company_id = ? AND created_at >= ? "
                "ORDER BY id ASC LIMIT ?",
                (company_id, start_str, limit),
            ).fetchall()
        else:
            # 无时间范围限制，查询该公司的所有历史记录
            rows = conn.execute(
                "SELECT id, company_id, library_id, query, response, files_read, created_at "
                "FROM conversations WHERE company_id = ? "
                "ORDER BY id ASC LIMIT ?",
                (company_id, limit),
            ).fetchall()

        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def _row_to_dict(row) -> dict:
    """将 SQLite 行对象转换为字典，同时将 files_read JSON 字段反序列化。"""
    result = {
        "id": row["id"],
        "company_id": row["company_id"],
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
