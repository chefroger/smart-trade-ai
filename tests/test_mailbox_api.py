"""邮箱绑定 REST API：TestClient + mock IMAP。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="module")
def setup_mocks():
    """模块级 mock Hermes 依赖。"""
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
def api_client(test_db, company_id, setup_mocks):
    """挂载 trade API 的 TestClient。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from trade.api import deps, router

    token = "mailbox-api-token"
    deps.set_session_token(token)
    deps._ACTIVE_COMPANY.pop(token, None)

    app = FastAPI()
    app.include_router(router, prefix="/api/trade")
    client = TestClient(app)
    return client, token, company_id


@pytest.fixture
def test_db(monkeypatch, tmp_path, setup_mocks):
    """临时 trade.db。"""
    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    from trade import database as db

    db.init_db()
    yield


@pytest.fixture
def company_id(test_db):
    from trade import company

    c = company.create(name="Mailbox API Co", slug="mailbox-api-co")
    return c["id"]


def _headers(token: str, company_id: int | None = None) -> dict[str, str]:
    h = {"X-Hermes-Session-Token": token}
    if company_id is not None:
        h["X-Company-ID"] = str(company_id)
    return h


@patch("trade.api.mailboxes.test_connection")
def test_mailbox_test_ok(mock_tc, api_client):
    """POST /mailboxes/test 测通返回 ok。"""
    client, token, _cid = api_client
    mock_tc.return_value = None
    resp = client.post(
        "/api/trade/mailboxes/test",
        headers=_headers(token),
        json={
            "preset": "126",
            "email_address": "seller@126.com",
            "secret": "sixteen-char-code",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    mock_tc.assert_called_once()
    host, port, user, secret = mock_tc.call_args[0]
    assert host == "imap.126.com"
    assert port == 993
    assert user == "seller@126.com"
    assert secret == "sixteen-char-code"


@patch("trade.mailbox_store.test_connection")
@patch("trade.api.mailboxes.test_connection")
def test_mailbox_create_duplicate_409(mock_api_tc, mock_store_tc, api_client):
    """重复 email_address → 409 约定文案。"""
    client, token, _cid = api_client
    mock_api_tc.return_value = None
    mock_store_tc.return_value = None
    body = {
        "preset": "qq",
        "email_address": "dup@qq.com",
        "secret": "sixteen-char-code",
        "display_name": "主邮箱",
    }
    r1 = client.post("/api/trade/mailboxes", headers=_headers(token), json=body)
    assert r1.status_code == 201
    r2 = client.post("/api/trade/mailboxes", headers=_headers(token), json=body)
    assert r2.status_code == 409
    assert r2.json()["detail"] == "该邮箱已经绑定过了，先解绑再绑"


@patch("trade.mailbox_store.test_connection")
@patch("trade.api.mailboxes.test_connection")
def test_mailbox_list_no_secret_field(mock_api_tc, mock_store_tc, api_client):
    """列表仅 has_secret，无 secret 字段。"""
    client, token, _cid = api_client
    mock_api_tc.return_value = None
    mock_store_tc.return_value = None
    client.post(
        "/api/trade/mailboxes",
        headers=_headers(token),
        json={
            "preset": "163",
            "email_address": "list@163.com",
            "secret": "sixteen-char-code",
        },
    )
    resp = client.get("/api/trade/mailboxes", headers=_headers(token))
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert "secret" not in rows[0]
    assert rows[0].get("has_secret") is True
    assert rows[0]["email_address"] == "list@163.com"


@patch("trade.mailbox_store.test_connection")
@patch("trade.api.mailboxes.test_connection")
def test_customer_emails_company_scoped(mock_api_tc, mock_store_tc, api_client):
    """客户邮件须属当前公司，否则 404。"""
    client, token, cid = api_client
    mock_api_tc.return_value = None
    mock_store_tc.return_value = None
    from trade import company, customer, mailbox_store

    other = company.create(name="Other Co", slug="other-mailbox-co")
    c1 = customer.create("客户甲", company_id=cid, email="scoped-a@example.com")
    _c2 = customer.create("客户乙", company_id=other["id"], email="scoped-b@example.com")

    client.post(
        "/api/trade/mailboxes",
        headers=_headers(token),
        json={
            "preset": "126",
            "email_address": "scope@126.com",
            "secret": "sixteen-char-code",
        },
    )
    mid = client.get("/api/trade/mailboxes", headers=_headers(token)).json()[0]["id"]
    conn = __import__("trade.database", fromlist=["get_connection"]).get_connection()
    eid = mailbox_store.insert_email_ignore(
        conn,
        mid,
        {
            "message_id": "<scope-test-1>",
            "from_addr": "scoped-a@example.com",
            "to_addrs": [],
            "subject": "hi",
            "snippet": "hi",
            "body_text": "hi",
            "received_at": "2026-01-01T12:00:00+08:00",
        },
    )
    conn.execute(
        "INSERT OR IGNORE INTO email_matches (email_id, company_id, customer_id) VALUES (?,?,?)",
        (eid, cid, c1["id"]),
    )
    conn.commit()

    ok = client.get(
        f"/api/trade/customers/{c1['id']}/emails",
        headers=_headers(token, cid),
    )
    assert ok.status_code == 200
    assert len(ok.json()) == 1

    # 用公司 A 的 header 查公司 B 的客户 → 404
    bad = client.get(
        f"/api/trade/customers/{_c2['id']}/emails",
        headers=_headers(token, cid),
    )
    assert bad.status_code == 404


@patch("trade.mailbox_store.pull_one")
@patch("trade.mailbox_store.list_mailboxes")
def test_pull_all_shape(mock_list, mock_pull, api_client):
    """pull-all 返回 results 列表且含 mailbox_id。"""
    client, token, _cid = api_client
    mock_list.return_value = [{"id": 7}, {"id": 8}]
    mock_pull.side_effect = [
        {"pulled": 2, "matched": 1},
        {"pulled": 0, "matched": 0, "error": "未配置邮箱凭证"},
    ]
    resp = client.post("/api/trade/mailboxes/pull-all", headers=_headers(token))
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert len(data["results"]) == 2
    assert data["results"][0]["mailbox_id"] == 7
    assert data["results"][0]["pulled"] == 2
    assert data["results"][1]["mailbox_id"] == 8
