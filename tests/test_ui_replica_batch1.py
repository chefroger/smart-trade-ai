"""批次一 W1–W6：主联系人职能/城市/stats 拆分/email_details/列表汇总/对话标题。"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="module")
def setup_mocks():
    """屏蔽 Hermes 顶层模块，避免 CI/本地无 Hermes 时 import 失败。"""
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
    """每个用例独立 TRADE_HOME + 初始化 schema。"""
    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    from trade import database as db

    db.init_db()
    yield tmp_path


@pytest.fixture
def company_id(test_db):
    """建一家测试公司。"""
    from trade import company

    return company.create(name="UI Replica Co", slug="ui-replica-co")["id"]


@pytest.fixture
def api_client(test_db, company_id, setup_mocks):
    """轻量 FastAPI TestClient + session token + 当前公司。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from trade.api import deps, router

    token = "ui-replica-batch1-token"
    deps.set_session_token(token)
    deps._ACTIVE_COMPANY.pop(token, None)

    app = FastAPI()
    app.include_router(router, prefix="/api/trade")
    return TestClient(app), token, company_id


def _h(token: str, cid: int) -> dict[str, str]:
    """组装会话头。"""
    return {"X-Hermes-Session-Token": token, "X-Company-ID": str(cid)}


def _insert_email(company_id: int, customer_id: int, *, subject: str, received_at: str) -> None:
    """往 emails 表插一行（需先有 mailbox）。"""
    from trade.database import get_connection

    conn = get_connection()
    try:
        row = conn.execute("SELECT id FROM mailboxes LIMIT 1").fetchone()
        if not row:
            conn.execute(
                "INSERT INTO mailboxes (provider, preset, email_address, host, port, username) "
                "VALUES ('imap', '126', 'box@x.com', 'imap.126.com', 993, 'box@x.com')"
            )
            conn.commit()
            mid = conn.execute("SELECT id FROM mailboxes LIMIT 1").fetchone()["id"]
        else:
            mid = row["id"]
        conn.execute(
            "INSERT INTO emails (mailbox_id, message_id, company_id, customer_id, subject, "
            "snippet, body_text, from_addr, to_addrs, received_at) "
            "VALUES (?, ?, ?, ?, ?, '', '', 'x@y.com', '[]', ?)",
            (mid, f"<{subject}-{received_at}>", company_id, customer_id, subject, received_at),
        )
        conn.commit()
    finally:
        conn.close()


# ── W1 主联系人 function / responsibility ──────────────────────────────


class TestW1PrimaryFunction:
    def test_create_and_overview_people(self, test_db, company_id):
        from trade import customer

        row = customer.create(
            "Acme",
            "Alice",
            company_id=company_id,
            title="采购主管",
            email="alice@acme.com",
            function="决策人",
            responsibility="主要对接人",
        )
        e2 = json.loads(row["extra2"])
        assert e2["function"] == "决策人"
        assert e2["responsibility"] == "主要对接人"

        ov = customer.get_overview(row["id"], company_id=company_id)
        p0 = ov["people"][0]
        assert p0["is_primary"] is True
        assert p0["function"] == "决策人"
        assert p0["responsibility"] == "主要对接人"
        assert p0["title"] == "采购主管"

    def test_dirty_function_normalized(self, test_db, company_id):
        from trade import customer

        row = customer.create(
            "Dirty Co", company_id=company_id, contact="Bob", function="老板"
        )
        e2 = json.loads(row["extra2"])
        assert e2["function"] == "其他"

        updated = customer.update(
            row["id"], company_id=company_id, function="CXO", responsibility="  对接  "
        )
        e2b = json.loads(updated["extra2"])
        assert e2b["function"] == "其他"
        assert e2b["responsibility"] == "对接"

    def test_update_omit_keeps_old(self, test_db, company_id):
        from trade import customer

        row = customer.create(
            "Keep Co",
            company_id=company_id,
            contact="Carol",
            function="财务",
            responsibility="付款",
        )
        customer.update(row["id"], company_id=company_id, title="CFO")
        again = customer.get(row["id"], company_id=company_id)
        e2 = json.loads(again["extra2"])
        assert e2["function"] == "财务"
        assert e2["responsibility"] == "付款"

    def test_api_create_update(self, api_client):
        client, token, company_id = api_client
        h = _h(token, company_id)
        r = client.post(
            "/api/trade/customers",
            headers=h,
            json={
                "name": "API Co",
                "contact": "Dan",
                "function": "仓储",
                "responsibility": "收货",
            },
        )
        assert r.status_code == 200
        cust_id = r.json()["id"]
        ov = client.get(f"/api/trade/customers/{cust_id}/overview", headers=h)
        assert ov.json()["people"][0]["function"] == "仓储"
        r2 = client.put(
            f"/api/trade/customers/{cust_id}",
            headers=h,
            json={"function": "决策人"},
        )
        assert r2.status_code == 200
        e2 = json.loads(r2.json()["extra2"])
        assert e2["function"] == "决策人"


