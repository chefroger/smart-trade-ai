"""多联系人 contacts：CRUD、overview、匹配、级联、缺表降级。"""

from __future__ import annotations

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


def test_primary_note_from_follow_up_or_customer_note(test_db, company_id):
    """O-1 / N3 §5：主联系人 note = follow_up_note or customers.note。"""
    from trade import contacts, customer

    # follow_up_note 优先
    a = customer.create(
        "Note A",
        company_id=company_id,
        contact="Alice",
        note="客户备注应被盖住",
        follow_up_note="下周跟进报价",
    )
    pa = contacts.build_primary_person(a)
    assert pa is not None
    assert pa["note"] == "下周跟进报价"
    # overview people[0] 同源
    ov = customer.get_overview(a["id"], company_id=company_id)
    assert ov["people"][0]["note"] == "下周跟进报价"

    # follow_up_note 空 → 取 customers.note
    b = customer.create(
        "Note B",
        company_id=company_id,
        contact="Bob",
        note="只用客户备注",
        follow_up_note="",
    )
    assert contacts.build_primary_person(b)["note"] == "只用客户备注"

    # 两处都空 → 空串
    c = customer.create(
        "Note C",
        company_id=company_id,
        contact="Carol",
        note="",
        follow_up_note="",
    )
    assert contacts.build_primary_person(c)["note"] == ""


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


def test_mail_match_extra2_beats_contacts_same_address(test_db, company_id):
    """C1 附加人邮箱 = C2 主邮箱时，pairs[0] 必须是 C2（extra2 优先）。"""
    from trade import contacts, customer, mailbox_store
    from trade.database import get_connection

    c1 = customer.create(
        company_id=company_id,
        name="C1 First",
        contact="P1",
        email="p1@x.com",
    )
    c2 = customer.create(
        company_id=company_id,
        name="C2 Second",
        contact="P2",
        email="shared@x.com",
    )
    assert c1["id"] < c2["id"]
    contacts.create(
        c1["id"],
        company_id=company_id,
        data={"name": "Extra", "email": "SHARED@x.com"},
    )
    pairs = mailbox_store.find_customer_matches("shared@x.com", [])
    assert pairs[0] == (company_id, c2["id"])
    assert (company_id, c1["id"]) in pairs
    assert pairs.index((company_id, c1["id"])) > 0

    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO mailboxes (provider, preset, email_address, host, port, username) "
            "VALUES ('imap', '126', 'box@x.com', 'imap.126.com', 993, 'box@x.com')"
        )
        conn.commit()
        mid = conn.execute("SELECT id FROM mailboxes LIMIT 1").fetchone()["id"]
        eid = mailbox_store.insert_email_ignore(
            conn,
            mid,
            {
                "message_id": "<shared-1>",
                "uid": 1,
                "from_addr": "Someone <shared@x.com>",
                "to_addrs": [],
                "subject": "hi",
                "snippet": "hi",
                "body_text": "hi",
                "received_at": "2026-01-01T00:00:00",
            },
        )
        conn.commit()
        n = mailbox_store.rematch_unmatched_emails(mid)
        assert n == 1
        row = conn.execute(
            "SELECT customer_id FROM emails WHERE id=?", (eid,)
        ).fetchone()
        assert row["customer_id"] == c2["id"]
    finally:
        conn.close()


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
    from trade import customer, mailbox_store
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


def test_same_company_cross_customer_contact_404(api_client):
    """同公司客户 B 不能改/删客户 A 的联系人。"""
    client, token, cid = api_client
    a = _make_customer(cid, name="Cust A", contact="A", email="a@x.com")
    b = _make_customer(cid, name="Cust B", contact="B", email="b@x.com")
    h = _h(token, cid)
    r = client.post(
        f"/api/trade/customers/{a['id']}/contacts",
        headers=h,
        json={"name": "X", "email": "x@x.com", "phone": "111"},
    )
    assert r.status_code == 201
    xid = r.json()["id"]
    r = client.put(
        f"/api/trade/customers/{b['id']}/contacts/{xid}",
        headers=h,
        json={"name": "Hacked"},
    )
    assert r.status_code == 404
    r = client.delete(
        f"/api/trade/customers/{b['id']}/contacts/{xid}",
        headers=h,
    )
    assert r.status_code == 404
    r = client.get(f"/api/trade/customers/{a['id']}/contacts", headers=h)
    assert r.status_code == 200
    extras = r.json()["contacts"]
    assert len(extras) == 1
    assert extras[0]["name"] == "X"
    assert extras[0]["phone"] == "111"


