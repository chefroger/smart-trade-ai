"""
Trade AI Assistant — 供应商管理业务层（一期 · 第一批数据底座）。

提供五张表的核心业务逻辑：
- suppliers：供应商主表 CRUD + 同名提醒
- supplier_contacts：联系人 CRUD + 主联系人互斥
- supplier_products：产品能力表 upsert（唯一约束 + 三态自产标记）
- supplier_quotes：报价历史追加、纠错与三向查询（产品/供应商/客户）
- compare_product：比价聚合（含税/不含税换算口径 + 不同单位分组）
- bulk_import_csv：CSV 模板批量导入（好行入库、坏行逐行报错）
- supplier_quote_drafts：AI 文件夹抽取与确认区审核（批准/驳回）

所有操作严格按 company_id 隔离，跨公司记录一律不可见、不可改。
"""

from __future__ import annotations

import csv
import io
import json
import logging
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from trade import doc_extract
from trade.database import get_connection

_log = logging.getLogger(__name__)


class SupplierError(ValueError):
    """供应商业务校验失败异常（路由层统一转为 HTTP 400）。"""


# ==============================================================================
# 通用辅助
# ==============================================================================


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    """将 sqlite3.Row 转为普通 dict；None 原样返回。"""
    # 空行直接返回 None，供上层判 404
    if row is None:
        return None
    return dict(row)


def _norm_text(value: Any) -> str:
    """把输入值规范为去除首尾空白的字符串；None 返回空串。"""
    # None 视为空字符串
    if value is None:
        return ""
    return str(value).strip()


def _parse_optional_float(value: Any, field_name: str, *, allow_negative: bool = False) -> float | None:
    """解析可选浮点数字段；空值返回 None，非法数字抛 SupplierError。"""
    # 空值或空串表示未填，保留为 None
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise SupplierError(f"{field_name}必须是数字")
    # 价格、MOQ、开票加点等业务数值不允许为负数
    if not allow_negative and num < 0:
        raise SupplierError(f"{field_name}不能为负数")
    return num


def _parse_optional_int(
    value: Any,
    field_name: str,
    *,
    min_val: int | None = None,
    max_val: int | None = None,
) -> int | None:
    """解析可选整数字段；空值返回 None，超界或非整数抛 SupplierError。"""
    # 空值视作未填
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        # 兼容 "5.0" 形式的数字字符串或整数
        if isinstance(value, bool):
            raise ValueError("bool is not int")
        num = int(float(value)) if isinstance(value, str) and "." in value else int(value)
    except (TypeError, ValueError):
        raise SupplierError(f"{field_name}必须是整数")
    # 下界校验
    if min_val is not None and num < min_val:
        raise SupplierError(f"{field_name}不能小于 {min_val}")
    # 上界校验
    if max_val is not None and num > max_val:
        raise SupplierError(f"{field_name}不能大于 {max_val}")
    return num


def _parse_tristate(value: Any, field_name: str, *, default: int = 2) -> int:
    """解析三态字段（0 否 / 1 是 / 2 待确认）。"""
    # 未提供时采用默认值（通常为 2 待确认）
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    # 布尔值直接转 1/0
    if isinstance(value, bool):
        return 1 if value else 0
    # 整数直接校验范围
    if isinstance(value, int):
        if value in (0, 1, 2):
            return value
        raise SupplierError(f"{field_name}只能是 0（否）、1（是）或 2（待确认）")
    raw = str(value).strip().lower()
    mapping = {
        "0": 0, "否": 0, "不能": 0, "不支持": 0, "no": 0, "false": 0,
        "1": 1, "是": 1, "能": 1, "支持": 1, "yes": 1, "true": 1,
        "2": 2, "待确认": 2, "未知": 2, "tbc": 2, "unknown": 2,
    }
    # 命中映射表则返回对应枚举值
    if raw in mapping:
        return mapping[raw]
    raise SupplierError(f"{field_name}取值无效：{value}（可选：是/否/待确认）")


def _is_expired(valid_until: str | None, *, today_str: str | None = None) -> bool:
    """判断报价是否已过期（valid_until 非空且早于今天）。"""
    val = _norm_text(valid_until)
    # 未填写有效期视为未过期
    if not val:
        return False
    today = today_str or date.today().isoformat()
    # 取前 10 位 YYYY-MM-DD 比较，兼容带时间后缀的日期串
    return val[:10] < today


def _ensure_json_str(value: Any) -> str:
    """把 extra1/extra2/extra3 规范为 JSON 字符串。"""
    # 空值默认空 JSON 对象
    if value is None or value == "":
        return "{}"
    # 已经是字符串时校验是否为合法 JSON
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return "{}"
        try:
            json.loads(stripped)
            return stripped
        except (TypeError, ValueError):
            raise SupplierError("扩展字段必须是合法 JSON")
    # dict / list 直接序列化
    return json.dumps(value, ensure_ascii=False)


def _check_supplier_belongs(conn: sqlite3.Connection, supplier_id: int, company_id: int) -> dict | None:
    """校验供应商是否属于指定公司；属于则返回行字典，否则返回 None。"""
    row = conn.execute(
        "SELECT * FROM suppliers WHERE id = ? AND company_id = ?",
        (supplier_id, company_id),
    ).fetchone()
    return _row_to_dict(row)


def _decorate_quote(row: dict, *, today_str: str | None = None) -> dict:
    """为报价行补充 expired 过期标记。"""
    item = dict(row)
    item["expired"] = _is_expired(item.get("valid_until"), today_str=today_str)
    return item


# ==============================================================================
# 供应商主表（suppliers）CRUD
# ==============================================================================


def list_suppliers(
    company_id: int,
    *,
    q: str = "",
    status: str = "",
    supplier_type: str = "",
    is_starred: int | None = None,
) -> list[dict]:
    """按公司查询供应商名录，支持名称/简称/主营搜索与状态/类型/星标筛选。"""
    conn = get_connection()
    try:
        where = ["s.company_id = ?"]
        params: list[Any] = [company_id]

        q_clean = _norm_text(q)
        # 关键词匹配供应商全称、简称或主营品类
        if q_clean:
            like = f"%{q_clean}%"
            where.append("(s.name LIKE ? OR s.short_name LIKE ? OR s.main_products LIKE ?)")
            params.extend([like, like, like])

        status_clean = _norm_text(status)
        # 按合作状态精确筛选
        if status_clean:
            where.append("s.status = ?")
            params.append(status_clean)

        type_clean = _norm_text(supplier_type)
        # 按供应商类型精确筛选
        if type_clean:
            where.append("s.supplier_type = ?")
            params.append(type_clean)

        # 按星标状态筛选
        if is_starred is not None:
            where.append("s.is_starred = ?")
            params.append(1 if int(is_starred) else 0)

        sql = (
            "SELECT s.*, "
            "(SELECT COUNT(*) FROM supplier_contacts c WHERE c.supplier_id = s.id) AS contacts_count, "
            "(SELECT COUNT(*) FROM supplier_products p WHERE p.supplier_id = s.id) AS products_count, "
            "(SELECT COUNT(*) FROM supplier_quotes sq WHERE sq.supplier_id = s.id) AS quotes_count "
            "FROM suppliers s "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY s.is_starred DESC, s.updated_at DESC, s.id DESC"
        )
        rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_supplier(
    company_id: int,
    *,
    name: str,
    short_name: str = "",
    supplier_type: str = "",
    main_products: str = "",
    province: str = "",
    city: str = "",
    address: str = "",
    status: str = "候选",
    rating: int | None = None,
    is_starred: int = 0,
    can_issue_vat: int = 2,
    tax_point: float | None = None,
    payment_terms: str = "",
    lead_time_days: int | None = None,
    source: str = "manual",
    note: str = "",
    extra1: Any = "{}",
    extra2: Any = "{}",
    extra3: Any = "{}",
) -> dict:
    """新建供应商；同公司同名时返回 duplicate_warning 提醒但不硬拦。"""
    clean_name = _norm_text(name)
    # 供应商全称是唯一必填项
    if not clean_name:
        raise SupplierError("供应商名称不能为空")

    rating_val = _parse_optional_int(rating, "评分", min_val=1, max_val=5)
    vat_val = _parse_tristate(can_issue_vat, "可开专票", default=2)
    tax_val = _parse_optional_float(tax_point, "开票加点")
    lead_val = _parse_optional_int(lead_time_days, "交期天数", min_val=0)
    starred_val = 1 if int(is_starred or 0) else 0
    status_val = _norm_text(status) or "候选"

    e1 = _ensure_json_str(extra1)
    e2 = _ensure_json_str(extra2)
    e3 = _ensure_json_str(extra3)

    conn = get_connection()
    try:
        # 软去重检查：同公司已有同名供应商时收集提醒，但不阻断创建
        dup_rows = conn.execute(
            "SELECT id, name FROM suppliers WHERE company_id = ? AND LOWER(TRIM(name)) = LOWER(?)",
            (company_id, clean_name),
        ).fetchall()
        cur = conn.execute(
            "INSERT INTO suppliers ("
            "company_id, name, short_name, supplier_type, main_products, "
            "province, city, address, status, rating, is_starred, "
            "can_issue_vat, tax_point, payment_terms, lead_time_days, "
            "source, note, extra1, extra2, extra3"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                company_id, clean_name, _norm_text(short_name), _norm_text(supplier_type),
                _norm_text(main_products), _norm_text(province), _norm_text(city),
                _norm_text(address), status_val, rating_val, starred_val,
                vat_val, tax_val, _norm_text(payment_terms), lead_val,
                _norm_text(source) or "manual", _norm_text(note), e1, e2, e3,
            ),
        )
        new_id = cur.lastrowid
        conn.commit()
        created = dict(
            conn.execute("SELECT * FROM suppliers WHERE id = ?", (new_id,)).fetchone()
        )
        # 存在同名供应商时在响应体附上软提醒
        if dup_rows:
            created["duplicate_warning"] = (
                f"本公司已存在同名供应商（共 {len(dup_rows)} 家，如 ID #{dup_rows[0]['id']}），已照常保存"
            )
            created["duplicates"] = [dict(r) for r in dup_rows]
        return created
    finally:
        conn.close()


