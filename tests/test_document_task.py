"""Trade 文档分析完成度任务测试。"""

from __future__ import annotations

from trade.document_task import DocumentTask, should_enforce_document_gate


def test_manifest_lists_regular_files_in_stable_order(tmp_path):
    """任务只纳入普通文件，并按相对路径排序。"""
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "c.txt").write_text("c", encoding="utf-8")
    (tmp_path / "link.txt").symlink_to(tmp_path / "a.txt")

    task = DocumentTask.from_root(tmp_path)

    assert [item.relative_path for item in task.files] == ["a.txt", "b.txt", "nested/c.txt"]


def test_gate_requires_every_manifest_file_to_be_complete(tmp_path):
    """任一文件缺少 Hermes 完整证据时，任务不能通过门禁。"""
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    task = DocumentTask.from_root(tmp_path)
    evidence = {
        str(tmp_path / "a.txt"): {"complete": True},
        str(tmp_path / "b.txt"): {"complete": False, "missing_ranges": [[1, 2]]},
    }

    result = task.evaluate(evidence)

    assert result.status == "incomplete"
    assert result.missing == ["b.txt"]


def test_gate_is_disabled_for_normal_chat():
    """普通聊天不应因为用户没有提出文件全量分析而被门禁拦截。"""
    assert should_enforce_document_gate("你好，介绍一下付款方式", has_library=True) is False
    assert should_enforce_document_gate("请完整读取这个目录的所有文件", has_library=True) is True