def test_purge_company_clears_contacts(test_db, company_id):
    from trade import contacts, customer
    from trade.company import crud
    from trade.database import get_connection

    cust = customer.create(
        company_id=company_id, name="Purge Me", contact="A", email="a@p.com"
    )
    contacts.create(
        cust["id"],
        company_id=company_id,
        data={"name": "Extra", "email": "e@p.com"},
    )
    assert crud.purge(company_id) is True
    conn = get_connection()
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM contacts WHERE company_id = ?",
            (company_id,),
        ).fetchone()["n"]
        assert n == 0
    finally:
        conn.close()


def test_api_missing_table_degrades(api_client):
    """DROP contacts 后 GET 200 降级，写操作 503。"""
    from trade.database import get_connection

    client, token, cid = api_client
    cust = _make_customer(cid, contact="A", email="a@d.com")
    h = _h(token, cid)
    # 先建一个附加人，拿到 id，再丢表
    r = client.post(
        f"/api/trade/customers/{cust['id']}/contacts",
        headers=h,
        json={"name": "X", "email": "x@d.com"},
    )
    xid = r.json()["id"]
    conn = get_connection()
    try:
        conn.execute("DROP TABLE contacts")
        conn.commit()
    finally:
        conn.close()

    r = client.get(f"/api/trade/customers/{cust['id']}/contacts", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["contacts"] == []
    assert body["primary"] is not None
    assert body["primary"]["name"] == "A"

    r = client.get(f"/api/trade/customers/{cust['id']}/overview", headers=h)
    assert r.status_code == 200

    r = client.post(
        f"/api/trade/customers/{cust['id']}/contacts",
        headers=h,
        json={"name": "Y"},
    )
    assert r.status_code == 503
    assert "请重启 Trade 完成升级" in r.json()["detail"]

    r = client.put(
        f"/api/trade/customers/{cust['id']}/contacts/{xid}",
        headers=h,
        json={"name": "Y"},
    )
    assert r.status_code == 503

    r = client.delete(
        f"/api/trade/customers/{cust['id']}/contacts/{xid}",
        headers=h,
    )
    assert r.status_code == 503


def test_email_shaped_contact_primary(api_client):
    """contact 含 @：name 未命名；email 优先 e2，否则用 contact。"""
    from trade import customer

    client, token, cid = api_client
    h = _h(token, cid)

    c1 = customer.create(
        company_id=cid,
        name="Email Shape 1",
        contact="boss@y.com",
        email="other@y.com",
    )
    r = client.get(f"/api/trade/customers/{c1['id']}/overview", headers=h)
    ov = r.json()
    assert ov["people"][0]["name"] == "未命名联系人"
    assert ov["people"][0]["email"] == "other@y.com"
    assert ov["emails"][0] == "other@y.com"
    assert "boss@y.com" not in ov["emails"]

    c2 = customer.create(
        company_id=cid,
        name="Email Shape 2",
        contact="boss2@y.com",
    )
    r = client.get(f"/api/trade/customers/{c2['id']}/overview", headers=h)
    ov = r.json()
    assert ov["people"][0]["name"] == "未命名联系人"
    assert ov["people"][0]["email"] == "boss2@y.com"
    assert ov["emails"][0] == "boss2@y.com"


def test_contact_write_wrong_types_400(api_client):
    client, token, cid = api_client
    cust = _make_customer(cid, contact="A", email="a@t.com")
    h = _h(token, cid)
    url = f"/api/trade/customers/{cust['id']}/contacts"

    r = client.post(url, headers=h, json={"name": 123})
    assert r.status_code == 400
    assert isinstance(r.json()["detail"], str)

    r = client.post(url, headers=h, json={"name": "Ok", "email": []})
    assert r.status_code == 400
    assert isinstance(r.json()["detail"], str)

    r = client.post(url, headers=h, json={"name": "Ok", "is_primary": "x"})
    assert r.status_code == 400
    assert isinstance(r.json()["detail"], str)
