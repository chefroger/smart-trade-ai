"""用户待办（P2-12）：公司内独立清单。

与定时任务（cron）完全无关：cron 是自动执行的任务，todo 是用户手记的待办。
"""

from __future__ import annotations

import re
from datetime import date, datetime

from trade.database import get_connection

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TITLE_MAX = 200

# 列表查询共用的投影：LEFT JOIN 客户，客户被删 / 属于别家时名称取空串
_SELECT_SQL = (
    "SELECT t.id, t.title, t.due_date, t.customer_id, "
    "COALESCE(c.name, '') AS customer_name, t.done, t.done_at, "
    "t.source, t.created_at "
    "FROM todos t "
    "LEFT JOIN customers c ON c.id = t.customer_id AND c.company_id = t.company_id "
)


class TodoError(Exception):
    """待办写入被拒（标题为空 / 日期格式错 / 客户不属于本公司）。"""


def _as_bool(value) -> bool:
    """把前端可能传来的字符串布尔解析成真正的 bool。

    JSON 里本该是布尔，但历史/第三方调用可能传 "false" / "0" 之类的字符串；
    Python 的真值判断会把非空字符串（包括 "false"）一律当 True，导致
    「取消完成」反而被标记完成。这里显式白名单化。
    """
    # 布尔原样返回，避免无谓的字符串比较
    if isinstance(value, bool):
        return value
    # 字符串先归一化（去空白 + 小写）再匹配白名单
    if isinstance(value, str):
        text = value.strip().lower()
        # 常见「真」写法
        if text in {"true", "1", "yes"}:
            return True
        # 常见「假」写法（含空串）
        if text in {"false", "0", "no", ""}:
            return False
    # 其余值（数字、None、其它字符串）按 Python 真值处理
    return bool(value)


def _validate_title(title) -> str:
    """校验并规范化标题：去首尾空白、必须非空且不超过 200 字。"""
    text = str(title or "").strip()
    # 空白标题没有意义，也避免列表里出现不可见条目
    if not text:
        raise TodoError("标题不能为空")
    # 超长标题会撑坏右栏布局，直接拒绝而不是悄悄截断
    if len(text) > _TITLE_MAX:
        raise TodoError(f"标题不能超过 {_TITLE_MAX} 字")
    return text


def _validate_due_date(value) -> str:
    """校验截止日：只接受空串或合法的 YYYY-MM-DD。"""
    # None 与非空字符串以外都按「无期限」处理（前端可能传 None/""）
    if value is None:
        return ""
    text = str(value).strip()
    # 空串 = 无期限（分组时归入「今天」）
    if not text:
        return ""
    # 先卡格式，避免 strptime 接受 2026-1-1 这类非零填充写法
    if not _DATE_RE.match(text):
        raise TodoError("截止日期格式应为 YYYY-MM-DD")
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        # 格式对但日历上不存在（如 2026-02-30）
        raise TodoError("截止日期不是有效日期")
    return text


def _coerce_customer_id(conn, value, company_id: int) -> int | None:
    """规范化 customer_id 并校验归属；空值表示不关联客户。"""
    # 空 id 是合法用法（不关联客户的待办），直接放行
    if value in (None, ""):
        return None
    try:
        cid = int(value)
    except (TypeError, ValueError):
        # 非数字的客户 id 属于客户端错误，转成业务异常返回 400
        raise TodoError("客户 ID 无效")
    row = conn.execute(
        "SELECT 1 FROM customers WHERE id = ? AND company_id = ?",
        (cid, company_id),
    ).fetchone()
    # 查不到 = 不存在或属于别家，一律拒绝，避免挂到别家客户身上
    if not row:
        raise TodoError("客户不属于本公司")
    return cid


def _fetch_todo(conn, todo_id: int, company_id: int) -> dict | None:
    """按 id + 公司读取单条待办（含客户名称）。"""
    row = conn.execute(
        _SELECT_SQL + "WHERE t.id = ? AND t.company_id = ?",
        (todo_id, company_id),
    ).fetchone()
    # 不存在或属于别家公司时返回 None，由上层决定 404
    return dict(row) if row else None


