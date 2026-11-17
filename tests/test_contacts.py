"""多联系人 contacts：CRUD、overview、匹配、级联、缺表降级。"""

from __future__ import annotations

import json
import sqlite3
import sys
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

    return company.create(name="Contacts Co", slug="contacts-co")["id"]


@pytest.fixture
def other_company_id(test_db):
    from trade import company

    return company.create(name="Other Co", slug="other-co")["id"]


@pytest.fixture
def api_client(test_db, company_id, setup_mocks):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from trade.api import deps, router

    token = "contacts-api-token"
    deps.set_session_token(token)
    deps._ACTIVE_COMPANY.pop(token, None)

    app = FastAPI()
    app.include_router(router, prefix="/api/trade")
    return TestClient(app), token, company_id


def _h(token: str, cid: int) -> dict[str, str]:
    return {"X-Hermes-Session-Token": token, "X-Company-ID": str(cid)}


def _make_customer(cid: int, **kwargs):
    from trade import customer

    return customer.create(company_id=cid, name=kwargs.pop("name", "Acme"), **kwargs)


# ── API CRUD ───────────────────────────────────────────────────────────────


def test_crud_and_validation(api_client):
    client, token, cid = api_client
    cust = _make_customer(cid, contact="Alice", email="alice@acme.com")
    cust_id = cust["id"]
    h = _h(token, cid)

    # GET：primary 来自 customers，contacts 空
    r = client.get(f"/api/trade/customers/{cust_id}/contacts", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["primary"]["name"] == "Alice"
    assert body["primary"]["is_primary"] is True
    assert body["primary"]["id"] is None
    assert body["contacts"] == []

    # POST 缺 name → 400
    r = client.post(
        f"/api/trade/customers/{cust_id}/contacts",
        headers=h,
        json={"name": "  ", "email": "b@acme.com"},
    )
    assert r.status_code == 400
    assert isinstance(r.json()["detail"], str)

    # email 无 @ → 400
    r = client.post(
        f"/api/trade/customers/{cust_id}/contacts",
        headers=h,
        json={"name": "Bob", "email": "not-an-email"},
    )
    assert r.status_code == 400

    # is_primary=1 → 400
    r = client.post(
        f"/api/trade/customers/{cust_id}/contacts",
        headers=h,
        json={"name": "Bob", "is_primary": 1},
    )
    assert r.status_code == 400
    assert "主联系人" in r.json()["detail"]

    # function 脏值归一
    r = client.post(
        f"/api/trade/customers/{cust_id}/contacts",
        headers=h,
        json={"name": "Bob", "function": "老板", "email": "bob@acme.com", "title": "CEO"},
    )
    assert r.status_code == 201
    bob = r.json()
    assert bob["function"] == "其他"
    assert bob["role"] == "CEO"
    assert bob["is_primary"] is False
    bob_id = bob["id"]

    # PUT
    r = client.put(
        f"/api/trade/customers/{cust_id}/contacts/{bob_id}",
        headers=h,
        json={"phone": "123"},
    )
    assert r.status_code == 200
    assert r.json()["phone"] == "123"
    assert r.json()["name"] == "Bob"

    # DELETE
    r = client.delete(
        f"/api/trade/customers/{cust_id}/contacts/{bob_id}",
        headers=h,
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_cross_company_404(api_client, other_company_id):
    client, token, cid = api_client
    cust = _make_customer(cid, contact="A", email="a@x.com")
    h = _h(token, cid)
    r = client.post(
        f"/api/trade/customers/{cust['id']}/contacts",
        headers=h,
        json={"name": "Extra", "email": "e@x.com"},
    )
    contact_id = r.json()["id"]

    # 换公司头
    h2 = _h(token, other_company_id)
    # 先绑到 other（switch 语义：直接用新 company 头会 403，除非清绑定）
    from trade.api import deps

    deps._ACTIVE_COMPANY[token] = other_company_id
    r = client.get(
        f"/api/trade/customers/{cust['id']}/contacts",
        headers=h2,
    )
    assert r.status_code == 404
    r = client.put(
        f"/api/trade/customers/{cust['id']}/contacts/{contact_id}",
        headers=h2,
        json={"name": "Hacked"},
    )
    assert r.status_code == 404


def test_overview_people_and_emails(api_client):
    client, token, cid = api_client
    cust = _make_customer(
        cid,
        contact="Alice",
        email="alice@acme.com",
        backup_email="backup@acme.com",
        title="Buyer",
    )
    h = _h(token, cid)
    client.post(
        f"/api/trade/customers/{cust['id']}/contacts",
        headers=h,
        json={"name": "Bob", "email": "bob@acme.com", "title": "Finance"},
    )
    client.post(
        f"/api/trade/customers/{cust['id']}/contacts",
        headers=h,
        json={"name": "Carol", "email": "ALICE@acme.com", "function": "仓储"},
    )
    r = client.get(f"/api/trade/customers/{cust['id']}/overview", headers=h)
    assert r.status_code == 200
    ov = r.json()
    assert ov["stats"]["people_count"] == 3
    assert ov["people"][0]["is_primary"] is True
    assert ov["people"][0]["name"] == "Alice"
    assert len(ov["people"]) == 3
    # 去重：alice / backup / bob（carol 与 alice 同址）
    emails = ov["emails"]
    assert emails[0] == "alice@acme.com"
    assert "backup@acme.com" in emails
    assert "bob@acme.com" in emails
    assert emails.count("alice@acme.com") == 1


def test_empty_primary_null(api_client):
    client, token, cid = api_client
    cust = _make_customer(cid, name="Empty Co")
    h = _h(token, cid)
    r = client.get(f"/api/trade/customers/{cust['id']}/contacts", headers=h)
    assert r.json()["primary"] is None


def test_delete_customer_clears_contacts(api_client):
    client, token, cid = api_client
    from trade.database import get_connection

    cust = _make_customer(cid, contact="A", email="a@x.com")
    h = _h(token, cid)
    client.post(
        f"/api/trade/customers/{cust['id']}/contacts",
        headers=h,
        json={"name": "Extra", "email": "e@x.com"},
    )
    r = client.delete(f"/api/trade/customers/{cust['id']}", headers=h)
    assert r.status_code == 200
    conn = get_connection()
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM contacts WHERE customer_id = ?",
            (cust["id"],),
        ).fetchone()["n"]
        assert n == 0
    finally:
        conn.close()


def test_mail_match_contacts_email(test_db, company_id):
    from trade import contacts, customer, mailbox_store

    cust = customer.create(
        company_id=company_id,
        name="Match Co",
        contact="Main",
        email="main@co.com",
    )
    contacts.create(
        cust["id"],
        company_id=company_id,
        data={"name": "Extra", "email": "extra-only@co.com"},
    )
    pairs = mailbox_store.find_customer_matches("extra-only@co.com", [])
    assert (company_id, cust["id"]) in pairs


def test_briefing_other_contacts(test_db, company_id):
    from trade import contacts, customer

    cust = customer.create(
        company_id=company_id, name="Brief Co", contact="Main", email="m@c.com"
    )
    contacts.create(
        cust["id"],
        company_id=company_id,
        data={"name": "Extra", "title": "CFO", "email": "e@c.com"},
    )
    text = customer.build_briefing(cust["id"], company_id=company_id)
    assert "其他联系人" in text
    assert "Extra" in text


def test_missing_table_degrades(test_db, company_id, monkeypatch):
    """缺表时 overview / 匹配 / 简报不 500。"""
    from trade import customer, database, mailbox_store
    from trade.database import get_connection

    cust = customer.create(
        company_id=company_id, name="Deg Co", contact="A", email="a@d.com"
    )
    conn = get_connection()
    try:
        conn.execute("DROP TABLE contacts")
        conn.commit()
    finally:
        conn.close()

    ov = customer.get_overview(cust["id"], company_id=company_id)
    assert ov is not None
    assert ov["stats"]["people_count"] == 1
    assert ov["people"][0]["name"] == "A"

    pairs = mailbox_store.find_customer_matches("a@d.com", [])
    assert (company_id, cust["id"]) in pairs

    text = customer.build_briefing(cust["id"], company_id=company_id)
    assert "Brief" in text or "Deg" in text or "客户简报" in text

    # 写操作 → ContactsUnavailableError
    from trade.contacts import ContactsUnavailableError, create

    with pytest.raises(ContactsUnavailableError):
        create(cust["id"], company_id=company_id, data={"name": "X"})


def test_no_seed_into_contacts(api_client):
    """读 overview 不往 contacts 插行。"""
    from trade.database import get_connection

    client, token, cid = api_client
    cust = _make_customer(cid, contact="Seed", email="s@x.com")
    h = _h(token, cid)
    client.get(f"/api/trade/customers/{cust['id']}/overview", headers=h)
    client.get(f"/api/trade/customers/{cust['id']}/contacts", headers=h)
    conn = get_connection()
    try:
        n = conn.execute("SELECT COUNT(*) AS n FROM contacts").fetchone()["n"]
        assert n == 0
    finally:
        conn.close()
