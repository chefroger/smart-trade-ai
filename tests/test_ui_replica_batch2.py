"""批次二 W7–W8：订单物流字段 + order_events + 时间线接口。"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="module")
def setup_mocks():
    with patch.dict(sys.modules, {
        "hermes_cli": MagicMock(),
        "hermes_cli.config": MagicMock(),
        "hermes_cli.auth": MagicMock(),
        "hermes_cli.env_loader": MagicMock(),
        "hermes_cli.models": MagicMock(),
        "hermes_constants": MagicMock(),
        "run_agent": MagicMock(),
    }):
        import hermes_cli
        hermes_cli.__version__ = "0.13.0"
        yield


@pytest.fixture
def test_db(monkeypatch, tmp_path, setup_mocks):
    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    from trade import database as db

    db.init_db()
    yield tmp_path


@pytest.fixture
def company_id(test_db):
    from trade import company

    return company.create(name="Batch2 Co", slug="batch2-co")["id"]


class TestW7OrderLogistics:
    def test_create_with_logistics_and_status_event(self, test_db, company_id):
        from trade import customer, order
        from trade.database import get_connection

        c = customer.create("Ship Co", company_id=company_id)
        o = order.create(
            company_id=company_id,
            customer_id=c["id"],
            product_name="Widget",
            order_no="PI-2611",
            status="报价中",
            payment_terms="30/70 T/T",
            incoterm="FOB",
            port_of_loading="宁波",
            container="1×20GP",
            lead_time_text="定金后 25 天",
            total_amount=100,
        )
        assert o["incoterm"] == "FOB"
        assert o["port_of_loading"] == "宁波"
        assert o["container"] == "1×20GP"
        assert o["lead_time_text"] == "定金后 25 天"

        updated = order.update(
            o["id"], company_id=company_id, status="已下单",
        )
        assert updated["status"] == "已下单"

        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT from_status, to_status FROM order_events WHERE order_id = ?",
                (o["id"],),
            ).fetchall()
        finally:
            conn.close()
        assert len(rows) == 1
        assert rows[0]["from_status"] == "报价中"
        assert rows[0]["to_status"] == "已下单"

        ov = customer.get_overview(c["id"], company_id=company_id)
        assert ov["orders"][0]["incoterm"] == "FOB"

    def test_list_orders_status_and_limit(self, test_db, company_id):
        from trade import customer, order

        c = customer.create("List Co", company_id=company_id)
        order.create(
            company_id=company_id, customer_id=c["id"],
            product_name="A", status="报价中",
        )
        order.create(
            company_id=company_id, customer_id=c["id"],
            product_name="B", status="已下单",
        )
        only = order.list_by_company(company_id, status="已下单", limit=10)
        assert len(only) == 1
        assert only[0]["product_name"] == "B"

    def test_migration_v2_adds_columns_idempotent(self, tmp_path, setup_mocks):
        """旧 orders 无物流列时迁移 2 补列；旧行不变；再跑一次幂等。"""
        from trade.database import (
            _KNOWN_MIGRATION_VERSIONS,
            _migrate_order_logistics_v2,
            _needs_schema_work,
        )

        db = tmp_path / "old.db"
        conn = sqlite3.connect(db)
        # 最小可用表集 + 迁移 1 已应用、缺迁移 2/3
        for table in (
            "companies", "trade_companies", "libraries", "customers",
            "customer_libraries", "conversations", "orders", "order_items",
            "usage_ledger", "cron_job_companies", "trial_events", "doc_extractions",
            "mailboxes", "emails", "contacts",
            "customer_facts", "customer_gifts", "inquiries", "visit_plans",
            "app_settings", "todos",
            "osint_jobs", "osint_job_events", "osint_facts",
        ):
            if table == "orders":
                conn.execute(
                    "CREATE TABLE orders (id INTEGER PRIMARY KEY, company_id INTEGER, "
                    "customer_id INTEGER, product_name TEXT, status TEXT, "
                    "extra1 TEXT, extra2 TEXT, extra3 TEXT)"
                )
            elif table == "customers":
                # N4：与 _needs_schema_work / _fresh_db 对齐，含 stage_override
                conn.execute(
                    "CREATE TABLE customers (id INTEGER PRIMARY KEY, "
                    "extra1 TEXT, extra2 TEXT, extra3 TEXT, company_id INTEGER, "
                    "customer_id INTEGER, stage TEXT, stage_override TEXT, "
                    "next_follow_up_date TEXT, is_starred INTEGER, "
                    "context TEXT, is_important INTEGER)"
                )
            else:
                conn.execute(
                    f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, "
                    f"extra1 TEXT, extra2 TEXT, extra3 TEXT, company_id INTEGER, "
                    f"customer_id INTEGER, stage TEXT, next_follow_up_date TEXT, "
                    f"is_starred INTEGER, context TEXT, is_important INTEGER)"
                )
        conn.execute(
            "CREATE TABLE schema_migrations "
            "(version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"
        )
        conn.execute(
            "INSERT INTO schema_migrations (version, name) VALUES (1, 'backfill_order_items')"
        )
        conn.execute(
            "INSERT INTO orders (id, company_id, customer_id, product_name, status) "
            "VALUES (1, 1, 1, 'Keep Me', '报价中')"
        )
        conn.commit()

        assert _needs_schema_work(conn) is True  # 缺迁移 2/3 + 缺 order_events

        _migrate_order_logistics_v2(conn)
        conn.execute(
            "INSERT INTO schema_migrations (version, name) "
            "VALUES (2, 'order_logistics_and_events')"
        )
        # v3~v5 与订单物流无关，但「已是最新」的判定要求已知迁移均已在册
        conn.execute(
            "INSERT INTO schema_migrations (version, name) "
            "VALUES (3, 'scrub_visit_plan_profile_reminders')"
        )
        conn.execute(
            "INSERT INTO schema_migrations (version, name) "
            "VALUES (4, 'osint_facts_verified')"
        )
        conn.execute(
            "INSERT INTO schema_migrations (version, name) "
            "VALUES (5, 'todos_reason')"
        )
        conn.commit()

        cols = {r[1] for r in conn.execute("PRAGMA table_info(orders)")}
        assert "incoterm" in cols and "shipped_at" in cols
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "order_events" in tables
        row = conn.execute("SELECT product_name, status FROM orders WHERE id=1").fetchone()
        assert row[0] == "Keep Me" and row[1] == "报价中"

        # 再跑一次：列已存在不炸
        _migrate_order_logistics_v2(conn)
        assert _KNOWN_MIGRATION_VERSIONS <= {
            r[0] for r in conn.execute("SELECT version FROM schema_migrations")
        }
        # 表齐 + 迁移齐 → 不需要再备份
        assert _needs_schema_work(conn) is False
        conn.close()


class TestW8Timeline:
    def test_timeline_kinds_and_days(self, test_db, company_id):
        from trade import chat_memory, customer, order
        from trade.database import get_connection

        c = customer.create(
            "TL Co",
            company_id=company_id,
            email="buyer@tl.com",
            next_follow_up_date=date.today().isoformat(),
        )
        o = order.create(
            company_id=company_id,
            customer_id=c["id"],
            product_name="Cable",
            order_no="PI-99",
            status="报价中",
            container="1×20GP",
            port_of_loading="宁波",
        )
        order.update(o["id"], company_id=company_id, status="已下单")
        order.update(
            o["id"], company_id=company_id, status="已出货", shipped_at="2026-09-01",
        )
        conv = chat_memory.save(
            company_id, "询盘问题", "我们报价", customer_id=c["id"],
        )
        chat_memory.set_conversation_note(
            company_id, conv["id"], title="询盘要点", summary="要样品",
        )

        # 插一封来自客户的邮件
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO mailboxes (provider, preset, email_address, host, port, username) "
                "VALUES ('imap', '126', 'me@x.com', 'imap.126.com', 993, 'me@x.com')"
            )
            mid = conn.execute("SELECT id FROM mailboxes").fetchone()[0]
            conn.execute(
                "INSERT INTO emails (mailbox_id, message_id, company_id, customer_id, "
                "subject, from_addr, to_addrs, snippet, body_text, received_at) "
                "VALUES (?, '<m1>', ?, ?, 'Hello', 'Buyer <buyer@tl.com>', '[]', '', '', "
                "datetime('now','localtime'))",
                (mid, company_id, c["id"]),
            )
            conn.commit()
        finally:
            conn.close()

        items = customer.get_timeline(c["id"], company_id=company_id, days=60)
        kinds = {e["kind"] for e in items}
        assert "order_created" in kinds
        assert "order_status" in kinds
        assert "talk" in kinds
        assert "email_in" in kinds
        assert "follow_up_due" in kinds
        # 标题/副文本
        talk = next(e for e in items if e["kind"] == "talk")
        assert talk["title"] == "询盘要点"
        ship = next(
            e for e in items
            if e["kind"] == "order_status" and "出货" in e["title"]
        )
        assert "20GP" in ship["detail"] or "宁波" in ship["detail"]

        # days=1 窗口：只含当天（构造的历史事件若时间戳是 now 也会进来）
        today_only = customer.get_timeline(c["id"], company_id=company_id, days=1)
        assert isinstance(today_only, list)

    def test_timeline_api(self, test_db, company_id, setup_mocks):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from trade import customer
        from trade.api import deps, router

        token = "batch2-tl"
        deps.set_session_token(token)
        deps._ACTIVE_COMPANY.pop(token, None)
        app = FastAPI()
        app.include_router(router, prefix="/api/trade")
        client = TestClient(app)
        h = {"X-Hermes-Session-Token": token, "X-Company-ID": str(company_id)}
        c = customer.create("API TL", company_id=company_id)
        r = client.get(
            f"/api/trade/customers/{c['id']}/timeline?days=30", headers=h,
        )
        assert r.status_code == 200
        assert isinstance(r.json(), list)


def test_clean_shipped_at_accepts_month_or_day():
    """出货日只收 YYYY-MM / YYYY-MM-DD，脏值 400（P2-5）。"""
    from fastapi import HTTPException

    from trade.api.orders import _clean_shipped_at

    assert _clean_shipped_at(None) is None
    assert _clean_shipped_at("") == ""
    assert _clean_shipped_at("2026-12") == "2026-12"
    assert _clean_shipped_at("2026-12-01") == "2026-12-01"
    for bad in ("2026/12/01", "2026-13", "2026-12-32", "2026-12-1", "abc"):
        with pytest.raises(HTTPException) as exc:
            _clean_shipped_at(bad)
        assert exc.value.status_code == 400


def test_orders_limit_out_of_range_is_400(test_db, company_id):
    """limit=0/501 走 400 + 中文字符串，不是 FastAPI 422（P2-6）。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from trade.api import deps, router

    token = "batch2-limit"
    deps.set_session_token(token)
    deps._ACTIVE_COMPANY.pop(token, None)
    app = FastAPI()
    app.include_router(router, prefix="/api/trade")
    client = TestClient(app)
    h = {"X-Hermes-Session-Token": token, "X-Company-ID": str(company_id)}
    for bad in (0, -1, 501):
        r = client.get(f"/api/trade/orders?limit={bad}", headers=h)
        assert r.status_code == 400, (bad, r.text)
        assert isinstance(r.json()["detail"], str)
    assert client.get("/api/trade/orders?limit=1", headers=h).status_code == 200
