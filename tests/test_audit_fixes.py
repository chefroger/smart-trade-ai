"""2026-10-23 全面审计的修复回归。

三条低风险缺陷：
    - 身份 PUT 只写 DB，而运行时"文件优先" → 改了永远不生效
    - deleteOrder 先关弹窗再读表单 → 每次删除必抛 TypeError（JS 侧）
    - search_history 用 ASC + LIMIT → 返回公司最早 N 条，不是最近 N 条
"""

from __future__ import annotations

import sqlite3

import pytest


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
