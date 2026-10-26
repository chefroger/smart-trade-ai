"""
订单管理 — 轻量订单 CRUD + 上下文搜索。

上下文检索只走两层（均有客户前提）：
  1. 精确匹配（联系人 + 品名）
  2. 联系人聚合（同一联系人的所有订单）

未指定/匹配不到客户时绝不回退公司级 —— 否则会把别家客户的价格写进
开发信或 OSINT 上下文（审计 P1-1）。
"""

from __future__ import annotations

import re

from trade.database import get_connection

ORDER_STATUSES = ("报价中", "已下单", "已出货", "已完成", "已取消")

# 状态机：只允许沿业务链前进；取消只能在发货前；已完成 / 已取消为终态。
# 目的：防止「已取消 → 已出货」把订单重新塞回跟进流，或「已完成 → 报价中」造成重复报价。
_ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "报价中": {"已下单", "已取消"},
    "已下单": {"已出货", "已取消"},
    "已出货": {"已完成"},
    "已完成": set(),
    "已取消": set(),
}

# 金额一致性容差：金额按分（0.01）比较，只吸收浮点噪声，不放宽到百分比。
_AMOUNT_TOLERANCE = 0.01


def can_transition_status(old: str, new: str) -> bool:
    """订单状态能否从 old 变到 new（同一状态视为无变化，允许）。

    当前状态为空或不在五值之内（历史脏数据）时不拦，避免用户无法修正旧记录。
    """
    if old == new:
        return True
    allowed = _ALLOWED_STATUS_TRANSITIONS.get(old or "")
    if allowed is None:
        return True
    return new in allowed


def reconcile_amounts(
    quantity, unit_price, total_amount,
) -> tuple[float, float, float]:
    """校验「数量 × 单价」与总金额一致，返回三元组 (quantity, unit_price, total)。

    - 总金额为空（0 / None）而数量与单价都有值时，自动算出总金额（保留 2 位）；
    - 三者都有值时做一致性校验，矛盾则抛 ValueError（文案直接展示给用户）。

    数量或单价缺任一项时无法校验（例如只录了报价总额），原样放行。
    """
    qty = float(quantity or 0)
    price = float(unit_price or 0)
    total = float(total_amount or 0)

    expected = qty * price
    if expected > 0 and total <= 0:
        return qty, price, round(expected, 2)
    if expected > 0 and total > 0 and abs(expected - total) > _AMOUNT_TOLERANCE:
        raise ValueError(
            f"总金额 {total:g} 与 数量×单价（{qty:g}×{price:g}={expected:g}）不一致，请核对后重填。"
        )
    return qty, price, total


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
        # BEGIN IMMEDIATE（直接拿写锁）—— 与 customer.update 同一理由：
        # deferred BEGIN 只开读快照，之后升级成写锁时若期间有别的连接提交过，
        # SQLite 抛 SQLITE_BUSY_SNAPSHOT 且**不重试**（busy_timeout 不生效），
        # 并发下必然 "database is locked"（2026-10-21 实测）。
        conn.execute("BEGIN IMMEDIATE")
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


# 只有问句里出现"订单/报价/交期"这类意图时才注入订单。
# 以前 Layer 3 无条件注入最近 20 笔 —— 写开发信、OSINT、闲聊都会带上
# 别家客户的价格（2026-10-23 审计 P0）。
_ORDER_INTENT_RE = re.compile(
    r"订单|报价|交期|发货|下单|采购|价格|单价|金额|那批|这批|上次|po\b|"
    r"order|quote|quotation|delivery|price",
    re.IGNORECASE,
)


def search_orders(
    company_id: int, query: str, customer_id: int | None = None
) -> str | None:
    """搜索与用户 query 相关的订单，返回注入上下文的文本块。

    2 层优先级：
      1. 联系人 + 品名精确匹配
      2. 联系人聚合

    给了 customer_id 时只查该客户；未给时也只按联系人匹配，**绝不回退公司级** ——
    宁可没有订单上下文，也不把别家客户的成交价带进当前回答。

    Returns:
        订单上下文字符串，或 None（无匹配/无订单意图时）。
    """
    from trade import customer as _cust

    if not _ORDER_INTENT_RE.search(query or ""):
        return None

    # 从 query 提取可能的产品名关键词（取 2-5 字的连续片段作为候选）
    words = query.replace("的", " ").replace("订单", " ").replace("报价", " ").split()
    candidates = [w for w in words if len(w) >= 2]

    # 指定客户：只查这个客户的订单
    if customer_id is not None:
        cust = _cust.get(customer_id, company_id=company_id)
        if not cust:
            return None
        for kw in candidates:
            rows = _search_by_customer_and_product(customer_id, kw, limit=5)
            if rows:
                return _format_order_context(rows, cust, kw)
        rows = _search_by_customer(customer_id, limit=5)
        return _format_order_context(rows, cust) if rows else None

    # 未指定客户：只按联系人匹配。**不再回退公司级** —— 回退等于把别家
    # 客户的成交价塞进当前回答（2026-10-25 审计 P1-1）。
    all_customers = _cust.list_by_company(company_id)
    for cust in all_customers:
        if not _contact_mentioned(cust.get("contact", ""), query):
            continue
        for kw in candidates:
            rows = _search_by_customer_and_product(cust["id"], kw, limit=5)
            if rows:
                return _format_order_context(rows, cust, kw)

    # Layer 2: 按联系人聚合
    for cust in all_customers:
        if not _contact_mentioned(cust.get("contact", ""), query):
            continue
        rows = _search_by_customer(cust["id"], limit=10)
        if rows:
            return _format_order_context(rows, cust)

    return None


def _contact_mentioned(contact: str, query: str) -> bool:
    """联系人是否被问句提到。

    长度 <2 的直接忽略（联系人填 "张"/"Li" 会命中几乎所有句子）；
    拉丁名要求词边界（"Li" 不能命中 "list"）。
    """
    contact = (contact or "").strip()
    if len(contact) < 2:
        return False
    if re.fullmatch(r"[A-Za-z0-9 ._\-]+", contact):
        return re.search(
            rf"(?<![A-Za-z0-9]){re.escape(contact)}(?![A-Za-z0-9])",
            query,
            re.IGNORECASE,
        ) is not None
    return contact in query


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
