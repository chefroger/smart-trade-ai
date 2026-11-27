"""
Trade AI Assistant — 采购单与拼柜履约业务层（供应商管理一期 · 第三批）。

提供三张表的核心业务逻辑：
- purchase_orders：采购单 CRUD、单号规则（手填优先 / 空则 PO{id} 且创建后不可改）、
  单号对应查询、从已选厂询价单生成、交期提醒与确定性催货话术模板
- consolidations / consolidation_items：拼柜看板 CRUD、code 规则（CG{id}）、
  截关倒计时计算、待拼池查询与入柜/移出管理

所有操作严格按 company_id 隔离，跨公司记录一律不可见、不可改。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from typing import Any

from trade.database import get_connection

VALID_PO_STATUSES = ("已下单", "生产中", "待出货", "已出货", "完成")
_VALID_PO_STATUS_SET = frozenset(VALID_PO_STATUSES)
_POOL_PO_STATUSES = ("已下单", "生产中", "待出货")

VALID_CONSOLIDATION_STATUSES = ("组货中", "已截关", "已发运")
_VALID_CONS_STATUS_SET = frozenset(VALID_CONSOLIDATION_STATUSES)

_VALID_FOLLOWUP_VARIANTS = frozenset({"upcoming", "overdue", "cutoff"})


class PurchaseError(ValueError):
    """采购履约业务校验失败异常（路由层统一转为 HTTP 400）。"""


# ==============================================================================
# 通用辅助
# ==============================================================================


def _norm_text(value: Any) -> str:
    """把输入值规范为去首尾空白的字符串；None 返回空串。"""
    # None 视作空串
    if value is None:
        return ""
    return str(value).strip()


def _parse_optional_float(value: Any, field_name: str) -> float | None:
    """解析可选非负浮点数；空值返回 None，非法或负数抛 PurchaseError。"""
    # 空值或空白表示未填
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise PurchaseError(f"{field_name}必须是数字")
    # 数量与金额不允许负数
    if num < 0:
        raise PurchaseError(f"{field_name}不能为负数")
    return num


def _parse_optional_int(value: Any, field_name: str, *, min_val: int | None = None) -> int | None:
    """解析可选整数；空值返回 None，非法或越界抛 PurchaseError。"""
    # 空值表示未填
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        # 布尔值不当作整数
        if isinstance(value, bool):
            raise ValueError("bool is not int")
        num = int(float(value)) if isinstance(value, str) and "." in value else int(value)
    except (TypeError, ValueError):
        raise PurchaseError(f"{field_name}必须是整数")
    # 下界校验
    if min_val is not None and num < min_val:
        raise PurchaseError(f"{field_name}不能小于 {min_val}")
    return num


def _ensure_json_str(value: Any) -> str:
    """把 extra1/extra2/extra3 规范为合法 JSON 字符串。"""
    # 空值默认空对象
    if value is None or value == "":
        return "{}"
    # 字符串校验 JSON 语法
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return "{}"
        try:
            json.loads(stripped)
            return stripped
        except (TypeError, ValueError):
            raise PurchaseError("扩展字段必须是合法 JSON")
    return json.dumps(value, ensure_ascii=False)


def _validate_po_status(status: Any) -> str:
    """校验采购单状态仅允许五态。"""
    st = _norm_text(status) or "已下单"
    # 拒绝五态之外的状态
    if st not in _VALID_PO_STATUS_SET:
        raise PurchaseError(f"采购单状态仅支持 {' / '.join(VALID_PO_STATUSES)}，收到：{st}")
    return st


def _validate_cons_status(status: Any) -> str:
    """校验拼柜状态仅允许三态。"""
    st = _norm_text(status) or "组货中"
    # 拒绝三态之外的状态
    if st not in _VALID_CONS_STATUS_SET:
        raise PurchaseError(f"拼柜状态仅支持 {' / '.join(VALID_CONSOLIDATION_STATUSES)}，收到：{st}")
    return st


def _parse_iso_date(raw: str | None) -> date | None:
    """将 YYYY-MM-DD（或带时间后缀）解析为 date；空或非法返回 None。"""
    text = _norm_text(raw)
    # 空串直接返回 None
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _today_date(today_str: str | None = None) -> date:
    """返回基准日期（测试可传固定日期字符串以消除真实时钟依赖）。"""
    # 若调用方显式传入固定日期则解析使用
    if today_str:
        parsed = _parse_iso_date(today_str)
        if parsed is not None:
            return parsed
    return date.today()


def _order_display_no(order_id: int | None, order_no: str | None) -> str:
    """计算客户订单显示号：有 order_no 用原值，空号显示 SO{order_id}，无关联返空串。"""
    # 未关联客户订单时返回空串
    if order_id is None:
        return ""
    clean = _norm_text(order_no)
    return clean if clean else f"SO{order_id}"


def _compute_days_to_cutoff(cutoff_date: str | None, *, today: date) -> int | None:
    """计算距离截关日的天数（正=剩余，0=当天，负=已过，无截关日=None）。"""
    parsed = _parse_iso_date(cutoff_date)
    # 无有效截关日返回 None
    if parsed is None:
        return None
    return (parsed - today).days


def _check_fk_refs(
    conn: sqlite3.Connection,
    company_id: int,
    *,
    supplier_id: int | None = None,
    order_id: int | None = None,
    rfq_id: int | None = None,
) -> None:
    """校验关联的供应商、客户订单、采购询价单均归属当前公司。"""
    # 校验供应商归属
    if supplier_id is not None:
        row = conn.execute(
            "SELECT id FROM suppliers WHERE id = ? AND company_id = ?",
            (supplier_id, company_id),
        ).fetchone()
        if not row:
            raise PurchaseError("关联的供应商不存在或不属于当前公司")

    # 校验客户订单归属
    if order_id is not None:
        row = conn.execute(
            "SELECT id FROM orders WHERE id = ? AND company_id = ?",
            (order_id, company_id),
        ).fetchone()
        if not row:
            raise PurchaseError("关联的客户订单不存在或不属于当前公司")

    # 校验采购询价单归属
    if rfq_id is not None:
        row = conn.execute(
            "SELECT id FROM rfqs WHERE id = ? AND company_id = ?",
            (rfq_id, company_id),
        ).fetchone()
        if not row:
            raise PurchaseError("关联的采购询价单不存在或不属于当前公司")


# ==============================================================================
# 采购单（purchase_orders）CRUD 与单号对应查询
# ==============================================================================


def list_company_orders(company_id: int) -> list[dict]:
    """列出本公司客户订单（带显示号与客户名），供采购单表单下拉关联。"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT o.id, o.order_no, o.product_name, o.status, o.customer_id, "
            "c.name AS customer_name "
            "FROM orders o "
            "LEFT JOIN customers c ON c.id = o.customer_id AND c.company_id = o.company_id "
            "WHERE o.company_id = ? "
            "ORDER BY o.updated_at DESC, o.id DESC",
            (company_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["display_no"] = _order_display_no(d.get("id"), d.get("order_no"))
            out.append(d)
        return out
    finally:
        conn.close()


def list_purchase_orders(
    company_id: int,
    *,
    supplier_id: int | None = None,
    order_id: int | None = None,
    status: str = "",
    q: str = "",
) -> list[dict]:
    """查询本公司采购单列表（q 同时匹配 po_no、产品名与关联客户订单 order_no/SO{id}）。"""
    conn = get_connection()
    try:
        where = ["po.company_id = ?"]
        params: list[Any] = [company_id]

        # 按供应商筛选
        if supplier_id is not None:
            where.append("po.supplier_id = ?")
            params.append(int(supplier_id))

        # 按关联客户订单筛选（客户订单详情侧关联采购单区块复用）
        if order_id is not None:
            where.append("po.order_id = ?")
            params.append(int(order_id))

        st_clean = _norm_text(status)
        # 按采购单状态筛选
        if st_clean:
            where.append("po.status = ?")
            params.append(st_clean)

        q_clean = _norm_text(q)
        # q 同时匹配采购单号、产品名、以及关联客户订单的 order_no / SO{order_id}
        if q_clean:
            like = f"%{q_clean}%"
            where.append(
                "(po.po_no LIKE ? OR po.product_name LIKE ? OR "
                "COALESCE(o.order_no, '') LIKE ? OR "
                "CASE WHEN po.order_id IS NOT NULL THEN ('SO' || po.order_id) ELSE '' END LIKE ?)"
            )
            params.extend([like, like, like, like])

        sql = (
            "SELECT po.*, "
            "s.name AS supplier_name, s.short_name AS supplier_short_name, "
            "o.order_no AS order_no, o.customer_id AS customer_id, "
            "c.name AS customer_name "
            "FROM purchase_orders po "
            "JOIN suppliers s ON s.id = po.supplier_id AND s.company_id = po.company_id "
            "LEFT JOIN orders o ON o.id = po.order_id AND o.company_id = po.company_id "
            "LEFT JOIN customers c ON c.id = o.customer_id AND c.company_id = po.company_id "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY po.updated_at DESC, po.id DESC"
        )
        rows = conn.execute(sql, tuple(params)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["order_display_no"] = _order_display_no(d.get("order_id"), d.get("order_no"))
            out.append(d)
        return out
    finally:
        conn.close()


def create_purchase_order(
    company_id: int,
    *,
    supplier_id: Any,
    product_name: str,
    po_no: str = "",
    order_id: Any = None,
    rfq_id: Any = None,
    spec_model: str = "",
    quantity: Any = None,
    unit: str = "",
    amount: Any = None,
    currency: str = "CNY",
    ordered_at: str = "",
    promised_date: str = "",
    status: str = "已下单",
    note: str = "",
    extra1: Any = "{}",
    extra2: Any = "{}",
    extra3: Any = "{}",
) -> dict:
    """新建采购单：手填 po_no 用原样，空则同事务回填 PO{id}；ordered_at 空默认今天。"""
    sup_id = _parse_optional_int(supplier_id, "供应商 ID", min_val=1)
    # 供应商必填
    if sup_id is None:
        raise PurchaseError("supplier_id 不能为空")

    clean_prod = _norm_text(product_name)
    # 产品名称必填
    if not clean_prod:
        raise PurchaseError("产品名称不能为空")

    ord_id = _parse_optional_int(order_id, "关联客户订单 ID", min_val=1)
    r_id = _parse_optional_int(rfq_id, "来源询价单 ID", min_val=1)
    qty_val = _parse_optional_float(quantity, "数量")
    amt_val = _parse_optional_float(amount, "总金额")
    st_val = _validate_po_status(status)
    ord_date = _norm_text(ordered_at) or date.today().isoformat()
    po_no_clean = _norm_text(po_no)
    e1 = _ensure_json_str(extra1)
    e2 = _ensure_json_str(extra2)
    e3 = _ensure_json_str(extra3)

    conn = get_connection()
    try:
        _check_fk_refs(conn, company_id, supplier_id=sup_id, order_id=ord_id, rfq_id=r_id)
        cur = conn.execute(
            "INSERT INTO purchase_orders ("
            "company_id, po_no, supplier_id, order_id, rfq_id, product_name, spec_model, "
            "quantity, unit, amount, currency, ordered_at, promised_date, status, note, "
            "extra1, extra2, extra3"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                company_id, po_no_clean, sup_id, ord_id, r_id, clean_prod, _norm_text(spec_model),
                qty_val, _norm_text(unit), amt_val, _norm_text(currency) or "CNY",
                ord_date, _norm_text(promised_date), st_val, _norm_text(note), e1, e2, e3,
            ),
        )
        new_id = int(cur.lastrowid)
        # 未手填采购单号时在同一事务内回填 PO{id}
        if not po_no_clean:
            conn.execute(
                "UPDATE purchase_orders SET po_no = ? WHERE id = ? AND company_id = ?",
                (f"PO{new_id}", new_id, company_id),
            )
        conn.commit()
    finally:
        conn.close()
    return get_purchase_order(new_id, company_id)  # type: ignore[return-value]


def get_purchase_order(po_id: int, company_id: int) -> dict | None:
    """获取采购单详情（单头 + 供应商主联系人 + 关联订单信息 + 所在拼柜列表）。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT po.*, "
            "s.name AS supplier_name, s.short_name AS supplier_short_name, "
            "o.order_no AS order_no, o.customer_id AS customer_id, "
            "c.name AS customer_name "
            "FROM purchase_orders po "
            "JOIN suppliers s ON s.id = po.supplier_id AND s.company_id = po.company_id "
            "LEFT JOIN orders o ON o.id = po.order_id AND o.company_id = po.company_id "
            "LEFT JOIN customers c ON c.id = o.customer_id AND c.company_id = po.company_id "
            "WHERE po.id = ? AND po.company_id = ?",
            (po_id, company_id),
        ).fetchone()
        # 不存在或跨公司返回 None
        if not row:
            return None
        po = dict(row)
        po["order_display_no"] = _order_display_no(po.get("order_id"), po.get("order_no"))

        # 查询供应商主联系人（优先 is_primary=1，其次最早一条）
        contact_row = conn.execute(
            "SELECT id, name, role, phone, wechat, email, is_primary "
            "FROM supplier_contacts "
            "WHERE supplier_id = ? AND company_id = ? "
            "ORDER BY is_primary DESC, id ASC LIMIT 1",
            (int(po["supplier_id"]), company_id),
        ).fetchone()
        po["primary_contact"] = dict(contact_row) if contact_row else None

        # 查询所在拼柜列表
        cons_rows = conn.execute(
            "SELECT co.id, co.code, co.cutoff_date, co.destination_port, co.status, ci.id AS item_id "
            "FROM consolidation_items ci "
            "JOIN consolidations co ON co.id = ci.consolidation_id AND co.company_id = ci.company_id "
            "WHERE ci.purchase_order_id = ? AND ci.company_id = ? "
            "ORDER BY co.id DESC",
            (po_id, company_id),
        ).fetchall()
        po["consolidations"] = [dict(r) for r in cons_rows]
        return po
    finally:
        conn.close()


_PO_UPDATABLE = {
    "supplier_id", "order_id", "rfq_id", "product_name", "spec_model",
    "quantity", "unit", "amount", "currency", "ordered_at", "promised_date",
    "status", "note", "extra1", "extra2", "extra3",
}


def update_purchase_order(po_id: int, company_id: int, **fields: Any) -> dict | None:
    """更新采购单（po_no 一经创建终身不可改：传入不同值时抛 PurchaseError）。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM purchase_orders WHERE id = ? AND company_id = ?",
            (po_id, company_id),
        ).fetchone()
        # 不存在或跨公司
        if not row:
            return None
        existing = dict(row)

        # §2.1 单号规则：po_no 不可修改（若显式传了不同单号则报错拒绝）
        if "po_no" in fields and fields["po_no"] is not None:
            attempted = _norm_text(fields["po_no"])
            if attempted != _norm_text(existing.get("po_no")):
                raise PurchaseError("采购单号一经创建不可修改")

        updates: dict[str, Any] = {}
        for key, raw in fields.items():
            # 忽略非白名单字段（含 po_no）
            if key not in _PO_UPDATABLE:
                continue
            if key == "supplier_id":
                sup_id = _parse_optional_int(raw, "供应商 ID", min_val=1)
                if sup_id is None:
                    raise PurchaseError("supplier_id 不能为空")
                _check_fk_refs(conn, company_id, supplier_id=sup_id)
                updates[key] = sup_id
            elif key == "order_id":
                ord_id = _parse_optional_int(raw, "关联客户订单 ID", min_val=1)
                _check_fk_refs(conn, company_id, order_id=ord_id)
                updates[key] = ord_id
            elif key == "rfq_id":
                r_id = _parse_optional_int(raw, "来源询价单 ID", min_val=1)
                _check_fk_refs(conn, company_id, rfq_id=r_id)
                updates[key] = r_id
            elif key == "product_name":
                val = _norm_text(raw)
                if not val:
                    raise PurchaseError("产品名称不能为空")
                updates[key] = val
            elif key in ("quantity", "amount"):
                updates[key] = _parse_optional_float(raw, key)
            elif key == "status":
                updates[key] = _validate_po_status(raw)
            elif key == "currency":
                updates[key] = _norm_text(raw) or "CNY"
            elif key in ("extra1", "extra2", "extra3"):
                updates[key] = _ensure_json_str(raw)
            else:
                updates[key] = _norm_text(raw)

        # 有修改字段时写库
        if updates:
            set_clause = ", ".join(f"{col} = ?" for col in updates)
            conn.execute(
                f"UPDATE purchase_orders SET {set_clause}, updated_at = datetime('now', 'localtime') "
                "WHERE id = ? AND company_id = ?",
                (*updates.values(), po_id, company_id),
            )
            conn.commit()
    finally:
        conn.close()
    return get_purchase_order(po_id, company_id)