# ── W2 city ────────────────────────────────────────────────────────────


class TestW2City:
    def test_city_in_extra1_and_csv(self, test_db, company_id):
        from trade import customer

        row = customer.create(
            "City Co", company_id=company_id, country="德国", city="汉堡"
        )
        e1 = json.loads(row["extra1"])
        assert e1["city"] == "汉堡"
        assert e1["country"] == "德国"

        bulk = customer.bulk_save(
            company_id,
            [{"name": "CSV City", "country": "Italy", "city": "Milan", "email": "a@b.com"}],
        )
        assert bulk["created"] == 1
        listed = {c["name"]: c for c in customer.list_by_company(company_id)}
        e1b = json.loads(listed["CSV City"]["extra1"])
        assert e1b["city"] == "Milan"

    def test_csv_template_has_city(self):
        from pathlib import Path

        text = (Path(__file__).resolve().parent.parent / "static" / "trade-customer-template.csv").read_text(
            encoding="utf-8"
        )
        assert "city" in text.splitlines()[0].split(",")


# ── W3 stats 拆分 ──────────────────────────────────────────────────────


class TestW3StatsSplit:
    def test_email_key_talk_quote_counts(self, test_db, company_id):
        from trade import chat_memory, customer, order

        c = customer.create("Stats Co", "Eve", company_id=company_id, email="eve@s.com")
        cid = c["id"]
        order.create(
            company_id=company_id, customer_id=cid,
            product_name="Q", status="报价中", total_amount=10, currency="USD",
        )
        order.create(
            company_id=company_id, customer_id=cid,
            product_name="O", status="已下单", total_amount=20, currency="USD",
        )
        a = chat_memory.save(company_id, "问1", "答1", customer_id=cid)
        chat_memory.save(company_id, "问2", "答2", customer_id=cid)
        chat_memory.set_important(company_id, a["id"], True)

        _insert_email(company_id, cid, subject="S0", received_at="2026-01-01 10:00:00")
        _insert_email(company_id, cid, subject="S1", received_at="2026-01-02 10:00:00")

        ov = customer.get_overview(cid, company_id=company_id)
        st = ov["stats"]
        assert st["email_count"] == 2
        assert st["key_talk_count"] == 1  # 只有 1 条 important
        assert st["quote_count"] == 1
        # 旧字段仍按地址数 + key_talks
        assert st["mail_and_talk_count"] == len(ov["emails"]) + len(ov["key_talks"])
        assert ov["key_talks"][0]["is_important_fallback"] is False

    def test_fallback_flag_when_no_important(self, test_db, company_id):
        from trade import chat_memory, customer

        c = customer.create("Fb Co", company_id=company_id, contact="F")
        for i in range(3):
            chat_memory.save(company_id, f"q{i}", f"a{i}", customer_id=c["id"])
        ov = customer.get_overview(c["id"], company_id=company_id)
        assert len(ov["key_talks"]) == 3
        assert all(t["is_important_fallback"] for t in ov["key_talks"])


# ── W4 email_details ───────────────────────────────────────────────────


class TestW4EmailDetails:
    def test_email_details_shape(self, test_db, company_id):
        from trade import contacts, customer

        c = customer.create(
            "Mail Co",
            "Gina",
            company_id=company_id,
            email="primary@mail.com",
            backup_email="backup@mail.com",
        )
        contacts.create(
            c["id"],
            company_id=company_id,
            data={"name": "Hank", "email": "hank@mail.com", "function": "财务"},
        )
        contacts.create(
            c["id"],
            company_id=company_id,
            data={"name": "Ivy", "email": "ivy@mail.com", "function": "仓储"},
        )
        ov = customer.get_overview(c["id"], company_id=company_id)
        details = ov["email_details"]
        assert len(details) == 4
        assert details[0]["address"] == "primary@mail.com"
        assert details[0]["is_primary"] is True
        assert details[0]["source"] == "primary"
        assert details[0]["contact_id"] is None
        assert details[1]["source"] == "backup"
        assert details[1]["is_primary"] is False
        contact_rows = [d for d in details if d["source"] == "contact"]
        assert len(contact_rows) == 2
        assert all(d["contact_id"] is not None for d in contact_rows)
        # 旧字段仍在
        assert ov["emails"][0] == "primary@mail.com"


# ── W5 summary / pagination / extra_contacts / last_email ──────────────


