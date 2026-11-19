"""验厂计划（s5–s7）：一份来访计划 = 元信息 + payload(JSON)。

所有明细字段（行程/日程/人员/清单/风险…）放在 payload，避免每加一个字段就
migration；列表/打印/长图共用同一条记录。
"""

from __future__ import annotations

import json
from typing import Any

from trade.database import get_connection


def _row_to_dict(row) -> dict:
    d = dict(row)
    try:
        payload = json.loads(d.get("payload") or "{}")
    except (TypeError, ValueError):
        payload = {}
    d["payload"] = payload if isinstance(payload, dict) else {}
    return d


def list_plans(company_id: int) -> list[dict]:
    """按公司列出验厂计划（最近更新在前）。"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM visit_plans WHERE company_id = ? AND status <> 'deleted' "
            "ORDER BY updated_at DESC, id DESC",
            (company_id,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception:
        # 升级未重启时表可能还不存在：降级为空列表，不阻断页面
        return []
    finally:
        conn.close()


def get_plan(plan_id: int, *, company_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM visit_plans WHERE id = ? AND company_id = ? AND status <> 'deleted'",
            (plan_id, company_id),
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def create_plan(
    company_id: int,
    *,
    customer_id: int | None = None,
    title: str = "",
    visit_date: str = "",
    days: Any = 1,
    location: str = "",
    payload: dict | None = None,
) -> int:
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "INSERT INTO visit_plans "
            "(company_id, customer_id, title, visit_date, days, location, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                company_id,
                customer_id,
                str(title or ""),
                str(visit_date or ""),
                int(days or 1),
                str(location or ""),
                json.dumps(payload or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_plan(plan_id: int, *, company_id: int, **fields) -> dict | None:
    """部分更新；payload 传 dict 时整体替换。"""
    allowed = {"customer_id", "title", "visit_date", "days", "location", "payload", "status"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_plan(plan_id, company_id=company_id)
    if "payload" in updates:
        updates["payload"] = json.dumps(updates["payload"] or {}, ensure_ascii=False)
    if "days" in updates:
        updates["days"] = int(updates["days"] or 1)
    cols = ", ".join(f"{k} = ?" for k in updates)
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            f"UPDATE visit_plans SET {cols}, updated_at = datetime('now','localtime') "
            "WHERE id = ? AND company_id = ?",
            (*updates.values(), plan_id, company_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_plan(plan_id, company_id=company_id)


def delete_plan(plan_id: int, *, company_id: int) -> bool:
    """软删除，保留审计痕迹。"""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "UPDATE visit_plans SET status = 'deleted', updated_at = datetime('now','localtime') "
            "WHERE id = ? AND company_id = ?",
            (plan_id, company_id),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
