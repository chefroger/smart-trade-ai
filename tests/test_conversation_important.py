"""CRM：conversations.is_important 迁移 + customers CRM 实列 + overview 聚合。"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def test_db(monkeypatch, tmp_path):
    """临时库 + 最新 SCHEMA（含 CRM 实列 / is_important）。"""
    db_path = tmp_path / "trade.db"
    import trade.database as _db
    original = _db._get_db_path
    _db._get_db_path = lambda: db_path
    from trade.database import SCHEMA_SQL, _add_spare_columns
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    _add_spare_columns(conn)
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
    return company.create("Test Company")["id"]


class TestIsImportantMigration:
    """旧库缺 is_important 时，_add_context_column 必须幂等补上。"""

    def test_add_is_important_to_legacy_conversations(self, tmp_path):
        from trade.database import _add_context_column

        db = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER,
                customer_id INTEGER,
                library_id INTEGER,
                query TEXT NOT NULL,
                response TEXT DEFAULT '',
                files_read TEXT DEFAULT '[]',
                context TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                extra1 TEXT DEFAULT '{}',
                extra2 TEXT DEFAULT '{}',
                extra3 TEXT DEFAULT '{}'
            );
            INSERT INTO conversations (company_id, customer_id, query, response)
            VALUES (1, 9, '旧问题', '旧回复');
            """
        )
        conn.commit()
        before = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]

        _add_context_column(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(conversations)")}
        assert "is_important" in cols
        assert conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == before
        row = conn.execute(
            "SELECT is_important, query FROM conversations WHERE id = 1"
        ).fetchone()
        assert row["is_important"] == 0
        assert row["query"] == "旧问题"
        _add_context_column(conn)  # 幂等
        conn.close()


class TestCustomerCrmColumns:
    """customers 实列 stage / next_follow_up_date / is_starred：只加列、旧值不变。"""

    def test_add_crm_columns_preserves_old_rows(self, tmp_path):
        from trade.database import _add_customer_crm_columns, _needs_schema_work

        db = tmp_path / "cust-legacy.db"
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        # 造一份「旧版」customers（无 CRM 实列），带一行真实数据
        conn.executescript(
            """
            CREATE TABLE companies (id INTEGER PRIMARY KEY, name TEXT);
            INSERT INTO companies (id, name) VALUES (1, 'Co');
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER,
                name TEXT NOT NULL,
                contact TEXT DEFAULT '',
                note TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT DEFAULT (datetime('now', 'localtime')),
                extra1 TEXT DEFAULT '{}',
                extra2 TEXT DEFAULT '{}',
                extra3 TEXT DEFAULT '{}'
            );
            INSERT INTO customers (company_id, name, contact, note, extra1, extra2, extra3)
            VALUES (1, '旧客户', 'Ada', '备注保留',
                    '{"country":"IT","tier":"A"}',
                    '{"email":"a@x.com"}', '{}');
            """
        )
        # 补齐 _needs_schema_work 会看的其它表，避免误判干扰本用例
        for table in (
            "trade_companies", "libraries", "customer_libraries", "conversations",
            "orders", "order_items", "usage_ledger", "cron_job_companies",
            "trial_events", "doc_extractions",
        ):
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table} "
                "(id INTEGER PRIMARY KEY, extra1 TEXT, extra2 TEXT, extra3 TEXT)"
            )
        conn.execute(
            "CREATE TABLE schema_migrations "
            "(version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"
        )
        conn.execute(
            "INSERT INTO schema_migrations (version, name) VALUES (1, 'backfill_order_items')"
        )
        conn.execute("ALTER TABLE conversations ADD COLUMN context TEXT DEFAULT ''")
        conn.execute("ALTER TABLE conversations ADD COLUMN customer_id INTEGER")
        conn.execute(
            "ALTER TABLE conversations ADD COLUMN is_important INTEGER NOT NULL DEFAULT 0"
        )
        conn.commit()

        assert _needs_schema_work(conn) is True
        before_count = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        old = conn.execute(
            "SELECT name, contact, note, extra1, extra2, extra3 FROM customers WHERE id=1"
        ).fetchone()

        _add_customer_crm_columns(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(customers)")}
        assert {"stage", "next_follow_up_date", "is_starred"} <= cols
        assert conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == before_count

        row = conn.execute("SELECT * FROM customers WHERE id=1").fetchone()
        assert row["name"] == old["name"]
        assert row["contact"] == old["contact"]
        assert row["note"] == old["note"]
        assert row["extra1"] == old["extra1"]
        assert row["extra2"] == old["extra2"]
        assert row["extra3"] == old["extra3"]
        assert row["stage"] == "询盘"
        assert row["next_follow_up_date"] == ""
        assert row["is_starred"] == 0

        _add_customer_crm_columns(conn)  # 幂等
        conn.close()


class TestListOverviewAndImportant:
    """list 聚合字段 + overview + set_important。"""

    def test_list_aggregates_and_overview(self, test_db, company_id):
        from trade import chat_memory, customer, order

        c = customer.create("Wall Co", "Ada", company_id=company_id)
        cid = c["id"]
        other = customer.create("Other Co", "Bob", company_id=company_id)

        order.create(
            company_id=company_id,
            customer_id=cid,
            product_name="Widget",
            quantity=2,
            unit_price=50,
            total_amount=100,
            status="已下单",
        )
        a = chat_memory.save(company_id, "给 Wall", "答 A", customer_id=cid)
        chat_memory.save(company_id, "别人的", "答 C", customer_id=other["id"])

        listed = customer.list_by_company(company_id)
        by_id = {row["id"]: row for row in listed}
        assert by_id[cid]["order_count"] == 1
        assert float(by_id[cid]["order_total_amount"]) == 100.0
        assert by_id[cid]["last_contact_at"]
        assert by_id[other["id"]]["order_count"] == 0

        updated = customer.update(
            cid, company_id=company_id, stage="报价", next_follow_up_date="2026-01-01"
        )
        assert updated["stage"] == "报价"
        assert updated["next_follow_up_date"] == "2026-01-01"

        marked = chat_memory.set_important(company_id, a["id"], True)
        assert marked["is_important"] is True

        ov = customer.get_overview(cid, company_id=company_id)
        assert ov is not None
        assert ov["stats"]["order_count"] == 1
        assert ov["stats"]["order_total_amount"] == 100.0
        assert ov["stats"]["order_total_currency"] == "USD"
        assert ov["people"]
        assert len(ov["orders"]) == 1
        assert any(t["is_important"] for t in ov["key_talks"])
        assert ov["timeline"]
        assert ov["customer"]["stage"] == "报价"

    def test_create_persists_crm_fields(self, test_db, company_id):
        """审计 P2：POST 建客户时 stage / next_follow_up_date / is_starred 必须入库。"""
        from trade import customer

        row = customer.create(
            "CRM New",
            company_id=company_id,
            stage="样品",
            next_follow_up_date="2026-03-15",
            is_starred=1,
        )
        assert row["stage"] == "样品"
        assert row["next_follow_up_date"] == "2026-03-15"
        assert row["is_starred"] in (1, True)

        again = customer.get(row["id"], company_id=company_id)
        assert again["stage"] == "样品"
        assert again["next_follow_up_date"] == "2026-03-15"
        assert again["is_starred"] in (1, True)

        # 非法阶段回落默认；非法标星视为 0
        bad = customer.create(
            "Bad Stage",
            company_id=company_id,
            stage="不存在的阶段",
            is_starred=9,
        )
        assert bad["stage"] == "询盘"
        assert bad["is_starred"] in (0, False)

    def test_multi_currency_totals_not_summed(self, test_db, company_id):
        """审计 P2：多币种订单不得硬加总额。"""
        from trade import customer, order

        c = customer.create("FX Co", company_id=company_id)
        cid = c["id"]
        order.create(
            company_id=company_id, customer_id=cid,
            product_name="A", total_amount=100, currency="USD",
        )
        order.create(
            company_id=company_id, customer_id=cid,
            product_name="B", total_amount=200, currency="EUR",
        )

        listed = {r["id"]: r for r in customer.list_by_company(company_id)}
        assert listed[cid]["order_count"] == 2
        assert listed[cid]["order_total_amount"] is None
        assert listed[cid]["order_total_currency"] is None
        assert listed[cid]["order_totals_by_currency"]["USD"] == 100.0
        assert listed[cid]["order_totals_by_currency"]["EUR"] == 200.0

        ov = customer.get_overview(cid, company_id=company_id)
        assert ov["stats"]["order_total_amount"] is None
        assert ov["stats"]["order_total_currency"] is None
        assert ov["stats"]["order_totals_by_currency"]["USD"] == 100.0
        assert ov["stats"]["order_totals_by_currency"]["EUR"] == 200.0

    def test_overview_cross_company_isolation(self, test_db, company_id):
        """审计：A 公司读不到 B 公司客户 overview。"""
        from trade import company, customer, order

        co_b = company.create("Other Co B")["id"]
        cust_b = customer.create("B Only", company_id=co_b)
        order.create(
            company_id=co_b, customer_id=cust_b["id"],
            product_name="Secret", total_amount=999, currency="USD",
        )

        # A 公司用 B 的 customer_id → fail-closed
        assert customer.get(cust_b["id"], company_id=company_id) is None
        assert customer.get_overview(cust_b["id"], company_id=company_id) is None

        # B 公司自己可读
        ov_b = customer.get_overview(cust_b["id"], company_id=co_b)
        assert ov_b is not None
        assert ov_b["stats"]["order_total_amount"] == 999.0
        assert ov_b["customer"]["name"] == "B Only"
