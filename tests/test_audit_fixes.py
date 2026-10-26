"""2026-10-23 全面审计的修复回归。

三条低风险缺陷：
    - 身份 PUT 只写 DB，而运行时"文件优先" → 改了永远不生效
    - deleteOrder 先关弹窗再读表单 → 每次删除必抛 TypeError（JS 侧）
    - search_history 用 ASC + LIMIT → 返回公司最早 N 条，不是最近 N 条
"""

from __future__ import annotations

import sqlite3

import pytest

from trade.copilot.types import CustomerContext


@pytest.fixture
def test_db(monkeypatch, tmp_path):
    db_path = tmp_path / "trade.db"

    import trade.database as _db

    monkeypatch.setattr(_db, "_get_db_path", lambda: db_path)

    from trade.database import SCHEMA_SQL, _add_spare_columns

    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    _add_spare_columns(conn)
    conn.commit()
    conn.close()
    return db_path


class TestSearchHistoryReturnsMostRecent:
    def _seed(self, db_path, count: int) -> None:
        conn = sqlite3.connect(str(db_path))
        for index in range(1, count + 1):
            conn.execute(
                "INSERT INTO conversations (company_id, query, response) "
                "VALUES (?, ?, ?)",
                (1, f"q{index}", f"r{index}"),
            )
        conn.commit()
        conn.close()

    def test_returns_latest_n_in_chronological_order(self, test_db):
        from trade import chat_memory

        self._seed(test_db, 5)
        rows = chat_memory.search_history(company_id=1, limit=3)

        assert [row["query"] for row in rows] == ["q3", "q4", "q5"]

    def test_time_window_also_takes_latest(self, test_db):
        from trade import chat_memory

        self._seed(test_db, 5)
        rows = chat_memory.search_history(company_id=1, time_range="all", limit=2)

        assert [row["query"] for row in rows] == ["q4", "q5"]

    def test_company_isolation_still_enforced(self, test_db):
        from trade import chat_memory

        self._seed(test_db, 2)
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "INSERT INTO conversations (company_id, query, response) VALUES (2, 'other', '')"
        )
        conn.commit()
        conn.close()

        rows = chat_memory.search_history(company_id=1, limit=10)
        assert all("other" not in row["query"] for row in rows)


class TestIdentityPutWritesFile:
    def test_put_persists_to_identity_file(self, monkeypatch):
        """运行时解析是文件优先：PUT 必须同时写文件，否则 UI 修改不生效。"""
        from trade.api import companies as api_companies
        from trade.api.models import AgentIdentityUpdate
        from trade.prompts import get_agent_identity_by_slug

        monkeypatch.setattr(
            api_companies.company_module, "update_trade_company",
            lambda company_id, agent_identity_md=None: {"company_id": company_id},
        )
        monkeypatch.setattr(
            api_companies.company_module, "slug_from_id", lambda cid: "acme"
        )

        api_companies.update_company_agent_identity(
            1, AgentIdentityUpdate(agent_identity_md="NEW IDENTITY"), x_company_id=1,
        )

        assert get_agent_identity_by_slug("acme") == "NEW IDENTITY"

    def test_empty_identity_clears_old_file(self, monkeypatch):
        """用户清空身份时，旧文件必须一起清掉，否则旧身份继续生效。"""
        from trade.api import companies as api_companies
        from trade.api.models import AgentIdentityUpdate
        from trade.prompts import get_agent_identity_by_slug, write_agent_identity

        write_agent_identity("acme", "OLD IDENTITY")
        monkeypatch.setattr(
            api_companies.company_module, "update_trade_company",
            lambda company_id, agent_identity_md=None: {"company_id": company_id},
        )
        monkeypatch.setattr(
            api_companies.company_module, "slug_from_id", lambda cid: "acme"
        )

        api_companies.update_company_agent_identity(
            1, AgentIdentityUpdate(agent_identity_md=""), x_company_id=1,
        )

        assert get_agent_identity_by_slug("acme") == ""


