"""
订单管理 — 轻量订单 CRUD + 上下文搜索。

支持 3 层优先级查询：
  1. 精确匹配（联系人 + 品名）
  2. 联系人聚合（同一联系人的所有订单）
  3. 公司聚合（同一公司的所有订单）
"""

from __future__ import annotations

from trade.database import get_connection


def _customer_in_company(conn, customer_id: int, company_id: int) -> bool:
    """校验客户是否属于指定公司。"""
    row = conn.execute(
        "SELECT 1 FROM customers WHERE id = ? AND company_id = ?",
        (customer_id, company_id),
    ).fetchone()
    return row is not None


def create(
    company_id: int,
    customer_id: int,
    product_name: str,
    *,
    order_no: str = "",
    quantity: float = 0,
    unit: str = "",
    unit_price: float = 0,
    currency: str = "USD",
    total_amount: float = 0,
    status: str = "报价中",
    delivery_date: str = "",
    payment_terms: str = "",
    notes: str = "",
) -> dict:
    """创建一条订单记录。校验 customer 必须属于指定公司。"""
    conn = get_connection()
    try:
        if not _customer_in_company(conn, customer_id, company_id):
            raise ValueError(f"customer {customer_id} does not belong to company {company_id}")
        cur = conn.execute(
            "INSERT INTO orders (company_id, customer_id, order_no, product_name, "
            "quantity, unit, unit_price, currency, total_amount, status, "
            "delivery_date, payment_terms, notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (company_id, customer_id, order_no, product_name,
             quantity, unit, unit_price, currency, total_amount, status,
             delivery_date, payment_terms, notes),
        )
        conn.commit()
        return get(cur.lastrowid, company_id=company_id)
    finally:
        conn.close()


