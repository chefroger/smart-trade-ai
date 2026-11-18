"""询盘实体 CRUD + 客户阶段自动推导（N4 B 方案）。"""

from __future__ import annotations

from datetime import datetime

from trade.customer import _normalize_crm_stage
from trade.database import get_connection

STAGE_ORDER = {"询盘": 0, "报价": 1, "样品": 2, "订单": 3}
STAGE_AUTO = "自动"


def table_available() -> bool:
    """inquiries 表是否存在。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='inquiries'"
        ).fetchone()
        return row is not None
    except Exception:
        return False
    finally:
        conn.close()


def _now() -> str:
    """本地时间戳字符串。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row(row) -> dict:
    """sqlite row → dict。"""
    return {k: row[k] for k in row.keys()}


def max_inquiry_stage(conn, customer_id: int, company_id: int) -> str | None:
    """该客户名下询盘 stage 的最大值；无询盘返回 None。"""
    if "inquiries" not in {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }:
        return None
    rows = conn.execute(
        "SELECT stage FROM inquiries WHERE customer_id=? AND company_id=?",
        (customer_id, company_id),
    ).fetchall()
    if not rows:
        return None
    best = "询盘"
    best_ord = -1
    for r in rows:
        st = _normalize_crm_stage(r["stage"])
        ord_ = STAGE_ORDER.get(st, 0)
        if ord_ > best_ord:
            best_ord = ord_
            best = st
    return best


def recompute_customer_stage(conn, customer_id: int, company_id: int) -> str:
    """写时维护：override 为空时按询盘重算 customers.stage。

    有 override 时不动 stage 列，返回有效阶段。
    调用方须已在事务内。
    """
    row = conn.execute(
        "SELECT stage, stage_override FROM customers WHERE id=? AND company_id=?",
        (customer_id, company_id),
    ).fetchone()
    if not row:
        return "询盘"
    keys = row.keys()
    override = None
    if "stage_override" in keys:
        override = row["stage_override"]
    if override is not None and str(override).strip() != "":
        return _normalize_crm_stage(override)

    derived = max_inquiry_stage(conn, customer_id, company_id)
    # 无询盘：保留/回落默认「询盘」
    new_stage = derived if derived is not None else "询盘"
    conn.execute(
        "UPDATE customers SET stage=?, updated_at=? WHERE id=? AND company_id=?",
        (new_stage, _now(), customer_id, company_id),
    )
    return new_stage


def effective_stage_fields(row) -> dict:
    """从 customers 行算出 stage / stage_auto / stage_override。"""
    keys = row.keys()
    raw_stage = row["stage"] if "stage" in keys and row["stage"] is not None else "询盘"
    override = None
    if "stage_override" in keys and row["stage_override"] is not None:
        ov = str(row["stage_override"]).strip()
        override = ov if ov else None
    if override:
        return {
            "stage": _normalize_crm_stage(override),
            "stage_auto": False,
            "stage_override": _normalize_crm_stage(override),
        }
    return {
        "stage": _normalize_crm_stage(raw_stage),
        "stage_auto": True,
        "stage_override": None,
    }


def list_for_customer(customer_id: int, *, company_id: int) -> list[dict]:
    """列出客户询盘（updated_at 倒序）。客户跨公司 → 空并让路由 404。"""
    conn = get_connection()
    try:
        cust = conn.execute(
            "SELECT id FROM customers WHERE id=? AND company_id=?",
            (customer_id, company_id),
        ).fetchone()
        if not cust:
            return None  # type: ignore[return-value]
        if not table_available():
            return []
        rows = conn.execute(
            "SELECT * FROM inquiries WHERE customer_id=? AND company_id=? "
            "ORDER BY updated_at DESC, id DESC",
            (customer_id, company_id),
        ).fetchall()
        return [_row(r) for r in rows]
    finally:
        conn.close()


