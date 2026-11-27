"""
供应商模块付费门禁验收测试（D1 / D3 / D4）。

逐条对应任务书 §4 验收用例：
  D1 后端门禁：三套 router（suppliers / rfqs / purchase）试用 402 + active 200 + 异常 fail-open
  D3 工具门禁：五个供应商 AI 工具试用拦截（零数据、零写入）+ active 正常 + 异常 fail-open
  D4 简报不受影响：试用状态下 get_today_brief 仍返回 delivery_alerts（内部调用不走门禁）
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trade import agent_context
from trade import brief as brief_mod
from trade import company as company_mod
from trade import database as db_mod
from trade import license as license_mod
from trade import purchase as purchase_mod
from trade import supplier as supplier_mod
from trade.api import deps as deps_mod
from trade.api import router as trade_router
from trade.hermes_chat_memory_plugin import tools as plugin_tools

EXPECTED_ERROR = "供应商管理为付费功能，激活后可用。"


@pytest.fixture
def gate_env(monkeypatch, tmp_path):
    """构造带一家公司与一条基础供应商/报价/采购单数据的隔离测试环境。"""
    trade_home = tmp_path / "trade_home"
    trade_home.mkdir(parents=True, exist_ok=True)
    db_path = trade_home / "data" / "trade.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("TRADE_HOME", str(trade_home))
    monkeypatch.setattr(db_mod, "_get_db_path", lambda: db_path)
    monkeypatch.setattr(company_mod.crud, "TRADE_HOME", trade_home)

    def _fake_work_dir(name, slug, suggested_name=""):
        wd = tmp_path / "work" / (slug or "co")
        wd.mkdir(parents=True, exist_ok=True)
        return wd, True

    monkeypatch.setattr(company_mod.workdir, "_setup_work_directory", _fake_work_dir)
    (tmp_path / "work").mkdir(parents=True, exist_ok=True)

    db_mod.init_db()

    app = FastAPI()
    app.include_router(trade_router, prefix="/api/trade")
    token = "test-gate-token"
    deps_mod.set_session_token(token)
    deps_mod._ACTIVE_COMPANY.clear()
    client = TestClient(app)

    co = company_mod.create(name="Gate Co", slug="gate-co")
    cid = int(co["id"])

    # 预置供应商、报价和一条逾期采购单，供读取接口 / AI 工具 / 简报验证
    sup = supplier_mod.create_supplier(cid, name="义乌宏达模具厂", main_products="硅胶模具")
    supplier_mod.create_quote(
        cid,
        int(sup["id"]),
        product_name="硅胶模具",
        price_excl_tax=12.5,
        currency="CNY",
        unit="个",
    )
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    purchase_mod.create_purchase_order(
        cid,
        supplier_id=int(sup["id"]),
        product_name="硅胶模具",
        promised_date=yesterday,
        status="生产中",
    )

    headers = {
        "X-Hermes-Session-Token": token,
        "X-Company-ID": str(cid),
    }

    return {
        "client": client,
        "cid": cid,
        "supplier_id": int(sup["id"]),
        "headers": headers,
    }


# ==============================================================================
# D1 后端门禁：三套 router（suppliers / rfqs / purchase）
# ==============================================================================


class TestD1BackendRouterGates:
    """验收 D1：三套供应商 router 的 GET 与 POST 均受统一门禁保护。"""

    def test_trial_blocks_all_three_routers_get_and_post(self, gate_env, monkeypatch):
        """试用状态（非 active）时，三套 router 代表性 GET 与 POST 全部返回 402 且文案统一。"""
        monkeypatch.setattr(license_mod, "license_state", lambda: ("trial", "试用中"))
        client = gate_env["client"]
        headers = gate_env["headers"]
        sup_id = gate_env["supplier_id"]

        cases = [
            # trade/api/suppliers.py
            ("GET", "/api/trade/suppliers", None),
            ("POST", "/api/trade/suppliers", {"name": "试用不应建成功"}),
            # trade/api/rfqs.py
            ("GET", "/api/trade/rfqs", None),
            ("POST", "/api/trade/rfqs", {"product_name": "硅胶模具"}),
            # trade/api/purchase.py
            ("GET", "/api/trade/purchase-orders", None),
            (
                "POST",
                "/api/trade/purchase-orders",
                {"supplier_id": sup_id, "product_name": "硅胶模具"},
            ),
        ]

        for method, path, payload in cases:
            if method == "GET":
                resp = client.get(path, headers=headers)
            else:
                resp = client.post(path, headers=headers, json=payload)
            assert resp.status_code == 402, f"{method} {path} 期望 402，实际 {resp.status_code}"
            assert resp.json().get("detail") == EXPECTED_ERROR

    def test_active_allows_all_three_routers(self, gate_env, monkeypatch):
        """active 状态下三套 router 的 GET 与 POST 正常返回 200。"""
        monkeypatch.setattr(license_mod, "license_state", lambda: ("active", ""))
        client = gate_env["client"]
        headers = gate_env["headers"]
        sup_id = gate_env["supplier_id"]

        assert client.get("/api/trade/suppliers", headers=headers).status_code == 200
        assert client.post(
            "/api/trade/suppliers", headers=headers, json={"name": "已激活新建厂"}
        ).status_code == 200

        assert client.get("/api/trade/rfqs", headers=headers).status_code == 200
        assert client.post(
            "/api/trade/rfqs", headers=headers, json={"product_name": "硅胶模具"}
        ).status_code == 200

        assert client.get("/api/trade/purchase-orders", headers=headers).status_code == 200
        assert client.post(
            "/api/trade/purchase-orders",
            headers=headers,
            json={"supplier_id": sup_id, "product_name": "硅胶模具"},
        ).status_code == 200

    def test_license_exception_fail_open(self, gate_env, monkeypatch):
        """license_state 抛异常时 fail-open 正常放行。"""
        def _boom():
            raise RuntimeError("disk io error")

        monkeypatch.setattr(license_mod, "license_state", _boom)
        client = gate_env["client"]
        headers = gate_env["headers"]

        assert client.get("/api/trade/suppliers", headers=headers).status_code == 200
        assert client.get("/api/trade/rfqs", headers=headers).status_code == 200
        assert client.get("/api/trade/purchase-orders", headers=headers).status_code == 200


# ==============================================================================
# D3 AI 工具门禁：五个供应商工具 handler
# ==============================================================================


class TestD3SupplierToolsGate:
    """验收 D3：五个供应商 AI 工具在试用态拦截且零写入，active 与异常 fail-open 正常。"""

    def test_trial_blocks_all_five_tools_with_zero_writes(self, gate_env, monkeypatch):
        """试用状态调用五个工具返回统一错误 JSON，无供应商数据、无数据库写入。"""
        monkeypatch.setattr(license_mod, "license_state", lambda: ("trial", "试用中"))
        cid = gate_env["cid"]
        before_count = len(supplier_mod.list_suppliers(cid))

        with agent_context.bind_company(company_id=cid):
            calls = [
                plugin_tools.handle_supplier_candidate_save({"name": "试用不可写入厂"}),
                plugin_tools.handle_supplier_quote_search({"product_name": "硅胶模具"}),
                plugin_tools.handle_supplier_compare({"product_name": "硅胶模具"}),
                plugin_tools.handle_supplier_list({}),
                plugin_tools.handle_supplier_delivery_alerts({}),
            ]

        for raw in calls:
            data = json.loads(raw)
            assert data == {"error": EXPECTED_ERROR}

        # candidate_save 在试用下数据库零变化
        after_count = len(supplier_mod.list_suppliers(cid))
        assert after_count == before_count

    def test_active_allows_all_five_tools(self, gate_env, monkeypatch):
        """active 状态下五个工具正常返回数据与写入。"""
        monkeypatch.setattr(license_mod, "license_state", lambda: ("active", ""))
        cid = gate_env["cid"]

        with agent_context.bind_company(company_id=cid):
            saved = json.loads(plugin_tools.handle_supplier_candidate_save({"name": "激活可写入厂"}))
            quotes = json.loads(plugin_tools.handle_supplier_quote_search({"product_name": "硅胶模具"}))
            compared = json.loads(plugin_tools.handle_supplier_compare({"product_name": "硅胶模具"}))
            listed = json.loads(plugin_tools.handle_supplier_list({}))
            alerts = json.loads(plugin_tools.handle_supplier_delivery_alerts({}))

        assert saved.get("created") is True
        assert quotes.get("count", 0) >= 1
        assert "error" not in compared
        assert listed.get("count", 0) >= 2
        assert alerts.get("count", 0) >= 1

    def test_license_exception_fail_open_for_tools(self, gate_env, monkeypatch):
        """license_state 抛异常时 AI 工具 fail-open 放行。"""
        def _boom():
            raise RuntimeError("license read failed")

        monkeypatch.setattr(license_mod, "license_state", _boom)
        cid = gate_env["cid"]

        with agent_context.bind_company(company_id=cid):
            listed = json.loads(plugin_tools.handle_supplier_list({}))
            alerts = json.loads(plugin_tools.handle_supplier_delivery_alerts({}))

        assert "error" not in listed
        assert listed.get("count", 0) >= 1
        assert "error" not in alerts
        assert alerts.get("count", 0) >= 1


# ==============================================================================
# D4 简报不受影响
# ==============================================================================


class TestD4BriefNotGated:
    """验收 D4：试用状态下 get_today_brief 仍返回 delivery_alerts。"""

    def test_today_brief_returns_delivery_alerts_in_trial(self, gate_env, monkeypatch):
        """内部函数调用不经过 HTTP 门禁，试用态下简报正常包含交期提醒。"""
        monkeypatch.setattr(license_mod, "license_state", lambda: ("trial", "试用中"))
        cid = gate_env["cid"]

        brief = brief_mod.get_today_brief(cid)
        assert brief["delivery_alert_count"] == 1
        assert len(brief["delivery_alerts"]) == 1
        assert brief["delivery_alerts"][0]["product_name"] == "硅胶模具"