def delete_purchase_order(po_id: int, company_id: int) -> bool:
    """删除采购单（外键级联删除拼柜明细，拼柜本身不动）。"""
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM purchase_orders WHERE id = ? AND company_id = ?",
            (po_id, company_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def create_purchase_order_from_rfq(company_id: int, rfq_id: int) -> dict | None:
    """从已选厂（decided）的采购询价单生成采购单；非 decided 或无选中行抛 PurchaseError。"""
    conn = get_connection()
    try:
        rfq_row = conn.execute(
            "SELECT * FROM rfqs WHERE id = ? AND company_id = ?",
            (rfq_id, company_id),
        ).fetchone()
        # 询价单不存在或跨公司返回 None（路由层返回 404）
        if not rfq_row:
            return None
        rfq = dict(rfq_row)

        # 必须为已选厂状态
        if rfq.get("status") != "decided":
            raise PurchaseError("只有已选厂（decided）的采购询价单才能生成采购单")

        selected = conn.execute(
            "SELECT * FROM rfq_responses "
            "WHERE rfq_id = ? AND company_id = ? AND selected = 1 LIMIT 1",
            (rfq_id, company_id),
        ).fetchone()
        # 必须存在选中的供应商回复行
        if not selected:
            raise PurchaseError("该采购询价单没有选中的供应商回复行，无法生成采购单")
        sel = dict(selected)

        # 单价优先取不含税价，无则取含税价；单价或数量任一缺失则总金额留空（绝不编造）
        unit_price = sel.get("price_excl_tax")
        if unit_price is None:
            unit_price = sel.get("price_incl_tax")
        qty = rfq.get("quantity")
        amount = round(float(unit_price) * float(qty), 4) if (unit_price is not None and qty is not None) else None

        supplier_id = int(sel["supplier_id"])
        currency = _norm_text(sel.get("currency")) or "CNY"
    finally:
        conn.close()

    return create_purchase_order(
        company_id,
        supplier_id=supplier_id,
        rfq_id=rfq_id,
        product_name=rfq["product_name"],
        spec_model=rfq.get("spec_model") or "",
        quantity=qty,
        unit=rfq.get("unit") or "",
        amount=amount,
        currency=currency,
        ordered_at=date.today().isoformat(),
        promised_date="",
        status="已下单",
        note=rfq.get("note") or "",
    )


# ==============================================================================
# 交期提醒（§3）
# ==============================================================================


def get_delivery_alerts(
    company_id: int,
    *,
    today_str: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """查询交期提醒：未出货/未完成且 promised_date <= 今天+3天；逾期优先，其次按交期升序。"""
    today = _today_date(today_str)
    horizon = (today + timedelta(days=3)).isoformat()

    conn = get_connection()
    try:
        # 极旧库兼容：表不存在时返回空列表
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='purchase_orders'"
        ).fetchone()
        if not has_table:
            return []

        rows = conn.execute(
            "SELECT po.*, "
            "s.name AS supplier_name, s.short_name AS supplier_short_name, "
            "o.order_no AS order_no, o.customer_id AS customer_id, "
            "c.name AS customer_name "
            "FROM purchase_orders po "
            "JOIN suppliers s ON s.id = po.supplier_id AND s.company_id = po.company_id "
            "LEFT JOIN orders o ON o.id = po.order_id AND o.company_id = po.company_id "
            "LEFT JOIN customers c ON c.id = o.customer_id AND c.company_id = po.company_id "
            "WHERE po.company_id = ? "
            "AND po.status NOT IN ('已出货', '完成') "
            "AND TRIM(COALESCE(po.promised_date, '')) != '' "
            "AND substr(TRIM(po.promised_date), 1, 10) <= ?",
            (company_id, horizon),
        ).fetchall()
    finally:
        conn.close()

    alerts: list[dict] = []
    for r in rows:
        d = dict(r)
        promised = _parse_iso_date(d.get("promised_date"))
        # 跳过格式无法解析的异常日期
        if promised is None:
            continue
        delta = (promised - today).days
        # 超出 3 天窗口的不计入
        if delta > 3:
            continue
        d["order_display_no"] = _order_display_no(d.get("order_id"), d.get("order_no"))
        if delta < 0:
            d["is_overdue"] = True
            d["days_overdue"] = abs(delta)
            d["days_left"] = 0
        else:
            d["is_overdue"] = False
            d["days_overdue"] = 0
            d["days_left"] = delta
        alerts.append(d)

    # 排序：逾期在前（逾期天数多者靠前），其次按约定交期升序
    alerts.sort(
        key=lambda item: (
            0 if item["is_overdue"] else 1,
            -int(item["days_overdue"]),
            item["promised_date"][:10],
            int(item["id"]),
        )
    )
    # 按需截断（如今日简报最多取前 10 条）
    if limit is not None and limit >= 0:
        return alerts[:limit]
    return alerts


# ==============================================================================
# 催货话术（§4 确定性模板，只出文本、零写库、永不发送）
# ==============================================================================


def build_followup_draft(
    po_id: int,
    company_id: int,
    variant: str,
    *,
    today_str: str | None = None,
) -> dict | None:
    """按确定性模板生成催货话术文本草稿（不调 LLM、零写库、永不发送）。"""
    var = _norm_text(variant).lower()
    # 仅支持三种标准话术变体
    if var not in _VALID_FOLLOWUP_VARIANTS:
        raise PurchaseError("variant 仅支持 upcoming / overdue / cutoff")

    po = get_purchase_order(po_id, company_id)
    # 采购单不存在或跨公司返回 None（路由层返回 404）
    if not po:
        return None

    contact = po.get("primary_contact") or {}
    contact_name = _norm_text(contact.get("name"))
    greeting = f"{contact_name}您好，" if contact_name else "您好，"
    prod_label = po["product_name"] + (f"（{po['spec_model']}）" if po.get("spec_model") else "")
    po_no = po.get("po_no") or f"PO{po['id']}"
    promised_raw = _norm_text(po.get("promised_date"))
    promised_date = _parse_iso_date(promised_raw)
    today = _today_date(today_str)

    if var == "upcoming":
        # 临期提醒：含联系人称呼、产品名、单号、约定交期、剩余天数，语气客气
        if promised_date is not None:
            days_left = max(0, (promised_date - today).days)
            time_phrase = (
                f"约定交期为 {promised_raw[:10]}（距交期还有 {days_left} 天）"
                if days_left > 0
                else f"约定交期为今天（{promised_raw[:10]}，剩余 0 天）"
            )
        else:
            time_phrase = "尚未明确约定交期"
        text = (
            f"{greeting}跟进一下采购单 {po_no} 的「{prod_label}」，"
            f"{time_phrase}。麻烦确认一下目前生产和包装进度，看能否按期出货？"
            "如有需要配合的地方请随时告知，辛苦了！"
        )
    elif var == "overdue":
        # 逾期催货：含联系人称呼、产品名、单号、约定交期、已逾期天数，请对方今天给确切出货时间
        if promised_date is not None:
            days_overdue = max(0, (today - promised_date).days)
            overdue_phrase = f"原约定交期为 {promised_raw[:10]}，目前已经逾期 {days_overdue} 天"
        else:
            overdue_phrase = "交期已临近/逾期"
        text = (
            f"{greeting}采购单 {po_no} 的「{prod_label}」{overdue_phrase}。"
            "这边下游客户也在等船期，麻烦您今天务必核实一下产线情况，"
            "给我们一个确切的出货时间，方便我们同步安排后续订舱和衔接，感谢支持！"
        )
    else:
        # cutoff（拼柜截关）：须已加入某个 status='组货中' 且有截关日的拼柜
        active_cons = next(
            (
                c for c in (po.get("consolidations") or [])
                if c.get("status") == "组货中" and _norm_text(c.get("cutoff_date"))
            ),
            None,
        )
        if not active_cons:
            raise PurchaseError("该采购单未加入带有截关日的「组货中」拼柜，无法生成截关催货话术")
        cons_code = active_cons["code"]
        cutoff_str = _norm_text(active_cons["cutoff_date"])[:10]
        text = (
            f"{greeting}采购单 {po_no} 的「{prod_label}」已安排进拼柜 {cons_code}，"
            f"本柜截关日为 {cutoff_str}。为避免耽误整柜装运和报关，"
            f"麻烦务必在 {cutoff_str} 截关前将货物送达指定仓库，发货前请提前告知司机信息和预计到仓时间，谢谢配合！"
        )

    return {"text": text, "variant": var, "po_no": po_no}


# ==============================================================================
# 拼柜轻表（consolidations）与明细（consolidation_items）
# ==============================================================================


def _load_consolidation_items(conn: sqlite3.Connection, consolidation_id: int, company_id: int) -> list[dict]:
    """查询指定拼柜内的全部采购单明细。"""
    rows = conn.execute(
        "SELECT ci.id AS item_id, ci.consolidation_id, ci.purchase_order_id, ci.note AS item_note, "
        "po.po_no, po.supplier_id, s.name AS supplier_name, po.product_name, po.spec_model, "
        "po.quantity, po.unit, po.status AS po_status, po.promised_date "
        "FROM consolidation_items ci "
        "JOIN purchase_orders po ON po.id = ci.purchase_order_id AND po.company_id = ci.company_id "
        "JOIN suppliers s ON s.id = po.supplier_id AND s.company_id = po.company_id "
        "WHERE ci.consolidation_id = ? AND ci.company_id = ? "
        "ORDER BY ci.id ASC",
        (consolidation_id, company_id),
    ).fetchall()
    return [dict(r) for r in rows]


def list_consolidations(company_id: int, *, status: str = "", today_str: str | None = None) -> list[dict]:
    """列出本公司拼柜看板列表（含明细数、截关倒计时 days_to_cutoff 与柜内采购单明细）。"""
    today = _today_date(today_str)
    conn = get_connection()
    try:
        where = ["company_id = ?"]
        params: list[Any] = [company_id]
        st_clean = _norm_text(status)
        # 按拼柜状态筛选
        if st_clean:
            where.append("status = ?")
            params.append(st_clean)

        rows = conn.execute(
            f"SELECT * FROM consolidations WHERE {' AND '.join(where)} "
            "ORDER BY CASE status WHEN '组货中' THEN 0 WHEN '已截关' THEN 1 ELSE 2 END, "
            "CASE WHEN TRIM(COALESCE(cutoff_date, '')) = '' THEN 1 ELSE 0 END, "
            "cutoff_date ASC, id DESC",
            tuple(params),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            items = _load_consolidation_items(conn, int(d["id"]), company_id)
            d["items"] = items
            d["item_count"] = len(items)
            d["days_to_cutoff"] = _compute_days_to_cutoff(d.get("cutoff_date"), today=today)
            out.append(d)
        return out
    finally:
        conn.close()


def create_consolidation(
    company_id: int,
    *,
    code: str = "",
    cutoff_date: str = "",
    destination_port: str = "",
    carrier: str = "",
    etd: str = "",
    status: str = "组货中",
    note: str = "",
    extra1: Any = "{}",
    extra2: Any = "{}",
    extra3: Any = "{}",
) -> dict:
    """新建拼柜：手填 code 用原样，空则同事务回填 CG{id}。"""
    st_val = _validate_cons_status(status)
    code_clean = _norm_text(code)
    e1 = _ensure_json_str(extra1)
    e2 = _ensure_json_str(extra2)
    e3 = _ensure_json_str(extra3)

    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO consolidations ("
            "company_id, code, cutoff_date, destination_port, carrier, etd, status, note, "
            "extra1, extra2, extra3"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                company_id, code_clean, _norm_text(cutoff_date), _norm_text(destination_port),
                _norm_text(carrier), _norm_text(etd), st_val, _norm_text(note), e1, e2, e3,
            ),
        )
        new_id = int(cur.lastrowid)
        # 未手填拼柜编号时在同一事务内回填 CG{id}
        if not code_clean:
            conn.execute(
                "UPDATE consolidations SET code = ? WHERE id = ? AND company_id = ?",
                (f"CG{new_id}", new_id, company_id),
            )
        conn.commit()
    finally:
        conn.close()
    return get_consolidation(new_id, company_id)  # type: ignore[return-value]


def get_consolidation(
    consolidation_id: int,
    company_id: int,
    *,
    today_str: str | None = None,
) -> dict | None:
    """获取拼柜详情（含 days_to_cutoff 与柜内采购单明细）；跨公司返回 None。"""
    today = _today_date(today_str)
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM consolidations WHERE id = ? AND company_id = ?",
            (consolidation_id, company_id),
        ).fetchone()
        # 不存在或跨公司
        if not row:
            return None
        d = dict(row)
        items = _load_consolidation_items(conn, consolidation_id, company_id)
        d["items"] = items
        d["item_count"] = len(items)
        d["days_to_cutoff"] = _compute_days_to_cutoff(d.get("cutoff_date"), today=today)
        return d
    finally:
        conn.close()