def create(
    customer_id: int,
    *,
    company_id: int,
    title: str = "",
    stage: str = "询盘",
) -> dict:
    """手工新建询盘，并按需重算客户阶段。"""
    title = (title or "").strip()
    stage = _normalize_crm_stage(stage)
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cust = conn.execute(
            "SELECT id FROM customers WHERE id=? AND company_id=?",
            (customer_id, company_id),
        ).fetchone()
        if not cust:
            conn.rollback()
            return None  # type: ignore[return-value]
        now = _now()
        cur = conn.execute(
            "INSERT INTO inquiries (company_id, customer_id, title, stage, source, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (company_id, customer_id, title, stage, "manual", now, now),
        )
        new_id = cur.lastrowid
        eff = recompute_customer_stage(conn, customer_id, company_id)
        conn.commit()
        row = conn.execute("SELECT * FROM inquiries WHERE id=?", (new_id,)).fetchone()
        out = _row(row)
        out["customer_stage"] = eff
        return out
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get(inquiry_id: int, *, company_id: int) -> dict | None:
    """按公司取询盘。"""
    if not table_available():
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM inquiries WHERE id=? AND company_id=?",
            (inquiry_id, company_id),
        ).fetchone()
        return _row(row) if row else None
    finally:
        conn.close()


def update(
    inquiry_id: int,
    *,
    company_id: int,
    title: str | None = None,
    stage: str | None = None,
) -> dict | None:
    """改 title/stage；改 stage 后重算。"""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM inquiries WHERE id=? AND company_id=?",
            (inquiry_id, company_id),
        ).fetchone()
        if not row:
            conn.rollback()
            return None
        new_title = row["title"] if title is None else (title or "").strip()
        new_stage = row["stage"] if stage is None else _normalize_crm_stage(stage)
        conn.execute(
            "UPDATE inquiries SET title=?, stage=?, updated_at=? WHERE id=? AND company_id=?",
            (new_title, new_stage, _now(), inquiry_id, company_id),
        )
        eff = recompute_customer_stage(conn, int(row["customer_id"]), company_id)
        conn.commit()
        out = get(inquiry_id, company_id=company_id)
        if out:
            out["customer_stage"] = eff
        return out
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete(inquiry_id: int, *, company_id: int) -> bool:
    """删除询盘并重算；不存在返回 True（幂等 ok）。"""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT customer_id FROM inquiries WHERE id=? AND company_id=?",
            (inquiry_id, company_id),
        ).fetchone()
        if not row:
            conn.commit()
            return True
        cid = int(row["customer_id"])
        conn.execute(
            "DELETE FROM inquiries WHERE id=? AND company_id=?",
            (inquiry_id, company_id),
        )
        recompute_customer_stage(conn, cid, company_id)
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_for_customer(conn, customer_id: int, company_id: int) -> None:
    """删客户时双保险清询盘（同事务）。"""
    try:
        conn.execute(
            "DELETE FROM inquiries WHERE customer_id=? AND company_id=?",
            (customer_id, company_id),
        )
    except Exception:
        # 缺表静默
        pass


def set_stage_override(
    customer_id: int,
    *,
    company_id: int,
    stage: str,
) -> dict | None:
    """PUT stage 新语义：四值设 override；「自动」清 override 并重算。"""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM customers WHERE id=? AND company_id=?",
            (customer_id, company_id),
        ).fetchone()
        if not row:
            conn.rollback()
            return None
        s = (stage or "").strip()
        if s == STAGE_AUTO:
            conn.execute(
                "UPDATE customers SET stage_override=NULL, updated_at=? "
                "WHERE id=? AND company_id=?",
                (_now(), customer_id, company_id),
            )
            recompute_customer_stage(conn, customer_id, company_id)
        else:
            norm = _normalize_crm_stage(s)
            conn.execute(
                "UPDATE customers SET stage_override=?, stage=?, updated_at=? "
                "WHERE id=? AND company_id=?",
                (norm, norm, _now(), customer_id, company_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    from trade.customer import get as get_customer
    return get_customer(customer_id, company_id=company_id)
