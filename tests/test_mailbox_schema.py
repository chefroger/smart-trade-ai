"""邮箱 IMAP 绑定：init_db 应创建 mailboxes / emails（两列挂客户），无 email_matches。"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_init_db_creates_mailbox_tables(tmp_path, monkeypatch):
    """全新库 init_db 后应有 mailboxes/emails，含两列，且无 email_matches。"""
    import trade.database as dbmod

    trade_home = tmp_path / ".trade"
    (trade_home / "data").mkdir(parents=True)
    db_path = trade_home / "data" / "trade.db"
    monkeypatch.setattr(dbmod, "_get_db_path", lambda: db_path)

    dbmod.init_db()

    conn = sqlite3.connect(str(db_path))
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "mailboxes" in tables
        assert "emails" in tables
        assert "email_matches" not in tables

        email_cols = {r[1] for r in conn.execute("PRAGMA table_info(emails)")}
        assert "company_id" in email_cols
        assert "customer_id" in email_cols
        # UNIQUE(mailbox_id, message_id) 已在表定义中
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
        assert "idx_emails_company_customer_time" in indexes
    finally:
        conn.close()


def test_init_db_upgrades_legacy_without_mailbox_tables(tmp_path, monkeypatch):
    """旧库缺邮箱表时升级：保留客户、补表、只备一次份。"""
    import trade.database as dbmod

    trade_home = tmp_path / ".trade"
    (trade_home / "data").mkdir(parents=True)
    db_path = trade_home / "data" / "trade.db"
    monkeypatch.setattr(dbmod, "_get_db_path", lambda: db_path)

    dbmod.init_db()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            "INSERT INTO companies (name, slug) VALUES ('邮箱测试公司', 'mb-test')"
        )
        company_id = conn.execute("SELECT id FROM companies WHERE slug='mb-test'").fetchone()[
            0
        ]
        conn.execute(
            "INSERT INTO customers (company_id, name, contact) VALUES (?, '保留下来的客户', 'c@x.com')",
            (company_id,),
        )
        before_name = conn.execute(
            "SELECT name FROM customers WHERE name='保留下来的客户'"
        ).fetchone()["name"]
        assert before_name == "保留下来的客户"

        # 模拟升级前版本：已有业务库但没有邮箱表
        conn.executescript(
            """
            DROP TABLE IF EXISTS email_matches;
            DROP TABLE IF EXISTS emails;
            DROP TABLE IF EXISTS mailboxes;
            """
        )
        conn.commit()

        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "mailboxes" not in tables
    finally:
        conn.close()

    backup_dir = trade_home / "backups"
    backups_before = (
        list(backup_dir.glob("trade-*.db")) if backup_dir.is_dir() else []
    )

    dbmod.init_db()

    backups_after_upgrade = (
        list(backup_dir.glob("trade-*.db")) if backup_dir.is_dir() else []
    )
    assert len(backups_after_upgrade) > len(backups_before), "缺表升级应先备份"

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "mailboxes" in tables
        assert "email_matches" not in tables
        assert conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0] == 0
        row = conn.execute(
            "SELECT name FROM customers WHERE name='保留下来的客户'"
        ).fetchone()
        assert row is not None
        assert row["name"] == "保留下来的客户"
    finally:
        conn.close()

    backup_n = len(backups_after_upgrade)
    dbmod.init_db()
    backups_again = (
        list(backup_dir.glob("trade-*.db")) if backup_dir.is_dir() else []
    )
    assert len(backups_again) == backup_n, "schema 已完整时不得再新增备份"


def test_empty_email_matches_dropped_on_init(tmp_path, monkeypatch):
    """开发机残留空 email_matches 时 init_db 应 DROP。"""
    import trade.database as dbmod

    trade_home = tmp_path / ".trade"
    (trade_home / "data").mkdir(parents=True)
    db_path = trade_home / "data" / "trade.db"
    monkeypatch.setattr(dbmod, "_get_db_path", lambda: db_path)
    dbmod.init_db()

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS email_matches ("
            "email_id INTEGER, company_id INTEGER, customer_id INTEGER)"
        )
        conn.commit()
    finally:
        conn.close()

    dbmod.init_db()
    conn = sqlite3.connect(str(db_path))
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "email_matches" not in tables
    finally:
        conn.close()
