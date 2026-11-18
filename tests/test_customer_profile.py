"""客户画像 facts / gifts 核心回归。"""

from __future__ import annotations

import sys
import threading
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


def test_list_facts_and_gifts_include_source_at(test_db, company_id, customer_id):
    """facts/gifts 的 source_at 由 source_ref 推导；不落库，来源表缺失不炸。"""
    from trade import profile as p
    from trade.database import get_connection

    conn = get_connection()
    try:
        conv_id = conn.execute(
            "INSERT INTO conversations (company_id, customer_id, query, response, created_at) "
            "VALUES (?,?,?,?,?)",
            (company_id, customer_id, "报价", "回复", "2026-11-17 09:00:00"),
        ).lastrowid
        mailbox_id = conn.execute(
            "INSERT INTO mailboxes (preset, email_address, host, username) VALUES (?,?,?,?)",
            ("imap", "buyer@example.com", "imap.example.com", "buyer@example.com"),
        ).lastrowid
        email_id = conn.execute(
            "INSERT INTO emails (mailbox_id, message_id, from_addr, subject, received_at, "
            "company_id, customer_id) VALUES (?,?,?,?,?,?,?)",
            (mailbox_id, "m1", "buyer@example.com", "hi",
             "2026-11-18T10:00:00+08:00", company_id, customer_id),
        ).lastrowid
        conn.commit()
    finally:
        conn.close()

    assert p._insert_pending_fact(
        company_id=company_id, customer_id=customer_id, category="喜好",
        subject="", content="喜欢蓝色包装", source_type="chat",
        source_ref=conv_id, source_quote="喜欢蓝色包装",
    )
    assert p._insert_pending_fact(
        company_id=company_id, customer_id=customer_id, category="禁忌",
        subject="", content="不饮酒", source_type="email",
        source_ref=email_id, source_quote="不饮酒",
    )
    # visit 表在干净库里不存在：不得抛错，只是没有日期
    assert p._insert_pending_fact(
        company_id=company_id, customer_id=customer_id, category="喜好",
        subject="", content="来自验厂", source_type="visit",
        source_ref=999, source_quote="",
    )
    facts = {f["content"]: f for f in p.list_facts(customer_id, company_id=company_id)}
    assert facts["喜欢蓝色包装"]["source_at"] == "2026-11-17 09:00:00"
    assert facts["不饮酒"]["source_at"] == "2026-11-18T10:00:00+08:00"
    assert facts["来自验厂"]["source_at"] is None

    assert p._insert_pending_gift(
        company_id=company_id, customer_id=customer_id, direction="我方赠送",
        item="宜兴茶具", approx_value=None, currency="", gift_date="",
        occasion="", source_type="chat", source_ref=conv_id, source_quote="茶具",
    )
    gifts = {g["item"]: g for g in p.list_gifts(customer_id, company_id=company_id)}
    assert gifts["宜兴茶具"]["source_at"] == "2026-11-17 09:00:00"


def _mk_contact(customer_id: int, company_id: int, name: str = "Lena", email: str = "") -> dict:
    from trade import contacts

    return contacts.create(
        customer_id, company_id=company_id, data={"name": name, "email": email},
    )


