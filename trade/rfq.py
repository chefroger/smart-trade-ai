"""
Trade AI Assistant — 采购询价单业务层（供应商管理一期 · 第二批）。

提供两张表的核心业务逻辑：
- rfqs：采购询价单头 CRUD（只允许 open / decided 两态）
- rfq_responses：供应商回复行管理、唯一选定、回复 → supplier_quotes 自动沉淀与同步清理

所有操作严格按 company_id 隔离，跨公司记录一律不可见、不可改。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Any

from trade.database import get_connection

_VALID_RFQ_STATUSES = frozenset({"open", "decided"})


class RfqError(ValueError):
    """采购询价业务校验失败异常（路由层统一转为 HTTP 400）。"""


# ==============================================================================
# 通用辅助
# ==============================================================================


def _norm_text(value: Any) -> str:
    """将输入值规范为去首尾空白的字符串；None 返回空串。"""
    # None 视为空串
    if value is None:
        return ""
    return str(value).strip()


def _parse_optional_float(value: Any, field_name: str) -> float | None:
    """解析可选非负浮点数；空值返回 None，非法或负数抛 RfqError。"""
    # 空值或空串表示未填
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise RfqError(f"{field_name}必须是数字")
    # 价格、数量、MOQ 不允许负数
    if num < 0:
        raise RfqError(f"{field_name}不能为负数")
    return num


def _parse_optional_int(value: Any, field_name: str, *, min_val: int | None = None) -> int | None:
    """解析可选整数；空值返回 None，非法或越界抛 RfqError。"""
    # 空值表示未填
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        # 布尔值不当作整数
        if isinstance(value, bool):
            raise ValueError("bool is not int")
        num = int(float(value)) if isinstance(value, str) and "." in value else int(value)
    except (TypeError, ValueError):
        raise RfqError(f"{field_name}必须是整数")
    # 下界校验
    if min_val is not None and num < min_val:
        raise RfqError(f"{field_name}不能小于 {min_val}")
    return num


def _parse_bool_flag(value: Any) -> int:
    """将布尔/整数/字符串解析为 0 或 1。"""
    # 布尔值直接转换
    if isinstance(value, bool):
        return 1 if value else 0
    # 整数非零即 1
    if isinstance(value, int):
        return 1 if value else 0
    raw = str(value or "").strip().lower()
    return 1 if raw in ("1", "true", "yes", "on", "是") else 0


def _ensure_json_str(value: Any) -> str:
    """将 extra1/extra2/extra3 规范为 JSON 字符串。"""
    # 空值默认空 JSON 对象
    if value is None or value == "":
        return "{}"
    # 字符串校验合法 JSON
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return "{}"
        try:
            json.loads(stripped)
            return stripped
        except (TypeError, ValueError):
            raise RfqError("扩展字段必须是合法 JSON")
    return json.dumps(value, ensure_ascii=False)


def _validate_status(status: Any) -> str:
    """校验询价单状态只允许 open 或 decided。"""
    st = _norm_text(status) or "open"
    # 严禁第三态
    if st not in _VALID_RFQ_STATUSES:
        raise RfqError(f"询价单状态仅支持 open 或 decided，收到：{st}")
    return st


def _resolve_inquiry_and_customer(
    conn: sqlite3.Connection,
    company_id: int,
    inquiry_id: Any,
    customer_id: Any,
) -> tuple[int | None, int | None]:
    """校验 inquiry_id 与 customer_id 归属本公司；选了询盘未传客户时自动带出客户。"""
    inq_id = _parse_optional_int(inquiry_id, "关联询盘 ID", min_val=1)
    cust_id = _parse_optional_int(customer_id, "关联客户 ID", min_val=1)

    # 若传了询盘 ID，校验其属于本公司，并在未指定客户时自动带出
    if inq_id is not None:
        inq_row = conn.execute(
            "SELECT id, customer_id FROM inquiries WHERE id = ? AND company_id = ?",
            (inq_id, company_id),
        ).fetchone()
        if not inq_row:
            raise RfqError("关联的客户询盘不存在或不属于当前公司")
        if cust_id is None and inq_row["customer_id"] is not None:
            cust_id = int(inq_row["customer_id"])

    # 若有客户 ID，校验其属于本公司
    if cust_id is not None:
        c_row = conn.execute(
            "SELECT id FROM customers WHERE id = ? AND company_id = ?",
            (cust_id, company_id),
        ).fetchone()
        if not c_row:
            raise RfqError("关联的客户不存在或不属于当前公司")

    return inq_id, cust_id


def _load_response_row(conn: sqlite3.Connection, response_id: int, company_id: int) -> dict | None:
    """查询单条回复行（附供应商名）；不存在或跨公司返回 None。"""
    row = conn.execute(
        "SELECT rr.*, s.name AS supplier_name, s.short_name AS supplier_short_name "
        "FROM rfq_responses rr "
        "JOIN suppliers s ON s.id = rr.supplier_id AND s.company_id = rr.company_id "
        "WHERE rr.id = ? AND rr.company_id = ?",
        (response_id, company_id),
    ).fetchone()
    return dict(row) if row else None


# ==============================================================================
# 回复 → 报价沉淀同步（§2.3 核心规则）
# ==============================================================================


def _ensure_supplier_product(
    conn: sqlite3.Connection,
    company_id: int,
    supplier_id: int,
    product_name: str,
    spec_model: str,
    unit: str,
) -> int:
    """按 (供应商, 产品, 规格) 查找能力行；找不到则新建一条（is_self_produced=2）。"""
    found = conn.execute(
        "SELECT id FROM supplier_products "
        "WHERE company_id = ? AND supplier_id = ? AND product_name = ? AND spec_model = ?",
        (company_id, supplier_id, product_name, spec_model),
    ).fetchone()
    # 已有能力行直接复用
    if found:
        return int(found["id"])
    cur = conn.execute(
        "INSERT INTO supplier_products ("
        "company_id, supplier_id, product_name, spec_model, unit, is_self_produced"
        ") VALUES (?, ?, ?, ?, ?, 2)",
        (company_id, supplier_id, product_name, spec_model, unit),
    )
    return int(cur.lastrowid)


def _sync_response_quote(
    conn: sqlite3.Connection,
    company_id: int,
    rfq: dict,
    resp: dict,
) -> int | None:
    """按 §2.3 规则将回复行同步沉淀到 supplier_quotes，返回最新 quote_id（或 None）。"""
    responded = int(resp.get("responded") or 0)
    price_excl = resp.get("price_excl_tax")
    price_incl = resp.get("price_incl_tax")
    existing_qid = resp.get("quote_id")

    has_price = (price_excl is not None) or (price_incl is not None)

    # 未回或双价皆空：永不沉淀；若此前沉淀过则一并删除
    if responded != 1 or not has_price:
        if existing_qid is not None:
            conn.execute(
                "DELETE FROM supplier_quotes WHERE id = ? AND company_id = ?",
                (int(existing_qid), company_id),
            )
            conn.execute(
                "UPDATE rfq_responses SET quote_id = NULL WHERE id = ? AND company_id = ?",
                (int(resp["id"]), company_id),
            )
        return None

    prod_name = _norm_text(rfq.get("product_name"))
    spec_model = _norm_text(rfq.get("spec_model"))
    unit = _norm_text(rfq.get("unit"))
    supplier_id = int(resp["supplier_id"])
    supplier_product_id = _ensure_supplier_product(
        conn, company_id, supplier_id, prod_name, spec_model, unit,
    )
    currency = _norm_text(resp.get("currency")) or "CNY"
    quoted_at = _norm_text(resp.get("responded_at"))
    moq = resp.get("moq")
    notes = _norm_text(resp.get("notes"))
    source_customer_id = rfq.get("customer_id")
    rfq_id = int(rfq["id"])

    # 若已有沉淀报价行且仍在库中：同步 UPDATE，绝不新建第二行
    if existing_qid is not None:
        exists = conn.execute(
            "SELECT id FROM supplier_quotes WHERE id = ? AND company_id = ?",
            (int(existing_qid), company_id),
        ).fetchone()
        if exists:
            conn.execute(
                "UPDATE supplier_quotes SET "
                "supplier_product_id = ?, product_name = ?, spec_model = ?, unit = ?, "
                "price_excl_tax = ?, price_incl_tax = ?, currency = ?, moq = ?, "
                "quoted_at = ?, source_customer_id = ?, rfq_id = ?, source = 'rfq', "
                "notes = ?, updated_at = datetime('now', 'localtime') "
                "WHERE id = ? AND company_id = ?",
                (
                    supplier_product_id, prod_name, spec_model, unit,
                    price_excl, price_incl, currency, moq,
                    quoted_at, source_customer_id, rfq_id, notes,
                    int(existing_qid), company_id,
                ),
            )
            return int(existing_qid)

    # 首次沉淀：插入 supplier_quotes 并回填 rfq_responses.quote_id
    cur = conn.execute(
        "INSERT INTO supplier_quotes ("
        "company_id, supplier_id, supplier_product_id, product_name, spec_model, unit, "
        "price_excl_tax, price_incl_tax, currency, moq, quoted_at, valid_until, "
        "source_customer_id, rfq_id, source, source_ref, notes"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, 'rfq', '', ?)",
        (
            company_id, supplier_id, supplier_product_id, prod_name, spec_model, unit,
            price_excl, price_incl, currency, moq, quoted_at,
            source_customer_id, rfq_id, notes,
        ),
    )
    new_qid = int(cur.lastrowid)
    conn.execute(
        "UPDATE rfq_responses SET quote_id = ? WHERE id = ? AND company_id = ?",
        (new_qid, int(resp["id"]), company_id),
    )
    return new_qid


# ==============================================================================
# 采购询价单头（rfqs）CRUD
# ==============================================================================


def list_company_inquiries(company_id: int) -> list[dict]:
    """列出本公司的客户询盘（附客户名），供采购询价单表单下拉选择。"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT i.id, i.title, i.stage, i.customer_id, c.name AS customer_name "
            "FROM inquiries i "
            "LEFT JOIN customers c ON c.id = i.customer_id AND c.company_id = i.company_id "
            "WHERE i.company_id = ? "
            "ORDER BY i.updated_at DESC, i.id DESC",
            (company_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_rfqs(
    company_id: int,
    *,
    status: str = "",
    customer_id: int | None = None,
    inquiry_id: int | None = None,
    q: str = "",
) -> list[dict]:
    """查询本公司采购询价单列表（带回复计数与选中供应商名）。"""
    conn = get_connection()
    try:
        where = ["r.company_id = ?"]
        params: list[Any] = [company_id]

        st_clean = _norm_text(status)
        # 按状态筛选
        if st_clean:
            where.append("r.status = ?")
            params.append(st_clean)

        # 按关联客户筛选
        if customer_id is not None:
            where.append("r.customer_id = ?")
            params.append(int(customer_id))

        # 按关联询盘筛选
        if inquiry_id is not None:
            where.append("r.inquiry_id = ?")
            params.append(int(inquiry_id))

        q_clean = _norm_text(q)
        # 按产品名或询价主题模糊筛选
        if q_clean:
            like = f"%{q_clean}%"
            where.append("(r.product_name LIKE ? OR r.title LIKE ?)")
            params.extend([like, like])

        sql = (
            "SELECT r.*, "
            "c.name AS customer_name, "
            "i.title AS inquiry_title, "
            "(SELECT COUNT(*) FROM rfq_responses rr WHERE rr.rfq_id = r.id) AS total_responses, "
            "(SELECT COUNT(*) FROM rfq_responses rr WHERE rr.rfq_id = r.id AND rr.responded = 1) AS responded_count, "
            "(SELECT s.name FROM rfq_responses rr "
            " JOIN suppliers s ON s.id = rr.supplier_id "
            " WHERE rr.rfq_id = r.id AND rr.selected = 1 LIMIT 1) AS selected_supplier_name, "
            "(SELECT rr.supplier_id FROM rfq_responses rr "
            " WHERE rr.rfq_id = r.id AND rr.selected = 1 LIMIT 1) AS selected_supplier_id "
            "FROM rfqs r "
            "LEFT JOIN customers c ON c.id = r.customer_id AND c.company_id = r.company_id "
            "LEFT JOIN inquiries i ON i.id = r.inquiry_id AND i.company_id = r.company_id "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY r.updated_at DESC, r.id DESC"
        )
        rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_rfq(
    company_id: int,
    *,
    product_name: str,
    title: str = "",
    spec_model: str = "",
    quantity: Any = None,
    unit: str = "",
    target_delivery_date: str = "",
    inquiry_id: Any = None,
    customer_id: Any = None,
    status: str = "open",
    note: str = "",
    extra1: Any = "{}",
    extra2: Any = "{}",
    extra3: Any = "{}",
) -> dict:
    """新建采购询价单头（product_name 必填；status 仅允许 open/decided）。"""
    clean_prod = _norm_text(product_name)
    # 产品名称必填
    if not clean_prod:
        raise RfqError("产品名称不能为空")

    qty_val = _parse_optional_float(quantity, "数量")
    st_val = _validate_status(status)
    e1 = _ensure_json_str(extra1)
    e2 = _ensure_json_str(extra2)
    e3 = _ensure_json_str(extra3)

    conn = get_connection()
    try:
        inq_id, cust_id = _resolve_inquiry_and_customer(conn, company_id, inquiry_id, customer_id)
        cur = conn.execute(
            "INSERT INTO rfqs ("
            "company_id, title, product_name, spec_model, quantity, unit, "
            "target_delivery_date, inquiry_id, customer_id, status, note, "
            "extra1, extra2, extra3"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                company_id, _norm_text(title), clean_prod, _norm_text(spec_model),
                qty_val, _norm_text(unit), _norm_text(target_delivery_date),
                inq_id, cust_id, st_val, _norm_text(note), e1, e2, e3,
            ),
        )
        new_id = int(cur.lastrowid)
        conn.commit()
    finally:
        conn.close()
    return get_rfq(new_id, company_id)  # type: ignore[return-value]


