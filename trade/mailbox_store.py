"""邮箱绑定存储：凭证文件、mailbox CRUD、匹配入库、拉取编排（分步实现）。"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import datetime
from email.utils import parseaddr
from pathlib import Path
from typing import Any

from trade.database import _get_db_path, get_connection
from trade.mailbox import PRESETS, MailboxError, fetch_new, test_connection

PULL_TIMEOUT_SEC = 120


def secrets_path() -> Path:
    """凭证文件与 trade.db 同目录。"""
    return _get_db_path().parent / "mailbox_secrets.json"


def _load_secrets() -> dict[str, str]:
    """从磁盘读取凭证映射；缺失、损坏或非对象 JSON 一律返回空 dict。"""
    p = secrets_path()
    # 文件不存在时无需创建，调用方按空映射处理
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # 损坏/半截写入：降级为空，避免绑定/拉取整条链路 500（同 license.py）
        return {}
    # 根节点必须是对象；[] / "x" / null 不当成映射
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def _save_secrets(data: dict[str, str]) -> None:
    """写入凭证 JSON，非 Windows 上限制为仅属主读写。"""
    p = secrets_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # Windows 不支持可靠 chmod，跳过
    if os.name != "nt":
        os.chmod(p, 0o600)


def get_secret(mailbox_id: int) -> str | None:
    """读取指定 mailbox 的授权码/凭证；无则 None。"""
    return _load_secrets().get(str(mailbox_id))


def set_secret(mailbox_id: int, secret: str) -> None:
    """保存指定 mailbox 的凭证（不落库、不写日志）。"""
    data = _load_secrets()
    data[str(mailbox_id)] = secret
    _save_secrets(data)


def delete_secret(mailbox_id: int) -> None:
    """删除指定 mailbox 的凭证项。"""
    data = _load_secrets()
    data.pop(str(mailbox_id), None)
    _save_secrets(data)


# ==== 地址归一化与客户匹配 ====


def normalize_addr(s: str) -> str:
    """邮箱地址小写 strip；尽量从 From/To 显示串抽出尖括号内地址。"""
    raw = (s or "").strip()
    if not raw:
        return ""
    _name, addr = parseaddr(raw)
    candidate = (addr or raw).strip()
    # 仍带尖括号时回退正则
    m = re.search(r"<([^>]+)>", candidate)
    if m:
        candidate = m.group(1)
    return candidate.strip().lower()


def find_customer_matches(from_addr: str, to_addrs: list[str]) -> list[tuple[int, int]]:
    """扫全部公司 customers.extra2 的 email/backup_email，与 From/To 不区分大小写匹配。"""
    want: set[str] = set()
    nf = normalize_addr(from_addr)
    if nf:
        want.add(nf)
    for raw in to_addrs or []:
        na = normalize_addr(raw)
        if na:
            want.add(na)
    if not want:
        return []

    conn = get_connection()
    pairs: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    rows = conn.execute(
        "SELECT company_id, id, extra2 FROM customers"
    ).fetchall()
    for row in rows:
        try:
            e2 = json.loads(row["extra2"] or "{}")
        except json.JSONDecodeError:
            e2 = {}
        for key in ("email", "backup_email"):
            val = normalize_addr(str(e2.get(key) or ""))
            if val and val in want:
                pair = (int(row["company_id"]), int(row["id"]))
                if pair not in seen:
                    seen.add(pair)
                    pairs.append(pair)
    return pairs


# ==== 邮件入库 ====


def insert_email_ignore(conn: sqlite3.Connection, mailbox_id: int, msg: dict) -> int | None:
    """INSERT OR IGNORE；重复 message_id 不更新正文（D1）。"""
    to_list = msg.get("to_addrs") or []
    to_json = json.dumps(to_list, ensure_ascii=False)
    uid = msg.get("uid")
    uid_s = str(uid) if uid is not None else None
    conn.execute(
        """
        INSERT OR IGNORE INTO emails
        (mailbox_id, message_id, uid, from_addr, to_addrs, subject, snippet, body_text, received_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            mailbox_id,
            msg.get("message_id") or "",
            uid_s,
            msg.get("from_addr") or "",
            to_json,
            msg.get("subject") or "",
            msg.get("snippet") or "",
            msg.get("body_text") or "",
            msg.get("received_at") or "",
        ),
    )
    row = conn.execute(
        "SELECT id FROM emails WHERE mailbox_id = ? AND message_id = ?",
        (mailbox_id, msg.get("message_id") or ""),
    ).fetchone()
    return int(row["id"]) if row else None