class TestAttachMatrix:
    """attach_to 三种挂法、脏值、跨客户/跨公司、删联系人归一（P1-7）。"""

    def test_three_modes_roundtrip(self, api_client, company_id, customer_id):
        client, token, cid = api_client
        contact = _mk_contact(customer_id, company_id)
        cases = [
            ({}, "none", None),
            ({"attach_to": "primary"}, "primary", None),
            ({"attach_to": "contact", "contact_id": contact["id"]}, "contact", contact["id"]),
        ]
        for i, (extra, want_at, want_cid) in enumerate(cases):
            body = {"category": "喜好", "content": f"内容{i}"}
            body.update(extra)
            r = client.post(
                f"/api/trade/customers/{customer_id}/facts",
                headers=_h(token, cid), json=body,
            )
            assert r.status_code == 200, r.text
            assert r.json()["attach_to"] == want_at
            assert r.json()["contact_id"] == want_cid
        items = client.get(
            f"/api/trade/customers/{customer_id}/facts", headers=_h(token, cid),
        ).json()["items"]
        assert len(items) == 3

    def test_gift_attach_contact_roundtrip(self, api_client, company_id, customer_id):
        client, token, cid = api_client
        contact = _mk_contact(customer_id, company_id)
        r = client.post(
            f"/api/trade/customers/{customer_id}/gifts",
            headers=_h(token, cid),
            json={"direction": "我方赠送", "item": "茶具",
                  "attach_to": "contact", "contact_id": contact["id"]},
        )
        assert r.status_code == 200
        assert r.json()["attach_to"] == "contact"
        assert r.json()["contact_id"] == contact["id"]

    def test_dirty_attach_400(self, api_client, company_id, customer_id):
        client, token, cid = api_client
        r = client.post(
            f"/api/trade/customers/{customer_id}/facts",
            headers=_h(token, cid),
            json={"category": "喜好", "content": "x", "attach_to": "乱挂"},
        )
        assert r.status_code == 400
        assert isinstance(r.json()["detail"], str)

    def test_contact_without_id_400(self, api_client, company_id, customer_id):
        client, token, cid = api_client
        r = client.post(
            f"/api/trade/customers/{customer_id}/facts",
            headers=_h(token, cid),
            json={"category": "喜好", "content": "x", "attach_to": "contact"},
        )
        assert r.status_code == 400

    def test_contact_unknown_400(self, api_client, company_id, customer_id):
        client, token, cid = api_client
        r = client.post(
            f"/api/trade/customers/{customer_id}/facts",
            headers=_h(token, cid),
            json={"category": "喜好", "content": "x",
                  "attach_to": "contact", "contact_id": 999999},
        )
        assert r.status_code == 400

    def test_contact_other_customer_400(self, api_client, company_id, customer_id):
        from trade import customer

        client, token, cid = api_client
        other = customer.create("Other Cust", company_id=company_id)
        foreign = _mk_contact(other["id"], company_id)
        r = client.post(
            f"/api/trade/customers/{customer_id}/facts",
            headers=_h(token, cid),
            json={"category": "喜好", "content": "x",
                  "attach_to": "contact", "contact_id": foreign["id"]},
        )
        assert r.status_code == 400

    def test_contact_other_company_400(self, api_client, company_id, customer_id):
        from trade import company, customer

        client, token, cid = api_client
        other_co = company.create(name="Other Co", slug="other-co-attach")
        other_cust = customer.create("Foreign Cust", company_id=other_co["id"])
        foreign = _mk_contact(other_cust["id"], other_co["id"])
        r = client.post(
            f"/api/trade/customers/{customer_id}/facts",
            headers=_h(token, cid),
            json={"category": "喜好", "content": "x",
                  "attach_to": "contact", "contact_id": foreign["id"]},
        )
        assert r.status_code == 400

    def test_primary_requires_primary(self, api_client, company_id):
        from trade import customer

        client, token, cid = api_client
        bare = customer.create("No Primary", company_id=company_id)
        r = client.post(
            f"/api/trade/customers/{bare['id']}/facts",
            headers=_h(token, cid),
            json={"category": "喜好", "content": "x", "attach_to": "primary"},
        )
        assert r.status_code == 400

    def test_deleted_contact_reads_as_none(self, api_client, company_id, customer_id):
        from trade import contacts

        client, token, cid = api_client
        contact = _mk_contact(customer_id, company_id)
        r = client.post(
            f"/api/trade/customers/{customer_id}/facts",
            headers=_h(token, cid),
            json={"category": "喜好", "content": "挂人后删联系人",
                  "attach_to": "contact", "contact_id": contact["id"]},
        )
        assert r.status_code == 200
        assert contacts.delete(customer_id, contact["id"], company_id=company_id)
        items = client.get(
            f"/api/trade/customers/{customer_id}/facts", headers=_h(token, cid),
        ).json()["items"]
        row = [i for i in items if i["content"] == "挂人后删联系人"][0]
        assert row["attach_to"] == "none"
        assert row["contact_id"] is None

    def test_primary_name_updates(self, company_id, customer_id, test_db):
        from trade import customer

        customer.update(customer_id, company_id=company_id, contact="Hans New")
        ov = customer.get_overview(customer_id, company_id=company_id)
        assert ov["people"][0]["name"] == "Hans New"