def get_rfq(rfq_id: int, company_id: int) -> dict | None:
    """获取采购询价单详情（单头 + 全部回复行）；跨公司或不存在返回 None。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT r.*, c.name AS customer_name, i.title AS inquiry_title "
            "FROM rfqs r "
            "LEFT JOIN customers c ON c.id = r.customer_id AND c.company_id = r.company_id "
            "LEFT JOIN inquiries i ON i.id = r.inquiry_id AND i.company_id = r.company_id "
            "WHERE r.id = ? AND r.company_id = ?",
            (rfq_id, company_id),
        ).fetchone()
        # 不存在或跨公司
        if not row:
            return None
        rfq = dict(row)
        resp_rows = conn.execute(
            "SELECT rr.*, s.name AS supplier_name, s.short_name AS supplier_short_name "
            "FROM rfq_responses rr "
            "JOIN suppliers s ON s.id = rr.supplier_id AND s.company_id = rr.company_id "
            "WHERE rr.rfq_id = ? AND rr.company_id = ? "
            "ORDER BY rr.selected DESC, rr.responded DESC, rr.id ASC",
            (rfq_id, company_id),
        ).fetchall()
        responses = [dict(r) for r in resp_rows]
        rfq["responses"] = responses
        rfq["total_responses"] = len(responses)
        rfq["responded_count"] = sum(1 for r in responses if int(r.get("responded") or 0) == 1)
        selected_row = next((r for r in responses if int(r.get("selected") or 0) == 1), None)
        rfq["selected_supplier_id"] = selected_row["supplier_id"] if selected_row else None
        rfq["selected_supplier_name"] = selected_row["supplier_name"] if selected_row else None
        return rfq
    finally:
        conn.close()


_RFQ_UPDATABLE = {
    "title", "product_name", "spec_model", "quantity", "unit",
    "target_delivery_date", "inquiry_id", "customer_id", "status", "note",
    "extra1", "extra2", "extra3",
}


def update_rfq(rfq_id: int, company_id: int, **fields: Any) -> dict | None:
    """更新采购询价单头；跨公司或不存在返回 None。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM rfqs WHERE id = ? AND company_id = ?",
            (rfq_id, company_id),
        ).fetchone()
        # 不存在或跨公司
        if not row:
            return None
        existing = dict(row)

        updates: dict[str, Any] = {}
        # 先解析 inquiry_id / customer_id（如果本次传入了其中任意一个）
        has_inq = "inquiry_id" in fields
        has_cust = "customer_id" in fields
        if has_inq or has_cust:
            raw_inq = fields["inquiry_id"] if has_inq else existing.get("inquiry_id")
            raw_cust = fields["customer_id"] if has_cust else (None if has_inq else existing.get("customer_id"))
            inq_id, cust_id = _resolve_inquiry_and_customer(conn, company_id, raw_inq, raw_cust)
            if has_inq:
                updates["inquiry_id"] = inq_id
            if has_cust or (has_inq and cust_id is not None):
                updates["customer_id"] = cust_id

        for key, raw in fields.items():
            # 忽略非白名单或已处理字段
            if key not in _RFQ_UPDATABLE or key in ("inquiry_id", "customer_id"):
                continue
            if key == "product_name":
                val = _norm_text(raw)
                # 产品名称不可改为空
                if not val:
                    raise RfqError("产品名称不能为空")
                updates[key] = val
            elif key == "quantity":
                updates[key] = _parse_optional_float(raw, "数量")
            elif key == "status":
                updates[key] = _validate_status(raw)
            elif key in ("extra1", "extra2", "extra3"):
                updates[key] = _ensure_json_str(raw)
            else:
                updates[key] = _norm_text(raw)

        # 有修改字段时落库
        if updates:
            set_clause = ", ".join(f"{col} = ?" for col in updates)
            conn.execute(
                f"UPDATE rfqs SET {set_clause}, updated_at = datetime('now', 'localtime') "
                "WHERE id = ? AND company_id = ?",
                (*updates.values(), rfq_id, company_id),
            )
            conn.commit()
    finally:
        conn.close()
    return get_rfq(rfq_id, company_id)


