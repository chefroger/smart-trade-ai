"""文档提取缓存 DAO 测试（租户隔离、复合键、fail-closed）。"""

from __future__ import annotations

import hashlib
import sqlite3  # noqa: F401 —— 关闭连接后的写失败依赖它的异常类型
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade import doc_cache
from trade.doc_cache import CacheEntry


@pytest.fixture
def conn(tmp_path, monkeypatch):
    """临时库 + init_db；每个用例独立。"""
    import trade.database as db

    monkeypatch.setattr(db, "_get_db_path", lambda: tmp_path / "cache.db")
    db.init_db()
    connection = db.get_connection()
    yield connection
    connection.close()


def _entry(**overrides) -> CacheEntry:
    values = {
        "tenant_id": "1",
        "sha256": hashlib.sha256(b"file").hexdigest(),
        "model": "deepseek:chat",
        "extractor_version": doc_cache.EXTRACTOR_VERSION,
        "extracted_at": "2026-11-07T10:00:00+08:00",
        "extraction_status": doc_cache.STATUS_COMPLETE,
        "doc_kind": doc_cache.KIND_INFO,
        "facts_json": '{"price": ["USD 3.50"]}',
        "summary_text": "产品介绍",
    }
    values.update(overrides)
    return CacheEntry(**values)


def test_table_is_created_by_init_db(conn):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='doc_extractions'"
    ).fetchone()
    assert row is not None


def test_roundtrip_and_upsert(conn):
    assert doc_cache.save(conn, _entry())
    got = doc_cache.get(
        conn, tenant_id=1, sha256=_entry().sha256, model="DeepSeek:Chat"
    )
    assert got is not None
    assert got.cacheable_info is True
    assert got.facts() == {"price": ["USD 3.50"]}

    # 同键覆盖：更新摘要与尝试次数，不产生第二行
    assert doc_cache.save(conn, _entry(summary_text="更新后的摘要", attempts=2))
    again = doc_cache.get(conn, tenant_id=1, sha256=_entry().sha256, model="deepseek:chat")
    assert again.summary_text == "更新后的摘要"
    assert again.attempts == 2
    count = conn.execute("SELECT COUNT(*) FROM doc_extractions").fetchone()[0]
    assert count == 1


def test_composite_key_misses(conn):
    doc_cache.save(conn, _entry())
    digest = _entry().sha256
    assert doc_cache.get(conn, tenant_id=2, sha256=digest, model="deepseek:chat") is None
    assert doc_cache.get(conn, tenant_id=1, sha256=digest, model="other:model") is None
    assert doc_cache.get(
        conn, tenant_id=1, sha256=digest, model="deepseek:chat",
        extractor_version="999",
    ) is None


def test_invalid_rows_are_misses(conn):
    doc_cache.save(conn, _entry())
    conn.execute(
        "UPDATE doc_extractions SET facts_json = 'not json' WHERE tenant_id = '1'"
    )
    conn.commit()
    assert doc_cache.get(
        conn, tenant_id=1, sha256=_entry().sha256, model="deepseek:chat"
    ) is None

    doc_cache.save(conn, _entry(tenant_id="2"))
    conn.execute(
        "UPDATE doc_extractions SET attempts = 0 WHERE tenant_id = '2'"
    )
    conn.commit()
    assert doc_cache.get(
        conn, tenant_id=2, sha256=_entry().sha256, model="deepseek:chat"
    ) is None


def test_save_rejects_invalid_entries(conn):
    assert doc_cache.save(conn, _entry(sha256="not-a-hash")) is False
    assert doc_cache.save(conn, _entry(facts_json="[]")) is False
    assert doc_cache.save(conn, _entry(extraction_status="weird")) is False
    assert conn.execute("SELECT COUNT(*) FROM doc_extractions").fetchone()[0] == 0


def test_purge_is_tenant_scoped(conn):
    doc_cache.save(conn, _entry(tenant_id="1"))
    doc_cache.save(conn, _entry(tenant_id="2", sha256=hashlib.sha256(b"b").hexdigest()))

    assert doc_cache.purge_tenant(conn, 1) == 1

    digest = _entry().sha256
    assert doc_cache.get(conn, tenant_id=1, sha256=digest, model="deepseek:chat") is None
    assert doc_cache.get(conn, tenant_id=2, sha256=digest, model="deepseek:chat") is None
    kept = doc_cache.get(
        conn, tenant_id=2, sha256=hashlib.sha256(b"b").hexdigest(), model="deepseek:chat"
    )
    assert kept is not None


def test_hash_is_content_based(tmp_path):
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_bytes(b"hello world")
    second.write_bytes(b"hello world")
    assert doc_cache.file_sha256(first) == doc_cache.file_sha256(second)

    second.write_bytes(b"hello worle")
    assert doc_cache.file_sha256(first) != doc_cache.file_sha256(second)


def test_model_key_is_normalized():
    assert doc_cache.normalize_model("  DeepSeek:Chat ") == "deepseek:chat"


def test_same_content_other_path_hits(conn, tmp_path):
    """缓存以内容哈希为键：同租户同内容换路径仍然命中（验收 6）。"""
    doc_cache.save(conn, _entry())
    moved = tmp_path / "moved.txt"
    moved.write_bytes(b"file")
    assert doc_cache.file_sha256(moved) == _entry().sha256
    assert doc_cache.get(
        conn, tenant_id=1, sha256=_entry().sha256, model="deepseek:chat"
    ) is not None


def test_cache_kill_switch(monkeypatch):
    monkeypatch.delenv("TRADE_DOC_CACHE", raising=False)
    assert doc_cache.cache_enabled() is True
    monkeypatch.setenv("TRADE_DOC_CACHE", "off")
    assert doc_cache.cache_enabled() is False


def test_all_queries_are_tenant_scoped():
    assert "tenant_id = ?" in doc_cache._SELECT_SQL
    assert doc_cache._PURGE_SQL == "DELETE FROM doc_extractions WHERE tenant_id = ?"


def test_company_purge_removes_only_own_cache(conn):
    """公司物理删除时清本公司缓存，别的公司行必须保留。"""
    from trade.company import crud as company_crud

    conn.execute("INSERT INTO companies (id, name, slug) VALUES (1, 'A', 'a')")
    conn.execute("INSERT INTO companies (id, name, slug) VALUES (2, 'B', 'b')")
    conn.commit()
    doc_cache.save(conn, _entry(tenant_id="1"))
    other_digest = hashlib.sha256(b"b").hexdigest()
    doc_cache.save(conn, _entry(tenant_id="2", sha256=other_digest))

    assert company_crud.purge(1) is True

    assert doc_cache.get(
        conn, tenant_id=1, sha256=_entry().sha256, model="deepseek:chat"
    ) is None
    assert doc_cache.get(
        conn, tenant_id=2, sha256=other_digest, model="deepseek:chat"
    ) is not None


def test_storage_failure_returns_false_or_none(conn):
    conn.close()
    assert doc_cache.save(conn, _entry()) is False
    assert doc_cache.get(
        conn, tenant_id=1, sha256=_entry().sha256, model="deepseek:chat"
    ) is None
