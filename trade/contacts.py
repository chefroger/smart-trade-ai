"""附加联系人存取（第 2 人起）。

主联系人唯一真源仍是 customers.contact + extra2；本表永不种子主联系人，
写操作也不回写 extra2。表缺失时只读路径降级、写路径抛 ContactsUnavailableError。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from trade import customer as customer_module
from trade.database import begin_immediate, get_connection

# function 白名单；脏值归一为「其他」
_FUNCTIONS = frozenset({"决策人", "财务", "仓储", "其他"})

_MISSING_MSG = "请重启 Trade 完成升级"


class ContactsUnavailableError(Exception):
    """contacts 表尚未建好（升级后未重启）。"""


class ContactValidationError(Exception):
    """字段校验失败，API 层映射为 400。"""


def _is_missing_table(exc: BaseException) -> bool:
    """判断是否为 contacts 表不存在。"""
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    msg = str(exc).lower()
    return "no such table" in msg and "contacts" in msg


def _normalize_function(raw: Any) -> str:
    """白名单外的 function 归一为「其他」。"""
    s = str(raw or "").strip()
    if s in _FUNCTIONS:
        return s
    return "其他"


def _trim(raw: Any) -> str:
    """字段 trim，None 当空串。"""
    return str(raw or "").strip()


_STR_FIELDS = (
    "name",
    "function",
    "title",
    "responsibility",
    "email",
    "phone",
    "whatsapp",
    "wechat",
    "note",
)
_PRIMARY_OK = (None, 0, 1, True, False, "0", "1")


def _require_str_or_none(key: str, raw: Any) -> str | None:
    """字符串字段只接受 str 或 None，禁止 str(数字) 悄悄转换。"""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ContactValidationError(f"字段 {key} 必须是字符串")
    return raw


def _validate_payload(data: dict, *, partial: bool = False) -> dict:
    """校验并规范化写入字段；partial=True 时只处理传入的键。"""
    out: dict[str, Any] = {}

    # is_primary：只接受布尔/0/1/"0"/"1"/None；=1 仍拒绝
    if "is_primary" in data:
        raw_p = data["is_primary"]
        if raw_p not in _PRIMARY_OK:
            raise ContactValidationError("字段 is_primary 必须是 0 或 1")
        if raw_p in (1, True, "1"):
            raise ContactValidationError(
                "主联系人请在客户资料中编辑，contacts 只存附加联系人"
            )

    if not partial or "name" in data:
        name = _trim(_require_str_or_none("name", data.get("name")))
        if not name:
            raise ContactValidationError("姓名不能为空")
        out["name"] = name

    if not partial or "email" in data:
        email = _trim(_require_str_or_none("email", data.get("email")))
        if email and "@" not in email:
            raise ContactValidationError("邮箱格式不正确（需包含 @）")
        out["email"] = email

    if not partial or "function" in data:
        fn = _require_str_or_none("function", data.get("function"))
        out["function"] = _normalize_function(fn if fn is not None else "")

    for key in ("title", "responsibility", "phone", "whatsapp", "wechat", "note"):
        if not partial or key in data:
            out[key] = _trim(_require_str_or_none(key, data.get(key)))

    out["is_primary"] = 0
    return out


def build_primary_person(cust: dict) -> dict | None:
    """从 customers.contact + extra2 拼装主联系人；无可展示信息时返回 None。

    contact 含 @ 时 name 一律为空（显示「未命名联系人」）；
    email 优先 extra2.email，为空才用 contact 里的地址。只读拼装，不改库。
    """
    try:
        import json

        e2 = json.loads(cust.get("extra2") or "{}")
    except (json.JSONDecodeError, TypeError):
        e2 = {}
    if not isinstance(e2, dict):
        e2 = {}

    contact_raw = _trim(cust.get("contact"))
    title = _trim(e2.get("title"))
    email = _trim(e2.get("email"))
    backup = _trim(e2.get("backup_email"))
    phone = _trim(e2.get("phone"))
    whatsapp = _trim(e2.get("whatsapp"))
    wechat = _trim(e2.get("wechat"))

    # 可展示判据：姓名列或任一联系字段非空
    if not any((contact_raw, title, email, backup, phone, whatsapp, wechat)):
        return None

    # contact 形如邮箱：name 一律空；e2.email 空时才用 contact 当 email
    name = contact_raw
    if contact_raw and "@" in contact_raw:
        name = ""
        if not email:
            email = contact_raw

    # 主联系人职能/职责存 extra2；空/脏值归一「其他」（与附加联系人白名单一致）
    function = _normalize_function(e2.get("function"))
    responsibility = _trim(e2.get("responsibility"))

    display_name = name if name else "未命名联系人"
    # 2026-11-18 口径：主联系人是只读拼装，备注不拼客户级 note / follow_up_note（客户级字段只在客户卡显示）
    return {
        "id": None,
        "name": display_name,
        "role": title,
        "title": title,
        "function": function,
        "responsibility": responsibility,
        "email": email,
        "phone": phone,
        "whatsapp": whatsapp,
        "wechat": wechat,
        "note": "",
        "is_primary": True,
        "backup_email": backup,
    }


def _row_to_person(row: sqlite3.Row | dict) -> dict:
    """contacts 行 → overview/API 人物字典。"""
    d = dict(row) if not isinstance(row, dict) else row
    title = _trim(d.get("title"))
    function = _normalize_function(d.get("function"))
    # role：title 非空用 title，否则 function（墙副标题不得空）
    role = title if title else function
    return {
        "id": int(d["id"]) if d.get("id") is not None else None,
        "name": _trim(d.get("name")),
        "role": role,
        "title": title,
        "function": function,
        "responsibility": _trim(d.get("responsibility")),
        "email": _trim(d.get("email")),
        "phone": _trim(d.get("phone")),
        "whatsapp": _trim(d.get("whatsapp")),
        "wechat": _trim(d.get("wechat")),
        "note": _trim(d.get("note")),
        "is_primary": False,
    }


def list_additional(
    customer_id: int, *, company_id: int, conn: sqlite3.Connection | None = None
) -> list[dict]:
    """列出附加联系人（id 升序）。表缺失返回 []。"""
    own = conn is None
    if own:
        conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM contacts WHERE customer_id = ? AND company_id = ? "
            "ORDER BY id ASC",
            (customer_id, company_id),
        ).fetchall()
        return [_row_to_person(r) for r in rows]
    except sqlite3.OperationalError as exc:
        if _is_missing_table(exc):
            return []
        raise
    finally:
        if own:
            conn.close()


def get_bundle(customer_id: int, *, company_id: int) -> dict | None:
    """GET 列表：{primary, contacts}；客户不存在返回 None。"""
    cust = customer_module.get(customer_id, company_id=company_id)
    if not cust:
        return None
    primary = build_primary_person(cust)
    # primary 对外不暴露 backup_email 键（emails 列表另算）
    if primary is not None:
        primary = {k: v for k, v in primary.items() if k != "backup_email"}
    extras = list_additional(customer_id, company_id=company_id)
    return {"primary": primary, "contacts": extras}


def create(customer_id: int, *, company_id: int, data: dict) -> dict:
    """新建附加联系人。"""
    cust = customer_module.get(customer_id, company_id=company_id)
    if not cust:
        raise LookupError("客户不存在")
    fields = _validate_payload(data, partial=False)
    conn = get_connection()
    try:
        begin_immediate(conn)
        cur = conn.execute(
            """
            INSERT INTO contacts (
                company_id, customer_id, name, function, title, responsibility,
                is_primary, email, phone, whatsapp, wechat, note
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
            """,
            (
                company_id,
                customer_id,
                fields["name"],
                fields["function"],
                fields["title"],
                fields["responsibility"],
                fields["email"],
                fields["phone"],
                fields["whatsapp"],
                fields["wechat"],
                fields["note"],
            ),
        )
        new_id = int(cur.lastrowid)
        conn.commit()
        row = conn.execute(
            "SELECT * FROM contacts WHERE id = ? AND customer_id = ? AND company_id = ?",
            (new_id, customer_id, company_id),
        ).fetchone()
        return _row_to_person(row)
    except sqlite3.OperationalError as exc:
        conn.rollback()
        if _is_missing_table(exc):
            raise ContactsUnavailableError(_MISSING_MSG) from exc
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update(
    customer_id: int, contact_id: int, *, company_id: int, data: dict
) -> dict | None:
    """修改附加联系人；不存在返回 None。"""
    cust = customer_module.get(customer_id, company_id=company_id)
    if not cust:
        raise LookupError("客户不存在")
    fields = _validate_payload(data, partial=True)
    conn = get_connection()
    try:
        begin_immediate(conn)
        row = conn.execute(
            "SELECT * FROM contacts WHERE id = ? AND customer_id = ? AND company_id = ?",
            (contact_id, customer_id, company_id),
        ).fetchone()
        if not row:
            conn.rollback()
            return None
        # 合并：未传的键保留原值
        merged = dict(row)
        merged.update(fields)
        conn.execute(
            """
            UPDATE contacts SET
                name = ?, function = ?, title = ?, responsibility = ?,
                is_primary = 0, email = ?, phone = ?, whatsapp = ?, wechat = ?,
                note = ?, updated_at = datetime('now', 'localtime')
            WHERE id = ? AND customer_id = ? AND company_id = ?
            """,
            (
                _trim(merged.get("name")),
                _normalize_function(merged.get("function")),
                _trim(merged.get("title")),
                _trim(merged.get("responsibility")),
                _trim(merged.get("email")),
                _trim(merged.get("phone")),
                _trim(merged.get("whatsapp")),
                _trim(merged.get("wechat")),
                _trim(merged.get("note")),
                contact_id,
                customer_id,
                company_id,
            ),
        )
        conn.commit()
        fresh = conn.execute(
            "SELECT * FROM contacts WHERE id = ? AND customer_id = ? AND company_id = ?",
            (contact_id, customer_id, company_id),
        ).fetchone()
        return _row_to_person(fresh)
    except sqlite3.OperationalError as exc:
        conn.rollback()
        if _is_missing_table(exc):
            raise ContactsUnavailableError(_MISSING_MSG) from exc
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete(customer_id: int, contact_id: int, *, company_id: int) -> bool:
    """删除附加联系人；删除成功返回 True。"""
    cust = customer_module.get(customer_id, company_id=company_id)
    if not cust:
        raise LookupError("客户不存在")
    conn = get_connection()
    try:
        begin_immediate(conn)
        cur = conn.execute(
            "DELETE FROM contacts WHERE id = ? AND customer_id = ? AND company_id = ?",
            (contact_id, customer_id, company_id),
        )
        conn.commit()
        return cur.rowcount > 0
    except sqlite3.OperationalError as exc:
        conn.rollback()
        if _is_missing_table(exc):
            raise ContactsUnavailableError(_MISSING_MSG) from exc
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_for_customer(
    conn: sqlite3.Connection, customer_id: int, company_id: int
) -> None:
    """同事务内显式删客户的 contacts（双保险；表缺失则静默）。"""
    try:
        conn.execute(
            "DELETE FROM contacts WHERE customer_id = ? AND company_id = ?",
            (customer_id, company_id),
        )
    except sqlite3.OperationalError as exc:
        if _is_missing_table(exc):
            return
        raise


def collect_email_details(cust: dict, extras: list[dict]) -> list[dict]:
    """主 / backup / 附加联系人邮箱的结构化列表（去重，主优先）。

    每项：{address, is_primary, contact_id|null, source: primary|backup|contact}。
    e2.email 为空且 contact 形如邮箱时，把 contact 当主地址；e2.email 有值时
    contact 里的地址不进列表。
    """
    try:
        import json

        e2 = json.loads(cust.get("extra2") or "{}")
    except (json.JSONDecodeError, TypeError):
        e2 = {}
    if not isinstance(e2, dict):
        e2 = {}

    details: list[dict] = []
    seen: set[str] = set()

    def _add(raw: Any, *, is_primary: bool, contact_id: int | None, source: str) -> None:
        # 空串或已见过的地址跳过，保持主邮箱优先顺序
        s = _trim(raw).lower()
        if not s or s in seen:
            return
        seen.add(s)
        details.append({
            "address": s,
            "is_primary": is_primary,
            "contact_id": contact_id,
            "source": source,
        })

    e2_email = _trim(e2.get("email"))
    contact_raw = _trim(cust.get("contact"))
    if e2_email:
        _add(e2_email, is_primary=True, contact_id=None, source="primary")
    elif contact_raw and "@" in contact_raw:
        _add(contact_raw, is_primary=True, contact_id=None, source="primary")
    _add(e2.get("backup_email"), is_primary=False, contact_id=None, source="backup")
    for p in extras:
        cid = p.get("id")
        try:
            cid_int = int(cid) if cid is not None else None
        except (TypeError, ValueError):
            cid_int = None
        _add(p.get("email"), is_primary=False, contact_id=cid_int, source="contact")
    return details


def collect_email_addrs(cust: dict, extras: list[dict]) -> list[str]:
    """主 email + backup + 附加联系人 email；lower/strip 去重，主优先。

    兼容旧调用方；新代码优先用 collect_email_details。
    """
    return [d["address"] for d in collect_email_details(cust, extras)]