_CONS_UPDATABLE = {
    "code", "cutoff_date", "destination_port", "carrier", "etd",
    "status", "note", "extra1", "extra2", "extra3",
}


def update_consolidation(consolidation_id: int, company_id: int, **fields: Any) -> dict | None:
    """更新拼柜信息；跨公司或不存在返回 None。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM consolidations WHERE id = ? AND company_id = ?",
            (consolidation_id, company_id),
        ).fetchone()
        # 不存在或跨公司
        if not row:
            return None

        updates: dict[str, Any] = {}
        for key, raw in fields.items():
            # 忽略非白名单字段
            if key not in _CONS_UPDATABLE:
                continue
            if key == "status":
                updates[key] = _validate_cons_status(raw)
            elif key in ("extra1", "extra2", "extra3"):
                updates[key] = _ensure_json_str(raw)
            else:
                updates[key] = _norm_text(raw)

        # 有修改字段时写库
        if updates:
            set_clause = ", ".join(f"{col} = ?" for col in updates)
            conn.execute(
                f"UPDATE consolidations SET {set_clause}, updated_at = datetime('now', 'localtime') "
                "WHERE id = ? AND company_id = ?",
                (*updates.values(), consolidation_id, company_id),
            )
            conn.commit()
    finally:
        conn.close()
    return get_consolidation(consolidation_id, company_id)


def delete_consolidation(consolidation_id: int, company_id: int) -> bool:
    """删除拼柜（外键级联删明细，采购单本身不动）。"""
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM consolidations WHERE id = ? AND company_id = ?",
            (consolidation_id, company_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def add_consolidation_item(
    consolidation_id: int,
    company_id: int,
    purchase_order_id: Any,
    *,
    note: str = "",
) -> dict | None:
    """把采购单加入拼柜；重复加入返回既有明细行，不报错不重复建。"""
    po_id = _parse_optional_int(purchase_order_id, "采购单 ID", min_val=1)
    # 采购单 ID 必填
    if po_id is None:
        raise PurchaseError("purchase_order_id 不能为空")

    conn = get_connection()
    try:
        cons = conn.execute(
            "SELECT id FROM consolidations WHERE id = ? AND company_id = ?",
            (consolidation_id, company_id),
        ).fetchone()
        # 拼柜不存在或跨公司返回 None（路由层返回 404）
        if not cons:
            return None

        po = conn.execute(
            "SELECT id FROM purchase_orders WHERE id = ? AND company_id = ?",
            (po_id, company_id),
        ).fetchone()
        # 采购单不存在或跨公司
        if not po:
            raise PurchaseError("采购单不存在或不属于当前公司")

        existing = conn.execute(
            "SELECT id FROM consolidation_items "
            "WHERE consolidation_id = ? AND purchase_order_id = ? AND company_id = ?",
            (consolidation_id, po_id, company_id),
        ).fetchone()
        # 重复加入直接返回既有明细行
        if existing:
            item_id = int(existing["id"])
        else:
            cur = conn.execute(
                "INSERT INTO consolidation_items (company_id, consolidation_id, purchase_order_id, note) "
                "VALUES (?, ?, ?, ?)",
                (company_id, consolidation_id, po_id, _norm_text(note)),
            )
            item_id = int(cur.lastrowid)
            conn.commit()

        row = conn.execute(
            "SELECT ci.id AS item_id, ci.id, ci.consolidation_id, ci.purchase_order_id, ci.note AS item_note, "
            "po.po_no, po.supplier_id, s.name AS supplier_name, po.product_name, po.spec_model, "
            "po.quantity, po.unit, po.status AS po_status, po.promised_date "
            "FROM consolidation_items ci "
            "JOIN purchase_orders po ON po.id = ci.purchase_order_id AND po.company_id = ci.company_id "
            "JOIN suppliers s ON s.id = po.supplier_id AND s.company_id = po.company_id "
            "WHERE ci.id = ? AND ci.company_id = ?",
            (item_id, company_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def remove_consolidation_item(consolidation_id: int, item_id: int, company_id: int) -> bool:
    """从拼柜移出一条采购单明细（采购单本身不动）。"""
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM consolidation_items "
            "WHERE id = ? AND consolidation_id = ? AND company_id = ?",
            (item_id, consolidation_id, company_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_consolidation_pool(company_id: int) -> list[dict]:
    """待拼池：status ∈ (已下单, 生产中, 待出货) 且未出现在任何 consolidation_items 里的采购单。"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT po.*, "
            "s.name AS supplier_name, s.short_name AS supplier_short_name, "
            "o.order_no AS order_no, o.customer_id AS customer_id, "
            "c.name AS customer_name "
            "FROM purchase_orders po "
            "JOIN suppliers s ON s.id = po.supplier_id AND s.company_id = po.company_id "
            "LEFT JOIN orders o ON o.id = po.order_id AND o.company_id = po.company_id "
            "LEFT JOIN customers c ON c.id = o.customer_id AND c.company_id = po.company_id "
            "WHERE po.company_id = ? "
            "AND po.status IN ('已下单', '生产中', '待出货') "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM consolidation_items ci "
            "  WHERE ci.purchase_order_id = po.id AND ci.company_id = po.company_id"
            ") "
            "ORDER BY CASE WHEN TRIM(COALESCE(po.promised_date, '')) = '' THEN 1 ELSE 0 END, "
            "po.promised_date ASC, po.id DESC",
            (company_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["order_display_no"] = _order_display_no(d.get("order_id"), d.get("order_no"))
            out.append(d)
        return out
    finally:
        conn.close()