def list_todos(company_id: int, *, today: str | None = None) -> dict:
    """按「逾期 / 今天 / 将来 / 已完成」四组列出本公司待办。

    参数 today 供测试注入固定日期；不传则用本机今天。
    """
    # 未显式指定日期时取本机当天，保证与 done_at / 截止日的本地时间口径一致
    if today is None:
        today = date.today().isoformat()

    conn = get_connection()
    try:
        # 逾期：未完成、有截止日、且早于今天
        overdue = conn.execute(
            _SELECT_SQL
            + "WHERE t.company_id = ? AND t.done = 0 AND t.due_date <> '' "
            "AND t.due_date < ? "
            "ORDER BY t.due_date ASC, t.id ASC",
            (company_id, today),
        ).fetchall()
        # 今天：未完成，且截止日就是今天或未设截止日
        today_rows = conn.execute(
            _SELECT_SQL
            + "WHERE t.company_id = ? AND t.done = 0 "
            "AND (t.due_date = ? OR t.due_date = '') "
        "ORDER BY t.created_at ASC, t.id ASC",
            (company_id, today),
        ).fetchall()
        # 将来：未完成、有截止日、且晚于今天（避免未来待办从右栏消失）
        upcoming = conn.execute(
            _SELECT_SQL
            + "WHERE t.company_id = ? AND t.done = 0 AND t.due_date <> '' "
            "AND t.due_date > ? "
            "ORDER BY t.due_date ASC, t.id ASC",
            (company_id, today),
        ).fetchall()
        # 已完成：只列**今天完成**的，按完成时间倒序
        done_rows = conn.execute(
            _SELECT_SQL
            + "WHERE t.company_id = ? AND t.done = 1 AND date(t.done_at) = ? "
            "ORDER BY t.done_at DESC, t.id DESC",
            (company_id, today),
        ).fetchall()
    finally:
        conn.close()

    overdue_list = [dict(r) for r in overdue]
    today_list = [dict(r) for r in today_rows]
    upcoming_list = [dict(r) for r in upcoming]
    done_list = [dict(r) for r in done_rows]
    return {
        "today": today,
        "overdue": overdue_list,
        "today_items": today_list,
        "upcoming": upcoming_list,
        "done": done_list,
        "counts": {
            "overdue": len(overdue_list),
            "today": len(today_list),
            "upcoming": len(upcoming_list),
            "done": len(done_list),
        },
    }


def create_todo(
    company_id: int,
    *,
    title,
    due_date="",
    customer_id=None,
    source="manual",
) -> dict:
    """新建待办并返回完整条目；非法输入抛 TodoError。"""
    clean_title = _validate_title(title)
    clean_due = _validate_due_date(due_date)

    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        clean_customer = _coerce_customer_id(conn, customer_id, company_id)
        cur = conn.execute(
            "INSERT INTO todos (company_id, title, due_date, customer_id, source) "
            "VALUES (?, ?, ?, ?, ?)",
            (company_id, clean_title, clean_due, clean_customer, str(source or "manual")),
        )
        new_id = int(cur.lastrowid)
        conn.commit()
        return _fetch_todo(conn, new_id, company_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_todo(todo_id: int, *, company_id: int, **fields) -> dict | None:
    """部分更新待办（title / due_date / done / customer_id）；不存在返回 None。

    done=True 时写入完成时间，done=False 时清空完成时间。
    """
    allowed = {"title", "due_date", "done", "customer_id"}
    updates = {k: v for k, v in fields.items() if k in allowed}

    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        # 没有任何可更新字段：原样返回当前行（或 None），不产生无意义的 UPDATE
        if not updates:
            conn.commit()
            return _fetch_todo(conn, todo_id, company_id)

        assignments = []
        params: list = []
        # 标题走统一校验，避免空标题把列表项变成空白
        if "title" in updates:
            assignments.append("title = ?")
            params.append(_validate_title(updates["title"]))
        # 截止日走统一校验，非法格式直接拒绝
        if "due_date" in updates:
            assignments.append("due_date = ?")
            params.append(_validate_due_date(updates["due_date"]))
        # 客户改挂同样校验归属，不能挪到别家客户身上
        if "customer_id" in updates:
            assignments.append("customer_id = ?")
            params.append(_coerce_customer_id(conn, updates["customer_id"], company_id))
        # 完成状态与完成时间一起维护：完成写 now，取消完成清空
        if "done" in updates:
            # 统一解析字符串布尔，避免 "false" 被 Python 真值当成已完成
            flag = 1 if _as_bool(updates["done"]) else 0
            assignments.append(
                "done = ?, done_at = CASE WHEN ? = 1 "
                "THEN datetime('now','localtime') ELSE NULL END"
            )
            params.extend([flag, flag])

        assignments.append("updated_at = datetime('now','localtime')")
        cur = conn.execute(
            f"UPDATE todos SET {', '.join(assignments)} "
            "WHERE id = ? AND company_id = ?",
            (*params, todo_id, company_id),
        )
        conn.commit()
        # 目标不存在或属于别家公司：rowcount 为 0，交由 API 层转 404
        if cur.rowcount == 0:
            return None
        return _fetch_todo(conn, todo_id, company_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_todo(todo_id: int, *, company_id: int) -> bool:
    """按 id + 公司删除待办，返回是否真的删到了行。"""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "DELETE FROM todos WHERE id = ? AND company_id = ?",
            (todo_id, company_id),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
