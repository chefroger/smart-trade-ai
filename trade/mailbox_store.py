"""邮箱绑定存储：凭证文件、mailbox CRUD、匹配入库、拉取编排。"""

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

from trade import database as _db
from trade.database import get_connection
from trade.mailbox import PRESETS, MailboxError, fetch_new, test_connection

PULL_TIMEOUT_SEC = 120


def secrets_path() -> Path:
    """凭证文件与 trade.db 同目录。

    经 ``_db._get_db_path`` 查模块属性，避免 ``from … import _get_db_path``
    把测试 monkeypatch 的 lambda 永久绑进本模块（chat_smoke 泄漏事故）。
    """
    return _db._get_db_path().parent / "mailbox_secrets.json"


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
    """扫 extra2.email/backup_email + contacts.email，与 From/To 不区分大小写匹配。

    返回两段拼接、之后不再整体排序（调用方只取 pairs[0]）：
    1. extra2（email/backup_email）命中的客户，按 customers.id 升序；
    2. 仅在 contacts.email 命中、且不在第 1 段的客户，按
       (contacts.customer_id ASC, contacts.id ASC)，同一客户只出现一次。
    contacts 表缺失时只扫 extra2（降级，不抛错）。
    """
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
    primary_pairs: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    try:
        # 第一段：extra2 命中，按 customers.id 升序
        rows = conn.execute(
            "SELECT company_id, id, extra2 FROM customers ORDER BY id ASC"
        ).fetchall()
        for row in rows:
            try:
                e2 = json.loads(row["extra2"] or "{}")
            except json.JSONDecodeError:
                e2 = {}
            hit = False
            for key in ("email", "backup_email"):
                val = normalize_addr(str(e2.get(key) or ""))
                if val and val in want:
                    hit = True
                    break
            if hit:
                pair = (int(row["company_id"]), int(row["id"]))
                if pair not in seen:
                    seen.add(pair)
                    primary_pairs.append(pair)

        # 第二段：仅 contacts.email 命中且不在第一段（缺表静默跳过）
        contact_pairs: list[tuple[int, int]] = []
        try:
            crows = conn.execute(
                "SELECT company_id, customer_id, email FROM contacts "
                "WHERE email IS NOT NULL AND email != '' "
                "ORDER BY customer_id ASC, id ASC"
            ).fetchall()
            for crow in crows:
                val = normalize_addr(str(crow["email"] or ""))
                if val and val in want:
                    pair = (int(crow["company_id"]), int(crow["customer_id"]))
                    if pair not in seen:
                        seen.add(pair)
                        contact_pairs.append(pair)
        except sqlite3.OperationalError as exc:
            msg = str(exc).lower()
            if not ("no such table" in msg and "contacts" in msg):
                raise
        return primary_pairs + contact_pairs
    finally:
        conn.close()


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
    """把匹配结果写到 emails.company_id / customer_id。

    一封邮件只挂一对：取 pairs[0]（extra2 命中段优先，段内再按 customer id；
    见 find_customer_matches）；多命中其余丢弃。
    无匹配则两列保持 NULL。返回 1 表示写入了一对，0 表示未写。
    """
    if not pairs:
        return 0
    company_id, customer_id = pairs[0]
    conn.execute(
        """
        UPDATE emails
        SET company_id = ?, customer_id = ?
        WHERE id = ?
        """,
        (company_id, customer_id, email_id),
    )
    return 1


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
    matched = 0
    if is_new:
        matched = attach_matches(conn, email_id, pairs)
    elif pairs:
        # 已存在行：仅当当前未挂客户时补写（避免覆盖已选的 pairs[0]）
        row = conn.execute(
            "SELECT company_id, customer_id FROM emails WHERE id = ?",
            (email_id,),
        ).fetchone()
        if row and row["company_id"] is None and row["customer_id"] is None:
            matched = attach_matches(conn, email_id, pairs)
    return is_new, matched


