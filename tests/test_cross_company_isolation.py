"""跨公司访问客户接口必须 404（V3，只加回归、不改行为）。

审计日志里的 401 是「没带 X-Company-ID」；带另一家公司头访问应 404，
且响应里不得泄露客户名。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def setup_mocks():
    """Hermes 不在 CI 里，按老规矩 mock 掉。"""
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
def api_client(test_db, setup_mocks):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from trade import company
    from trade.api import deps, router

    cid = company.create(name="Iso Co", slug="iso-co")["id"]
    token = "cross-company-token"
    deps.set_session_token(token)
    deps._ACTIVE_COMPANY.pop(token, None)

    app = FastAPI()
    app.include_router(router, prefix="/api/trade")
    return TestClient(app), token, cid


def _h(token: str, cid: int) -> dict[str, str]:
    return {"X-Hermes-Session-Token": token, "X-Company-ID": str(cid)}


class TestCrossCompanyIsolation:
    def test_customer_subresources_are_404_for_other_company(self, api_client):
        from trade import company, customer

        client, token, cid = api_client
        name = "Secret Customer Name"
        cust = customer.create(name, company_id=cid)
        other = company.create(name="Other Iso Co", slug="other-iso-co")["id"]

        paths = [
            "",
            "/overview",
            "/timeline",
            "/emails",
            "/facts",
            "/gifts",
            "/inquiries",
            "/orders",
        ]
        for suffix in paths:
            r = client.get(
                f"/api/trade/customers/{cust['id']}{suffix}",
                headers=_h(token, other),
            )
            assert r.status_code == 404, f"{suffix or '/'} 跨公司应 404，实际 {r.status_code}"
            assert name not in r.text, f"{suffix} 响应泄露了客户名"

    def test_missing_company_header_is_401(self, api_client):
        """不带 X-Company-ID → 401（设计如此，不是 bug）。"""
        client, token, cid = api_client
        r = client.get(
            "/api/trade/customers/1/overview",
            headers={"X-Hermes-Session-Token": token},
        )
        assert r.status_code == 401
