"""询盘 REST API + PUT stage 新语义。"""

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
    yield


@pytest.fixture
def company_id(test_db):
    from trade import company

    return company.create(name="Inq API Co", slug="inq-api-co")["id"]


@pytest.fixture
def api_client(test_db, company_id, setup_mocks):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from trade.api import deps, router

    token = "inq-api-token"
    deps.set_session_token(token)
    deps._ACTIVE_COMPANY.pop(token, None)
    app = FastAPI()
    app.include_router(router, prefix="/api/trade")
    return TestClient(app), token, company_id


def _h(token: str, cid: int) -> dict:
    return {"X-Hermes-Session-Token": token, "X-Company-ID": str(cid)}


def test_inquiry_crud_and_stage_put(api_client, test_db):
    """四组询盘接口 + PUT stage override/自动。"""
    from trade import customer
    from trade.company import create as create_company

    client, token, cid = api_client
    cust = customer.create("API Cust", company_id=cid)
    cust_id = cust["id"]
    h = _h(token, cid)

    # 别的公司的客户 id + 本公司 header → 404（不得串数据）
    other_cid = create_company(name="Other", slug="inq-other")["id"]
    foreign = customer.create("Foreign", company_id=other_cid)
    r404 = client.get(
        f"/api/trade/customers/{foreign['id']}/inquiries",
        headers=h,
    )
    assert r404.status_code == 404

    r0 = client.get(f"/api/trade/customers/{cust_id}/inquiries", headers=h)
    assert r0.status_code == 200
    assert r0.json() == []

    created = client.post(
        f"/api/trade/customers/{cust_id}/inquiries",
        headers=h,
        json={"title": "首询", "stage": "报价"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["title"] == "首询"
    assert body["stage"] == "报价"
    assert body["customer_stage"] == "报价"
    inq_id = body["id"]

    listed = client.get(f"/api/trade/customers/{cust_id}/inquiries", headers=h)
    assert len(listed.json()) == 1

    upd = client.put(
        f"/api/trade/inquiries/{inq_id}",
        headers=h,
        json={"stage": "样品"},
    )
    assert upd.status_code == 200
    assert upd.json()["stage"] == "样品"
    assert upd.json()["customer_stage"] == "样品"

    # 存取层跨公司隔离（session 绑定后换 header 会 403，不在此测 HTTP）
    from trade import inquiry as inquiry_mod

    foreign_row = inquiry_mod.create(
        foreign["id"], company_id=other_cid, title="外司"
    )
    assert inquiry_mod.update(
        foreign_row["id"], company_id=cid, title="hack"
    ) is None

    # PUT stage 锁定 override
    locked = client.put(
        f"/api/trade/customers/{cust_id}",
        headers=h,
        json={"stage": "询盘"},
    )
    assert locked.status_code == 200
    assert locked.json()["stage"] == "询盘"
    assert locked.json()["stage_auto"] is False

    # 询盘已是样品，但 override 锁在询盘
    client.put(
        f"/api/trade/inquiries/{inq_id}",
        headers=h,
        json={"stage": "订单"},
    )
    still = customer.get(cust_id, company_id=cid)
    assert still["stage"] == "询盘"

    # 「自动」清 override → 订单
    auto = client.put(
        f"/api/trade/customers/{cust_id}",
        headers=h,
        json={"stage": "自动"},
    )
    assert auto.status_code == 200
    assert auto.json()["stage"] == "订单"
    assert auto.json()["stage_auto"] is True

    # 删除幂等
    assert client.delete(
        f"/api/trade/inquiries/{inq_id}", headers=h
    ).json() == {"ok": True}
    assert client.delete(
        f"/api/trade/inquiries/{inq_id}", headers=h
    ).json() == {"ok": True}
    assert customer.get(cust_id, company_id=cid)["stage"] == "询盘"


def test_put_stage_auto_literal_accepted(api_client, test_db):
    """CustomerUpdate.stage 必须接受「自动」，否则 422。"""
    from trade import customer

    client, token, cid = api_client
    cust = customer.create("Lit", company_id=cid)
    r = client.put(
        f"/api/trade/customers/{cust['id']}",
        headers=_h(token, cid),
        json={"stage": "自动"},
    )
    assert r.status_code == 200, r.text
