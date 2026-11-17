"""客户画像 facts / gifts 核心回归。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="module")
def setup_mocks():
    """屏蔽 Hermes。"""
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
    """独立 TRADE_HOME。"""
    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    from trade import database as db
    from trade import profile as profile_mod

    db.init_db()
    profile_mod.invalidate_table_cache()
    yield tmp_path


@pytest.fixture
def company_id(test_db):
    """测试公司。"""
    from trade import company

    return company.create(name="Profile Co", slug="profile-co")["id"]


@pytest.fixture
def customer_id(company_id):
    """带主联系人的客户。"""
    from trade import customer

    return customer.create(
        "Velmora Bau", company_id=company_id, contact="Hans Mueller",
    )["id"]


@pytest.fixture
def api_client(test_db, company_id, setup_mocks):
    """TestClient。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from trade.api import deps, router

    token = "profile-test-token"
    deps.set_session_token(token)
    deps._ACTIVE_COMPANY.pop(token, None)
    app = FastAPI()
    app.include_router(router, prefix="/api/trade")
    return TestClient(app), token, company_id


def _h(token: str, cid: int) -> dict[str, str]:
    return {"X-Hermes-Session-Token": token, "X-Company-ID": str(cid)}


class TestFactsCrud:
    def test_create_list_confirm_void(self, api_client, company_id, customer_id):
        """手工新建 → 列表 → 确认路径；脏分类返回 400 非 422。"""
        client, token, cid = api_client
        # 脏分类
        bad = client.post(
            f"/api/trade/customers/{customer_id}/facts",
            headers=_h(token, cid),
            json={"category": "乱七八糟", "content": "x"},
        )
        assert bad.status_code == 400
        assert isinstance(bad.json()["detail"], str)

        # 空内容
        empty = client.post(
            f"/api/trade/customers/{customer_id}/facts",
            headers=_h(token, cid),
            json={"category": "喜好", "content": "  "},
        )
        assert empty.status_code == 400

        r = client.post(
            f"/api/trade/customers/{customer_id}/facts",
            headers=_h(token, cid),
            json={
                "category": "喜好", "subject": "咖啡", "content": "喜欢手冲",
                "attach_to": "primary",
            },
        )
        assert r.status_code == 200, r.text
        fact = r.json()
        assert fact["status"] == "已确认"
        assert fact["ai_visible"] == 1  # 非敏感默认开
        assert fact["attach_to"] == "primary"

        listed = client.get(
            f"/api/trade/customers/{customer_id}/facts",
            headers=_h(token, cid),
        ).json()
        assert listed["available"] is True
        assert len(listed["items"]) == 1

        # 指纹去重
        dup = client.post(
            f"/api/trade/customers/{customer_id}/facts",
            headers=_h(token, cid),
            json={"category": "喜好", "subject": "咖啡", "content": "喜欢手冲"},
        )
        assert dup.status_code == 409

    def test_family_default_ai_off(self, api_client, company_id, customer_id):
        """敏感类家庭默认 ai_visible=0。"""
        client, token, cid = api_client
        r = client.post(
            f"/api/trade/customers/{customer_id}/facts",
            headers=_h(token, cid),
            json={"category": "家庭", "subject": "女儿", "content": "Emma"},
        )
        assert r.status_code == 200
        assert r.json()["ai_visible"] == 0

    def test_ai_fact_cannot_delete(self, company_id, customer_id, test_db):
        """AI 条目只能作废。"""
        from trade import profile as p
        from trade.database import get_connection

        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO customer_facts ("
                "company_id, customer_id, attach_to, category, subject, content, "
                "source_type, status, ai_visible, fingerprint) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (company_id, customer_id, "none", "喜好", "茶", "喜欢红茶",
                 "chat", "待确认", 0, "fp-ai-1"),
            )
            fid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(p.ProfileError):
            p.delete_fact(fid, customer_id=customer_id, company_id=company_id)
        p.void_fact(fid, customer_id=customer_id, company_id=company_id)
        items = p.list_facts(customer_id, company_id=company_id)
        assert all(i["id"] != fid for i in items)


class TestGifts:
    def test_request_never_ai(self, api_client, company_id, customer_id):
        """客户索要：ai_visible 恒 0，不进简报。"""
        client, token, cid = api_client
        r = client.post(
            f"/api/trade/customers/{customer_id}/gifts",
            headers=_h(token, cid),
            json={"direction": "客户索要", "item": "iPhone"},
        )
        assert r.status_code == 200
        gift = r.json()
        assert gift["ai_visible"] == 0

        # PUT 开开关也被忽略
        u = client.put(
            f"/api/trade/customers/{customer_id}/gifts/{gift['id']}",
            headers=_h(token, cid),
            json={"ai_visible": 1},
        )
        assert u.status_code == 200
        assert u.json()["ai_visible"] == 0

        from trade.customer import build_briefing
        brief = build_briefing(customer_id, company_id=company_id)
        assert "iPhone" not in brief
        assert "客户索要" not in brief

    def test_dirty_direction_400(self, api_client, company_id, customer_id):
        """脏 direction → 400。"""
        client, token, cid = api_client
        r = client.post(
            f"/api/trade/customers/{customer_id}/gifts",
            headers=_h(token, cid),
            json={"direction": "乱送", "item": "x"},
        )
        assert r.status_code == 400


