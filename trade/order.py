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

# 允许显式清空（写 NULL）的字段。数值字段必须在内：单价"待谈"、总额未定
# 都是正常的报价阶段状态，清空即回到 NULL（Batch 1 的待谈口径），不能因为
# 不在这个集合里就被静默丢弃、把旧值留在库里。
CLEARABLE_FIELDS = frozenset({
    "order_no", "unit", "currency", "delivery_date", "payment_terms", "notes",
    "quantity", "unit_price", "total_amount",
})

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
) -> tuple[float | None, float | None, float]:
    """校验「数量 × 单价」与总金额一致，返回三元组 (quantity, unit_price, total)。

    业务口径（2026-10-28 定）：
    - 数量 > 0、单价 > 0：总额为空自动算出；总额非零则按容差校验。
    - 数量 > 0、单价为空/0、总额 > 0：**单价待谈**，放行，单价返回 None
      （按柜/整单报价、单价还没谈，是外贸常态）。
    - 数量为空、单价为空、总额 > 0：只录总额，放行，两个都返回 None。
    - 数量为空/0、单价 > 0、总额 > 0：拒绝（0 个单位不可能有总额）。
    - 数量与单价都为空/0（且非“都未填”）、总额 > 0：拒绝（无法校验）。
    """
    qty = None if quantity is None else float(quantity)
    price = None if unit_price is None else float(unit_price)
    total = None if total_amount is None else float(total_amount)
    q = qty or 0.0
    p = price or 0.0
    t = total or 0.0

    if q > 0 and p > 0:
        expected = q * p
        if t <= 0:
            return q, p, round(expected, 2)
        if abs(expected - t) > _AMOUNT_TOLERANCE:
            raise ValueError(
                f"总金额 {t:g} 与 数量×单价（{q:g}×{p:g}={expected:g}）不一致，请核对后重填。"
            )
        return q, p, t

    if q > 0 and p <= 0:
        # 单价待谈：显式 0 也视为待谈（0 元单价配非零总额本身矛盾）。
        # 总额原样返回 —— 未填就是 NULL，别把"没填"写成 0。
        return q, None, total

    if q <= 0 and p > 0:
        if t > 0:
            raise ValueError(
                f"数量为 0（或未填），但总金额为 {t:g}；"
                "0 个单位不可能有总额，请补全数量或清空总金额。"
            )
        return q, p, total

    # 数量与单价都不足以算出金额
    if t > 0:
        if qty is None and price is None:
            return None, None, t
        raise ValueError(
            f"数量与单价都为 0（或未填全），但总金额为 {t:g}，无法校验；"
            "请补全数量与单价，或把总金额留空。"
        )
    # 三者都为空/0：原样返回。None 保持 None（未填 ≠ 显式 0），
    # 否则全空订单会被存成 0，前端显示成"0"而不是"待谈"。
    return qty, price, total


def _customer_in_company(conn, customer_id: int, company_id: int) -> bool:
    """校验客户是否属于指定公司。"""
    row = conn.execute(
        "SELECT 1 FROM customers WHERE id = ? AND company_id = ?",
        (customer_id, company_id),
    ).fetchone()
    return row is not None


# ── 订单明细（一单多行商品）──────────────────────────────────────────────────


def _prepare_items(items, currency: str = "USD") -> list[dict]:
    """标准化明细行并逐行做金额校验（保留「单价待谈」语义）。

    行级规则与订单头一致：数量/单价/总额可为 NULL；任一行无法校验就整体拒绝，
    不落半张订单。
    """
    prepared: list[dict] = []
    for idx, raw in enumerate(items or []):
        if not isinstance(raw, dict):
            raise ValueError("订单明细格式不正确。")
        name = str(raw.get("product_name") or "").strip()
        if not name:
            raise ValueError(f"第 {idx + 1} 行商品缺少品名。")
        qty, price, total = reconcile_amounts(
            raw.get("quantity"), raw.get("unit_price"), raw.get("total_amount"),
        )
        prepared.append({
            "position": idx,
            "product_name": name,
            "quantity": qty,
            "unit": str(raw.get("unit") or ""),
            "unit_price": price,
            "currency": str(raw.get("currency") or currency or "USD"),
            "total_amount": total,
            "notes": str(raw.get("notes") or ""),
        })
    if not prepared:
        raise ValueError("订单至少需要一行商品。")
    return prepared