def delete_rfq(rfq_id: int, company_id: int) -> bool:
    """删除采购询价单（级联删回复行，并按 §2.3 删除全部已沉淀报价行）。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM rfqs WHERE id = ? AND company_id = ?",
            (rfq_id, company_id),
        ).fetchone()
        # 不存在或跨公司
        if not row:
            return False

        # 先删除所有由本单回复沉淀出的 supplier_quotes 行
        quote_rows = conn.execute(
            "SELECT quote_id FROM rfq_responses "
            "WHERE rfq_id = ? AND company_id = ? AND quote_id IS NOT NULL",
            (rfq_id, company_id),
        ).fetchall()
        for qr in quote_rows:
            conn.execute(
                "DELETE FROM supplier_quotes WHERE id = ? AND company_id = ?",
                (int(qr["quote_id"]), company_id),
            )
        # 兜底清理任何直接挂在本 rfq_id 下的 rfq 来源报价
        conn.execute(
            "DELETE FROM supplier_quotes WHERE rfq_id = ? AND company_id = ? AND source = 'rfq'",
            (rfq_id, company_id),
        )
        # 删除单头（外键 ON DELETE CASCADE 自动删除 rfq_responses）
        cur = conn.execute(
            "DELETE FROM rfqs WHERE id = ? AND company_id = ?",
            (rfq_id, company_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ==============================================================================
# 回复行（rfq_responses）管理与选定
# ==============================================================================


def add_rfq_response(rfq_id: int, company_id: int, supplier_id: Any) -> dict | None:
    """把一家供应商加入询价单；重复加入返回既有行，不报错不重复建。"""
    sup_id = _parse_optional_int(supplier_id, "供应商 ID", min_val=1)
    # 供应商 ID 必填
    if sup_id is None:
        raise RfqError("supplier_id 不能为空")

    conn = get_connection()
    try:
        rfq = conn.execute(
            "SELECT id FROM rfqs WHERE id = ? AND company_id = ?",
            (rfq_id, company_id),
        ).fetchone()
        # 询价单不存在或跨公司
        if not rfq:
            return None

        sup = conn.execute(
            "SELECT id FROM suppliers WHERE id = ? AND company_id = ?",
            (sup_id, company_id),
        ).fetchone()
        # 供应商不存在或跨公司
        if not sup:
            raise RfqError("供应商不存在或不属于当前公司")

        # 同一询价单里一家只占一行：重复加入直接返回既有行
        existing = conn.execute(
            "SELECT id FROM rfq_responses WHERE rfq_id = ? AND supplier_id = ? AND company_id = ?",
            (rfq_id, sup_id, company_id),
        ).fetchone()
        if existing:
            return _load_response_row(conn, int(existing["id"]), company_id)

        cur = conn.execute(
            "INSERT INTO rfq_responses (company_id, rfq_id, supplier_id, responded, responded_at, selected) "
            "VALUES (?, ?, ?, 0, '', 0)",
            (company_id, rfq_id, sup_id),
        )
        new_id = int(cur.lastrowid)
        conn.commit()
        return _load_response_row(conn, new_id, company_id)
    finally:
        conn.close()


_RESPONSE_UPDATABLE = {
    "responded", "responded_at", "price_excl_tax", "price_incl_tax",
    "currency", "lead_time_days", "lead_time_text", "moq", "notes",
    "extra1", "extra2", "extra3",
}


def update_rfq_response(response_id: int, company_id: int, **fields: Any) -> dict | None:
    """录入或修改回复行，并按 §2.3 同步沉淀/更新/删除 supplier_quotes。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM rfq_responses WHERE id = ? AND company_id = ?",
            (response_id, company_id),
        ).fetchone()
        # 不存在或跨公司
        if not row:
            return None
        existing = dict(row)

        rfq_row = conn.execute(
            "SELECT * FROM rfqs WHERE id = ? AND company_id = ?",
            (int(existing["rfq_id"]), company_id),
        ).fetchone()
        # 所属单头异常缺失
        if not rfq_row:
            return None
        rfq = dict(rfq_row)

        updates: dict[str, Any] = {}
        for key, raw in fields.items():
            # 忽略非白名单字段
            if key not in _RESPONSE_UPDATABLE:
                continue
            if key == "responded":
                updates[key] = _parse_bool_flag(raw)
            elif key in ("price_excl_tax", "price_incl_tax", "moq"):
                updates[key] = _parse_optional_float(raw, key)
            elif key == "lead_time_days":
                updates[key] = _parse_optional_int(raw, "交期天数", min_val=0)
            elif key == "currency":
                updates[key] = _norm_text(raw) or "CNY"
            elif key in ("extra1", "extra2", "extra3"):
                updates[key] = _ensure_json_str(raw)
            else:
                updates[key] = _norm_text(raw)

        # 首次置已回时自动打戳（YYYY-MM-DD）；改回未回时清空 responded_at
        new_responded = updates.get("responded", int(existing.get("responded") or 0))
        if new_responded == 1:
            current_at = updates.get("responded_at", existing.get("responded_at") or "")
            if not _norm_text(current_at):
                updates["responded_at"] = date.today().isoformat()
        elif "responded" in updates and new_responded == 0:
            updates["responded_at"] = ""

        # 落库回复行修改
        if updates:
            set_clause = ", ".join(f"{col} = ?" for col in updates)
            conn.execute(
                f"UPDATE rfq_responses SET {set_clause}, updated_at = datetime('now', 'localtime') "
                "WHERE id = ? AND company_id = ?",
                (*updates.values(), response_id, company_id),
            )

        # 读取更新后的回复行，同步报价沉淀
        updated_resp = dict(
            conn.execute("SELECT * FROM rfq_responses WHERE id = ?", (response_id,)).fetchone()
        )
        _sync_response_quote(conn, company_id, rfq, updated_resp)

        # 同步刷新单头 updated_at
        conn.execute(
            "UPDATE rfqs SET updated_at = datetime('now', 'localtime') WHERE id = ? AND company_id = ?",
            (int(rfq["id"]), company_id),
        )
        conn.commit()
        return _load_response_row(conn, response_id, company_id)
    finally:
        conn.close()


