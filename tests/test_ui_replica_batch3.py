"""批次三 W9–W10：今日简报聚合 + trade-json 结构化块。"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="module")
def setup_mocks():
    """屏蔽 Hermes 顶层模块。"""
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
    """每个用例独立 TRADE_HOME。"""
    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    from trade import database as db

    db.init_db()
    yield tmp_path


@pytest.fixture
def company_id(test_db):
    """建测试公司。"""
    from trade import company

    return company.create(name="Brief Co", slug="brief-co")["id"]


@pytest.fixture
def api_client(test_db, company_id, setup_mocks):
    """FastAPI TestClient + session。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from trade.api import deps, router

    token = "ui-replica-batch3-token"
    deps.set_session_token(token)
    deps._ACTIVE_COMPANY.pop(token, None)

    app = FastAPI()
    app.include_router(router, prefix="/api/trade")
    return TestClient(app), token, company_id


def _h(token: str, cid: int) -> dict[str, str]:
    """组装会话头。"""
    return {"X-Hermes-Session-Token": token, "X-Company-ID": str(cid)}


# ── W9 brief ───────────────────────────────────────────────────────────────


class TestBriefToday:
    def test_overdue_and_pending_shipments(self, api_client, company_id):
        """有逾期客户与「已下单」订单时 KPI 正确；无今日询盘时 new_inquiries 为 0。"""
        from trade import customer, order

        yesterday = (date.today() - timedelta(days=1)).isoformat()
        late = customer.create(
            "Late Co", company_id=company_id, next_follow_up_date=yesterday,
        )
        customer.create(
            "Future Co", company_id=company_id,
            next_follow_up_date=(date.today() + timedelta(days=3)).isoformat(),
        )
        order.create(
            company_id, late["id"], product_name="Pipe",
            status="已下单", total_amount=100, currency="USD",
        )
        order.create(
            company_id, late["id"], product_name="Quote",
            status="报价中", total_amount=50, currency="USD",
        )

        client, token, cid = api_client
        r = client.get("/api/trade/brief/today", headers=_h(token, cid))
        assert r.status_code == 200
        body = r.json()
        assert body["new_inquiries"] == 0
        assert body["overdue_followups"] == 1
        assert body["pending_shipments"] == 1
        assert body["summary"] is None
        assert body["date"] == date.today().isoformat()

    def test_summary_null_without_cron(self, api_client, company_id):
        """无 cron 产出时 summary 为 null。"""
        client, token, cid = api_client
        r = client.get("/api/trade/brief/today", headers=_h(token, cid))
        assert r.status_code == 200
        assert r.json()["summary"] is None

    def test_today_inquiries_counted(self, api_client, company_id):
        """今日新询盘按 created_at 计数，不限阶段；昨天的不算。"""
        from trade import customer, inquiry

        cust = customer.create("Inquiry Co", company_id=company_id)
        inquiry.create(cust["id"], company_id=company_id, title="今日 A")
        inquiry.create(cust["id"], company_id=company_id, title="今日 B", stage="报价")
        old = inquiry.create(cust["id"], company_id=company_id, title="昨天的")

        # 把一条改成昨天，验证按日期过滤
        from trade.database import get_connection
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE inquiries SET created_at=? WHERE id=?",
                ((date.today() - timedelta(days=1)).isoformat() + " 09:00:00", old["id"]),
            )
            conn.commit()
        finally:
            conn.close()

        client, token, cid = api_client
        body = client.get("/api/trade/brief/today", headers=_h(token, cid)).json()
        assert body["new_inquiries"] == 2

    def test_other_company_inquiries_not_counted(self, api_client, company_id):
        """别家公司今天的询盘不计入本公司的今日简报。"""
        from trade import company, customer, inquiry

        other = company.create(name="Other Brief Co", slug="other-brief-co")["id"]
        oc = customer.create("Other Co", company_id=other)
        inquiry.create(oc["id"], company_id=other, title="别家今日询盘")

        client, token, cid = api_client
        body = client.get("/api/trade/brief/today", headers=_h(token, cid)).json()
        assert body["new_inquiries"] == 0

    def test_missing_inquiries_table_returns_none(self, api_client, company_id):
        """极旧库没有 inquiries 表时返回 null（前端显示「—」），接口仍 200。"""
        from trade.database import get_connection

        conn = get_connection()
        try:
            conn.execute("DROP TABLE inquiries")
            conn.commit()
        finally:
            conn.close()

        client, token, cid = api_client
        r = client.get("/api/trade/brief/today", headers=_h(token, cid))
        assert r.status_code == 200
        assert r.json()["new_inquiries"] is None


# ── W10 trade-json ─────────────────────────────────────────────────────────


class TestTradeJsonBlocks:
    def test_parses_fence_and_strips(self):
        """正文带围栏 → 解析出 blocks，且围栏从 text 移除。"""
        from trade.chat_blocks import parse_trade_json_blocks

        text = (
            "报价如下，请确认。\n\n"
            "```trade-json\n"
            '{"facts":[{"label":"数量","value":"2000"},'
            '{"label":"单价","value":"3.5"}],'
            '"draft":{"lang":"en","subject":"Quote","body":"Hi"},'
            '"next_actions":[{"label":"生成 PI","action":"gen_pi"},'
            '{"label":"加入待办","action":"add_todo"}]}\n'
            "```"
        )
        clean, blocks = parse_trade_json_blocks(text)
        assert "trade-json" not in clean
        assert "报价如下" in clean
        assert blocks is not None
        assert len(blocks["facts"]) == 2
        assert blocks["draft"]["subject"] == "Quote"
        # add_todo 被过滤，只剩 gen_pi
        assert blocks["next_actions"] == [{"label": "生成 PI", "action": "gen_pi"}]

    def test_invalid_fence_keeps_text(self):
        """围栏非法 → 无 blocks 且不抛错，原文保留。"""
        from trade.chat_blocks import parse_trade_json_blocks

        text = "Hello\n```trade-json\n{not json}\n```"
        clean, blocks = parse_trade_json_blocks(text)
        assert blocks is None
        assert clean == text

    def test_no_fence(self):
        """无围栏 → 无 blocks。"""
        from trade.chat_blocks import parse_trade_json_blocks

        clean, blocks = parse_trade_json_blocks("普通回复，没有结构化块。")
        assert clean == "普通回复，没有结构化块。"
        assert blocks is None

    def test_prompt_hint_in_all_reply_tiers(self):
        """FULL / FULL_DOCGEN / FIRST_TURN / MINIMAL 都含 trade-json 约定。"""
        from trade.prompt import (
            TRADE_SYSTEM_PROMPT_FIRST_TURN,
            TRADE_SYSTEM_PROMPT_FULL,
            TRADE_SYSTEM_PROMPT_FULL_DOCGEN,
            TRADE_SYSTEM_PROMPT_MINIMAL,
        )

        for text in (
            TRADE_SYSTEM_PROMPT_FULL,
            TRADE_SYSTEM_PROMPT_FULL_DOCGEN,
            TRADE_SYSTEM_PROMPT_FIRST_TURN,
            TRADE_SYSTEM_PROMPT_MINIMAL,
        ):
            assert "trade-json" in text