def attach_matches(
    conn: sqlite3.Connection,
    email_id: int,
    pairs: list[tuple[int, int]],
) -> int:
    """写入 email_matches；INSERT OR IGNORE，返回新插入行数。"""
    added = 0
    for company_id, customer_id in pairs:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO email_matches (email_id, company_id, customer_id)
            VALUES (?, ?, ?)
            """,
            (email_id, company_id, customer_id),
        )
        if cur.rowcount > 0:
            added += 1
    return added


def _ingest_message(
    conn: sqlite3.Connection,
    mailbox_id: int,
    msg: dict,
) -> tuple[bool, int]:
    """单封入库+匹配；返回 (是否新插入邮件, 本封新增匹配数)。"""
    before = conn.execute(
        "SELECT COUNT(*) AS c FROM emails WHERE mailbox_id = ?",
        (mailbox_id,),
    ).fetchone()["c"]
    email_id = insert_email_ignore(conn, mailbox_id, msg)
    if email_id is None:
        return False, 0
    after = conn.execute(
        "SELECT COUNT(*) AS c FROM emails WHERE mailbox_id = ?",
        (mailbox_id,),
    ).fetchone()["c"]
    is_new = after > before
    pairs = find_customer_matches(msg.get("from_addr") or "", msg.get("to_addrs") or [])
    matched = attach_matches(conn, email_id, pairs)
    return is_new, matched


# ==== Mailbox CRUD ====


def _mailbox_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """sqlite Row → 普通 dict。"""
    return {k: row[k] for k in row.keys()}


def create_mailbox(
    preset: str,
    email_address: str,
    secret: str,
    *,
    display_name: str = "",
    host: str | None = None,
    port: int | None = None,
    username: str | None = None,
) -> dict[str, Any]:
    """创建 IMAP 邮箱绑定；provider 恒为 imap，测通后写库并保存凭证。"""
    if preset in PRESETS:
        phost, pport = PRESETS[preset]
        host = host or phost
        port = port or pport
    else:
        if not host:
            raise ValueError("自定义预设必须提供 host")
        port = port if port is not None else 993

    username = (username or email_address).strip()
    email_address = email_address.strip()
    test_connection(str(host), int(port), username, secret)

    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO mailboxes
            (provider, preset, display_name, email_address, host, port, use_ssl, username)
            VALUES ('imap', ?, ?, ?, ?, ?, 1, ?)
            """,
            (preset, display_name, email_address, host, port, username),
        )
        mailbox_id = int(cur.lastrowid)
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise ValueError("该邮箱地址已绑定") from exc

    set_secret(mailbox_id, secret)
    row = conn.execute("SELECT * FROM mailboxes WHERE id = ?", (mailbox_id,)).fetchone()
    return _mailbox_row_to_dict(row)


