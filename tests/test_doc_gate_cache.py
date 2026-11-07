"""请求范围、缓存证据门禁、读取拦截的单元测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade import doc_cache, doc_scope
from trade.document_task import DocumentFile, DocumentTask


@pytest.mark.parametrize("query, expected", [
    ("介绍一下这批资料", doc_scope.SCOPE_SUMMARY),
    ("这些文件主要讲了什么", doc_scope.SCOPE_SUMMARY),
    ("哪些文件涉及 LED 灯带", doc_scope.SCOPE_LOCATE),
    ("LED 的资料在哪个文件", doc_scope.SCOPE_LOCATE),
    ("介绍一下这批报价单", doc_scope.SCOPE_FULL_READ),   # 含"报价" → money 全文
    ("总结一下这些文件里的价格", doc_scope.SCOPE_FULL_READ),
    ("哪些文件里有 2026 年的单子", doc_scope.SCOPE_FULL_READ),  # 含数字
    ("总结一下我们的优势", doc_scope.SCOPE_FULL_READ),    # 没有文档指代
    ("", doc_scope.SCOPE_FULL_READ),
])
def test_request_scope_table(query, expected):
    assert doc_scope.detect_request_scope(query) == expected


def _task(tmp_path) -> DocumentTask:
    path = tmp_path / "a.txt"
    path.write_text("hello", encoding="utf-8")
    return DocumentTask(
        root=tmp_path,
        files=[DocumentFile(
            path=path.resolve(), relative_path="a.txt",
            size=path.stat().st_size, mtime_ns=path.stat().st_mtime_ns,
        )],
        skipped=[],
    )


def _cache_record(**overrides):
    record = {
        "source": "cache",
        "cache_complete": True,
        "doc_kind": "info",
        "allowed_scope": ["summary", "locate"],
    }
    record.update(overrides)
    return record


class TestGateCacheEvidence:
    def test_info_cache_satisfies_summary(self, tmp_path):
        task = _task(tmp_path)
        evidence = {str(task.files[0].path): _cache_record()}
        result = task.evaluate(evidence, request_scope="summary")
        assert result.status == "complete"
        assert result.cache_complete == ["a.txt"]
        assert result.complete == []

    def test_info_cache_satisfies_locate(self, tmp_path):
        task = _task(tmp_path)
        result = task.evaluate(
            {str(task.files[0].path): _cache_record()}, request_scope="locate"
        )
        assert result.status == "complete"
        assert result.cache_complete == ["a.txt"]

    def test_cache_cannot_satisfy_full_read(self, tmp_path):
        task = _task(tmp_path)
        result = task.evaluate(
            {str(task.files[0].path): _cache_record()}, request_scope="full_read"
        )
        assert result.status == "incomplete"
        assert result.missing == ["a.txt"]
        assert result.cache_complete == []

    def test_money_cache_never_satisfies(self, tmp_path):
        task = _task(tmp_path)
        result = task.evaluate(
            {str(task.files[0].path): _cache_record(doc_kind="money")},
            request_scope="summary",
        )
        assert result.status == "incomplete"
        assert result.missing == ["a.txt"]

    def test_full_read_evidence_wins_over_cache(self, tmp_path):
        task = _task(tmp_path)
        evidence = {
            str(task.files[0].path): {"complete": True, "source": "hermes"},
        }
        result = task.evaluate(evidence, request_scope="summary")
        assert result.status == "complete"
        assert result.complete == ["a.txt"]
        assert result.cache_complete == []


class TestDocSkipHook:
    def test_blocks_registered_file_only(self, tmp_path, monkeypatch):
        from trade.hermes_chat_memory_plugin import doc_skip

        monkeypatch.setenv("TRADE_HOST", "1")
        target = tmp_path / "a.txt"
        target.write_text("x", encoding="utf-8")
        doc_skip.register("task-1", [str(target)])
        try:
            blocked = doc_skip.on_pre_tool_call(
                "read_file", {"path": str(target)}, task_id="task-1"
            )
            assert blocked and blocked["action"] == "block"
            # 别的 task / 别的工具 / 别的文件一律放行
            assert doc_skip.on_pre_tool_call(
                "read_file", {"path": str(target)}, task_id="task-2"
            ) is None
            assert doc_skip.on_pre_tool_call(
                "list_dir", {"path": str(target)}, task_id="task-1"
            ) is None
            assert doc_skip.on_pre_tool_call(
                "read_file", {"path": str(tmp_path / "b.txt")}, task_id="task-1"
            ) is None
        finally:
            doc_skip.release("task-1")

    def test_inactive_outside_trade_host(self, tmp_path, monkeypatch):
        from trade.hermes_chat_memory_plugin import doc_skip

        monkeypatch.delenv("TRADE_HOST", raising=False)
        target = tmp_path / "a.txt"
        target.write_text("x", encoding="utf-8")
        doc_skip.register("task-1", [str(target)])
        try:
            assert doc_skip.on_pre_tool_call(
                "read_file", {"path": str(target)}, task_id="task-1"
            ) is None
        finally:
            doc_skip.release("task-1")


class TestLoadCacheHits:
    @pytest.fixture
    def conn(self, tmp_path, monkeypatch):
        import trade.database as db

        monkeypatch.setattr(db, "_get_db_path", lambda: tmp_path / "cache.db")
        db.init_db()
        connection = db.get_connection()
        yield connection
        connection.close()

    def test_hits_info_for_summary(self, tmp_path, monkeypatch, conn):
        import trade.api.chat as chat

        task = _task(tmp_path)
        digest = doc_cache.file_sha256(task.files[0].path)
        doc_cache.save(conn, doc_cache.CacheEntry(
            tenant_id="1", sha256=digest, model="p:m",
            extractor_version=doc_cache.EXTRACTOR_VERSION,
            extracted_at="2026-11-07T10:00:00+00:00",
            extraction_status=doc_cache.STATUS_COMPLETE,
            doc_kind=doc_cache.KIND_INFO,
            facts_json="{}", summary_text="公司介绍",
        ))
        monkeypatch.setattr(chat, "resolve_extraction_model", lambda: ("p", "m", "p:m"))
        monkeypatch.setattr(chat, "get_connection", lambda: conn)

        evidence, skip, prompt = chat._load_cache_hits(task, 1, "summary")

        assert str(task.files[0].path) in skip
        assert evidence[str(task.files[0].path)]["source"] == "cache"
        assert "公司介绍" in prompt
        assert "仅用于概览/定位" in prompt

    def test_full_read_scope_never_hits(self, tmp_path, monkeypatch, conn):
        import trade.api.chat as chat

        task = _task(tmp_path)
        monkeypatch.setattr(chat, "resolve_extraction_model", lambda: ("p", "m", "p:m"))
        evidence, skip, prompt = chat._load_cache_hits(task, 1, "full_read")
        assert (evidence, skip, prompt) == ({}, set(), "")
