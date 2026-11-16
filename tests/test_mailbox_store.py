"""邮箱 IMAP 绑定：凭证文件 mailbox_secrets.json 读写与权限。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_secrets_roundtrip_and_chmod(tmp_path, monkeypatch):
    """凭证与 trade.db 同目录；读写删除；非 Windows 上文件权限 0o600。"""
    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    from trade import database as db

    db.init_db()
    from trade import mailbox_store as ms

    path = ms.secrets_path()
    assert path.parent == db._get_db_path().parent

    ms.set_secret(1, "auth-code-16chars")
    assert ms.get_secret(1) == "auth-code-16chars"

    if os.name == "nt":
        # Windows 上 chmod 不可靠，只验证文件存在且可读
        assert path.is_file()
        path.read_text(encoding="utf-8")
    else:
        mode = path.stat().st_mode & 0o777
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"
        assert path.stat().st_mode & 0o077 == 0

    ms.delete_secret(1)
    assert ms.get_secret(1) is None


def test_secrets_corrupt_json_degrades_empty(tmp_path, monkeypatch):
    """损坏或非对象 JSON 不抛异常，按空映射降级。"""
    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    from trade import database as db

    db.init_db()
    from trade import mailbox_store as ms

    path = ms.secrets_path()
    path.write_text("{not-json", encoding="utf-8")
    assert ms.get_secret(1) is None
    path.write_text("[]", encoding="utf-8")
    assert ms.get_secret(2) is None
    # 降级后仍可写入
    ms.set_secret(3, "fake-auth-code-xx")
    assert ms.get_secret(3) == "fake-auth-code-xx"


def _init_mailbox_db(tmp_path, monkeypatch):
    """初始化临时库并返回 database 模块。"""
    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    from trade import database as db

    db.init_db()
    return db


def _seed_two_companies_with_customers(tmp_path, monkeypatch):
    """两家公司有各一客户，主邮箱/备用邮箱用于 From/To 匹配测。"""
    _init_mailbox_db(tmp_path, monkeypatch)
    from trade import customer
    from trade.company import crud as company

    co_a = company.create(name="Co A", slug="co-a-mail")
    co_b = company.create(name="Co B", slug="co-b-mail")
    cust_a = customer.create(
        "Buyer A",
        company_id=co_a["id"],
        email="buyer@example.com",
    )
    cust_b = customer.create(
        "Buyer B",
        company_id=co_b["id"],
        email="seller@example.com",
        backup_email="  SELLER@EXAMPLE.COM ",
    )
    return co_a["id"], co_b["id"], cust_a["id"], cust_b["id"]


def test_match_from_or_to_case_insensitive(tmp_path, monkeypatch):
    """多公司命中时只挂 pairs[0]；未命中客户两列 NULL；无 email_matches 表。"""
    _seed_two_companies_with_customers(tmp_path, monkeypatch)
    from trade import mailbox_store as ms
    from trade.database import get_connection

    conn = get_connection()
    tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "email_matches" not in tables

    conn.execute(
        "INSERT INTO mailboxes (provider, preset, email_address, host, port, username) "
        "VALUES ('imap', '126', 'bind@example.com', 'imap.126.com', 993, 'bind@example.com')"
    )
    conn.commit()
    mailbox_id = conn.execute("SELECT id FROM mailboxes LIMIT 1").fetchone()["id"]

    msg = {
        "message_id": "<thread-1@example.com>",
        "uid": 42,
        "from_addr": "Buyer Person <BUYER@example.com>",
        "to_addrs": ["seller@example.com"],
        "subject": "Hello",
        "snippet": "Hi",
        "body_text": "Body",
        "received_at": "2026-01-01T10:00:00",
    }
    pairs = ms.find_customer_matches(msg["from_addr"], msg["to_addrs"])
    assert len(pairs) == 2  # 两公司都命中，但入库只取第一对

    email_id = ms.insert_email_ignore(conn, mailbox_id, msg)
    assert email_id is not None
    inserted = ms.attach_matches(conn, email_id, pairs)
    conn.commit()

    assert inserted == 1
    row = conn.execute(
        "SELECT company_id, customer_id FROM emails WHERE id=?", (email_id,)
    ).fetchone()
    assert row["company_id"] == pairs[0][0]
    assert row["customer_id"] == pairs[0][1]
    # 其余命中丢弃（显式：不静默多挂）
    assert (row["company_id"], row["customer_id"]) != pairs[1]

    # 未命中客户：两列 NULL，邮件仍入库
    msg2 = {
        **msg,
        "message_id": "<no-match@example.com>",
        "from_addr": "nobody@example.com",
        "to_addrs": [],
    }
    eid2 = ms.insert_email_ignore(conn, mailbox_id, msg2)
    ms.attach_matches(conn, eid2, ms.find_customer_matches(msg2["from_addr"], []))
    conn.commit()
    row2 = conn.execute(
        "SELECT company_id, customer_id FROM emails WHERE id=?", (eid2,)
    ).fetchone()
    assert row2["company_id"] is None
    assert row2["customer_id"] is None


def test_dedupe_d1_skips_second_insert(tmp_path, monkeypatch):
    """同一 message_id 二次入库不更新正文（D1）。"""
    _init_mailbox_db(tmp_path, monkeypatch)
    from trade import mailbox_store as ms
    from trade.database import get_connection

    conn = get_connection()
    conn.execute(
        "INSERT INTO mailboxes (provider, preset, email_address, host, port, username) "
        "VALUES ('imap', 'qq', 'qq@example.com', 'imap.qq.com', 993, 'qq@example.com')"
    )
    conn.commit()
    mailbox_id = conn.execute("SELECT id FROM mailboxes LIMIT 1").fetchone()["id"]

    msg1 = {
        "message_id": "dedupe-msg-1",
        "uid": 1,
        "from_addr": "a@example.com",
        "to_addrs": [],
        "subject": "First",
        "snippet": "s1",
        "body_text": "FIRST_BODY",
        "received_at": "2026-01-02T10:00:00",
    }
    msg2 = {**msg1, "body_text": "SECOND_BODY", "subject": "Second"}

    id1 = ms.insert_email_ignore(conn, mailbox_id, msg1)
    conn.commit()
    id2 = ms.insert_email_ignore(conn, mailbox_id, msg2)
    conn.commit()

    assert id1 == id2
    row = conn.execute("SELECT body_text, subject FROM emails WHERE id=?", (id1,)).fetchone()
    assert row["body_text"] == "FIRST_BODY"
    assert row["subject"] == "First"
    assert conn.execute("SELECT COUNT(*) AS c FROM emails").fetchone()["c"] == 1


def test_unbind_deletes_secret_emails_matches(tmp_path, monkeypatch):
    """delete_mailbox 删除凭证与邮件。"""
    _seed_two_companies_with_customers(tmp_path, monkeypatch)
    from trade import mailbox_store as ms
    from trade.database import get_connection

    conn = get_connection()
    conn.execute(
        "INSERT INTO mailboxes (provider, preset, email_address, host, port, username) "
        "VALUES ('imap', '126', 'unbind2@example.com', 'imap.126.com', 993, 'unbind2@example.com')"
    )
    conn.commit()
    mailbox_id = conn.execute(
        "SELECT id FROM mailboxes WHERE email_address='unbind2@example.com'"
    ).fetchone()["id"]
    ms.set_secret(mailbox_id, "fake-secret-16chars")

    msg = {
        "message_id": "unbind-one",
        "uid": 7,
        "from_addr": "buyer@example.com",
        "to_addrs": [],
        "subject": "x",
        "snippet": "x",
        "body_text": "x",
        "received_at": "2026-01-03T10:00:00",
    }
    pairs = ms.find_customer_matches(msg["from_addr"], msg["to_addrs"])
    eid = ms.insert_email_ignore(conn, mailbox_id, msg)
    ms.attach_matches(conn, eid, pairs)
    conn.commit()

    ms.delete_mailbox(mailbox_id)

    assert ms.get_secret(mailbox_id) is None
    assert conn.execute("SELECT COUNT(*) AS c FROM mailboxes WHERE id=?", (mailbox_id,)).fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM emails").fetchone()["c"] == 0


def test_pull_timeout_advances_cursor(tmp_path, monkeypatch):
    """拉取中途超时：已入库游标前进，不回滚。"""
    _init_mailbox_db(tmp_path, monkeypatch)
    from trade import mailbox_store as ms
    from trade.database import get_connection

    conn = get_connection()
    conn.execute(
        "INSERT INTO mailboxes (provider, preset, email_address, host, port, username, last_uid) "
        "VALUES ('imap', '126', 'pull@example.com', 'imap.126.com', 993, 'pull@example.com', 50)"
    )
    conn.commit()
    mailbox_id = conn.execute(
        "SELECT id FROM mailboxes WHERE email_address='pull@example.com'"
    ).fetchone()["id"]
    ms.set_secret(mailbox_id, "fake-secret-16chars")

    batch = []
    for i in range(8):
        uid = 60 + i
        batch.append(
            {
                "message_id": f"timeout-msg-{uid}",
                "uid": uid,
                "from_addr": f"user{i}@example.com",
                "to_addrs": [],
                "subject": "t",
                "snippet": "t",
                "body_text": "t",
                "received_at": "2026-01-04T10:00:00",
            }
        )

    def fake_fetch(_row, _secret):
        return batch, {
            "last_uidvalidity": 99,
            "last_uid": 67,
            "truncated": False,
            "is_first_pull": False,
        }

    monkeypatch.setattr(ms, "fetch_new", fake_fetch)

    tick = {"n": 0}
    t0 = 1_000_000.0

    def fake_monotonic():
        tick["n"] += 1
        # pull_one 会先算 deadline 占 1 次；第 5 次起超时（已入库 3 封）
        if tick["n"] >= 5:
            return t0 + ms.PULL_TIMEOUT_SEC + 1
        return t0 + tick["n"] * 0.01

    monkeypatch.setattr(ms.time, "monotonic", fake_monotonic)

    result = ms.pull_one(mailbox_id)

    assert result["pulled"] == 3
    assert result.get("error")
    row = conn.execute("SELECT last_uid, last_error FROM mailboxes WHERE id=?", (mailbox_id,)).fetchone()
    assert row["last_uid"] is not None
    assert int(row["last_uid"]) == 62
    assert conn.execute("SELECT COUNT(*) AS c FROM emails").fetchone()["c"] == result["pulled"]
    assert "超时" in (row["last_error"] or "")


def test_list_customer_emails_company_scoped(tmp_path, monkeypatch):
    """两公司客户同邮箱：一封邮件两条 match；list_customer_emails 按公司+客户过滤。"""
    _init_mailbox_db(tmp_path, monkeypatch)
    from trade import customer
    from trade import mailbox_store as ms
    from trade.company import crud as company
    from trade.database import get_connection

    co_a = company.create(name="Co A Scope", slug="co-a-scope")
    co_b = company.create(name="Co B Scope", slug="co-b-scope")
    cust_a = customer.create(
        "Buyer A",
        company_id=co_a["id"],
        email="shared@example.com",
    )
    cust_b = customer.create(
        "Buyer B",
        company_id=co_b["id"],
        email="shared@example.com",
    )

    conn = get_connection()
    conn.execute(
        "INSERT INTO mailboxes (provider, preset, email_address, host, port, username) "
        "VALUES ('imap', '126', 'scope@example.com', 'imap.126.com', 993, 'scope@example.com')"
    )
    conn.commit()
    mailbox_id = conn.execute("SELECT id FROM mailboxes LIMIT 1").fetchone()["id"]

    msg = {
        "message_id": "<scope-1@example.com>",
        "uid": 1,
        "from_addr": "shared@example.com",
        "to_addrs": [],
        "subject": "Scoped",
        "snippet": "s",
        "body_text": "b",
        "received_at": "2026-01-05T10:00:00",
    }
    pairs = ms.find_customer_matches(msg["from_addr"], msg["to_addrs"])
    assert len(pairs) == 2

    email_id = ms.insert_email_ignore(conn, mailbox_id, msg)
    inserted = ms.attach_matches(conn, email_id, pairs)
    conn.commit()

    assert inserted == 1
    # 只挂 pairs[0]；另一公司客户看不到这封
    assert len(ms.list_customer_emails(pairs[0][0], pairs[0][1])) == 1
    assert ms.list_customer_emails(pairs[1][0], pairs[1][1]) == []
    assert ms.list_customer_emails(co_a["id"], cust_b["id"]) == []
    assert ms.list_customer_emails(co_b["id"], cust_a["id"]) == []


def test_pull_first_timeout_does_not_advance_cursor(tmp_path, monkeypatch):
    """首拉降序超时：不把 last_uid 推到最大 UID。"""
    _init_mailbox_db(tmp_path, monkeypatch)
    from trade import mailbox_store as ms
    from trade.database import get_connection

    conn = get_connection()
    conn.execute(
        "INSERT INTO mailboxes (provider, preset, email_address, host, port, username) "
        "VALUES ('imap', '126', 'first-to@example.com', 'imap.126.com', 993, 'first-to@example.com')"
    )
    conn.commit()
    mailbox_id = conn.execute("SELECT id FROM mailboxes LIMIT 1").fetchone()["id"]
    ms.set_secret(mailbox_id, "fake-secret-16chars")

    # 降序：最新 UID 在前
    batch = [
        {
            "message_id": f"ft-{uid}",
            "uid": uid,
            "from_addr": "a@example.com",
            "to_addrs": [],
            "subject": "t",
            "snippet": "t",
            "body_text": "t",
            "received_at": "2026-01-04T10:00:00",
        }
        for uid in (90, 80, 70, 60, 50)
    ]

    def fake_fetch(_row, _secret):
        return batch, {
            "last_uidvalidity": 1,
            "last_uid": 90,
            "truncated": False,
            "is_first_pull": True,
        }

    monkeypatch.setattr(ms, "fetch_new", fake_fetch)
    tick = {"n": 0}
    t0 = 1_000_000.0

    def fake_monotonic():
        tick["n"] += 1
        if tick["n"] >= 5:
            return t0 + ms.PULL_TIMEOUT_SEC + 1
        return t0 + tick["n"] * 0.01

    monkeypatch.setattr(ms.time, "monotonic", fake_monotonic)
    result = ms.pull_one(mailbox_id)
    assert result["pulled"] == 3
    row = conn.execute(
        "SELECT last_uid, last_uidvalidity FROM mailboxes WHERE id=?", (mailbox_id,)
    ).fetchone()
    assert row["last_uid"] is None
    assert conn.execute("SELECT COUNT(*) AS c FROM emails").fetchone()["c"] == 3


def test_pull_first_truncated_holds_cursor(tmp_path, monkeypatch):
    """首拉截断：入库 500（此处用小上限），last_uid 不推进；二次仍走首拉且不重复。"""
    _init_mailbox_db(tmp_path, monkeypatch)
    from trade import mailbox as mb
    from trade import mailbox_store as ms
    from trade.database import get_connection

    monkeypatch.setattr(mb, "FIRST_PULL_LIMIT", 3)
    conn = get_connection()
    conn.execute(
        "INSERT INTO mailboxes (provider, preset, email_address, host, port, username) "
        "VALUES ('imap', '126', 'trunc@example.com', 'imap.126.com', 993, 'trunc@example.com')"
    )
    conn.commit()
    mailbox_id = conn.execute("SELECT id FROM mailboxes LIMIT 1").fetchone()["id"]
    ms.set_secret(mailbox_id, "fake-secret-16chars")

    batch = [
        {
            "message_id": f"tr-{uid}",
            "uid": uid,
            "from_addr": "a@example.com",
            "to_addrs": [],
            "subject": "t",
            "snippet": "t",
            "body_text": "t",
            "received_at": "2026-01-04T10:00:00",
        }
        for uid in (30, 20, 10)
    ]
    calls = {"n": 0}

    def fake_fetch(row, _secret):
        calls["n"] += 1
        # 第二次仍应是首拉（last_uid 仍空）
        assert row.get("last_uid") is None
        return batch, {
            "last_uidvalidity": 5,
            "last_uid": 30,
            "truncated": True,
            "is_first_pull": True,
        }

    monkeypatch.setattr(ms, "fetch_new", fake_fetch)
    r1 = ms.pull_one(mailbox_id)
    assert r1["pulled"] == 3
    assert r1.get("truncated") is True
    row = conn.execute("SELECT last_uid FROM mailboxes WHERE id=?", (mailbox_id,)).fetchone()
    assert row["last_uid"] is None
    assert conn.execute("SELECT COUNT(*) AS c FROM emails").fetchone()["c"] == 3

    r2 = ms.pull_one(mailbox_id)
    assert r2["pulled"] == 0  # message_id 去重，不计入
    assert conn.execute("SELECT COUNT(*) AS c FROM emails").fetchone()["c"] == 3
    assert calls["n"] == 2


def test_create_mailbox_case_insensitive_duplicate(tmp_path, monkeypatch):
    """大小写不同的同一地址不可重复绑定。"""
    _init_mailbox_db(tmp_path, monkeypatch)
    from trade import mailbox_store as ms

    monkeypatch.setattr(ms, "test_connection", lambda *a, **k: None)
    ms.create_mailbox("126", "Case@Example.COM", "sixteen-char-code")
    with pytest.raises(ValueError, match="已绑定"):
        ms.create_mailbox("126", "case@example.com", "sixteen-char-code")


def test_pull_all_isolates_single_mailbox_failure(tmp_path, monkeypatch):
    """一个邮箱失败不影响 pull-all 继续处理下一个。"""
    _init_mailbox_db(tmp_path, monkeypatch)
    from trade import mailbox_store as ms
    from trade.database import get_connection

    conn = get_connection()
    for addr in ("a@example.com", "b@example.com"):
        conn.execute(
            "INSERT INTO mailboxes (provider, preset, email_address, host, port, username) "
            "VALUES ('imap', '126', ?, 'imap.126.com', 993, ?)",
            (addr, addr),
        )
    conn.commit()
    ids = [r["id"] for r in conn.execute("SELECT id FROM mailboxes ORDER BY id").fetchall()]
    for mid in ids:
        ms.set_secret(mid, "fake-secret-16chars")

    def fake_pull(mid):
        if mid == ids[0]:
            raise RuntimeError("boom-isolated")
        return {"pulled": 1, "matched": 0}

    monkeypatch.setattr(ms, "pull_one", fake_pull)
    out = ms.pull_all()
    assert len(out["results"]) == 2
    assert out["results"][0]["mailbox_id"] == ids[0]
    assert "boom" in (out["results"][0].get("error") or "")
    assert out["results"][1]["pulled"] == 1