class TestExplicitPathAllowlist:
    """P0：客户消息里的绝对路径只能落在本公司白名单内。"""

    def _prepare(self, tmp_path, monkeypatch):
        from trade import helpers

        company_root = tmp_path / "company"
        company_root.mkdir()
        inside = company_root / "price.md"
        inside.write_text("USD 1", encoding="utf-8")
        outside = tmp_path / "secrets.txt"
        outside.write_text("token", encoding="utf-8")

        monkeypatch.setattr(
            helpers, "_allowed_path_roots", lambda cid: [company_root.resolve()]
        )
        return helpers, company_root, inside, outside

    def test_path_inside_company_root_is_kept(self, tmp_path, monkeypatch):
        helpers, _, inside, _ = self._prepare(tmp_path, monkeypatch)
        result = helpers._extract_explicit_paths(f"读 {inside}", company_id=1)
        assert str(inside.resolve()) in result

    def test_path_outside_company_root_is_dropped(self, tmp_path, monkeypatch):
        helpers, _, _, outside = self._prepare(tmp_path, monkeypatch)
        result = helpers._extract_explicit_paths(f"读 {outside}", company_id=1)
        assert result == []

    def test_no_company_means_no_explicit_paths(self, tmp_path, monkeypatch):
        from trade import helpers

        secret = tmp_path / "secrets.txt"
        secret.write_text("x", encoding="utf-8")
        monkeypatch.setattr(helpers, "_allowed_path_roots", lambda cid: [])
        assert helpers._extract_explicit_paths(f"读 {secret}", company_id=None) == []

    def test_symlink_escape_is_dropped(self, tmp_path, monkeypatch):
        helpers, company_root, _, outside = self._prepare(tmp_path, monkeypatch)
        link = company_root / "leak.txt"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("当前文件系统不支持创建符号链接")
        result = helpers._extract_explicit_paths(f"读 {link}", company_id=1)
        assert result == [], "软链接指向白名单外时必须按真实路径拒绝"


class TestDraftRunsWithoutTools:
    """P0：草稿 path 不得带 file/terminal，也不得走 build_query。"""

    def test_draft_agent_gets_empty_toolsets(self, monkeypatch):
        from trade.copilot import draft as draft_mod

        captured: dict = {}

        class FakeAgent:
            def chat(self, prompt):
                captured["prompt"] = prompt
                return '{"draft":"ok","summary_zh":"","sources":[]}'

        def fake_create_agent(**kwargs):
            captured["agent_kwargs"] = kwargs
            return FakeAgent()

        monkeypatch.setattr("trade.helpers.create_agent", fake_create_agent)
        monkeypatch.setattr("trade.prompts.resolve_system_prompt", lambda **kw: "SYS")
        monkeypatch.setattr("trade.company.slug_from_id", lambda cid: "acme")
        monkeypatch.setattr(
            "trade.company.get_trade_company",
            lambda cid: {"agent_identity_md": ""},
        )

        def boom(*args, **kwargs):
            raise AssertionError("草稿路径不应再调用 build_query")

        monkeypatch.setattr("trade.helpers.build_query", boom)

        result = draft_mod.generate_draft(
            "hi", CustomerContext(new_contact=True), company_id=1, timeout=2,
        )

        assert result.ok, result.error
        assert captured["agent_kwargs"]["enabled_toolsets"] == []
        assert captured["agent_kwargs"]["ephemeral_system_prompt"] == "SYS"
        assert "hi" in captured["prompt"]