class TestBriefing:
    def test_only_ai_visible_confirmed(self, company_id, customer_id, test_db):
        """只有已确认且 ai_visible=1 进简报。"""
        from trade import profile as p
        from trade.customer import build_briefing

        f1 = p.create_fact_manual(
            customer_id, company_id=company_id,
            category="喜好", subject="酒", content="喜欢干红",
        )
        assert f1["ai_visible"] == 1
        f2 = p.create_fact_manual(
            customer_id, company_id=company_id,
            category="家庭", subject="儿子", content="Tom",
        )
        assert f2["ai_visible"] == 0

        brief = build_briefing(customer_id, company_id=company_id)
        assert "干红" in brief
        assert "Tom" not in brief


class TestDegrade:
    def test_missing_table_get_available_false(self, api_client, company_id, customer_id):
        """删表后 GET 200 + available:false；写 503。"""
        from trade import profile as p
        from trade.database import get_connection

        conn = get_connection()
        try:
            conn.execute("DROP TABLE customer_facts")
            conn.commit()
        finally:
            conn.close()
        p.invalidate_table_cache()

        client, token, cid = api_client
        r = client.get(
            f"/api/trade/customers/{customer_id}/facts",
            headers=_h(token, cid),
        )
        assert r.status_code == 200
        assert r.json() == {"available": False, "items": []}

        w = client.post(
            f"/api/trade/customers/{customer_id}/facts",
            headers=_h(token, cid),
            json={"category": "喜好", "content": "x"},
        )
        assert w.status_code == 503


class TestCascade:
    def test_delete_customer_clears_facts(self, company_id, customer_id, test_db):
        """删客户级联清画像。"""
        from trade import customer
        from trade import profile as p
        from trade.database import get_connection

        p.create_fact_manual(
            customer_id, company_id=company_id,
            category="喜好", content="喜欢足球",
        )
        customer.delete(customer_id, company_id=company_id)
        conn = get_connection()
        try:
            n = conn.execute(
                "SELECT COUNT(*) AS c FROM customer_facts WHERE customer_id=?",
                (customer_id,),
            ).fetchone()["c"]
        finally:
            conn.close()
        assert n == 0


class TestExtractMock:
    def test_quote_must_be_substring(self, company_id, customer_id, test_db):
        """原句不是原文子串 → 丢弃。"""
        from trade import chat_memory
        from trade import profile as p

        chat_memory.save_with_context(
            company_id=company_id, library_id=None,
            query="客户说他喜欢滑雪", response="好的，已记下喜欢滑雪。",
            customer_id=customer_id,
        )

        async def fake_llm(*args, **kwargs):
            return (
                '{"facts":[{"category":"喜好","subject":"","content":"喜欢滑雪",'
                '"quote":"这段话根本不在原文里","source_id":1}],"gifts":[]}'
            )

        # 修正 source_id 为真实 id
        from trade.database import get_connection
        conn = get_connection()
        try:
            real_id = conn.execute(
                "SELECT id FROM conversations WHERE customer_id=?",
                (customer_id,),
            ).fetchone()["id"]
        finally:
            conn.close()

        async def fake_llm2(*args, **kwargs):
            return (
                '{"facts":['
                f'{{"category":"喜好","subject":"","content":"喜欢滑雪",'
                f'"quote":"喜欢滑雪","source_id":{real_id}}},'
                f'{{"category":"喜好","subject":"","content":"编造的",'
                f'"quote":"不存在的句子","source_id":{real_id}}}'
                '],"gifts":[]}'
            )

        with patch("trade.profile.resolve_extraction_model", create=True), \
             patch("trade.doc_extract.resolve_extraction_model",
                   return_value=("deepseek", "flash", "k")), \
             patch("trade.profile._call_extract_llm", side_effect=fake_llm2):
            result = p.extract_from_sources(
                customer_id, company_id=company_id, source="chat", limit=10,
            )
        assert result["added_facts"] == 1
        assert result["dropped_invalid"] >= 1
        items = p.list_facts(customer_id, company_id=company_id)
        assert any(i["content"] == "喜欢滑雪" and i["status"] == "待确认" for i in items)