def _insert_items(conn, order_id: int, items: list[dict]) -> None:
    conn.executemany(
        "INSERT INTO order_items (order_id, position, product_name, quantity, unit, "
        "unit_price, currency, total_amount, notes) VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (order_id, it["position"], it["product_name"], it["quantity"],
             it["unit"], it["unit_price"], it["currency"],
             it["total_amount"], it["notes"])
            for it in items
        ],
    )


def _items_for(conn, order_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM order_items WHERE order_id = ? ORDER BY position, id",
        (order_id,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _attach_items(conn, orders: list[dict]) -> list[dict]:
    """批量挂上 items（一次查询，避免 N+1）。"""
    if not orders:
        return orders
    ids = [int(o["id"]) for o in orders]
    by_order: dict[int, list[dict]] = {oid: [] for oid in ids}
    placeholders = ",".join("?" for _ in ids)
    for row in conn.execute(
        f"SELECT * FROM order_items WHERE order_id IN ({placeholders}) "
        "ORDER BY order_id, position, id",
        ids,
    ).fetchall():
        by_order[int(row["order_id"])].append(_row_to_dict(row))
    for o in orders:
        o["items"] = by_order.get(int(o["id"]), [])
    return orders


def _sync_order_summary(conn, order_id: int) -> None:
    """把明细汇总回 orders 的摘要列（客户简报 / 搜索 / 列表 / 旧 UI 都读这里）。

    口径：
    - 单行：五列直接取该行。
    - 多行：品名取前 3 项拼接（超出加「等N项」）；数量仅在各行单位一致且都有数量
      时求和，否则 NULL/空（避免把「套」和「米」加在一起）；单价多行一律 NULL
      （行级单价才有意义）；总额**仅当所有行都有总额**时求和 —— 任一行待谈就
      留 NULL，绝不展示部分合计。
    """
    rows = conn.execute(
        "SELECT * FROM order_items WHERE order_id = ? ORDER BY position, id",
        (order_id,),
    ).fetchall()
    if not rows:
        return

    if len(rows) == 1:
        it = rows[0]
        summary = (
            it["product_name"], it["quantity"], it["unit"] or "",
            it["unit_price"], it["total_amount"],
        )
    else:
        names = [str(it["product_name"]) for it in rows[:3]]
        name = " / ".join(names)
        if len(rows) > 3:
            name += f" 等{len(rows)}项"
        units = {str(it["unit"] or "") for it in rows}
        quantities = [it["quantity"] for it in rows]
        if len(units) == 1 and all(q is not None for q in quantities):
            qty: float | None = sum(float(q) for q in quantities)
            unit = units.pop()
        else:
            qty, unit = None, ""
        totals = [it["total_amount"] for it in rows]
        total = (
            sum(float(t) for t in totals)
            if all(t is not None for t in totals) else None
        )
        summary = (name, qty, unit, None, total)

    conn.execute(
        "UPDATE orders SET product_name = ?, quantity = ?, unit = ?, "
        "unit_price = ?, total_amount = ?, "
        "updated_at = datetime('now','localtime') WHERE id = ?",
        (*summary, order_id),
    )


_ITEM_FLAT_FIELDS = ("product_name", "quantity", "unit", "unit_price", "total_amount")


def _apply_flat_fields_to_items(conn, order_id: int, existing, updates: dict) -> None:
    """兼容旧 UI 的平铺金额：把字段落到明细行，不让头/行两处各自为政。

    - 0 条明细（历史直插或迁移前数据）→ 用合并后的平铺值惰性补一行；
    - 恰好 1 条 → 平铺字段落到该行；
    - 多行 → 平铺字段与当前摘要一致就忽略（旧 UI 会全量 PUT），不一致直接拒绝，
      避免「改了一个头的金额」把多行明细的语义弄坏。
    """
    flat = {k: updates[k] for k in _ITEM_FLAT_FIELDS if k in updates}
    if not flat:
        return
    rows = conn.execute(
        "SELECT * FROM order_items WHERE order_id = ? ORDER BY position, id",
        (order_id,),
    ).fetchall()
    if len(rows) > 1:
        for key, value in flat.items():
            if not _amounts_equal(existing[key], value):
                raise ValueError(
                    "这是多商品订单，请按行修改明细，不要直接改订单头的合计字段。"
                )
        return
    if not rows:
        merged = {
            "product_name": flat.get("product_name", existing["product_name"]),
            "quantity": flat.get("quantity", existing["quantity"]),
            "unit": flat.get("unit", existing["unit"] or ""),
            "unit_price": flat.get("unit_price", existing["unit_price"]),
            "total_amount": flat.get("total_amount", existing["total_amount"]),
        }
        conn.execute(
            "INSERT INTO order_items (order_id, position, product_name, quantity, "
            "unit, unit_price, currency, total_amount) VALUES (?,?,?,?,?,?,?,?)",
            (order_id, 0, merged["product_name"], merged["quantity"], merged["unit"],
             merged["unit_price"], existing["currency"], merged["total_amount"]),
        )
        return
    set_clause = ", ".join(f"{k} = ?" for k in flat)
    conn.execute(
        f"UPDATE order_items SET {set_clause}, updated_at = datetime('now','localtime') "
        "WHERE order_id = ?",
        [*flat.values(), order_id],
    )


def _amounts_equal(a, b) -> bool:
    """0 与 NULL 视为等价（历史数据两种写法混用）。"""
    def _key(v):
        if v is None:
            return None
        try:
            number = float(v)
        except (TypeError, ValueError):
            return v
        return None if number == 0 else number

    ka, kb = _key(a), _key(b)
    if ka is None or kb is None:
        return ka is None and kb is None
    try:
        return abs(float(ka) - float(kb)) <= 1e-6
    except (TypeError, ValueError):
        return ka == kb


def create(
    company_id: int,
    customer_id: int,
    product_name: str = "",
    *,
    order_no: str = "",
    quantity: float | None = None,
    unit: str = "",
    unit_price: float | None = None,
    currency: str = "USD",
    total_amount: float | None = None,
    status: str = "报价中",
    delivery_date: str = "",
    payment_terms: str = "",
    notes: str = "",
    items: list[dict] | None = None,
) -> dict:
    """创建一条订单（订单头 + 明细行）。校验 customer 必须属于指定公司。

    `items` 缺省时用平铺字段构造一行，兼容旧调用方。
    """
    conn = get_connection()
    try:
        if not _customer_in_company(conn, customer_id, company_id):
            raise ValueError(f"customer {customer_id} does not belong to company {company_id}")
        if items is None:
            items = [{
                "product_name": product_name,
                "quantity": quantity,
                "unit": unit,
                "unit_price": unit_price,
                "total_amount": total_amount,
                "currency": currency,
            }]
        prepared = _prepare_items(items, currency)
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "INSERT INTO orders (company_id, customer_id, order_no, product_name, "
            "quantity, unit, unit_price, currency, total_amount, status, "
            "delivery_date, payment_terms, notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (company_id, customer_id, order_no, prepared[0]["product_name"],
             prepared[0]["quantity"], prepared[0]["unit"], prepared[0]["unit_price"],
             currency, prepared[0]["total_amount"], status,
             delivery_date, payment_terms, notes),
        )
        order_id = cur.lastrowid
        _insert_items(conn, order_id, prepared)
        _sync_order_summary(conn, order_id)
        conn.commit()
        return get(order_id, company_id=company_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_by_customer(customer_id: int, *, company_id: int | None = None) -> list[dict]:
    """返回指定客户的所有订单，按创建时间倒序。

    company_id 缺失时 fail-closed 返回空列表（审计 P2-30）。
    """
    if company_id is None:
        return []
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM orders WHERE customer_id = ? AND company_id = ? "
            "ORDER BY created_at DESC",
            (customer_id, company_id),
        ).fetchall()
        return _attach_items(conn, [_row_to_dict(r) for r in rows])
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
        return _attach_items(conn, [_row_to_dict(r) for r in rows])
    finally:
        conn.close()


