"""邮箱 IMAP 绑定：init_db 应创建 mailboxes / emails / email_matches 三表。"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_init_db_creates_mailbox_tables(tmp_path, monkeypatch):
    """全新库 init_db 后应有三表，且 emails 不含 company_id/customer_id。"""
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
        assert "email_matches" in tables

        email_cols = {r[1] for r in conn.execute("PRAGMA table_info(emails)")}
        assert "company_id" not in email_cols
        assert "customer_id" not in email_cols
    finally:
        conn.close()


def test_init_db_upgrades_legacy_without_mailbox_tables(tmp_path, monkeypatch):
    """旧库缺邮箱三表时升级：保留客户、补表、只备一次份。"""
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

        # 模拟升级前版本：已有业务库但没有邮箱三表
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