class TestConversationCustomerScope:
    """P0：历史注入必须按 customer_id 过滤。"""

    def _seed(self, db_path):
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("INSERT INTO companies (id, name, slug) VALUES (1, 'Co', 'co')")
        conn.execute(
            "INSERT INTO customers (id, company_id, name) VALUES (10, 1, 'A')"
        )
        conn.execute(
            "INSERT INTO customers (id, company_id, name) VALUES (11, 1, 'B')"
        )
        rows = [
            (10, "qA1", "rA1"),
            (10, "qA2", "rA2"),
            (11, "qB1", "rB1"),
            (None, "qNull", "rNull"),
        ]
        for customer_id, query, response in rows:
            conn.execute(
                "INSERT INTO conversations (company_id, customer_id, query, response) "
                "VALUES (1, ?, ?, ?)",
                (customer_id, query, response),
            )
        conn.commit()
        conn.close()

    def test_get_recent_filters_by_customer(self, test_db):
        from trade import chat_memory

        self._seed(test_db)
        rows = chat_memory.get_recent(1, limit=20, customer_id=10)
        assert [row["query"] for row in rows] == ["qA1", "qA2"]

    def test_search_history_filters_by_customer(self, test_db):
        from trade import chat_memory

        self._seed(test_db)
        rows = chat_memory.search_history(1, limit=20, customer_id=10)
        assert [row["query"] for row in rows] == ["qA1", "qA2"]

    def test_without_customer_only_returns_unattributed(self, test_db):
        """未选客户时只注入未归属对话，不能把别家客户的历史带进来。"""
        from trade import chat_memory

        self._seed(test_db)
        rows = chat_memory.get_recent(1, limit=20)
        assert [row["query"] for row in rows] == ["qNull"]

    def test_search_history_unattributed_only(self, test_db):
        from trade import chat_memory

        self._seed(test_db)
        rows = chat_memory.search_history(1, limit=20, unattributed_only=True)
        assert [row["query"] for row in rows] == ["qNull"]

    def test_save_records_customer_id(self, test_db):
        from trade import chat_memory

        conn = sqlite3.connect(str(test_db))
        conn.execute("INSERT INTO companies (id, name, slug) VALUES (1, 'Co', 'co')")
        conn.execute(
            "INSERT INTO customers (id, company_id, name) VALUES (10, 1, 'A')"
        )
        conn.commit()
        conn.close()

        saved = chat_memory.save_with_context(
            company_id=1, query="hello", response="hi",
            customer_id=10, retain_to_memory=False,
        )
        assert saved["customer_id"] == 10

    def test_history_block_uses_customer_scope(self, test_db):
        from trade import helpers

        self._seed(test_db)
        block, _ = helpers._get_history_block(1, 0, customer_id=10)
        assert "qA1" in block
        assert "qB1" not in block
        assert "qNull" not in block


class TestOrderInjectionScope:
    """P0：订单只在有意图时注入，且指定客户时绝不回退公司级。"""

    def _seed(self, db_path):
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("INSERT INTO companies (id, name, slug) VALUES (1, 'Co', 'co')")
        conn.execute(
            "INSERT INTO customers (id, company_id, name, contact) "
            "VALUES (10, 1, 'A Corp', 'Alice')"
        )
        conn.execute(
            "INSERT INTO customers (id, company_id, name, contact) "
            "VALUES (11, 1, 'B Corp', 'Bob')"
        )
        conn.execute(
            "INSERT INTO customers (id, company_id, name, contact) "
            "VALUES (12, 1, 'C Corp', 'Carol')"
        )
        conn.execute(
            "INSERT INTO orders (company_id, customer_id, product_name, unit_price, "
            "currency, status) VALUES (1, 10, 'WidgetA', 3.5, 'USD', '已下单')"
        )
        conn.execute(
            "INSERT INTO orders (company_id, customer_id, product_name, unit_price, "
            "currency, status) VALUES (1, 11, 'WidgetB', 9.9, 'USD', '已下单')"
        )
        conn.commit()
        conn.close()

    def test_no_intent_means_no_order_context(self, test_db):
        from trade.order import search_orders

        self._seed(test_db)
        assert search_orders(1, "你好，今天忙吗") is None

    def test_contact_query_can_match_that_customer(self, test_db):
        from trade.order import search_orders

        self._seed(test_db)
        text = search_orders(1, "Alice 的订单")
        assert text and "WidgetA" in text
        assert "WidgetB" not in text

    def test_customer_id_only_returns_own_orders(self, test_db):
        from trade.order import search_orders

        self._seed(test_db)
        text = search_orders(1, "报价多少", customer_id=10)
        assert text and "WidgetA" in text
        assert "WidgetB" not in text

    def test_customer_id_never_falls_back_to_company(self, test_db):
        from trade.order import search_orders

        self._seed(test_db)
        # Carol 没有订单：宁可空，也不能把 A/B 的订单塞进来
        assert search_orders(1, "报价多少", customer_id=12) is None

    def test_no_customer_no_company_fallback(self, test_db):
        """未选客户时也不能回退公司级 —— 3 笔别家订单仍是串户。"""
        from trade.order import search_orders

        self._seed(test_db)
        assert search_orders(1, "报价多少") is None

    def test_short_contact_does_not_match(self, test_db):
        """联系人只有一个字时不能命中（"张"会命中"紧张"）。"""
        from trade.order import search_orders

        conn = sqlite3.connect(str(test_db))
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("INSERT INTO companies (id, name, slug) VALUES (1, 'Co', 'co')")
        conn.execute(
            "INSERT INTO customers (id, company_id, name, contact) "
            "VALUES (10, 1, 'A Corp', '张')"
        )
        conn.execute(
            "INSERT INTO orders (company_id, customer_id, product_name) "
            "VALUES (1, 10, 'WidgetA')"
        )
        conn.commit()
        conn.close()

        assert search_orders(1, "我很紧张，报价多少") is None