def get_supplier(supplier_id: int, company_id: int) -> dict | None:
    """获取供应商详情（主表 + 联系人 + 产品能力 + 最近 20 条报价 + 报价总数）。"""
    conn = get_connection()
    try:
        sup = _check_supplier_belongs(conn, supplier_id, company_id)
        # 不存在或跨公司直接返回 None（路由层返回 404）
        if not sup:
            return None

        contacts = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM supplier_contacts WHERE supplier_id = ? AND company_id = ? "
                "ORDER BY is_primary DESC, id ASC",
                (supplier_id, company_id),
            ).fetchall()
        ]
        products = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM supplier_products WHERE supplier_id = ? AND company_id = ? "
                "ORDER BY updated_at DESC, id DESC",
                (supplier_id, company_id),
            ).fetchall()
        ]
        quotes_total = conn.execute(
            "SELECT COUNT(*) FROM supplier_quotes WHERE supplier_id = ? AND company_id = ?",
            (supplier_id, company_id),
        ).fetchone()[0]
        today_str = date.today().isoformat()
        quotes_rows = conn.execute(
            "SELECT sq.*, c.name AS source_customer_name "
            "FROM supplier_quotes sq "
            "LEFT JOIN customers c ON c.id = sq.source_customer_id AND c.company_id = sq.company_id "
            "WHERE sq.supplier_id = ? AND sq.company_id = ? "
            "ORDER BY sq.quoted_at DESC, sq.id DESC LIMIT 20",
            (supplier_id, company_id),
        ).fetchall()
        quotes = [_decorate_quote(dict(r), today_str=today_str) for r in quotes_rows]

        sup["contacts"] = contacts
        sup["products"] = products
        sup["quotes"] = quotes
        sup["quotes_total"] = int(quotes_total)
        return sup
    finally:
        conn.close()


_SUPPLIER_UPDATABLE = {
    "name", "short_name", "supplier_type", "main_products", "province", "city",
    "address", "status", "rating", "is_starred", "can_issue_vat", "tax_point",
    "payment_terms", "lead_time_days", "source", "note", "extra1", "extra2", "extra3",
}


def update_supplier(supplier_id: int, company_id: int, **fields: Any) -> dict | None:
    """更新供应商主表字段；跨公司或不存在返回 None。"""
    conn = get_connection()
    try:
        # 归属校验，防越权修改
        if not _check_supplier_belongs(conn, supplier_id, company_id):
            return None

        updates: dict[str, Any] = {}
        for key, raw in fields.items():
            # 忽略非白名单字段
            if key not in _SUPPLIER_UPDATABLE:
                continue
            if key == "name":
                val = _norm_text(raw)
                # 供应商全称不可改为空
                if not val:
                    raise SupplierError("供应商名称不能为空")
                updates[key] = val
            elif key == "rating":
                updates[key] = _parse_optional_int(raw, "评分", min_val=1, max_val=5)
            elif key == "is_starred":
                updates[key] = 1 if int(raw or 0) else 0
            elif key == "can_issue_vat":
                updates[key] = _parse_tristate(raw, "可开专票", default=2)
            elif key == "tax_point":
                updates[key] = _parse_optional_float(raw, "开票加点")
            elif key == "lead_time_days":
                updates[key] = _parse_optional_int(raw, "交期天数", min_val=0)
            elif key in ("extra1", "extra2", "extra3"):
                updates[key] = _ensure_json_str(raw)
            else:
                updates[key] = _norm_text(raw)

        # 有待更新字段时才执行 UPDATE
        if updates:
            set_clause = ", ".join(f"{col} = ?" for col in updates)
            conn.execute(
                f"UPDATE suppliers SET {set_clause}, updated_at = datetime('now', 'localtime') "
                "WHERE id = ? AND company_id = ?",
                (*updates.values(), supplier_id, company_id),
            )
            conn.commit()
        return _check_supplier_belongs(conn, supplier_id, company_id)
    finally:
        conn.close()


def delete_supplier(supplier_id: int, company_id: int) -> bool:
    """删除供应商（外键级联删除联系人、能力、报价）；不存在或跨公司返回 False。"""
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM suppliers WHERE id = ? AND company_id = ?",
            (supplier_id, company_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ==============================================================================
# 供应商联系人（supplier_contacts）CRUD
# ==============================================================================


def create_contact(
    company_id: int,
    supplier_id: int,
    *,
    name: str,
    role: str = "其他",
    is_primary: int = 0,
    phone: str = "",
    wechat: str = "",
    email: str = "",
    qq: str = "",
    note: str = "",
) -> dict | None:
    """为指定供应商新增联系人；设主联系人时清零同供应商其余联系人。"""
    clean_name = _norm_text(name)
    # 联系人姓名必填
    if not clean_name:
        raise SupplierError("联系人姓名不能为空")

    primary_val = 1 if int(is_primary or 0) else 0
    conn = get_connection()
    try:
        # 供应商必须属于当前公司
        if not _check_supplier_belongs(conn, supplier_id, company_id):
            return None
        # 设为主联系人前，清除该供应商原有的主联系人标记
        if primary_val == 1:
            conn.execute(
                "UPDATE supplier_contacts SET is_primary = 0, updated_at = datetime('now', 'localtime') "
                "WHERE supplier_id = ? AND company_id = ?",
                (supplier_id, company_id),
            )
        cur = conn.execute(
            "INSERT INTO supplier_contacts ("
            "company_id, supplier_id, name, role, is_primary, phone, wechat, email, qq, note"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                company_id, supplier_id, clean_name, _norm_text(role) or "其他",
                primary_val, _norm_text(phone), _norm_text(wechat),
                _norm_text(email), _norm_text(qq), _norm_text(note),
            ),
        )
        new_id = cur.lastrowid
        conn.commit()
        return dict(
            conn.execute("SELECT * FROM supplier_contacts WHERE id = ?", (new_id,)).fetchone()
        )
    finally:
        conn.close()


_CONTACT_UPDATABLE = {"name", "role", "is_primary", "phone", "wechat", "email", "qq", "note"}