def list_by_customer(customer_id: int, *, company_id: int | None = None) -> list[dict]:
    """返回指定客户的所有订单，按创建时间倒序。

    提供 company_id 时增加租户隔离校验。
    """
    conn = get_connection()
    try:
        if company_id is not None:
            rows = conn.execute(
                "SELECT * FROM orders WHERE customer_id = ? AND company_id = ? "
                "ORDER BY created_at DESC",
                (customer_id, company_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM orders WHERE customer_id = ? ORDER BY created_at DESC",
                (customer_id,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def list_by_company(company_id: int, limit: int = 50) -> list[dict]:
    """返回指定公司的所有订单，按创建时间倒序。"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM orders WHERE company_id = ? ORDER BY created_at DESC LIMIT ?",
            (company_id, limit),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get(order_id: int, *, company_id: int | None = None) -> dict | None:
    """根据 ID 获取订单。指定 company_id 时进行多租户隔离检验。"""
    conn = get_connection()
    try:
        if company_id is not None:
            row = conn.execute(
                "SELECT * FROM orders WHERE id = ? AND company_id = ?",
                (order_id, company_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM orders WHERE id = ?", (order_id,)
            ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def update(order_id: int, *, company_id: int | None = None, **kwargs) -> dict | None:
    """部分更新订单字段。指定 company_id 时进行多租户隔离检验。

    如果传入了 customer_id，校验新 customer 必须属于同一公司。
    """
    allowed = {"order_no", "product_name", "quantity", "unit", "unit_price",
               "currency", "total_amount", "status", "delivery_date",
               "payment_terms", "notes", "customer_id"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return get(order_id, company_id=company_id)

    conn = get_connection()
    try:
        conn.execute("BEGIN")
        # 如果更新了 customer_id 且提供了 company_id，校验新客户归属
        if "customer_id" in updates and company_id is not None:
            if not _customer_in_company(conn, updates["customer_id"], company_id):
                conn.rollback()
                return None

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values())
        if company_id is not None:
            values.extend([order_id, company_id])
            sql = f"UPDATE orders SET {set_clause}, updated_at = datetime('now','localtime') WHERE id = ? AND company_id = ?"
        else:
            values.append(order_id)
            sql = f"UPDATE orders SET {set_clause}, updated_at = datetime('now','localtime') WHERE id = ?"
        n = conn.execute(sql, values).rowcount
        if n == 0:
            conn.rollback()
            return None
        conn.commit()
        return get(order_id, company_id=company_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete(order_id: int, *, company_id: int | None = None) -> bool:
    """删除订单。指定 company_id 时进行多租户隔离检验。"""
    conn = get_connection()
    try:
        if company_id is not None:
            cur = conn.execute(
                "DELETE FROM orders WHERE id = ? AND company_id = ?",
                (order_id, company_id),
            )
        else:
            cur = conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ── 订单-文档库关联 ───────────────────────────────────────────────────────────


def link_library(order_id: int, library_id: int, *, company_id: int | None = None) -> bool:
    """关联文档库到订单。指定 company_id 时校验订单和文档库都属于该公司。"""
    conn = get_connection()
    try:
        if company_id is not None:
            # 校验订单属于该公司
            order_ok = conn.execute(
                "SELECT 1 FROM orders WHERE id = ? AND company_id = ?",
                (order_id, company_id),
            ).fetchone()
            # 校验文档库也属于该公司
            lib_ok = conn.execute(
                "SELECT 1 FROM libraries WHERE id = ? AND company_id = ?",
                (library_id, company_id),
            ).fetchone()
            if not order_ok or not lib_ok:
                return False
        conn.execute(
            "INSERT OR IGNORE INTO order_libraries (order_id, library_id) VALUES (?,?)",
            (order_id, library_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def unlink_library(order_id: int, library_id: int, *, company_id: int | None = None) -> bool:
    """取消订单的文档库关联。指定 company_id 时先校验订单与库的归属。"""
    conn = get_connection()
    try:
        if company_id is not None:
            row = conn.execute(
                "SELECT 1 FROM orders WHERE id = ? AND company_id = ?",
                (order_id, company_id),
            ).fetchone()
            if not row:
                return False
            # 校验 library 也归属该公司，防止解绑他公司的库
            lib = conn.execute(
                "SELECT 1 FROM libraries WHERE id = ? AND company_id = ?",
                (library_id, company_id),
            ).fetchone()
            if not lib:
                return False
        cur = conn.execute(
            "DELETE FROM order_libraries WHERE order_id = ? AND library_id = ?",
            (order_id, library_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_libraries(order_id: int, company_id: int) -> list[dict]:
    """获取订单关联的文档库列表（按公司隔离）。

    通过 JOIN orders 校验 order 归属 company_id，防止跨租户拉取他公司订单的库列表。
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT l.* FROM libraries l "
            "JOIN order_libraries ol ON ol.library_id = l.id "
            "JOIN orders o ON o.id = ol.order_id "
            "WHERE ol.order_id = ? AND o.company_id = ?",
            (order_id, company_id),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── 上下文搜索 ────────────────────────────────────────────────────────────────


def search_orders(company_id: int, query: str) -> str | None:
    """搜索与用户 query 相关的订单，返回注入上下文的文本块。

    3 层优先级：
      1. 联系人 + 品名精确匹配
      2. 联系人聚合
      3. 公司聚合

    Returns:
        订单上下文字符串，或 None（无匹配订单时）。
    """
    from trade import customer as _cust

    # 从 query 提取可能的产品名关键词（取 2-5 字的连续片段作为候选）
    words = query.replace("的", " ").replace("订单", " ").replace("报价", " ").split()
    candidates = [w for w in words if len(w) >= 2]

    # Layer 1: 尝试按联系人 + 品名精确匹配
    all_customers = _cust.list_by_company(company_id)
    for cust in all_customers:
        contact = cust.get("contact", "")
        if contact and contact in query:
            for kw in candidates:
                rows = _search_by_customer_and_product(cust["id"], kw, limit=5)
                if rows:
                    return _format_order_context(rows, cust, kw)

    # Layer 2: 按联系人聚合
    for cust in all_customers:
        contact = cust.get("contact", "")
        if contact and contact in query:
            rows = _search_by_customer(cust["id"], limit=10)
            if rows:
                return _format_order_context(rows, cust)

    # Layer 3: 公司级聚合
    rows = _search_by_company(company_id, limit=20)
    if rows:
        return _format_order_context(rows)

    return None


def _search_by_customer_and_product(customer_id: int, product_kw: str, limit: int = 5) -> list[dict]:
    # 转义 LIKE 通配符，防止产品名中的 % 或 _ 匹配意外行
    safe_kw = product_kw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM orders WHERE customer_id = ? AND product_name LIKE ? ESCAPE '\\' "
            "ORDER BY created_at DESC LIMIT ?",
            (customer_id, f"%{safe_kw}%", limit),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def _search_by_customer(customer_id: int, limit: int = 10) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM orders WHERE customer_id = ? ORDER BY created_at DESC LIMIT ?",
            (customer_id, limit),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def _search_by_company(company_id: int, limit: int = 20) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM orders WHERE company_id = ? ORDER BY created_at DESC LIMIT ?",
            (company_id, limit),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def _format_order_context(rows: list[dict], cust: dict | None = None, product_kw: str = "") -> str | None:
    """将订单列表格式化为 LLM 可读的上下文文本。"""
    if not rows:
        return None

    lines = ["\n[订单上下文]"]
    if cust:
        lines.append(f"客户：{cust['name']}（联系人：{cust.get('contact','')}）")
    if product_kw:
        lines.append(f"匹配品名：{product_kw}")

    lines.append("")
    for o in rows:
        parts = [f"  [{o['status']}] {o['product_name']}"]
        if o.get("quantity"):
            parts.append(f"{o['quantity']}{o.get('unit','')}")
        if o.get("unit_price"):
            parts.append(f"单价 {o['unit_price']} {o.get('currency','USD')}")
        if o.get("total_amount"):
            parts.append(f"总金额 {o['total_amount']} {o.get('currency','USD')}")
        if o.get("order_no"):
            parts.append(f"订单号: {o['order_no']}")
        if o.get("delivery_date"):
            parts.append(f"交期: {o['delivery_date']}")
        if o.get("created_at"):
            parts.append(f"创建: {o['created_at'][:10]}")
        lines.append("  · ".join(parts))
    return "\n".join(lines)


# ── 内部工具 ──────────────────────────────────────────────────────────────────


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    return dict(row)