class TestIdentityClearsLegacy:
    def test_empty_write_removes_canonical_and_legacy(self):
        from trade.prompts import (
            _company_identity_path,
            _legacy_identity_path,
            get_agent_identity_by_slug,
            write_agent_identity,
        )

        write_agent_identity("acme", "OLD")
        legacy = _legacy_identity_path("acme")
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("LEGACY OLD", encoding="utf-8")

        write_agent_identity("acme", "")

        assert not _company_identity_path("acme").exists()
        assert not legacy.exists()
        assert get_agent_identity_by_slug("acme") == ""


class TestCompanyDeactivateSyncsAuthTable:
    def _seed(self, db_path):
        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO companies (id, name, slug) VALUES (1, 'Co', 'co')")
        conn.execute(
            "INSERT INTO trade_companies (company_id, data_dir, agent_identity_md, is_active) "
            "VALUES (1, '/tmp/co', '', 1)"
        )
        conn.commit()
        conn.close()

    def test_delete_sets_trade_companies_inactive(self, test_db):
        from trade import company as company_module

        self._seed(test_db)
        assert company_module.delete(1) is True

        conn = sqlite3.connect(str(test_db))
        row = conn.execute(
            "SELECT is_active FROM trade_companies WHERE company_id = 1"
        ).fetchone()
        conn.close()
        assert row[0] == 0

    def test_update_is_active_sets_trade_companies(self, test_db):
        from trade import company as company_module

        self._seed(test_db)
        company_module.update(1, is_active=False)

        conn = sqlite3.connect(str(test_db))
        row = conn.execute(
            "SELECT is_active FROM trade_companies WHERE company_id = 1"
        ).fetchone()
        conn.close()
        assert row[0] == 0


class TestChatScopeValidation:
    def test_foreign_customer_is_rejected(self, monkeypatch):
        from fastapi import HTTPException

        from trade.api import chat as chat_api

        class Payload:
            customer_id = 5
            library_id = None

        monkeypatch.setattr(
            "trade.customer.get", lambda cid, company_id=None: None
        )
        with pytest.raises(HTTPException) as exc:
            chat_api._validate_scope(Payload(), 1)
        assert exc.value.status_code == 400

    def test_foreign_library_is_rejected(self, monkeypatch):
        from fastapi import HTTPException

        from trade.api import chat as chat_api

        class Payload:
            customer_id = None
            library_id = 9

        monkeypatch.setattr(
            "trade.library.get", lambda lid, company_id=None: None
        )
        with pytest.raises(HTTPException) as exc:
            chat_api._validate_scope(Payload(), 1)
        assert exc.value.status_code == 400

    def test_valid_scope_passes(self, monkeypatch):
        from trade.api import chat as chat_api

        class Payload:
            customer_id = 5
            library_id = 9

        monkeypatch.setattr("trade.customer.get", lambda cid, company_id=None: {"id": cid})
        monkeypatch.setattr("trade.library.get", lambda lid, company_id=None: {"id": lid})
        chat_api._validate_scope(Payload(), 1)