def rematch_unmatched_emails(
    mailbox_id: int | None = None,
    *,
    conn: sqlite3.Connection | None = None,
) -> int:
    """对尚未挂客户的已入库邮件重新跑匹配（改客户邮箱后无需等新信）。

    只填 ``customer_id IS NULL`` 的行，不覆盖已有关联。返回新挂上的封数。
    支持传入调用方已打开的 ``conn``（如 pull_one 事务内），避免跨连接写锁自死锁与连接泄漏。
    """
    own_conn = conn is None
    if own_conn:
        # 调用方未传入连接时自行开启，并在 finally 中关闭
        conn = get_connection()
    try:
        if mailbox_id is not None:
            # 仅重匹配指定邮箱下未归属客户的邮件
            rows = conn.execute(
                """
                SELECT id, from_addr, to_addrs FROM emails
                WHERE mailbox_id = ? AND customer_id IS NULL
                """,
                (mailbox_id,),
            ).fetchall()
        else:
            # 全局重匹配所有未归属客户的邮件
            rows = conn.execute(
                """
                SELECT id, from_addr, to_addrs FROM emails
                WHERE customer_id IS NULL
                """
            ).fetchall()
        fixed = 0
        for row in rows:
            try:
                tos = json.loads(row["to_addrs"] or "[]")
            except json.JSONDecodeError:
                tos = []
            # 非列表脏数据降级为空列表
            if not isinstance(tos, list):
                tos = []
            pairs = find_customer_matches(row["from_addr"] or "", tos)
            # 无匹配客户则跳过
            if not pairs:
                continue
            # 挂接成功后累计计数
            if attach_matches(conn, int(row["id"]), pairs):
                fixed += 1
        # 仅当本函数自管连接时提交事务；外部传入连接由外层统一提交
        if own_conn:
            conn.commit()
        return fixed
    finally:
        # 自建连接必须确保关闭，防止句柄泄漏
        if own_conn and conn is not None:
            conn.close()


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
    """创建 IMAP 邮箱绑定；provider 恒为 imap，测通后写库并保存凭证。

    地址统一小写入库，避免 UNIQUE 大小写可重复绑定。
    """
    if preset in PRESETS:
        phost, pport = PRESETS[preset]
        host = host or phost
        port = port or pport
    else:
        if not host:
            raise ValueError("自定义预设必须提供 host")
        port = port if port is not None else 993

    email_address = normalize_addr(email_address)
    if not email_address:
        raise ValueError("邮箱地址不能为空")
    # username 默认跟地址；若调用方显式传入则 strip，但仍建议小写
    username = (username or email_address).strip()
    if username == email_address or not username:
        username = email_address
    test_connection(str(host), int(port), username, secret)

    conn = get_connection()
    try:
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
    finally:
        conn.close()