class TestW5ListSide:
    def test_summary_and_follow_up_pending(self, test_db, company_id, api_client):
        from trade import customer, order

        today = date.today()
        customer.create(
            "Soon", company_id=company_id,
            next_follow_up_date=(today + timedelta(days=2)).isoformat(),
            stage="询盘",
        )
        customer.create(
            "Overdue", company_id=company_id,
            next_follow_up_date=(today - timedelta(days=3)).isoformat(),
            stage="报价",
        )
        customer.create(
            "NoneFollow", company_id=company_id, stage="样品",
        )
        c = customer.create("Buyer", company_id=company_id, stage="订单")
        order.create(
            company_id=company_id, customer_id=c["id"],
            product_name="X", total_amount=100, currency="USD",
        )
        order.create(
            company_id=company_id, customer_id=c["id"],
            product_name="Y", total_amount=50, currency="EUR",
        )

        s = customer.get_company_summary(company_id)
        assert s["total"] == 4
        assert s["follow_up_pending"] == 1  # 只有 Soon（≥ 今天）
        assert s["overdue"] == 1
        assert s["stage_counts"]["询盘"] == 1
        assert s["order_totals_by_currency"]["USD"] == 100.0
        assert s["order_totals_by_currency"]["EUR"] == 50.0

        client, token, cid = api_client
        r = client.get("/api/trade/customers/summary", headers=_h(token, cid))
        assert r.status_code == 200
        assert r.json()["total"] == 4

    def test_extra_contacts_and_last_email(self, test_db, company_id):
        from trade import chat_memory, contacts, customer

        c = customer.create(
            "Search Co", "Main", company_id=company_id, email="main@s.com"
        )
        contacts.create(
            c["id"],
            company_id=company_id,
            data={"name": "Hidden Extra", "email": "hidden@extra.com"},
        )
        chat_memory.save(company_id, "talk", "ok", customer_id=c["id"])
        _insert_email(
            company_id, c["id"], subject="hi", received_at="2099-01-01 12:00:00"
        )

        listed = {row["id"]: row for row in customer.list_by_company(company_id)}
        row = listed[c["id"]]
        assert any(x["email"] == "hidden@extra.com" for x in row["extra_contacts"])
        assert row["last_talk_at"]
        assert row["last_email_at"] == "2099-01-01 12:00:00"
        assert row["last_contact_at"] == "2099-01-01 12:00:00"

    def test_pagination_headers(self, api_client, company_id):
        from trade import customer

        client, token, cid = api_client
        h = _h(token, cid)
        for i in range(3):
            customer.create(f"Page{i}", company_id=company_id)
        # 未传 page → 全量
        r = client.get("/api/trade/customers", headers=h)
        assert r.status_code == 200
        assert len(r.json()) >= 3
        assert r.headers.get("X-Total-Count")
        # 传 page → 切页
        r2 = client.get("/api/trade/customers?page=1&limit=2", headers=h)
        assert r2.status_code == 200
        assert len(r2.json()) == 2
        assert int(r2.headers["X-Total-Count"]) >= 3


# ── W6 conversation note ───────────────────────────────────────────────


class TestW6ConversationNote:
    def test_set_note_and_overview(self, test_db, company_id, api_client):
        from trade import chat_memory, customer

        client, token, cid = api_client
        h = _h(token, cid)
        c = customer.create("Note Co", company_id=company_id, contact="N")
        conv = chat_memory.save(company_id, "询盘内容很长", "回复很长", customer_id=c["id"])
        chat_memory.set_important(company_id, conv["id"], True)

        r = client.put(
            f"/api/trade/conversations/{conv['id']}/note",
            headers=h,
            json={"title": "询盘回复要点", "summary": "对方要样品"},
        )
        assert r.status_code == 200
        body = r.json()["conversation"]
        assert body["title"] == "询盘回复要点"
        assert body["summary"] == "对方要样品"

        ov = customer.get_overview(c["id"], company_id=company_id)
        kt = ov["key_talks"][0]
        assert kt["title"] == "询盘回复要点"
        assert kt["summary"] == "对方要样品"

    def test_note_too_long_400(self, api_client, company_id):
        from trade import chat_memory

        client, token, cid = api_client
        h = _h(token, cid)
        conv = chat_memory.save(company_id, "q", "a")
        r = client.put(
            f"/api/trade/conversations/{conv['id']}/note",
            headers=h,
            json={"title": "x" * 61, "summary": "ok"},
        )
        assert r.status_code == 400
        assert isinstance(r.json()["detail"], str)

    def test_unset_empty_strings(self, test_db, company_id):
        from trade import chat_memory, customer

        c = customer.create("Empty Note", company_id=company_id)
        conv = chat_memory.save(company_id, "q", "a", customer_id=c["id"])
        ov = customer.get_overview(c["id"], company_id=company_id)
        assert ov["key_talks"][0]["title"] == ""
        assert ov["key_talks"][0]["summary"] == ""
        assert conv["title"] == ""