def update_contact(contact_id: int, company_id: int, **fields: Any) -> dict | None:
    """更新供应商联系人；设主联系人时互斥清零同供应商其余联系人。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM supplier_contacts WHERE id = ? AND company_id = ?",
            (contact_id, company_id),
        ).fetchone()
        # 不存在或跨公司返回 None
        if not row:
            return None
        existing = dict(row)

        updates: dict[str, Any] = {}
        for key, raw in fields.items():
            # 过滤非白名单字段
            if key not in _CONTACT_UPDATABLE:
                continue
            if key == "name":
                val = _norm_text(raw)
                # 姓名不可改为空
                if not val:
                    raise SupplierError("联系人姓名不能为空")
                updates[key] = val
            elif key == "is_primary":
                updates[key] = 1 if int(raw or 0) else 0
            else:
                updates[key] = _norm_text(raw)

        # 设为主联系人时，先清零同供应商其余联系人
        if updates.get("is_primary") == 1:
            conn.execute(
                "UPDATE supplier_contacts SET is_primary = 0, updated_at = datetime('now', 'localtime') "
                "WHERE supplier_id = ? AND company_id = ? AND id != ?",
                (existing["supplier_id"], company_id, contact_id),
            )
        # 有字段变更时执行更新
        if updates:
            set_clause = ", ".join(f"{col} = ?" for col in updates)
            conn.execute(
                f"UPDATE supplier_contacts SET {set_clause}, updated_at = datetime('now', 'localtime') "
                "WHERE id = ? AND company_id = ?",
                (*updates.values(), contact_id, company_id),
            )
            conn.commit()
        return dict(
            conn.execute("SELECT * FROM supplier_contacts WHERE id = ?", (contact_id,)).fetchone()
        )
    finally:
        conn.close()


def delete_contact(contact_id: int, company_id: int) -> bool:
    """删除供应商联系人（严格按公司隔离）。"""
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM supplier_contacts WHERE id = ? AND company_id = ?",
            (contact_id, company_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ==============================================================================
# 产品能力表（supplier_products）Upsert 与 CRUD
# ==============================================================================


def upsert_product(
    company_id: int,
    supplier_id: int,
    *,
    product_name: str,
    spec_model: str = "",
    unit: str = "",
    is_self_produced: int = 2,
    quality_note: str = "",
    lead_time_days: int | None = None,
    lead_time_text: str = "",
    moq: float | None = None,
    packing_info: str = "",
    notes: str = "",
    extra1: Any = "{}",
    extra2: Any = "{}",
    extra3: Any = "{}",
) -> dict | None:
    """按 (company_id, supplier_id, product_name, spec_model) 唯一约束 upsert 能力行。"""
    clean_prod = _norm_text(product_name)
    # 产品名称必填
    if not clean_prod:
        raise SupplierError("产品名称不能为空")

    clean_spec = _norm_text(spec_model)
    self_val = _parse_tristate(is_self_produced, "是否自产", default=2)
    lead_days = _parse_optional_int(lead_time_days, "交期天数", min_val=0)
    moq_val = _parse_optional_float(moq, "MOQ")
    e1 = _ensure_json_str(extra1)
    e2 = _ensure_json_str(extra2)
    e3 = _ensure_json_str(extra3)

    conn = get_connection()
    try:
        # 供应商归属校验
        if not _check_supplier_belongs(conn, supplier_id, company_id):
            return None
        conn.execute(
            "INSERT INTO supplier_products ("
            "company_id, supplier_id, product_name, spec_model, unit, is_self_produced, "
            "quality_note, lead_time_days, lead_time_text, moq, packing_info, notes, "
            "extra1, extra2, extra3"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(company_id, supplier_id, product_name, spec_model) DO UPDATE SET "
            "unit = excluded.unit, "
            "is_self_produced = excluded.is_self_produced, "
            "quality_note = excluded.quality_note, "
            "lead_time_days = excluded.lead_time_days, "
            "lead_time_text = excluded.lead_time_text, "
            "moq = excluded.moq, "
            "packing_info = excluded.packing_info, "
            "notes = excluded.notes, "
            "extra1 = excluded.extra1, "
            "extra2 = excluded.extra2, "
            "extra3 = excluded.extra3, "
            "updated_at = datetime('now', 'localtime')",
            (
                company_id, supplier_id, clean_prod, clean_spec, _norm_text(unit),
                self_val, _norm_text(quality_note), lead_days, _norm_text(lead_time_text),
                moq_val, _norm_text(packing_info), _norm_text(notes), e1, e2, e3,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM supplier_products "
            "WHERE company_id = ? AND supplier_id = ? AND product_name = ? AND spec_model = ?",
            (company_id, supplier_id, clean_prod, clean_spec),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


_PRODUCT_UPDATABLE = {
    "product_name", "spec_model", "unit", "is_self_produced", "quality_note",
    "lead_time_days", "lead_time_text", "moq", "packing_info", "notes",
    "extra1", "extra2", "extra3",
}


def update_product(product_id: int, company_id: int, **fields: Any) -> dict | None:
    """更新产品能力行；跨公司或不存在返回 None，唯一键冲突抛 SupplierError。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM supplier_products WHERE id = ? AND company_id = ?",
            (product_id, company_id),
        ).fetchone()
        # 跨公司或不存在
        if not row:
            return None

        updates: dict[str, Any] = {}
        for key, raw in fields.items():
            # 忽略非白名单字段
            if key not in _PRODUCT_UPDATABLE:
                continue
            if key == "product_name":
                val = _norm_text(raw)
                # 产品名称不可改为空
                if not val:
                    raise SupplierError("产品名称不能为空")
                updates[key] = val
            elif key == "is_self_produced":
                updates[key] = _parse_tristate(raw, "是否自产", default=2)
            elif key == "lead_time_days":
                updates[key] = _parse_optional_int(raw, "交期天数", min_val=0)
            elif key == "moq":
                updates[key] = _parse_optional_float(raw, "MOQ")
            elif key in ("extra1", "extra2", "extra3"):
                updates[key] = _ensure_json_str(raw)
            else:
                updates[key] = _norm_text(raw)

        # 有修改字段时落库
        if updates:
            set_clause = ", ".join(f"{col} = ?" for col in updates)
            try:
                conn.execute(
                    f"UPDATE supplier_products SET {set_clause}, updated_at = datetime('now', 'localtime') "
                    "WHERE id = ? AND company_id = ?",
                    (*updates.values(), product_id, company_id),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                raise SupplierError("该供应商已存在相同产品名称与规格的能力记录")
        return dict(
            conn.execute("SELECT * FROM supplier_products WHERE id = ?", (product_id,)).fetchone()
        )
    finally:
        conn.close()


def delete_product(product_id: int, company_id: int) -> bool:
    """删除产品能力行（严格按公司隔离）。"""
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM supplier_products WHERE id = ? AND company_id = ?",
            (product_id, company_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ==============================================================================
# 报价历史（supplier_quotes）追加、纠错与三向查询
# ==============================================================================


def create_quote(
    company_id: int,
    supplier_id: int,
    *,
    product_name: str,
    spec_model: str = "",
    unit: str = "",
    price_excl_tax: float | None = None,
    price_incl_tax: float | None = None,
    currency: str = "CNY",
    moq: float | None = None,
    quoted_at: str = "",
    valid_until: str = "",
    source_customer_id: int | None = None,
    supplier_product_id: int | None = None,
    source: str = "manual",
    source_ref: str = "",
    notes: str = "",
    extra1: Any = "{}",
    extra2: Any = "{}",
    extra3: Any = "{}",
) -> dict | None:
    """追加一条供应商报价记录（只追加，不覆盖历史）。"""
    clean_prod = _norm_text(product_name)
    # 产品名称必填
    if not clean_prod:
        raise SupplierError("产品名称不能为空")

    excl_val = _parse_optional_float(price_excl_tax, "不含税价")
    incl_val = _parse_optional_float(price_incl_tax, "含税价")
    moq_val = _parse_optional_float(moq, "MOQ")
    src_val = _norm_text(source) or "manual"
    src_ref_val = _norm_text(source_ref)
    # ai-extract 来源必须记录出处文件路径
    if src_val == "ai-extract" and not src_ref_val:
        raise SupplierError("AI 抽取来源必须提供来源文件路径（source_ref）")

    quoted_date = _norm_text(quoted_at) or date.today().isoformat()
    e1 = _ensure_json_str(extra1)
    e2 = _ensure_json_str(extra2)
    e3 = _ensure_json_str(extra3)

    conn = get_connection()
    try:
        # 校验供应商属于当前公司
        if not _check_supplier_belongs(conn, supplier_id, company_id):
            return None

        cust_id: int | None = None
        # 若关联了询盘客户，校验该客户归属当前公司，防止跨公司外键挂载
        if source_customer_id is not None and source_customer_id != "":
            cust_id = _parse_optional_int(source_customer_id, "来源客户", min_val=1)
            if cust_id is not None:
                c_row = conn.execute(
                    "SELECT id FROM customers WHERE id = ? AND company_id = ?",
                    (cust_id, company_id),
                ).fetchone()
                if not c_row:
                    raise SupplierError("关联的来源客户不存在或不属于当前公司")

        prod_id: int | None = None
        # 若关联了能力行，校验能力行归属当前公司与当前供应商
        if supplier_product_id is not None and supplier_product_id != "":
            prod_id = _parse_optional_int(supplier_product_id, "产品能力 ID", min_val=1)
            if prod_id is not None:
                p_row = conn.execute(
                    "SELECT id FROM supplier_products WHERE id = ? AND company_id = ? AND supplier_id = ?",
                    (prod_id, company_id, supplier_id),
                ).fetchone()
                if not p_row:
                    raise SupplierError("关联的产品能力行不存在或不属于该供应商")

        # rfq_id 为第二批预留列，本批恒写 NULL
        cur = conn.execute(
            "INSERT INTO supplier_quotes ("
            "company_id, supplier_id, supplier_product_id, product_name, spec_model, unit, "
            "price_excl_tax, price_incl_tax, currency, moq, quoted_at, valid_until, "
            "source_customer_id, rfq_id, source, source_ref, notes, extra1, extra2, extra3"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)",
            (
                company_id, supplier_id, prod_id, clean_prod, _norm_text(spec_model),
                _norm_text(unit), excl_val, incl_val, _norm_text(currency) or "CNY",
                moq_val, quoted_date, _norm_text(valid_until), cust_id,
                src_val, src_ref_val, _norm_text(notes), e1, e2, e3,
            ),
        )
        new_id = cur.lastrowid
        conn.commit()
        row = dict(conn.execute("SELECT * FROM supplier_quotes WHERE id = ?", (new_id,)).fetchone())
        return _decorate_quote(row)
    finally:
        conn.close()


_QUOTE_UPDATABLE = {
    "product_name", "spec_model", "unit", "price_excl_tax", "price_incl_tax",
    "currency", "moq", "quoted_at", "valid_until", "source_customer_id",
    "supplier_product_id", "source", "source_ref", "notes", "extra1", "extra2", "extra3",
}


def update_quote(quote_id: int, company_id: int, **fields: Any) -> dict | None:
    """人工纠错修改一条报价；跨公司或不存在返回 None。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM supplier_quotes WHERE id = ? AND company_id = ?",
            (quote_id, company_id),
        ).fetchone()
        # 跨公司或不存在
        if not row:
            return None
        existing = dict(row)

        updates: dict[str, Any] = {}
        for key, raw in fields.items():
            # 忽略非白名单字段（含 rfq_id）
            if key not in _QUOTE_UPDATABLE:
                continue
            if key == "product_name":
                val = _norm_text(raw)
                if not val:
                    raise SupplierError("产品名称不能为空")
                updates[key] = val
            elif key in ("price_excl_tax", "price_incl_tax", "moq"):
                updates[key] = _parse_optional_float(raw, key)
            elif key == "source_customer_id":
                cust_id = _parse_optional_int(raw, "来源客户", min_val=1)
                # 若指定客户 ID，校验属于当前公司
                if cust_id is not None:
                    c_row = conn.execute(
                        "SELECT id FROM customers WHERE id = ? AND company_id = ?",
                        (cust_id, company_id),
                    ).fetchone()
                    if not c_row:
                        raise SupplierError("关联的来源客户不存在或不属于当前公司")
                updates[key] = cust_id
            elif key == "supplier_product_id":
                prod_id = _parse_optional_int(raw, "产品能力 ID", min_val=1)
                # 若指定能力行，校验属于同公司同供应商
                if prod_id is not None:
                    p_row = conn.execute(
                        "SELECT id FROM supplier_products WHERE id = ? AND company_id = ? AND supplier_id = ?",
                        (prod_id, company_id, existing["supplier_id"]),
                    ).fetchone()
                    if not p_row:
                        raise SupplierError("关联的产品能力行不存在或不属于该供应商")
                updates[key] = prod_id
            elif key in ("extra1", "extra2", "extra3"):
                updates[key] = _ensure_json_str(raw)
            else:
                updates[key] = _norm_text(raw)

        # 有修改字段时写回
        if updates:
            set_clause = ", ".join(f"{col} = ?" for col in updates)
            conn.execute(
                f"UPDATE supplier_quotes SET {set_clause}, updated_at = datetime('now', 'localtime') "
                "WHERE id = ? AND company_id = ?",
                (*updates.values(), quote_id, company_id),
            )
            conn.commit()
        updated = dict(
            conn.execute("SELECT * FROM supplier_quotes WHERE id = ?", (quote_id,)).fetchone()
        )
        return _decorate_quote(updated)
    finally:
        conn.close()


def delete_quote(quote_id: int, company_id: int) -> bool:
    """删除报价记录（严格按公司隔离）。"""
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM supplier_quotes WHERE id = ? AND company_id = ?",
            (quote_id, company_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def search_quotes(
    company_id: int,
    *,
    product_name: str = "",
    supplier_id: int | None = None,
    customer_id: int | None = None,
    limit: int = 200,
) -> list[dict]:
    """三向查询报价：支持按产品名（模糊）、供应商 ID、客户 ID 任一或组合筛选。"""
    conn = get_connection()
    try:
        where = ["sq.company_id = ?"]
        params: list[Any] = [company_id]

        prod_clean = _norm_text(product_name)
        # 按产品名模糊查询
        if prod_clean:
            where.append("sq.product_name LIKE ?")
            params.append(f"%{prod_clean}%")

        # 按供应商 ID 精确过滤
        if supplier_id is not None:
            where.append("sq.supplier_id = ?")
            params.append(int(supplier_id))

        # 按来源客户 ID 精确过滤
        if customer_id is not None:
            where.append("sq.source_customer_id = ?")
            params.append(int(customer_id))

        cap = max(1, min(int(limit or 200), 1000))
        sql = (
            "SELECT sq.*, s.name AS supplier_name, s.short_name AS supplier_short_name, "
            "s.tax_point AS supplier_tax_point, s.can_issue_vat AS supplier_can_issue_vat, "
            "c.name AS source_customer_name "
            "FROM supplier_quotes sq "
            "JOIN suppliers s ON s.id = sq.supplier_id AND s.company_id = sq.company_id "
            "LEFT JOIN customers c ON c.id = sq.source_customer_id AND c.company_id = sq.company_id "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY sq.quoted_at DESC, sq.id DESC LIMIT ?"
        )
        params.append(cap)
        today_str = date.today().isoformat()
        rows = conn.execute(sql, tuple(params)).fetchall()
        return [_decorate_quote(dict(r), today_str=today_str) for r in rows]
    finally:
        conn.close()


# ==============================================================================
# 比价聚合（§8.7 / A6）
# ==============================================================================


def _apply_tax_conversion(quote: dict, tax_point: float | None) -> dict:
    """按 §8.7 口径处理单边价格换算：有 tax_point 才换算并标 converted=True，绝不编造。"""
    item = dict(quote)
    excl = item.get("price_excl_tax")
    incl = item.get("price_incl_tax")
    item["price_excl_tax_converted"] = False
    item["price_incl_tax_converted"] = False
    item["converted"] = False

    # 无 tax_point 或两边都空/两边都有值：原样返回，不换算
    if tax_point is None or tax_point < 0:
        return item

    factor = 1.0 + float(tax_point) / 100.0
    # 仅有不含税价 → 换算含税价
    if excl is not None and incl is None:
        item["price_incl_tax"] = round(float(excl) * factor, 4)
        item["price_incl_tax_converted"] = True
        item["converted"] = True
    # 仅有含税价 → 换算不含税价
    elif incl is not None and excl is None:
        item["price_excl_tax"] = round(float(incl) / factor, 4)
        item["price_excl_tax_converted"] = True
        item["converted"] = True
    return item


def compare_product(
    company_id: int,
    *,
    product_name: str,
    spec_model: str = "",
) -> dict:
    """按品名（及可选规格）比价：按单位分组展示，不把不同单位混排成同一最低价。"""
    prod_clean = _norm_text(product_name)
    spec_clean = _norm_text(spec_model)
    # 未输入品名时返回空结构
    if not prod_clean:
        return {
            "product_name": "",
            "spec_model": spec_clean,
            "unit_groups": [],
            "no_quote_suppliers": [],
            "suppliers": [],
        }

    conn = get_connection()
    try:
        prod_where = ["sp.company_id = ?", "sp.product_name LIKE ?"]
        prod_params: list[Any] = [company_id, f"%{prod_clean}%"]
        # 附加规格过滤
        if spec_clean:
            prod_where.append("sp.spec_model LIKE ?")
            prod_params.append(f"%{spec_clean}%")

        product_rows = conn.execute(
            "SELECT sp.*, s.name AS supplier_name, s.short_name AS supplier_short_name, "
            "s.status AS supplier_status, s.rating AS supplier_rating, "
            "s.can_issue_vat, s.tax_point, s.payment_terms, s.lead_time_days AS supplier_lead_time_days "
            "FROM supplier_products sp "
            "JOIN suppliers s ON s.id = sp.supplier_id AND s.company_id = sp.company_id "
            f"WHERE {' AND '.join(prod_where)} "
            "ORDER BY sp.updated_at DESC, sp.id DESC",
            tuple(prod_params),
        ).fetchall()

        quote_where = ["sq.company_id = ?", "sq.product_name LIKE ?"]
        quote_params: list[Any] = [company_id, f"%{prod_clean}%"]
        # 附加规格过滤
        if spec_clean:
            quote_where.append("sq.spec_model LIKE ?")
            quote_params.append(f"%{spec_clean}%")

        quote_rows = conn.execute(
            "SELECT sq.*, s.name AS supplier_name, s.short_name AS supplier_short_name, "
            "s.status AS supplier_status, s.rating AS supplier_rating, "
            "s.can_issue_vat, s.tax_point, s.payment_terms, s.lead_time_days AS supplier_lead_time_days "
            "FROM supplier_quotes sq "
            "JOIN suppliers s ON s.id = sq.supplier_id AND s.company_id = sq.company_id "
            f"WHERE {' AND '.join(quote_where)} "
            "ORDER BY sq.quoted_at DESC, sq.id DESC",
            tuple(quote_params),
        ).fetchall()

        today_str = date.today().isoformat()

        # 按供应商聚合能力与报价
        supplier_map: dict[int, dict] = {}

        def _ensure_sup(r: dict) -> dict:
            sid = int(r["supplier_id"])
            if sid not in supplier_map:
                supplier_map[sid] = {
                    "supplier_id": sid,
                    "supplier_name": r.get("supplier_name") or "",
                    "supplier_short_name": r.get("supplier_short_name") or "",
                    "supplier_status": r.get("supplier_status") or "",
                    "supplier_rating": r.get("supplier_rating"),
                    "can_issue_vat": r.get("can_issue_vat"),
                    "tax_point": r.get("tax_point"),
                    "payment_terms": r.get("payment_terms") or "",
                    "products": [],
                    "quotes": [],
                }
            return supplier_map[sid]

        for pr in product_rows:
            rd = dict(pr)
            entry = _ensure_sup(rd)
            entry["products"].append({
                "id": rd["id"],
                "product_name": rd["product_name"],
                "spec_model": rd["spec_model"],
                "unit": rd["unit"],
                "is_self_produced": rd["is_self_produced"],
                "quality_note": rd["quality_note"],
                "lead_time_days": rd["lead_time_days"],
                "lead_time_text": rd["lead_time_text"],
                "moq": rd["moq"],
                "packing_info": rd["packing_info"],
                "notes": rd["notes"],
            })

        for qr in quote_rows:
            rd = dict(qr)
            entry = _ensure_sup(rd)
            decorated = _decorate_quote(rd, today_str=today_str)
            converted = _apply_tax_conversion(decorated, rd.get("tax_point"))
            entry["quotes"].append(converted)

        # 按报价单位分组：不同单位绝不混排进同一个最低价排序
        groups_by_unit: dict[str, dict[int, dict]] = {}
        no_quote_suppliers: list[dict] = []

        for sup_entry in supplier_map.values():
            # 只有能力行、没有报价的供应商单独列出
            if not sup_entry["quotes"]:
                no_quote_suppliers.append(sup_entry)
                continue

            # 按单位拆分该供应商的报价
            by_unit: dict[str, list[dict]] = {}
            for q_item in sup_entry["quotes"]:
                unit_key = _norm_text(q_item.get("unit")) or "未填单位"
                by_unit.setdefault(unit_key, []).append(q_item)

            for unit_key, u_quotes in by_unit.items():
                # 报价已按 quoted_at DESC, id DESC 排好，第 0 条即最近报价
                latest = u_quotes[0]
                # O-供2：价格区间仅统计原值，排除换算侧，与最低价口径一致
                excl_vals = [
                    q["price_excl_tax"]
                    for q in u_quotes
                    if q.get("price_excl_tax") is not None
                    and not q.get("price_excl_tax_converted")
                ]
                incl_vals = [
                    q["price_incl_tax"]
                    for q in u_quotes
                    if q.get("price_incl_tax") is not None
                    and not q.get("price_incl_tax_converted")
                ]
                # 优先取匹配单位的能力行，否则取该供应商首条能力行
                matched_prod = next(
                    (p for p in sup_entry["products"] if _norm_text(p.get("unit")) == unit_key),
                    sup_entry["products"][0] if sup_entry["products"] else None,
                )
                row_summary = {
                    "supplier_id": sup_entry["supplier_id"],
                    "supplier_name": sup_entry["supplier_name"],
                    "supplier_short_name": sup_entry["supplier_short_name"],
                    "supplier_status": sup_entry["supplier_status"],
                    "supplier_rating": sup_entry["supplier_rating"],
                    "can_issue_vat": sup_entry["can_issue_vat"],
                    "tax_point": sup_entry["tax_point"],
                    "payment_terms": sup_entry["payment_terms"],
                    "product": matched_prod,
                    "latest_quote": latest,
                    "quotes": u_quotes,
                    "quote_count": len(u_quotes),
                    "price_excl_range": [min(excl_vals), max(excl_vals)] if excl_vals else None,
                    "price_incl_range": [min(incl_vals), max(incl_vals)] if incl_vals else None,
                }
                groups_by_unit.setdefault(unit_key, {})[sup_entry["supplier_id"]] = row_summary

        unit_groups: list[dict] = []
        for unit_key, sup_rows_map in groups_by_unit.items():
            sup_rows = list(sup_rows_map.values())

            def _sort_key(item: dict) -> tuple:
                lq = item["latest_quote"]
                # O-供1：过期仍沉底；组内统一按含税价（原值优先，无原值用换算值）升序；
                # 无含税价（仅不含税且无加点）排在含税价之后，无任何价格的行排最后
                expired_rank = 1 if lq.get("expired") else 0
                p_incl = lq.get("price_incl_tax")
                p_excl = lq.get("price_excl_tax")
                if p_incl is not None:
                    # 原值优先于换算值（同价时原值排前）
                    conv_rank = 1 if lq.get("price_incl_tax_converted") else 0
                    return (expired_rank, 0, float(p_incl), conv_rank, item["supplier_id"])
                if p_excl is not None:
                    return (expired_rank, 1, float(p_excl), 0, item["supplier_id"])
                return (expired_rank, 2, float("inf"), 0, item["supplier_id"])

            sup_rows.sort(key=_sort_key)

            # 组内最低价仅统计未过期的原值（不含换算值，也不跨单位）
            valid_excl = [
                r["latest_quote"]["price_excl_tax"]
                for r in sup_rows
                if not r["latest_quote"].get("expired")
                and r["latest_quote"].get("price_excl_tax") is not None
                and not r["latest_quote"].get("price_excl_tax_converted")
            ]
            valid_incl = [
                r["latest_quote"]["price_incl_tax"]
                for r in sup_rows
                if not r["latest_quote"].get("expired")
                and r["latest_quote"].get("price_incl_tax") is not None
                and not r["latest_quote"].get("price_incl_tax_converted")
            ]

            unit_groups.append({
                "unit": unit_key,
                "suppliers": sup_rows,
                "lowest_excl_tax": min(valid_excl) if valid_excl else None,
                "lowest_incl_tax": min(valid_incl) if valid_incl else None,
            })

        return {
            "product_name": prod_clean,
            "spec_model": spec_clean,
            "unit_groups": unit_groups,
            "no_quote_suppliers": no_quote_suppliers,
            "suppliers": list(supplier_map.values()),
        }
    finally:
        conn.close()


# ==============================================================================
# CSV 模板批量导入（§4 / A9）
# ==============================================================================

_CSV_HEADER_ALIASES: dict[str, str] = {
    "供应商名称": "name",
    "供应商全称": "name",
    "name": "name",
    "简称": "short_name",
    "short_name": "short_name",
    "类型": "supplier_type",
    "供应商类型": "supplier_type",
    "supplier_type": "supplier_type",
    "主营品类": "main_products",
    "main_products": "main_products",
    "省": "province",
    "省份": "province",
    "province": "province",
    "市": "city",
    "城市": "city",
    "city": "city",
    "状态": "status",
    "status": "status",
    "可开专票": "can_issue_vat",
    "can_issue_vat": "can_issue_vat",
    "开票加点": "tax_point",
    "tax_point": "tax_point",
    "结算方式": "payment_terms",
    "payment_terms": "payment_terms",
    "联系人姓名": "contact_name",
    "contact_name": "contact_name",
    "联系人角色": "contact_role",
    "contact_role": "contact_role",
    "联系电话": "contact_phone",
    "contact_phone": "contact_phone",
    "微信": "contact_wechat",
    "contact_wechat": "contact_wechat",
    "产品名": "product_name",
    "产品名称": "product_name",
    "product_name": "product_name",
    "规格": "spec_model",
    "规格型号": "spec_model",
    "spec_model": "spec_model",
    "单位": "unit",
    "unit": "unit",
    "是否自产": "is_self_produced",
    "is_self_produced": "is_self_produced",
    "不含税价": "price_excl_tax",
    "price_excl_tax": "price_excl_tax",
    "含税价": "price_incl_tax",
    "price_incl_tax": "price_incl_tax",
    "moq": "moq",
    "报价日期": "quoted_at",
    "quoted_at": "quoted_at",
    "报价有效期": "valid_until",
    "valid_until": "valid_until",
}


def _normalize_csv_header(raw_col: str) -> str:
    """将 CSV 表头列名归一为内部键名（去除必填星号和括号说明）。"""
    cleaned = (raw_col or "").strip().rstrip("*").strip()
    # 去掉中文或英文括号内的填写提示，例如「是否自产（是/否/待确认）」→「是否自产」
    for sep in ("（", "("):
        if sep in cleaned:
            cleaned = cleaned.split(sep, 1)[0].strip()
    return _CSV_HEADER_ALIASES.get(cleaned) or _CSV_HEADER_ALIASES.get(cleaned.lower(), "")


def bulk_import_csv(company_id: int, csv_text: str) -> dict:
    """解析并导入供应商 CSV 模板：好行照常入库，坏行逐行报错；同名供应商合并为一家。"""
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        fieldnames = reader.fieldnames
    except csv.Error as exc:
        raise SupplierError(f"CSV 格式解析失败：{exc}")

    # 空文件或缺少表头直接拒绝
    if not fieldnames:
        raise SupplierError("CSV 文件为空或缺少表头")

    col_map = {col: _normalize_csv_header(col) for col in fieldnames}
    # 必须包含供应商名称列
    if "name" not in col_map.values():
        raise SupplierError("CSV 缺少必填列：供应商名称")

    conn = get_connection()
    try:
        # 预加载本公司已有供应商（按小写去空白名称索引）
        existing_rows = conn.execute(
            "SELECT id, name FROM suppliers WHERE company_id = ?",
            (company_id,),
        ).fetchall()
        name_to_id: dict[str, int] = {
            r["name"].strip().lower(): int(r["id"]) for r in existing_rows
        }

        created_suppliers = 0
        reused_suppliers = 0
        created_contacts = 0
        upserted_products = 0
        created_quotes = 0
        ok_rows = 0
        errors: list[dict] = []

        for idx, raw_row in enumerate(reader, start=2):
            row: dict[str, str] = {}
            for raw_col, internal_key in col_map.items():
                # 忽略未映射列
                if not internal_key:
                    continue
                val = raw_row.get(raw_col)
                row[internal_key] = val.strip() if isinstance(val, str) else ""

            # 跳过整行全空的尾行
            if not any(row.values()):
                continue

            sup_name = row.get("name", "")
            # 必填校验：供应商名称
            if not sup_name:
                errors.append({"row": idx, "error": "缺少供应商名称"})
                continue

            try:
                vat_val = _parse_tristate(row.get("can_issue_vat"), "可开专票", default=2)
                tax_val = _parse_optional_float(row.get("tax_point"), "开票加点")
                self_val = _parse_tristate(row.get("is_self_produced"), "是否自产", default=2)
                excl_val = _parse_optional_float(row.get("price_excl_tax"), "不含税价")
                incl_val = _parse_optional_float(row.get("price_incl_tax"), "含税价")
                moq_val = _parse_optional_float(row.get("moq"), "MOQ")
            except SupplierError as exc:
                errors.append({"row": idx, "error": str(exc)})
                continue

            name_key = sup_name.lower()
            # 同一文件或本公司已有同名供应商时合并复用
            if name_key in name_to_id:
                sup_id = name_to_id[name_key]
                reused_suppliers += 1
            else:
                cur = conn.execute(
                    "INSERT INTO suppliers ("
                    "company_id, name, short_name, supplier_type, main_products, "
                    "province, city, status, can_issue_vat, tax_point, payment_terms, source"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'template-import')",
                    (
                        company_id, sup_name, row.get("short_name", ""),
                        row.get("supplier_type", ""), row.get("main_products", ""),
                        row.get("province", ""), row.get("city", ""),
                        row.get("status", "") or "候选",
                        vat_val, tax_val, row.get("payment_terms", ""),
                    ),
                )
                sup_id = int(cur.lastrowid)
                name_to_id[name_key] = sup_id
                created_suppliers += 1

            # 联系人：填了联系人姓名时写入（同供应商同名同电话去重）
            contact_name = row.get("contact_name", "")
            if contact_name:
                contact_phone = row.get("contact_phone", "")
                dup_c = conn.execute(
                    "SELECT id FROM supplier_contacts "
                    "WHERE company_id = ? AND supplier_id = ? AND name = ? AND phone = ?",
                    (company_id, sup_id, contact_name, contact_phone),
                ).fetchone()
                if not dup_c:
                    has_primary = conn.execute(
                        "SELECT 1 FROM supplier_contacts WHERE supplier_id = ? AND is_primary = 1",
                        (sup_id,),
                    ).fetchone()
                    conn.execute(
                        "INSERT INTO supplier_contacts ("
                        "company_id, supplier_id, name, role, is_primary, phone, wechat"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            company_id, sup_id, contact_name,
                            row.get("contact_role", "") or "其他",
                            0 if has_primary else 1,
                            contact_phone, row.get("contact_wechat", ""),
                        ),
                    )
                    created_contacts += 1

            # 产品能力与报价：填了产品名时落能力行，并按需追加报价
            prod_name = row.get("product_name", "")
            if prod_name:
                spec_val = row.get("spec_model", "")
                unit_val = row.get("unit", "")
                conn.execute(
                    "INSERT INTO supplier_products ("
                    "company_id, supplier_id, product_name, spec_model, unit, is_self_produced, moq"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(company_id, supplier_id, product_name, spec_model) DO UPDATE SET "
                    "unit = CASE WHEN excluded.unit != '' THEN excluded.unit ELSE supplier_products.unit END, "
                    "is_self_produced = excluded.is_self_produced, "
                    "moq = COALESCE(excluded.moq, supplier_products.moq), "
                    "updated_at = datetime('now', 'localtime')",
                    (company_id, sup_id, prod_name, spec_val, unit_val, self_val, moq_val),
                )
                prod_row = conn.execute(
                    "SELECT id FROM supplier_products "
                    "WHERE company_id = ? AND supplier_id = ? AND product_name = ? AND spec_model = ?",
                    (company_id, sup_id, prod_name, spec_val),
                ).fetchone()
                prod_id = int(prod_row["id"]) if prod_row else None
                upserted_products += 1

                # 有任一价格或报价日期时追加一条报价历史
                if excl_val is not None or incl_val is not None or row.get("quoted_at"):
                    quoted_date = row.get("quoted_at") or date.today().isoformat()
                    conn.execute(
                        "INSERT INTO supplier_quotes ("
                        "company_id, supplier_id, supplier_product_id, product_name, spec_model, "
                        "unit, price_excl_tax, price_incl_tax, currency, moq, quoted_at, "
                        "valid_until, source"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'CNY', ?, ?, ?, 'template-import')",
                        (
                            company_id, sup_id, prod_id, prod_name, spec_val, unit_val,
                            excl_val, incl_val, moq_val, quoted_date, row.get("valid_until", ""),
                        ),
                    )
                    created_quotes += 1

            ok_rows += 1

        conn.commit()
        return {
            "ok_rows": ok_rows,
            "error_count": len(errors),
            "errors": errors,
            "created_suppliers": created_suppliers,
            "reused_suppliers": reused_suppliers,
            "created_contacts": created_contacts,
            "upserted_products": upserted_products,
            "created_quotes": created_quotes,
        }
    finally:
        conn.close()


# ==============================================================================
# AI 文件夹抽取与草稿确认区（§5 / A10 / A11）
# ==============================================================================

_SUPPLIER_QUOTE_EXTRACT_PROMPT = """\
你是供应商报价文档抽取器。只抽取文档里明确写出的供应商报价信息：
- 严禁用常识或猜测补全任何文档里没有的字段，尤其是价格、税率、日期、MOQ。
- 文档没有写价格时，price_excl_tax 和 price_incl_tax 必须都为 null。
- 文档只给了一个价格且未说明含税或不含税时，只填对应字段，另一字段必须为 null，严禁自行换算。
- 每条记录必须附带 raw_excerpt（原文中对应这行报价的摘录，供人工核对）。

严格输出 JSON（不要解释文字、不要 markdown 围栏）：
{"quotes": [
  {
    "supplier_name": "供应商名称（文档没有则空串）",
    "product_name": "产品名称（必填，没有则不要输出该条）",
    "spec_model": "规格型号（设备类可写年份/工时/配置，没有则空串）",
    "unit": "单位（没有则空串）",
    "price_excl_tax": null,
    "price_incl_tax": null,
    "currency": "CNY",
    "quoted_at": "YYYY-MM-DD（没有则空串）",
    "valid_until": "YYYY-MM-DD（没有则空串）",
    "raw_excerpt": "原文摘录"
  }
]}
"""

_EXTRACTABLE_SUFFIXES = frozenset({
    ".txt", ".md", ".csv", ".tsv", ".xlsx", ".docx", ".pdf",
})


def _expand_input_paths(raw_paths: list[str]) -> tuple[list[Path], list[dict]]:
    """展开传入的文件/文件夹路径列表，返回 (文件列表, 失败项列表)。"""
    files: list[Path] = []
    failed: list[dict] = []
    seen: set[str] = set()

    for raw in raw_paths:
        text = _norm_text(raw)
        # 跳过空路径
        if not text:
            continue
        p = Path(text)
        # 路径不存在记录失败，不阻塞其余文件
        if not p.exists():
            failed.append({"file": text, "error": "file_not_found"})
            continue
        if p.is_dir():
            # 遍历文件夹下的普通文件（不跟进符号链接）
            for child in sorted(p.rglob("*")):
                if child.is_symlink() or not child.is_file():
                    continue
                if child.suffix.lower() not in _EXTRACTABLE_SUFFIXES:
                    continue
                key = str(child.resolve())
                if key not in seen:
                    seen.add(key)
                    files.append(child)
        elif p.is_file():
            key = str(p.resolve())
            if key not in seen:
                seen.add(key)
                files.append(p)
    return files, failed


async def extract_files_to_drafts(company_id: int, file_paths: list[str]) -> dict:
    """从选定的文件/文件夹抽取供应商报价到草稿确认区（绝不直接写正式表）。"""
    # 先解析用户配置的抽取模型；未配置时直接报错返回
    resolved = doc_extract.resolve_extraction_model()
    if resolved is None:
        raise SupplierError("未配置对话/抽取模型，请先在设置中配置模型后再执行抽取")
    provider, model, _cache_key = resolved

    files, failed = _expand_input_paths(file_paths)
    created_drafts: list[dict] = []

    conn = get_connection()
    try:
        # 预加载本公司供应商名用于匹配 supplier_id
        sup_rows = conn.execute(
            "SELECT id, name FROM suppliers WHERE company_id = ?",
            (company_id,),
        ).fetchall()
        sup_by_name = {r["name"].strip().lower(): int(r["id"]) for r in sup_rows}

        for fpath in files:
            source_file = str(fpath)
            parsed = doc_extract.parse_document(fpath)
            # 复用 doc_extract 的确定性失败分类，单文件失败不阻塞整批
            if parsed.unsupported:
                failed.append({"file": source_file, "error": "unsupported_type"})
                continue
            if parsed.error:
                failed.append({"file": source_file, "error": f"parse_error: {parsed.error}"})
                continue
            if parsed.needs_ocr:
                failed.append({"file": source_file, "error": "needs_ocr"})
                continue
            if parsed.truncated:
                failed.append({"file": source_file, "error": "truncated"})
                continue
            if not parsed.text.strip() and not parsed.facts:
                failed.append({"file": source_file, "error": "empty"})
                continue

            prompt = (
                _SUPPLIER_QUOTE_EXTRACT_PROMPT
                + "\n\n## 文档内容\n\n"
                + (parsed.text.strip() or "（无文本，仅表格结构）")
                + "\n\n## 解析出的表格事实\n\n"
                + json.dumps(parsed.facts[:doc_extract._MAX_PARSED_FACTS], ensure_ascii=False)
            )
            messages = [{"role": "user", "content": prompt}]
            try:
                raw_out = await doc_extract._call_model(
                    messages,
                    provider=provider,
                    model=model,
                    timeout=doc_extract._extract_timeout(),
                )
            except Exception as exc:
                _log.warning("供应商报价抽取调用模型失败（%s）：%s", source_file, exc)
                failed.append({"file": source_file, "error": f"model_error: {exc}"})
                continue

            obj = doc_extract._parse_json_object(raw_out)
            # 模型返回无法解析为合法 JSON 时归入失败清单
            if obj is None or not isinstance(obj.get("quotes"), list):
                failed.append({"file": source_file, "error": "parse_error"})
                continue

            for item in obj["quotes"]:
                # 忽略非字典或缺少品名的条目
                if not isinstance(item, dict):
                    continue
                prod_name = _norm_text(item.get("product_name"))
                if not prod_name:
                    continue

                sup_raw = _norm_text(item.get("supplier_name"))
                matched_sid = sup_by_name.get(sup_raw.lower()) if sup_raw else None

                # 严格解析价格：非数字或空一律落 None，绝不编造
                try:
                    excl_val = _parse_optional_float(item.get("price_excl_tax"), "不含税价")
                except SupplierError:
                    excl_val = None
                try:
                    incl_val = _parse_optional_float(item.get("price_incl_tax"), "含税价")
                except SupplierError:
                    incl_val = None

                excerpt = _norm_text(item.get("raw_excerpt")) or (parsed.text.strip()[:300])
                cur = conn.execute(
                    "INSERT INTO supplier_quote_drafts ("
                    "company_id, supplier_id, supplier_name_raw, product_name, spec_model, unit, "
                    "price_excl_tax, price_incl_tax, currency, quoted_at, valid_until, "
                    "source_file, raw_excerpt, status"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
                    (
                        company_id, matched_sid, sup_raw, prod_name,
                        _norm_text(item.get("spec_model")), _norm_text(item.get("unit")),
                        excl_val, incl_val, _norm_text(item.get("currency")) or "CNY",
                        _norm_text(item.get("quoted_at")), _norm_text(item.get("valid_until")),
                        source_file, excerpt,
                    ),
                )
                draft_row = dict(
                    conn.execute(
                        "SELECT * FROM supplier_quote_drafts WHERE id = ?",
                        (cur.lastrowid,),
                    ).fetchone()
                )
                created_drafts.append(draft_row)

        conn.commit()
        return {
            "drafts_created": len(created_drafts),
            "drafts": created_drafts,
            "failed": failed,
            "files_processed": len(files),
        }
    finally:
        conn.close()


def list_drafts(company_id: int, *, status: str = "pending") -> list[dict]:
    """查询报价确认区草稿列表（默认 pending；传 all 返回全部状态）。"""
    conn = get_connection()
    try:
        st = _norm_text(status) or "pending"
        # status='all' 返回所有状态（含已批准/已驳回留痕）
        if st == "all":
            rows = conn.execute(
                "SELECT d.*, s.name AS matched_supplier_name "
                "FROM supplier_quote_drafts d "
                "LEFT JOIN suppliers s ON s.id = d.supplier_id AND s.company_id = d.company_id "
                "WHERE d.company_id = ? "
                "ORDER BY d.id DESC",
                (company_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT d.*, s.name AS matched_supplier_name "
                "FROM supplier_quote_drafts d "
                "LEFT JOIN suppliers s ON s.id = d.supplier_id AND s.company_id = d.company_id "
                "WHERE d.company_id = ? AND d.status = ? "
                "ORDER BY d.id DESC",
                (company_id, st),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


_DRAFT_UPDATABLE = {
    "supplier_id", "supplier_name_raw", "product_name", "spec_model", "unit",
    "price_excl_tax", "price_incl_tax", "currency", "quoted_at", "valid_until",
    "raw_excerpt",
}


def update_draft(draft_id: int, company_id: int, **fields: Any) -> dict | None:
    """人工修改待确认草稿字段；跨公司或不存在返回 None。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM supplier_quote_drafts WHERE id = ? AND company_id = ?",
            (draft_id, company_id),
        ).fetchone()
        # 不存在或跨公司
        if not row:
            return None

        updates: dict[str, Any] = {}
        for key, raw in fields.items():
            # 忽略非白名单字段
            if key not in _DRAFT_UPDATABLE:
                continue
            if key == "supplier_id":
                sid = _parse_optional_int(raw, "供应商 ID", min_val=1)
                # 若手动关联供应商，校验其属于本公司
                if sid is not None and not _check_supplier_belongs(conn, sid, company_id):
                    raise SupplierError("关联的供应商不存在或不属于当前公司")
                updates[key] = sid
            elif key in ("price_excl_tax", "price_incl_tax"):
                updates[key] = _parse_optional_float(raw, key)
            else:
                updates[key] = _norm_text(raw)

        # 有修改字段时更新草稿
        if updates:
            set_clause = ", ".join(f"{col} = ?" for col in updates)
            conn.execute(
                f"UPDATE supplier_quote_drafts SET {set_clause}, updated_at = datetime('now', 'localtime') "
                "WHERE id = ? AND company_id = ?",
                (*updates.values(), draft_id, company_id),
            )
            conn.commit()
        return dict(
            conn.execute("SELECT * FROM supplier_quote_drafts WHERE id = ?", (draft_id,)).fetchone()
        )
    finally:
        conn.close()