def delete_rfq_response(response_id: int, company_id: int) -> bool:
    """删除回复行，并按 §2.3 删除其沉淀报价；若删的是选中行则单头回 open。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM rfq_responses WHERE id = ? AND company_id = ?",
            (response_id, company_id),
        ).fetchone()
        # 不存在或跨公司
        if not row:
            return False
        resp = dict(row)

        # 若已沉淀报价，先删除对应报价行
        if resp.get("quote_id") is not None:
            conn.execute(
                "DELETE FROM supplier_quotes WHERE id = ? AND company_id = ?",
                (int(resp["quote_id"]), company_id),
            )

        conn.execute(
            "DELETE FROM rfq_responses WHERE id = ? AND company_id = ?",
            (response_id, company_id),
        )

        # 若被删除的是选中行，把单头状态重置回 open
        if int(resp.get("selected") or 0) == 1:
            conn.execute(
                "UPDATE rfqs SET status = 'open', updated_at = datetime('now', 'localtime') "
                "WHERE id = ? AND company_id = ?",
                (int(resp["rfq_id"]), company_id),
            )
        conn.commit()
        return True
    finally:
        conn.close()


def select_rfq_response(response_id: int, company_id: int) -> dict | None:
    """选定该回复行：同单其余行 selected 清零，本行 selected=1，单头 status 置 decided。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, rfq_id FROM rfq_responses WHERE id = ? AND company_id = ?",
            (response_id, company_id),
        ).fetchone()
        # 不存在或跨公司
        if not row:
            return None
        rfq_id = int(row["rfq_id"])

        # 先清零同单全部回复行，再标记当前行选中
        conn.execute(
            "UPDATE rfq_responses SET selected = 0, updated_at = datetime('now', 'localtime') "
            "WHERE rfq_id = ? AND company_id = ?",
            (rfq_id, company_id),
        )
        conn.execute(
            "UPDATE rfq_responses SET selected = 1, updated_at = datetime('now', 'localtime') "
            "WHERE id = ? AND company_id = ?",
            (response_id, company_id),
        )
        conn.execute(
            "UPDATE rfqs SET status = 'decided', updated_at = datetime('now', 'localtime') "
            "WHERE id = ? AND company_id = ?",
            (rfq_id, company_id),
        )
        conn.commit()
        return _load_response_row(conn, response_id, company_id)
    finally:
        conn.close()


def unselect_rfq_response(response_id: int, company_id: int) -> dict | None:
    """取消选定该回复行：selected 清零，单头 status 回 open。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, rfq_id FROM rfq_responses WHERE id = ? AND company_id = ?",
            (response_id, company_id),
        ).fetchone()
        # 不存在或跨公司
        if not row:
            return None
        rfq_id = int(row["rfq_id"])

        conn.execute(
            "UPDATE rfq_responses SET selected = 0, updated_at = datetime('now', 'localtime') "
            "WHERE id = ? AND company_id = ?",
            (response_id, company_id),
        )
        conn.execute(
            "UPDATE rfqs SET status = 'open', updated_at = datetime('now', 'localtime') "
            "WHERE id = ? AND company_id = ?",
            (rfq_id, company_id),
        )
        conn.commit()
        return _load_response_row(conn, response_id, company_id)
    finally:
        conn.close()
