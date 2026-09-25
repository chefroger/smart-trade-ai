"""Trade 文档分析完成度任务测试。"""

from __future__ import annotations

from trade.document_task import (
    DocumentTask,
    format_incomplete_report,
    should_enforce_document_gate,
)


def test_manifest_marks_non_analyzable_files_as_skipped(tmp_path):
    """二进制、隐藏和临时文件不纳入强制读取范围，但仍记录在清单里。"""
    (tmp_path / "报价.xlsx").write_bytes(b"PK\x03\x04")
    (tmp_path / ".DS_Store").write_bytes(b"\x00\x01")
    (tmp_path / "~$报价.xlsx").write_bytes(b"\x00")
    (tmp_path / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "link.txt").symlink_to(tmp_path / "报价.xlsx")

    task = DocumentTask.from_root(tmp_path)

    assert [item.relative_path for item in task.files] == ["报价.xlsx"]
    assert {item.relative_path for item in task.skipped} == {
        ".DS_Store", "~$报价.xlsx", "photo.png", "link.txt"}


def test_gate_ignores_skipped_files(tmp_path):
    """存在 .DS_Store 等无法读取的文件时，只要可分析文件读完就算通过。"""
    (tmp_path / "报价.xlsx").write_bytes(b"PK\x03\x04")
    (tmp_path / ".DS_Store").write_bytes(b"\x00\x01")
    task = DocumentTask.from_root(tmp_path)

    result = task.evaluate({
        str((tmp_path / "报价.xlsx").resolve()): {
            "complete": True,
            "document_metadata": {"kind": "xlsx", "sheets": ["Sheet1"]},
        },
    })

    assert result.status == "complete"
    assert result.complete == ["报价.xlsx"]
    assert [item["file"] for item in result.skipped] == [".DS_Store"]


def test_gate_requires_every_analyzable_file_to_be_complete(tmp_path):
    """任一可分析文件缺少 Hermes 完整证据时，任务不能通过门禁。"""
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    task = DocumentTask.from_root(tmp_path)
    evidence = {
        str((tmp_path / "a.txt").resolve()): {"complete": True},
        str((tmp_path / "b.txt").resolve()): {"complete": False, "missing_ranges": [[1, 2]]},
    }

    result = task.evaluate(evidence)

    assert result.status == "incomplete"
    assert result.missing == ["b.txt"]


def test_gate_normalizes_path_aliases(tmp_path):
    """同一文件经由不同书写形式访问时不应被误判为未读取。"""
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    task = DocumentTask.from_root(tmp_path)
    alias = str(tmp_path / "sub" / ".." / "a.txt")

    result = task.evaluate({alias: {"complete": True}})

    assert result.status == "complete"


def test_gate_untracked_when_no_evidence_at_all(tmp_path):
    """完全没有读取证据（例如全程用 terminal 读）时不判失败，避免误拦。"""
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    task = DocumentTask.from_root(tmp_path)

    result = task.evaluate({})

    assert result.status == "untracked"


def test_incomplete_report_names_missing_and_skipped_files(tmp_path):
    """不通过时要给出人可读的原因，说明哪些文件没读完、哪些未纳入。"""
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / ".DS_Store").write_bytes(b"\x00")
    task = DocumentTask.from_root(tmp_path)
    result = task.evaluate({str((tmp_path / "a.txt").resolve()): {"complete": True}})

    report = format_incomplete_report(result)

    assert "b.txt" in report
    assert ".DS_Store" in report
    assert "未读完" in report


def test_manifest_truncates_large_directories(tmp_path):
    """文件过多时标记 truncated，调用方据此放弃强制，避免大面积误判。"""
    for i in range(205):
        (tmp_path / f"f{i:03d}.txt").write_text("x", encoding="utf-8")

    task = DocumentTask.from_root(tmp_path)

    assert task.truncated is True
    assert len(task.files) + len(task.skipped) <= 200


def test_gate_disabled_for_normal_chat():
    """普通聊天不应因为用户没有提出文件全量分析而被门禁拦截。"""
    assert should_enforce_document_gate("你好，介绍一下付款方式") is False
    assert should_enforce_document_gate("逐个介绍一下你们的产品线") is False
    assert should_enforce_document_gate("read all you can about payment terms") is False
    assert should_enforce_document_gate("这个报价单完整读取一下金额") is False


def test_gate_enabled_for_explicit_full_directory_read():
    """明确要求读完整个目录时才启用门禁。"""
    assert should_enforce_document_gate("请完整读取这个目录的所有文件") is True
    assert should_enforce_document_gate("逐个读取全部文件，不要遗漏") is True
    assert should_enforce_document_gate("read every file completely") is True