class TestApiValidation:
    """400 不是 422、PUT 指纹 409、作废复活、并发、跨公司 404（P1-7）。"""

    def test_type_errors_are_400_not_422(self, api_client, company_id, customer_id):
        client, token, cid = api_client
        h = _h(token, cid)
        cases = [
            ("post", f"/api/trade/customers/{customer_id}/facts",
             {"category": "喜好", "content": 123}),
            ("post", f"/api/trade/customers/{customer_id}/facts",
             {"category": "喜好", "content": "x", "attach_to": 123}),
            ("post", f"/api/trade/customers/{customer_id}/gifts",
             {"direction": "我方赠送", "item": ["x"]}),
            ("post", f"/api/trade/customers/{customer_id}/gifts",
             {"direction": "我方赠送", "item": "x", "approx_value": "abc"}),
        ]
        for method, path, body in cases:
            r = getattr(client, method)(path, headers=h, json=body)
            assert r.status_code == 400, (path, body, r.text)
            assert isinstance(r.json()["detail"], str)

    def test_ai_visible_strict_400(self, api_client, company_id, customer_id):
        client, token, cid = api_client
        h = _h(token, cid)
        r = client.post(
            f"/api/trade/customers/{customer_id}/facts", headers=h,
            json={"category": "喜好", "content": "x"},
        )
        fid = r.json()["id"]
        bad = client.put(
            f"/api/trade/customers/{customer_id}/facts/{fid}",
            headers=h, json={"ai_visible": "yes"},
        )
        assert bad.status_code == 400

    def test_put_fingerprint_conflict_409(self, api_client, company_id, customer_id):
        client, token, cid = api_client
        h = _h(token, cid)
        client.post(
            f"/api/trade/customers/{customer_id}/facts", headers=h,
            json={"category": "喜好", "subject": "咖啡", "content": "喜欢手冲"},
        )
        f2 = client.post(
            f"/api/trade/customers/{customer_id}/facts", headers=h,
            json={"category": "喜好", "subject": "茶", "content": "喜欢红茶"},
        ).json()
        r = client.put(
            f"/api/trade/customers/{customer_id}/facts/{f2['id']}", headers=h,
            json={"category": "喜好", "subject": "咖啡", "content": "喜欢手冲"},
        )
        assert r.status_code == 409
        assert r.json()["detail"]

    def test_voided_manual_fact_resurrects(self, company_id, customer_id, test_db):
        from trade import profile as p

        first = p.create_fact_manual(
            customer_id, company_id=company_id, category="喜好", content="喜欢足球",
        )
        p.void_fact(first["id"], customer_id=customer_id, company_id=company_id)
        again = p.create_fact_manual(
            customer_id, company_id=company_id, category="喜好", content="喜欢足球",
        )
        assert again["id"] == first["id"]
        assert again["status"] == "已确认"

    def test_concurrent_same_fingerprint_one_row(self, company_id, customer_id, test_db):
        from trade import profile as p
        from trade.database import get_connection

        barrier = threading.Barrier(2)
        results: list[str] = []

        def worker() -> None:
            barrier.wait()
            try:
                p.create_fact_manual(
                    customer_id, company_id=company_id,
                    category="喜好", content="并发写入",
                )
                results.append("ok")
            except p.ProfileConflictError:
                results.append("conflict")

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(results) == ["conflict", "ok"]
        conn = get_connection()
        try:
            n = conn.execute(
                "SELECT COUNT(*) AS c FROM customer_facts "
                "WHERE customer_id=? AND company_id=?",
                (customer_id, company_id),
            ).fetchone()["c"]
        finally:
            conn.close()
        assert n == 1

    def test_cross_company_404(self, api_client, company_id, customer_id):
        from trade import company, customer
        from trade.api import deps

        client, token, cid = api_client
        h = _h(token, cid)
        fid = client.post(
            f"/api/trade/customers/{customer_id}/facts", headers=h,
            json={"category": "喜好", "content": "x"},
        ).json()["id"]
        other = company.create(name="Other 404", slug="other-404-profile")
        customer.create("Other 404 Cust", company_id=other["id"])
        deps._ACTIVE_COMPANY.pop(token, None)
        h2 = _h(token, other["id"])
        assert client.get(
            f"/api/trade/customers/{customer_id}/facts", headers=h2,
        ).status_code == 404
        assert client.put(
            f"/api/trade/customers/{customer_id}/facts/{fid}",
            headers=h2, json={"content": "y"},
        ).status_code == 404


