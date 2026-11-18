"""询盘实体 + 阶段自动推导（N4 B 方案）。"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def test_db(monkeypatch, tmp_path):
    """临时库（完整 SCHEMA + CRM 补列）。"""
    db_path = tmp_path / "trade.db"
    import trade.database as _db

    original = _db._get_db_path
    _db._get_db_path = lambda: db_path
    from trade.database import SCHEMA_SQL, _add_customer_crm_columns, _add_spare_columns

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    _add_spare_columns(conn)
    _add_customer_crm_columns(conn)
    conn.commit()
    conn.close()
    import trade.company as _co

    def _mock_work_dir(company_name, slug, suggested_name=""):
        work_dir = tmp_path / (suggested_name or company_name)
        work_dir.mkdir(parents=True, exist_ok=True)
        for cat_name, _ in _co._WORK_DIR_CATEGORIES:
            (work_dir / cat_name).mkdir(parents=True, exist_ok=True)
        return work_dir, True

    monkeypatch.setattr(_co, "_setup_work_directory", _mock_work_dir)
    yield db_path
    _db._get_db_path = original


@pytest.fixture
def company_id(test_db):
    from trade import company

    return company.create("Inq Test Co")["id"]


class TestInquiryDerive:
    def test_no_inquiry_stays_default(self, test_db, company_id):
        """无询盘时有效阶段保持默认「询盘」，且为自动。"""
        from trade import customer, inquiry

        c = customer.create("No Inq", company_id=company_id)
        assert c["stage"] == "询盘"
        assert c["stage_auto"] is True
        assert c["stage_override"] is None
        assert inquiry.list_for_customer(c["id"], company_id=company_id) == []

    def test_max_stage_across_inquiries(self, test_db, company_id):
        """多询盘取 STAGE_ORDER 最大。"""
        from trade import customer, inquiry

        c = customer.create("Multi", company_id=company_id)
        inquiry.create(c["id"], company_id=company_id, title="A", stage="询盘")
        inquiry.create(c["id"], company_id=company_id, title="B", stage="样品")
        inquiry.create(c["id"], company_id=company_id, title="C", stage="报价")
        got = customer.get(c["id"], company_id=company_id)
        assert got["stage"] == "样品"
        assert got["stage_auto"] is True

    def test_delete_max_falls_back(self, test_db, company_id):
        """删掉最靠后询盘后回落。"""
        from trade import customer, inquiry

        c = customer.create("Fall", company_id=company_id)
        a = inquiry.create(c["id"], company_id=company_id, title="低", stage="报价")
        b = inquiry.create(c["id"], company_id=company_id, title="高", stage="订单")
        assert customer.get(c["id"], company_id=company_id)["stage"] == "订单"
        inquiry.delete(b["id"], company_id=company_id)
        assert customer.get(c["id"], company_id=company_id)["stage"] == "报价"
        inquiry.delete(a["id"], company_id=company_id)
        assert customer.get(c["id"], company_id=company_id)["stage"] == "询盘"

    def test_update_inquiry_stage_recomputes(self, test_db, company_id):
        """改询盘 stage 后重算。"""
        from trade import customer, inquiry

        c = customer.create("Upd", company_id=company_id)
        row = inquiry.create(c["id"], company_id=company_id, title="X", stage="询盘")
        inquiry.update(row["id"], company_id=company_id, stage="订单")
        assert customer.get(c["id"], company_id=company_id)["stage"] == "订单"

    def test_override_blocks_recompute(self, test_db, company_id):
        """设 override 后询盘变化不覆盖；清 override 立即重算。"""
        from trade import customer, inquiry

        c = customer.create("Ov", company_id=company_id, stage="询盘")
        customer.update(c["id"], company_id=company_id, stage="报价")
        locked = customer.get(c["id"], company_id=company_id)
        assert locked["stage"] == "报价"
        assert locked["stage_auto"] is False
        assert locked["stage_override"] == "报价"

        inquiry.create(c["id"], company_id=company_id, title="应被忽略", stage="订单")
        still = customer.get(c["id"], company_id=company_id)
        assert still["stage"] == "报价"

        customer.update(c["id"], company_id=company_id, stage="自动")
        freed = customer.get(c["id"], company_id=company_id)
        assert freed["stage"] == "订单"
        assert freed["stage_auto"] is True
        assert freed["stage_override"] is None

    def test_dirty_stage_normalized(self, test_db, company_id):
        """脏 stage 归一化回询盘。"""
        from trade import inquiry, customer

        c = customer.create("Dirty", company_id=company_id)
        row = inquiry.create(
            c["id"], company_id=company_id, title="D", stage="乱七八糟"
        )
        assert row["stage"] == "询盘"

    def test_create_nondefault_locks_override(self, test_db, company_id):
        """新建客户非默认 stage → 同时写 override。"""
        from trade import customer

        c = customer.create("Lock", company_id=company_id, stage="样品")
        assert c["stage"] == "样品"
        assert c["stage_auto"] is False
        assert c["stage_override"] == "样品"

    def test_company_isolation(self, test_db, company_id):
        """A 公司询盘 B 公司查不到。"""
        from trade.company import create as create_company
        from trade import customer, inquiry

        other = create_company(name="Other Co", slug="other-inq")
        oid = other["id"]
        a = customer.create("A Cust", company_id=company_id)
        inquiry.create(a["id"], company_id=company_id, title="私有", stage="报价")
        assert inquiry.list_for_customer(a["id"], company_id=oid) is None
        assert inquiry.get(
            inquiry.list_for_customer(a["id"], company_id=company_id)[0]["id"],
            company_id=oid,
        ) is None


def _insert_email(conn, *, company_id, customer_id, subject, received_at, mid="m1"):
    """插入测试邮件（满足 mailbox_id/message_id NOT NULL）。"""
    conn.execute(
        "INSERT INTO emails (mailbox_id, message_id, company_id, customer_id, "
        "subject, received_at) VALUES (?,?,?,?,?,?)",
        (1, mid, company_id, customer_id, subject, received_at),
    )


class TestTimestampCompare:
    """§7 P2-1：对话空格格式 vs 邮件 ISO 带 T。"""

    def test_summary_prefers_later_talk(self, test_db, company_id):
        from trade import chat_memory, customer
        from trade.database import get_connection

        c = customer.create("Ts Sum", company_id=company_id)
        cid = c["id"]
        talk = chat_memory.save(company_id, "下午对话", "答", customer_id=cid)
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE conversations SET created_at=? WHERE id=?",
                ("2026-11-17 15:00:00", talk["id"]),
            )
            _insert_email(
                conn,
                company_id=company_id,
                customer_id=cid,
                subject="早邮",
                received_at="2026-11-17T09:00:00+08:00",
            )
            conn.commit()
        finally:
            conn.close()
        summary = customer.get_company_summary(company_id)
        assert summary["last_contact_at"] == "2026-11-17 15:00:00"

    def test_timeline_orders_talk_before_morning_email(self, test_db, company_id):
        from trade import chat_memory, customer
        from trade.database import get_connection

        c = customer.create("Ts Tl", company_id=company_id)
        cid = c["id"]
        talk = chat_memory.save(company_id, "下午", "答", customer_id=cid)
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE conversations SET created_at=? WHERE id=?",
                ("2026-11-17 15:00:00", talk["id"]),
            )
            _insert_email(
                conn,
                company_id=company_id,
                customer_id=cid,
                subject="早邮",
                received_at="2026-11-17T09:00:00+08:00",
                mid="m2",
            )
            conn.commit()
        finally:
            conn.close()
        events = customer.get_timeline(cid, company_id=company_id, days=60)
        kinds = [e["kind"] for e in events]
        # 15:00 对话应排在 09:00 邮件前面
        talk_i = next(
            i for i, e in enumerate(events)
            if e.get("kind") == "talk" or e.get("ref_type") == "conversation"
        )
        mail_i = next(
            i for i, e in enumerate(events)
            if e.get("ref_type") == "email"
        )
        assert talk_i < mail_i, kinds


class TestInquirySchemaUpgrade:
    """§5：旧库无 inquiries / stage_override 时完整 init_db。"""

    def test_upgrade_adds_table_and_backfills_override(self, tmp_path, monkeypatch):
        import sqlite3

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
                "INSERT INTO companies (name, slug) VALUES ('升级公司', 'inq-up')"
            )
            cid = conn.execute(
                "SELECT id FROM companies WHERE slug='inq-up'"
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO customers (company_id, name, stage) VALUES (?,?,?)",
                (cid, "默认询盘客", "询盘"),
            )
            conn.execute(
                "INSERT INTO customers (company_id, name, stage) VALUES (?,?,?)",
                (cid, "已报价客", "报价"),
            )
            # 剥掉本单新增：inquiries 表 + stage_override 列
            conn.execute("DROP TABLE IF EXISTS inquiries")
            cols = {r[1] for r in conn.execute("PRAGMA table_info(customers)")}
            if "stage_override" in cols:
                conn.executescript(
                    """
                    CREATE TABLE customers_pre_ov (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        company_id INTEGER,
                        name TEXT NOT NULL,
                        contact TEXT DEFAULT '',
                        note TEXT DEFAULT '',
                        stage TEXT DEFAULT '询盘',
                        next_follow_up_date TEXT DEFAULT '',
                        is_starred INTEGER DEFAULT 0,
                        created_at TEXT,
                        updated_at TEXT,
                        extra1 TEXT DEFAULT '{}',
                        extra2 TEXT DEFAULT '{}',
                        extra3 TEXT DEFAULT '{}'
                    );
                    INSERT INTO customers_pre_ov
                        (id, company_id, name, contact, note, stage,
                         next_follow_up_date, is_starred, created_at, updated_at,
                         extra1, extra2, extra3)
                    SELECT id, company_id, name, contact, note, stage,
                           next_follow_up_date, is_starred, created_at, updated_at,
                           extra1, extra2, extra3
                    FROM customers;
                    DROP TABLE customers;
                    ALTER TABLE customers_pre_ov RENAME TO customers;
                    """
                )
            conn.commit()
            before = {
                r["name"]: r["stage"]
                for r in conn.execute("SELECT name, stage FROM customers")
            }
            assert "inquiries" not in {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            assert "stage_override" not in {
                r[1] for r in conn.execute("PRAGMA table_info(customers)")
            }
        finally:
            conn.close()

        backup_dir = trade_home / "backups"
        before_n = len(list(backup_dir.glob("trade-*.db"))) if backup_dir.is_dir() else 0
        dbmod.init_db()
        after_n = len(list(backup_dir.glob("trade-*.db"))) if backup_dir.is_dir() else 0
        assert after_n == before_n + 1

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            assert "inquiries" in {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            idx = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                )
            }
            assert "idx_inquiries_customer" in idx
            rows = {
                r["name"]: dict(r)
                for r in conn.execute(
                    "SELECT name, stage, stage_override FROM customers"
                )
            }
            assert rows["默认询盘客"]["stage"] == before["默认询盘客"]
            assert rows["默认询盘客"]["stage_override"] is None
            assert rows["已报价客"]["stage"] == "报价"
            assert rows["已报价客"]["stage_override"] == "报价"
        finally:
            conn.close()

        # 二次启动不新增备份
        n2 = len(list(backup_dir.glob("trade-*.db")))
        dbmod.init_db()
        assert len(list(backup_dir.glob("trade-*.db"))) == n2