def get(order_id: int, *, company_id: int | None = None) -> dict | None:
    """根据 ID 获取订单（必须限定公司；缺失时 fail-closed，审计 P2-30）。"""
    if company_id is None:
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM orders WHERE id = ? AND company_id = ?",
            (order_id, company_id),
        ).fetchone()
        if not row:
            return None
        data = _row_to_dict(row)
        data["items"] = _items_for(conn, order_id)
        return data
    finally:
        conn.close()


def update(
    order_id: int, *, company_id: int | None = None,
    items: list[dict] | None = None, **kwargs,
) -> dict | None:
    """部分更新订单字段（必须限定公司；缺失时 fail-closed，审计 P2-30）。

    如果传入了 customer_id，校验新 customer 必须属于同一公司。
    传 `items` = 整单替换明细；不传则按平铺字段落到明细行（兼容旧 UI）。
    """
    if company_id is None:
        return None
    allowed = {"order_no", "product_name", "quantity", "unit", "unit_price",
               "currency", "total_amount", "status", "delivery_date",
               "payment_terms", "notes", "customer_id"}
    # None 对可清空字段表示「显式清空」，对其它字段表示「未提供」——两者必须区分
    updates = {
        k: v for k, v in kwargs.items()
        if k in allowed and (v is not None or k in CLEARABLE_FIELDS)
    }
    if items is None and not updates:
        return get(order_id, company_id=company_id)

    conn = get_connection()
    try:
        # BEGIN IMMEDIATE（直接拿写锁）—— 与 customer.update 同一理由：
        # deferred BEGIN 只开读快照，之后升级成写锁时若期间有别的连接提交过，
        # SQLite 抛 SQLITE_BUSY_SNAPSHOT 且**不重试**（busy_timeout 不生效），
        # 并发下必然 "database is locked"（2026-10-21 实测）。
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM orders WHERE id = ? AND company_id = ?",
            (order_id, company_id),
        ).fetchone()
        if not existing:
            conn.rollback()
            return None
        # 如果更新了 customer_id，校验新客户归属
        if "customer_id" in updates:
            if not _customer_in_company(conn, updates["customer_id"], company_id):
                conn.rollback()
                return None

        if items is not None:
            # 整单替换：删+插+重算摘要，同一事务
            prepared = _prepare_items(
                items, updates.get("currency") or existing["currency"],
            )
            conn.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
            _insert_items(conn, order_id, prepared)
        else:
            # 兼容旧 UI：平铺金额落到明细行（0/1/多行三种情形见函数说明）
            _apply_flat_fields_to_items(conn, order_id, existing, updates)

        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [order_id, company_id]
            n = conn.execute(
                f"UPDATE orders SET {set_clause}, updated_at = datetime('now','localtime') "
                "WHERE id = ? AND company_id = ?",
                values,
            ).rowcount
            if n == 0:
                conn.rollback()
                return None

        _sync_order_summary(conn, order_id)
        conn.commit()
        return get(order_id, company_id=company_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete(order_id: int, *, company_id: int | None = None) -> bool:
    """删除订单（必须限定公司；缺失时 fail-closed，审计 P2-30）。"""
    if company_id is None:
        return False
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM orders WHERE id = ? AND company_id = ?",
            (order_id, company_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ── 订单-文档库关联 ───────────────────────────────────────────────────────────


def link_library(order_id: int, library_id: int, *, company_id: int | None = None) -> bool:
    """关联文档库到订单（必须限定公司；缺失时 fail-closed，审计 P2-30）。"""
    if company_id is None:
        return False
    conn = get_connection()
    try:
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
    """取消订单的文档库关联（必须限定公司；缺失时 fail-closed，审计 P2-30）。"""
    if company_id is None:
        return False
    conn = get_connection()
    try:
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
    pattern = f"%{safe_kw}%"
    conn = get_connection()
    try:
        # 摘要列只含前 3 项品名 —— 多行订单靠 EXISTS 兜底匹配任意一行
        rows = conn.execute(
            "SELECT * FROM orders o WHERE o.customer_id = ? AND ("
            "  o.product_name LIKE ? ESCAPE '\\' OR EXISTS ("
            "    SELECT 1 FROM order_items i WHERE i.order_id = o.id "
            "    AND i.product_name LIKE ? ESCAPE '\\'"
            "  )"
            ") ORDER BY o.created_at DESC LIMIT ?",
            (customer_id, pattern, pattern, limit),
        ).fetchall()
        return _attach_items(conn, [_row_to_dict(r) for r in rows])
    finally:
        conn.close()


def _search_by_customer(customer_id: int, limit: int = 10) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM orders WHERE customer_id = ? ORDER BY created_at DESC LIMIT ?",
            (customer_id, limit),
        ).fetchall()
        return _attach_items(conn, [_row_to_dict(r) for r in rows])
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


def _format_price_part(unit_price, currency: str) -> str | None:
    """单价文字。无单价时**必须明写待谈**，否则模型会用 总额÷数量 反推。"""
    if unit_price:
        return f"单价 {unit_price} {currency}"
    if unit_price is None:
        return "单价待谈"
    return "单价待谈（旧数据，单价未填）"


def _format_item_line(item: dict, currency: str) -> str:
    parts = [f"    · {item.get('product_name') or '（未填品名）'}"]
    if item.get("quantity") is not None:
        parts.append(f"{item['quantity']}{item.get('unit') or ''}")
    price = _format_price_part(item.get("unit_price"), currency)
    if price:
        parts.append(price)
    if item.get("total_amount") is not None:
        parts.append(f"行总额 {item['total_amount']} {currency}")
    return " · ".join(parts)


def _format_order_context(rows: list[dict], cust: dict | None = None, product_kw: str = "") -> str | None:
    """将订单列表格式化为 LLM 可读的上下文文本（多商品订单逐行列出）。"""
    if not rows:
        return None

    lines = ["\n[订单上下文]"]
    if cust:
        lines.append(f"客户：{cust['name']}（联系人：{cust.get('contact','')}）")
    if product_kw:
        lines.append(f"匹配品名：{product_kw}")

    lines.append("")
    for o in rows:
        currency = o.get("currency") or "USD"
        items = o.get("items") or []
        if items:
            head = f"  [{o['status']}] {len(items)} 项商品"
            if o.get("order_no"):
                head += f" · 订单号 {o['order_no']}"
            lines.append(head)
            for item in items:
                lines.append(_format_item_line(item, item.get("currency") or currency))
            if o.get("total_amount") is not None:
                lines.append(f"    合计 {o['total_amount']} {currency}")
            else:
                # 任一行待谈 → 头合计为 NULL；明说，别让模型自己加总
                lines.append("    合计：待谈（有行未定价）")
            if o.get("delivery_date"):
                lines.append(f"    交期: {o['delivery_date']}")
            if o.get("created_at"):
                lines.append(f"    创建: {o['created_at'][:10]}")
            continue

        # 无明细行（迁移前数据 / 直接 SQL 写入）：回退单行格式
        parts = [f"  [{o['status']}] {o['product_name']}"]
        if o.get("quantity"):
            parts.append(f"{o['quantity']}{o.get('unit','')}")
        if o.get("unit_price"):
            parts.append(f"单价 {o['unit_price']} {currency}")
        elif o.get("quantity") or o.get("total_amount"):
            # 有数量或总额却没有单价 = 待谈；0 是旧数据（历史里 0 与"未填"混用）
            parts.append(
                "单价待谈" if o.get("unit_price") is None
                else "单价待谈（旧数据，单价未填）"
            )
        if o.get("total_amount"):
            parts.append(f"总金额 {o['total_amount']} {currency}")
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