class TestPurge:
    def test_purge_company_cascades_profile(self, company_id, customer_id, test_db):
        from trade import profile as p
        from trade.company import crud
        from trade.database import get_connection

        p.create_fact_manual(
            customer_id, company_id=company_id, category="喜好", content="喜欢足球",
        )
        p.create_gift_manual(
            customer_id, company_id=company_id, direction="我方赠送", item="茶具",
        )
        assert crud.purge(company_id) is True
        conn = get_connection()
        try:
            f = conn.execute(
                "SELECT COUNT(*) AS c FROM customer_facts WHERE company_id=?",
                (company_id,),
            ).fetchone()["c"]
            g = conn.execute(
                "SELECT COUNT(*) AS c FROM customer_gifts WHERE company_id=?",
                (company_id,),
            ).fetchone()["c"]
        finally:
            conn.close()
        assert (f, g) == (0, 0)


class TestExtractEdges:
    """提取：source_id 不在集合、脏分类、只取 query 不取 response、502、409（P1-7）。"""

    def _seed_chat(self, company_id: int, customer_id: int) -> int:
        from trade import chat_memory
        from trade.database import get_connection

        chat_memory.save_with_context(
            company_id=company_id, library_id=None,
            query="客户说他喜欢滑雪也喜欢蓝色包装",
            response="回复：他明确说不喝酒。",
            customer_id=customer_id,
        )
        conn = get_connection()
        try:
            return int(conn.execute(
                "SELECT id FROM conversations WHERE customer_id=? "
                "ORDER BY id DESC LIMIT 1",
                (customer_id,),
            ).fetchone()["id"])
        finally:
            conn.close()

    def test_invalid_source_and_dirty_category_dropped(
        self, company_id, customer_id, test_db
    ):
        from trade import profile as p

        conv_id = self._seed_chat(company_id, customer_id)

        async def fake_llm(*args, **kwargs):
            return (
                '{"facts":['
                '{"category":"乱七八糟","content":"x","quote":"喜欢滑雪",'
                f'"source_id":{conv_id}}},'
                '{"category":"喜好","content":"y","quote":"喜欢滑雪",'
                '"source_id":9999}'
                '],"gifts":[]}'
            )

        with patch("trade.doc_extract.resolve_extraction_model",
                   return_value=("deepseek", "flash", "k")), \
             patch("trade.profile._call_extract_llm", side_effect=fake_llm):
            result = p.extract_from_sources(
                customer_id, company_id=company_id, source="chat", limit=10,
            )
        assert result["added_facts"] == 0
        assert result["dropped_invalid"] >= 2

    def test_response_text_not_used(self, company_id, customer_id, test_db):
        """取材只取 query：原句只在 response 里 → 丢弃。"""
        from trade import profile as p

        conv_id = self._seed_chat(company_id, customer_id)

        async def fake_llm(*args, **kwargs):
            return (
                '{"facts":[{"category":"禁忌","content":"不喝酒",'
                f'"quote":"他明确说不喝酒","source_id":{conv_id}}}],'
                '"gifts":[]}'
            )

        with patch("trade.doc_extract.resolve_extraction_model",
                   return_value=("deepseek", "flash", "k")), \
             patch("trade.profile._call_extract_llm", side_effect=fake_llm):
            result = p.extract_from_sources(
                customer_id, company_id=company_id, source="chat", limit=10,
            )
        assert result["added_facts"] == 0
        assert result["dropped_invalid"] == 1

    def test_model_error_502(self, api_client, company_id, customer_id):
        client, token, cid = api_client
        self._seed_chat(company_id, customer_id)
        with patch("trade.doc_extract.resolve_extraction_model",
                   return_value=("deepseek", "flash", "k")), \
             patch("trade.profile._call_extract_llm",
                   side_effect=RuntimeError("boom")):
            r = client.post(
                f"/api/trade/customers/{customer_id}/facts/extract",
                headers=_h(token, cid), json={"source": "chat", "limit": 5},
            )
        assert r.status_code == 502
        assert "提取失败" in r.json()["detail"]

    def test_extract_in_progress_409(self, api_client, company_id, customer_id):
        from trade import profile as p

        client, token, cid = api_client
        p._EXTRACT_LOCKS.add(customer_id)
        try:
            r = client.post(
                f"/api/trade/customers/{customer_id}/facts/extract",
                headers=_h(token, cid), json={"source": "chat", "limit": 5},
            )
        finally:
            p._EXTRACT_LOCKS.discard(customer_id)
        assert r.status_code == 409