def list_mailboxes() -> list[dict[str, Any]]:
    """列表含 has_secret、email_count，不返回 secret。"""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT m.*, COUNT(e.id) AS email_count
            FROM mailboxes m
            LEFT JOIN emails e ON e.mailbox_id = m.id
            GROUP BY m.id
            ORDER BY m.id
            """
        ).fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = _mailbox_row_to_dict(row)
        mid = int(item["id"])
        item["has_secret"] = get_secret(mid) is not None
        item["email_count"] = int(item.get("email_count") or 0)
        out.append(item)
    return out


def delete_mailbox(mailbox_id: int) -> None:
    """删除 mailbox、关联邮件与凭证。"""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM emails WHERE mailbox_id = ?", (mailbox_id,))
        conn.execute("DELETE FROM mailboxes WHERE id = ?", (mailbox_id,))
        conn.commit()
    finally:
        conn.close()
    delete_secret(mailbox_id)


def update_secret(mailbox_id: int, secret: str) -> None:
    """更新凭证：先测通，失败则保留旧凭证。"""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM mailboxes WHERE id = ?", (mailbox_id,)).fetchone()
        # 邮箱不存在时立即抛错，不继续执行网络测通
        if row is None:
            raise ValueError("邮箱不存在")
        host = row["host"]
        port = int(row["port"] or 993)
        username = row["username"] or row["email_address"]
    finally:
        conn.close()
    old_secret = get_secret(mailbox_id)
    try:
        test_connection(host, port, username, secret)
    except MailboxError:
        # 测通失败：保留原凭证不覆盖
        if old_secret is not None:
            set_secret(mailbox_id, old_secret)
        raise
    set_secret(mailbox_id, secret)


# ==== 拉取编排 ====


def pull_one(mailbox_id: int) -> dict[str, Any]:
    """拉取单 mailbox。

    - 入库循环墙钟上限 PULL_TIMEOUT_SEC（不含 IMAP 网络拉取，网络另有 socket 超时）。
    - 首拉超时或首拉截断：不推进 last_uid（下次仍走首拉，靠 message_id 去重）。
    - 增量超时：推进到已入库最大 UID。
    - pulled 只计新插入，去重跳过的不计入。
    """
    secret = get_secret(mailbox_id)
    if not secret:
        return {"pulled": 0, "matched": 0, "error": "未配置邮箱凭证"}

    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM mailboxes WHERE id = ?", (mailbox_id,)).fetchone()
        # 邮箱记录不存在时直接返回错误描述
        if row is None:
            return {"pulled": 0, "matched": 0, "error": "邮箱不存在"}
        mailbox_dict = _mailbox_row_to_dict(row)
        prev_last_uid = row["last_uid"]
        prev_last_v = row["last_uidvalidity"]
    finally:
        # 网络拉取前先释放读连接，避免慢速 IMAP 长期占用句柄
        conn.close()

    try:
        messages, cursor_update = fetch_new(mailbox_dict, secret)
    except MailboxError as exc:
        err_conn = get_connection()
        try:
            err_conn.execute(
                "UPDATE mailboxes SET last_error = ? WHERE id = ?",
                (str(exc), mailbox_id),
            )
            err_conn.commit()
        finally:
            err_conn.close()
        return {"pulled": 0, "matched": 0, "error": str(exc)}

    deadline = time.monotonic() + PULL_TIMEOUT_SEC
    pulled = 0
    matched_total = 0
    max_ingested_uid: int | None = None
    last_uidvalidity = cursor_update.get("last_uidvalidity")
    timed_out = False
    is_first_pull = bool(cursor_update.get("is_first_pull"))
    truncated = bool(cursor_update.get("truncated"))

    conn = get_connection()
    try:
        for msg in messages:
            if time.monotonic() >= deadline:
                # 超时：停拉但不回滚已写入
                timed_out = True
                break
            is_new, matched_n = _ingest_message(conn, mailbox_id, msg)
            # O-6：去重跳过的不计入 pulled
            if is_new:
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

        # 复用当前事务连接回填未挂客户邮件，避免新开连接撞上本连接未提交的写锁
        matched_total += rematch_unmatched_emails(mailbox_id, conn=conn)

        now = datetime.now().astimezone().replace(microsecond=0).isoformat()

        # 首拉超时或截断：游标不推进到最新端，否则窗口内更旧邮件永久丢失
        hold_cursor = (timed_out and is_first_pull) or (not timed_out and truncated)

        if timed_out:
            if hold_cursor:
                last_uid = prev_last_uid
                last_v_write = prev_last_v
            else:
                # 增量超时：推进到已入库最大 UID
                last_uid = (
                    max_ingested_uid
                    if max_ingested_uid is not None
                    else prev_last_uid
                )
                last_v_write = last_uidvalidity
            last_error = f"超时已拉 {pulled}"
            conn.execute(
                """
                UPDATE mailboxes
                SET last_uid = ?, last_uidvalidity = ?, last_sync_at = ?, last_error = ?
                WHERE id = ?
                """,
                (last_uid, last_v_write, now, last_error, mailbox_id),
            )
            conn.commit()
            return {"pulled": pulled, "matched": matched_total, "error": last_error}

        if hold_cursor:
            # 首拉截断完成：邮件已入库，但 last_uid 保持原值以便下次仍走首拉
            conn.execute(
                """
                UPDATE mailboxes
                SET last_uidvalidity = ?, last_sync_at = ?, last_error = NULL
                WHERE id = ?
                """,
                (last_uidvalidity, now, mailbox_id),
            )
            # 刻意不改 last_uid（保持 NULL/原值）
            conn.commit()
            return {"pulled": pulled, "matched": matched_total, "truncated": True}

        # 全量完成且未截断：游标与 fetch_new 一致
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
    finally:
        conn.close()


def pull_all() -> dict[str, Any]:
    """串行 pull_one；单邮箱失败记入自身结果后继续下一个。"""
    results: list[dict[str, Any]] = []
    for item in list_mailboxes():
        mid = int(item["id"])
        try:
            one = pull_one(mid)
        except Exception as exc:
            # 意外异常也隔离，避免一个邮箱卡住整次 pull-all
            one = {"pulled": 0, "matched": 0, "error": str(exc)}
            try:
                err_conn = get_connection()
                try:
                    err_conn.execute(
                        "UPDATE mailboxes SET last_error = ? WHERE id = ?",
                        (str(exc)[:500], mid),
                    )
                    err_conn.commit()
                finally:
                    err_conn.close()
            except Exception:
                pass
        one["mailbox_id"] = mid
        results.append(one)
    return {"results": results}


def list_customer_emails(
    company_id: int,
    customer_id: int,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """客户关联邮件：按 emails.company_id / customer_id 过滤，received_at 降序。"""
    lim = max(1, min(int(limit), 50))
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT e.*
            FROM emails e
            WHERE e.company_id = ? AND e.customer_id = ?
            ORDER BY e.received_at DESC
            LIMIT ?
            """,
            (company_id, customer_id, lim),
        ).fetchall()
    finally:
        conn.close()
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