def list_mailboxes() -> list[dict[str, Any]]:
    """列表含 has_secret、email_count，不返回 secret。"""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT m.*, COUNT(e.id) AS email_count
        FROM mailboxes m
        LEFT JOIN emails e ON e.mailbox_id = m.id
        GROUP BY m.id
        ORDER BY m.id
        """
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = _mailbox_row_to_dict(row)
        mid = int(item["id"])
        item["has_secret"] = get_secret(mid) is not None
        item["email_count"] = int(item.get("email_count") or 0)
        out.append(item)
    return out


def delete_mailbox(mailbox_id: int) -> None:
    """删除 mailbox、关联邮件、匹配与凭证。"""
    conn = get_connection()
    try:
        ids = [
            int(r["id"])
            for r in conn.execute(
                "SELECT id FROM emails WHERE mailbox_id = ?", (mailbox_id,)
            ).fetchall()
        ]
        if ids:
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"DELETE FROM email_matches WHERE email_id IN ({placeholders})",
                ids,
            )
        conn.execute("DELETE FROM emails WHERE mailbox_id = ?", (mailbox_id,))
        conn.execute("DELETE FROM mailboxes WHERE id = ?", (mailbox_id,))
        conn.commit()
    finally:
        conn.close()
    delete_secret(mailbox_id)


def update_secret(mailbox_id: int, secret: str) -> None:
    """更新凭证：先测通，失败则保留旧凭证。"""
    conn = get_connection()
    row = conn.execute("SELECT * FROM mailboxes WHERE id = ?", (mailbox_id,)).fetchone()
    if row is None:
        raise ValueError("邮箱不存在")
    old_secret = get_secret(mailbox_id)
    host = row["host"]
    port = int(row["port"] or 993)
    username = row["username"] or row["email_address"]
    try:
        test_connection(host, port, username, secret)
    except MailboxError:
        # 测通失败：不写新 secret
        if old_secret is not None:
            set_secret(mailbox_id, old_secret)
        raise
    set_secret(mailbox_id, secret)


# ==== 拉取编排 ====


def pull_one(mailbox_id: int) -> dict[str, Any]:
    """拉取单 mailbox；120s 超时则提交已入库并推进 last_uid 到已成功最大 UID。"""
    secret = get_secret(mailbox_id)
    if not secret:
        return {"pulled": 0, "matched": 0, "error": "未配置邮箱凭证"}

    conn = get_connection()
    row = conn.execute("SELECT * FROM mailboxes WHERE id = ?", (mailbox_id,)).fetchone()
    if row is None:
        return {"pulled": 0, "matched": 0, "error": "邮箱不存在"}

    mailbox_dict = _mailbox_row_to_dict(row)
    try:
        messages, cursor_update = fetch_new(mailbox_dict, secret)
    except MailboxError as exc:
        conn.execute(
            "UPDATE mailboxes SET last_error = ? WHERE id = ?",
            (str(exc), mailbox_id),
        )
        conn.commit()
        return {"pulled": 0, "matched": 0, "error": str(exc)}

    deadline = time.monotonic() + PULL_TIMEOUT_SEC
    pulled = 0
    matched_total = 0
    max_ingested_uid: int | None = None
    last_uidvalidity = cursor_update.get("last_uidvalidity")
    timed_out = False

    for msg in messages:
        if time.monotonic() >= deadline:
            # 超时：停拉但不回滚已写入
            timed_out = True
            break
        _is_new, matched_n = _ingest_message(conn, mailbox_id, msg)
        pulled += 1
        matched_total += matched_n
        uid = msg.get("uid")
        if uid is not None:
            try:
                uid_i = int(uid)
            except (TypeError, ValueError):
                uid_i = None
            if uid_i is not None:
                if max_ingested_uid is None or uid_i > max_ingested_uid:
                    max_ingested_uid = uid_i

    now = datetime.now().astimezone().replace(microsecond=0).isoformat()
    if timed_out:
        last_uid = max_ingested_uid if max_ingested_uid is not None else (row["last_uid"] or 0)
        last_error = f"超时已拉 {pulled}"
        conn.execute(
            """
            UPDATE mailboxes
            SET last_uid = ?, last_uidvalidity = ?, last_sync_at = ?, last_error = ?
            WHERE id = ?
            """,
            (last_uid, last_uidvalidity, now, last_error, mailbox_id),
        )
        conn.commit()
        return {"pulled": pulled, "matched": matched_total, "error": last_error}

    # 全量完成：游标与 fetch_new 一致
    conn.execute(
        """
        UPDATE mailboxes
        SET last_uid = ?, last_uidvalidity = ?, last_sync_at = ?, last_error = NULL
        WHERE id = ?
        """,
        (
            cursor_update.get("last_uid"),
            cursor_update.get("last_uidvalidity"),
            now,
            mailbox_id,
        ),
    )
    conn.commit()
    return {"pulled": pulled, "matched": matched_total}


def pull_all() -> dict[str, Any]:
    """串行 pull_one，返回各邮箱结果列表。"""
    results: list[dict[str, Any]] = []
    for item in list_mailboxes():
        mid = int(item["id"])
        one = pull_one(mid)
        one["mailbox_id"] = mid
        results.append(one)
    return {"results": results}


def list_customer_emails(
    company_id: int,
    customer_id: int,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """客户关联邮件：JOIN email_matches，按 received_at 降序。"""
    lim = max(1, min(int(limit), 50))
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT e.*
        FROM emails e
        INNER JOIN email_matches m ON m.email_id = e.id
        WHERE m.company_id = ? AND m.customer_id = ?
        ORDER BY e.received_at DESC
        LIMIT ?
        """,
        (company_id, customer_id, lim),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = _mailbox_row_to_dict(row)
        raw = item.get("to_addrs") or "[]"
        try:
            item["to_addrs"] = json.loads(raw)
        except json.JSONDecodeError:
            item["to_addrs"] = []
        out.append(item)
    return out
