"""客户标签校验：路由层 400 + Unicode 码点。"""

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
def api_client(test_db, setup_mocks):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from trade import company
    from trade.api import deps, router

    cid = company.create(name="Tags Co", slug="tags-co")["id"]
    token = "tags-api-token"
    deps.set_session_token(token)
    deps._ACTIVE_COMPANY.pop(token, None)

    app = FastAPI()
    app.include_router(router, prefix="/api/trade")
    return TestClient(app), token, cid


def _h(token, cid):
    return {"X-Hermes-Session-Token": token, "X-Company-ID": str(cid)}


def test_tags_validation_and_persist(api_client):
    from trade import customer

    client, token, cid = api_client
    cust = customer.create(company_id=cid, name="Tagged")
    h = _h(token, cid)
    url = f"/api/trade/customers/{cust['id']}"

    # 非数组 → 400 字符串
    r = client.put(url, headers=h, json={"tags": "vip"})
    assert r.status_code == 400
    assert isinstance(r.json()["detail"], str)

    # 非字符串项
    r = client.put(url, headers=h, json={"tags": [1, "ok"]})
    assert r.status_code == 400

    # 单项超长（21 个码点）
    r = client.put(url, headers=h, json={"tags": ["啊" * 21]})
    assert r.status_code == 400

    # 超量
    r = client.put(url, headers=h, json={"tags": [f"t{i}" for i in range(21)]})
    assert r.status_code == 400

    # emoji 计码点：一个 emoji = 1（Python len）
    emoji = "😀"
    assert len(emoji) == 1
    r = client.put(
        url,
        headers=h,
        json={"tags": [emoji * 20, "  VIP  ", "vip", "", "Buyer"]},
    )
    assert r.status_code == 200
    import json

    e3 = json.loads(r.json()["extra3"] or "{}")
    # 大小写不敏感去重：VIP 保留首次，vip 丢弃；空串丢弃
    assert e3["tags"] == [emoji * 20, "VIP", "Buyer"]

    # 重读一致
    r2 = client.get(url, headers=h)
    e3b = json.loads(r2.json()["extra3"] or "{}")
    assert e3b["tags"] == e3["tags"]
