"""客户语义检索：默认关闭（opt-in）、清库同步与 CLI（2026-11-04 审计）。"""

from __future__ import annotations

import sqlite3
import sys

import pytest

from trade import vec_search


def _sqlite_vec_usable() -> bool:
    try:
        import sqlite_vec

        c = sqlite3.connect(":memory:")
        c.enable_load_extension(True)
        sqlite_vec.load(c)
        c.close()
        return True
    except Exception:
        return False


HAS_VEC = _sqlite_vec_usable()
needs_vec = pytest.mark.skipif(not HAS_VEC, reason="sqlite-vec 未安装")


@pytest.fixture()
def customer_conn():
    c = sqlite3.connect(":memory:")
    c.execute(
        """CREATE TABLE customers (
               id INTEGER PRIMARY KEY, company_id INTEGER,
               name TEXT, contact TEXT, note TEXT,
               extra1 TEXT DEFAULT '{}', extra2 TEXT DEFAULT '{}')"""
    )
    c.execute(
        "INSERT INTO customers (company_id, name, contact, note) VALUES (1, 'Acme Lighting', 'john@acme.com', '灯具采购商')"
    )
    c.commit()
    yield c
    c.close()


class TestDefaultOff:
    def test_switch_defaults_to_off(self, monkeypatch):
        monkeypatch.delenv("TRADE_SEMANTIC", raising=False)
        assert vec_search.semantic_enabled() is False

    def test_vec_unavailable_when_off_even_if_installed(self, monkeypatch):
        monkeypatch.delenv("TRADE_SEMANTIC", raising=False)
        assert vec_search.vec_available() is False

    def test_search_falls_back_to_keyword_when_off(self, monkeypatch, customer_conn):
        monkeypatch.delenv("TRADE_SEMANTIC", raising=False)
        hits = vec_search.search_customers(customer_conn, "灯具", 1)
        assert len(hits) == 1
        assert hits[0]["match_type"] == "keyword"

    def test_index_customer_is_noop_when_off(self, monkeypatch, customer_conn):
        monkeypatch.delenv("TRADE_SEMANTIC", raising=False)
        assert vec_search.index_customer(
            customer_conn, {"id": 1, "company_id": 1, "name": "Acme Lighting"}
        ) is False


class TestEnabledButMissing:
    def test_enabled_without_module_falls_back(self, monkeypatch, customer_conn):
        monkeypatch.setenv("TRADE_SEMANTIC", "on")
        monkeypatch.setitem(sys.modules, "sqlite_vec", None)
        monkeypatch.setattr(vec_search, "_vec_available", None)
        assert vec_search.vec_available() is False
        hits = vec_search.search_customers(customer_conn, "灯具", 1)
        assert hits and hits[0]["match_type"] == "keyword"

    def test_invalid_value_is_treated_as_off(self, monkeypatch):
        monkeypatch.setenv("TRADE_SEMANTIC", "maybe")
        assert vec_search.semantic_enabled() is False


@needs_vec
class TestVectorCleanup:
    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch):
        monkeypatch.setenv("TRADE_SEMANTIC", "on")

    def _build(self):
        from trade.embeddings import TfidfBackend

        c = sqlite3.connect(":memory:")
        rows = [
            (1, 1, "公司一的客户 灯具"),
            (2, 1, "公司一的客户 五金"),
            (3, 2, "公司二的客户 纺织"),
        ]
        assert vec_search.rebuild_customer_index(c, rows, backend=TfidfBackend()) == 3
        return c

    def test_purge_company_vectors_removes_only_that_company(self):
        c = self._build()
        assert vec_search.purge_company_vectors(c, 1) == 2
        stats = vec_search.index_status(c)
        assert stats["rows"] == 1
        assert c.execute(
            "SELECT company_id FROM vec_customers"
        ).fetchone()[0] == 2
        c.close()

    def test_purge_last_company_clears_meta(self):
        c = self._build()
        vec_search.purge_company_vectors(c, 1)
        vec_search.purge_company_vectors(c, 2)
        stats = vec_search.index_status(c)
        assert stats["rows"] == 0 and stats["updated_at"] is None
        c.close()

    def test_clear_all_vectors(self):
        c = self._build()
        assert vec_search.clear_all_vectors(c) is True
        stats = vec_search.index_status(c)
        assert stats["rows"] == 0 and stats["updated_at"] is None
        c.close()


class TestCompanyPurgeHook:
    def test_purge_invokes_vector_cleanup(self, monkeypatch, tmp_path):
        db_path = tmp_path / "trade.db"
        import trade.database as _db

        monkeypatch.setattr(_db, "_get_db_path", lambda: db_path)
        from trade.database import SCHEMA_SQL, _add_spare_columns

        c = sqlite3.connect(str(db_path))
        c.executescript(SCHEMA_SQL)
        _add_spare_columns(c)
        c.commit()
        c.close()

        from trade.company import create as create_company
        from trade.company import crud

        company = create_company(name="清理公司", slug="purge-co")
        called = []
        monkeypatch.setattr(
            vec_search,
            "purge_company_vectors",
            lambda conn, cid: called.append(cid) or 0,
        )
        assert crud.purge(company["id"]) is True
        assert called == [company["id"]]


class TestVecCli:
    def test_status_off(self, monkeypatch, capsys, tmp_path):
        monkeypatch.delenv("TRADE_SEMANTIC", raising=False)
        import trade.database as _db

        monkeypatch.setattr(_db, "_get_db_path", lambda: tmp_path / "trade.db")
        from trade import vec_cli

        assert vec_cli.main(["status"]) == 0
        out = capsys.readouterr().out
        assert "off（默认）" in out

    def test_rebuild_refuses_when_off(self, monkeypatch, capsys):
        monkeypatch.delenv("TRADE_SEMANTIC", raising=False)
        from trade import vec_cli

        assert vec_cli.main(["rebuild"]) == 1
        assert "TRADE_SEMANTIC=on" in capsys.readouterr().out

    def test_clear_is_safe_without_index(self, monkeypatch, tmp_path):
        db_path = tmp_path / "trade.db"
        import trade.database as _db

        monkeypatch.setattr(_db, "_get_db_path", lambda: db_path)
        from trade import vec_cli

        assert vec_cli.main(["clear"]) == 0