def approve_draft(draft_id: int, company_id: int) -> dict | None:
    """批准草稿入正式库：生成 supplier_quotes（source='ai-extract'）并补齐供应商与能力行。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM supplier_quote_drafts WHERE id = ? AND company_id = ?",
            (draft_id, company_id),
        ).fetchone()
        # 不存在或跨公司
        if not row:
            return None
        draft = dict(row)
        # 仅 pending 草稿允许批准，避免重复入库
        if draft["status"] != "pending":
            raise SupplierError(f"草稿当前状态为 {draft['status']}，不可重复批准")

        prod_name = _norm_text(draft.get("product_name"))
        # 品名是入库必填字段
        if not prod_name:
            raise SupplierError("草稿缺少产品名称，请先编辑补全后再批准")

        sup_id = draft.get("supplier_id")
        # 校验草稿上绑定的 supplier_id 确实属于本公司
        if sup_id is not None and not _check_supplier_belongs(conn, int(sup_id), company_id):
            sup_id = None

        sup_created = False
        # 未匹配到 supplier_id 时按 supplier_name_raw 找同名供应商，找不到则新建
        if sup_id is None:
            sup_name = _norm_text(draft.get("supplier_name_raw"))
            if not sup_name:
                raise SupplierError("草稿缺少供应商名称，请先编辑补全或关联已有供应商后再批准")
            found = conn.execute(
                "SELECT id FROM suppliers WHERE company_id = ? AND LOWER(TRIM(name)) = LOWER(?)",
                (company_id, sup_name),
            ).fetchone()
            if found:
                sup_id = int(found["id"])
            else:
                cur_s = conn.execute(
                    "INSERT INTO suppliers (company_id, name, status, source) "
                    "VALUES (?, ?, '候选', 'ai-extract')",
                    (company_id, sup_name),
                )
                sup_id = int(cur_s.lastrowid)
                sup_created = True

        spec_val = _norm_text(draft.get("spec_model"))
        unit_val = _norm_text(draft.get("unit"))

        # 能力行不存在时顺带建一条，is_self_produced 固定为 2（待确认），绝不从文档猜
        prod_row = conn.execute(
            "SELECT id FROM supplier_products "
            "WHERE company_id = ? AND supplier_id = ? AND product_name = ? AND spec_model = ?",
            (company_id, sup_id, prod_name, spec_val),
        ).fetchone()
        if prod_row:
            prod_id = int(prod_row["id"])
        else:
            cur_p = conn.execute(
                "INSERT INTO supplier_products ("
                "company_id, supplier_id, product_name, spec_model, unit, is_self_produced"
                ") VALUES (?, ?, ?, ?, ?, 2)",
                (company_id, sup_id, prod_name, spec_val, unit_val),
            )
            prod_id = int(cur_p.lastrowid)

        # O-供3：草稿未注明报价日期时留空字符串，不再填批准当天
        quoted_date = _norm_text(draft.get("quoted_at"))
        cur_q = conn.execute(
            "INSERT INTO supplier_quotes ("
            "company_id, supplier_id, supplier_product_id, product_name, spec_model, unit, "
            "price_excl_tax, price_incl_tax, currency, quoted_at, valid_until, "
            "rfq_id, source, source_ref"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'ai-extract', ?)",
            (
                company_id, sup_id, prod_id, prod_name, spec_val, unit_val,
                draft.get("price_excl_tax"), draft.get("price_incl_tax"),
                _norm_text(draft.get("currency")) or "CNY",
                quoted_date, _norm_text(draft.get("valid_until")),
                draft["source_file"],
            ),
        )
        quote_id = int(cur_q.lastrowid)

        conn.execute(
            "UPDATE supplier_quote_drafts "
            "SET status = 'approved', supplier_id = ?, updated_at = datetime('now', 'localtime') "
            "WHERE id = ? AND company_id = ?",
            (sup_id, draft_id, company_id),
        )
        conn.commit()

        quote = _decorate_quote(
            dict(conn.execute("SELECT * FROM supplier_quotes WHERE id = ?", (quote_id,)).fetchone())
        )
        updated_draft = dict(
            conn.execute("SELECT * FROM supplier_quote_drafts WHERE id = ?", (draft_id,)).fetchone()
        )
        return {
            "draft": updated_draft,
            "quote": quote,
            "supplier_id": sup_id,
            "supplier_created": sup_created,
            "product_id": prod_id,
        }
    finally:
        conn.close()


def reject_draft(draft_id: int, company_id: int) -> dict | None:
    """驳回草稿（置 status='rejected'，留痕不删除）。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM supplier_quote_drafts WHERE id = ? AND company_id = ?",
            (draft_id, company_id),
        ).fetchone()
        # 不存在或跨公司
        if not row:
            return None
        conn.execute(
            "UPDATE supplier_quote_drafts "
            "SET status = 'rejected', updated_at = datetime('now', 'localtime') "
            "WHERE id = ? AND company_id = ?",
            (draft_id, company_id),
        )
        conn.commit()
        return dict(
            conn.execute("SELECT * FROM supplier_quote_drafts WHERE id = ?", (draft_id,)).fetchone()
        )
    finally:
        conn.close()
