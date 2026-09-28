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


def test_unreadable_file_is_disclosed_not_blocking(tmp_path):
    """文件本身读不出来（损坏/二进制）时照常给结果，只在披露里列出。"""
    (tmp_path / "notes.txt").write_text("a", encoding="utf-8")
    (tmp_path / "合同.xlsx").write_bytes(b"PK\x03\x04broken")
    task = DocumentTask.from_root(tmp_path)

    result = task.evaluate({
        str((tmp_path / "notes.txt").resolve()): {"status": "complete", "complete": True},
        str((tmp_path / "合同.xlsx").resolve()): {
            "status": "failed", "complete": False, "error": "document extraction failed"},
    })

    assert result.status == "complete"
    assert result.complete == ["notes.txt"]
    assert result.missing == []
    assert {"file": "合同.xlsx", "reason": "document extraction failed"} in result.skipped


def test_binary_document_read_as_plain_text_is_disclosed(tmp_path):
    """PDF/Office 未走解析器（被当纯文本读出）时披露，不误判为已完整读取。"""
    (tmp_path / "notes.txt").write_text("a", encoding="utf-8")
    (tmp_path / "真实合同.pdf").write_bytes(b"%PDF-1.4 ...")
    task = DocumentTask.from_root(tmp_path)

    result = task.evaluate({
        str((tmp_path / "notes.txt").resolve()): {"status": "complete", "complete": True},
        # 纯文本读取：没有 document_metadata，说明解析器没参与
        str((tmp_path / "真实合同.pdf").resolve()): {"status": "complete", "complete": True},
    })

    assert result.status == "complete"
    assert result.complete == ["notes.txt"]
    assert any(item["file"] == "真实合同.pdf" for item in result.skipped)


def test_pdf_with_page_metadata_counts_as_complete(tmp_path):
    """PDF 走了解析器、有页数且无扫描页时才算完整读取。"""
    (tmp_path / "真实合同.pdf").write_bytes(b"%PDF-1.4 ...")
    task = DocumentTask.from_root(tmp_path)

    result = task.evaluate({
        str((tmp_path / "真实合同.pdf").resolve()): {
            "status": "complete", "complete": True,
            "document_metadata": {"kind": "pdf", "pages": 3, "scanned_pages": []},
        },
    })

    assert result.status == "complete"
    assert result.complete == ["真实合同.pdf"]
    assert result.skipped == []


def test_pdf_with_scanned_pages_is_disclosed(tmp_path):
    """扫描页没有文字层，其内容不在提取结果里，不能算已完整读取。"""
    (tmp_path / "扫描合同.pdf").write_bytes(b"%PDF-1.4 ...")
    task = DocumentTask.from_root(tmp_path)

    result = task.evaluate({
        str((tmp_path / "扫描合同.pdf").resolve()): {
            "status": "complete", "complete": True,
            "document_metadata": {"kind": "pdf", "pages": 4, "scanned_pages": [2, 3]},
        },
    })

    assert result.status == "complete"
    assert result.complete == []
    assert result.missing == []
    assert result.skipped == [{"file": "扫描合同.pdf", "reason": "scanned_pages"}]


def test_fully_scanned_pdf_is_disclosed(tmp_path):
    """整份都是扫描件时同样披露，不判成 agent 漏读。"""
    (tmp_path / "扫描件.pdf").write_bytes(b"%PDF-1.4 ...")
    task = DocumentTask.from_root(tmp_path)

    result = task.evaluate({
        str((tmp_path / "扫描件.pdf").resolve()): {
            "status": "complete", "complete": True,
            "document_metadata": {"kind": "pdf", "pages": 2, "scanned_pages": [1, 2]},
        },
    })

    assert result.status == "complete"
    assert result.skipped == [{"file": "扫描件.pdf", "reason": "scanned_pages"}]


def test_pdf_without_page_count_is_not_complete(tmp_path):
    """解析器认得 PDF 但拿不到页数时，不能算完整读取。"""
    (tmp_path / "真实合同.pdf").write_bytes(b"%PDF-1.4 ...")
    task = DocumentTask.from_root(tmp_path)

    result = task.evaluate({
        str((tmp_path / "真实合同.pdf").resolve()): {
            "status": "complete", "complete": True,
            "document_metadata": {"kind": "pdf", "pages": None},
        },
    })

    assert result.complete == []
    assert any(item["file"] == "真实合同.pdf" for item in result.skipped)


def test_callback_evidence_does_not_require_structured_metadata(tmp_path):
    """回调来源的证据没有页数/Sheet 元数据，不能因此把正常文件判成未解析。"""
    (tmp_path / "报价.xlsx").write_bytes(b"PK\x03\x04")
    (tmp_path / "合同.pdf").write_bytes(b"%PDF-1.4")
    task = DocumentTask.from_root(tmp_path)
    evidence = {
        str((tmp_path / "报价.xlsx").resolve()): {
            "status": "complete", "complete": True, "source": "callbacks",
            "document_metadata": {"kind": "xlsx"},
        },
        str((tmp_path / "合同.pdf").resolve()): {
            "status": "complete", "complete": True, "source": "callbacks",
            "document_metadata": {"kind": "pdf"},
        },
    }

    result = task.evaluate(evidence)

    assert result.status == "complete"
    assert set(result.complete) == {"报价.xlsx", "合同.pdf"}
    assert result.skipped == []


def test_callback_evidence_still_detects_unparsed_document(tmp_path):
    """回调来源也能识别「文档没走解析器」——例如没解析就直接读成文本的 PDF。"""
    (tmp_path / "合同.pdf").write_bytes(b"%PDF-1.4")
    task = DocumentTask.from_root(tmp_path)
    evidence = {
        str((tmp_path / "合同.pdf").resolve()): {
            "status": "complete", "complete": True, "source": "callbacks",
            "document_metadata": {},          # 没有 kind = 没走解析器
        },
    }

    result = task.evaluate(evidence)

    assert result.complete == []
    assert result.skipped == [{"file": "合同.pdf", "reason": "not_parsed_as_pdf"}]


def test_agent_skipping_a_readable_file_still_blocks(tmp_path):
    """Hermes 能读、但 agent 完全没读的文件仍算不通过。"""
    (tmp_path / "notes.txt").write_text("a", encoding="utf-8")
    (tmp_path / "合同.xlsx").write_bytes(b"PK\x03\x04")
    task = DocumentTask.from_root(tmp_path)

    result = task.evaluate({
        str((tmp_path / "notes.txt").resolve()): {"status": "complete", "complete": True},
    })

    assert result.status == "incomplete"
    assert result.missing == ["合同.xlsx"]


def test_gate_untracked_when_no_evidence_at_all(tmp_path):
    """完全没有读取证据时不判失败，避免误拦。

    （不再等同于「全程用 terminal 读」——那种情形现在会产生弱证据，
    见 test_weak_evidence_is_disclosed_not_blocking。）
    """
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


# ── 弱证据（terminal / 代码执行读取）────────────────────────────────────────
# 用这些工具读过的文件：不判漏读（消除误杀），但必须披露「无法核验完整性」，
# 不能让用户以为已经逐 Sheet / 逐页校验过。


def test_weak_evidence_is_disclosed_not_blocking(tmp_path):
    """terminal 读过的 PDF：不判漏读，但要披露无法核验完整性。"""
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
    task = DocumentTask.from_root(tmp_path)

    result = task.evaluate({
        str((tmp_path / "a.pdf").resolve()): {
            "status": "unverified", "complete": None, "ranges": [],
            "document_metadata": {}, "source": "callbacks", "weak": True,
        },
    })

    assert result.missing == [], "弱证据不该被判成漏读 —— 这正是要消除的误杀"
    assert result.status == "complete"
    assert "coverage_unverifiable" in {item["reason"] for item in result.skipped}


def test_weak_evidence_does_not_hide_untouched_files(tmp_path):
    """弱证据只覆盖它触碰的文件，未触碰的文件仍必须判漏读。"""
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "b.txt").write_text("x", encoding="utf-8")
    task = DocumentTask.from_root(tmp_path)

    result = task.evaluate({
        str((tmp_path / "a.pdf").resolve()): {
            "status": "unverified", "complete": None, "weak": True, "source": "callbacks",
        },
    })

    assert result.missing == ["b.txt"]
    assert result.status == "incomplete"


def test_mixed_read_file_and_weak_evidence_does_not_block(tmp_path):
    """混合场景（read_file 读 A + terminal 读 B）不应再被整体误杀。"""
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4")
    task = DocumentTask.from_root(tmp_path)

    result = task.evaluate({
        str((tmp_path / "a.txt").resolve()): {
            "status": "complete", "complete": True, "total_lines": 1,
            "ranges": [[1, 1]], "missing_ranges": [],
            "document_metadata": {}, "source": "callbacks",
        },
        str((tmp_path / "b.pdf").resolve()): {
            "status": "unverified", "complete": None, "weak": True, "source": "callbacks",
        },
    })

    assert result.status == "complete", "terminal 读过的文件不该把整体判成 incomplete"
    assert result.missing == []


def test_partial_read_still_blocks(tmp_path):
    """回归护栏：read_file 只读了一半仍必须判漏读（弱证据不能放宽这条）。"""
    (tmp_path / "a.txt").write_text("x\ny\nz\n", encoding="utf-8")
    task = DocumentTask.from_root(tmp_path)

    result = task.evaluate({
        str((tmp_path / "a.txt").resolve()): {
            "status": "partial", "complete": False, "total_lines": 3,
            "ranges": [[1, 1]], "missing_ranges": [[2, 3]],
            "document_metadata": {}, "source": "callbacks",
        },
    })

    assert result.missing == ["a.txt"]
    assert result.status == "incomplete"


def test_unverifiable_reason_has_human_label():
    """披露原因必须有中文说明，否则用户看到的是机器码。"""
    from trade.document_task import _REASON_LABELS

    assert "coverage_unverifiable" in _REASON_LABELS


# ── 能力边界如实披露 ────────────────────────────────────────────────────────
# 只有在 Hermes 提供结构化读取快照时才能核验 Sheet / 页数 / 扫描页。
# 客户机装的是原版 Hermes，没有这个接口 —— 此时必须如实说明「未能核验」，
# 否则用户会以为已经逐 Sheet 逐页校验过（开发机上能校验、客户机上不能）。


def test_callback_evidence_discloses_unverifiable_coverage(tmp_path):
    """回调证据（原版 Hermes）：要披露无法逐 Sheet/逐页核验。"""
    (tmp_path / "a.xlsx").write_bytes(b"PK")
    task = DocumentTask.from_root(tmp_path)

    result = task.evaluate({
        str((tmp_path / "a.xlsx").resolve()): {
            "status": "complete", "complete": True, "total_lines": 3,
            "ranges": [[1, 3]], "missing_ranges": [],
            "document_metadata": {}, "source": "callbacks",
        },
    })

    assert result.status == "complete"
    assert result.coverage_note, "回调证据下必须说明完整性未经核验"
    assert "Sheet" in result.coverage_note or "页" in result.coverage_note


def test_structured_evidence_has_no_coverage_note(tmp_path):
    """有结构化快照（开发机）时不需要额外披露。"""
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
    task = DocumentTask.from_root(tmp_path)

    result = task.evaluate({
        str((tmp_path / "a.pdf").resolve()): {
            "status": "complete", "complete": True,
            "document_metadata": {"kind": "pdf", "pages": 3},
            "source": "hermes_snapshot",
        },
    })

    assert result.status == "complete"
    assert result.coverage_note == ""


def test_incomplete_report_carries_coverage_note(tmp_path):
    """被拦下时也要带上能力边界说明，避免用户以为差异是漏读造成的。"""
    (tmp_path / "a.xlsx").write_bytes(b"PK")
    (tmp_path / "b.xlsx").write_bytes(b"PK")
    task = DocumentTask.from_root(tmp_path)

    result = task.evaluate({
        # a 读了、b 没读 → incomplete
        str((tmp_path / "a.xlsx").resolve()): {
            "status": "complete", "complete": True, "source": "callbacks",
        },
    })

    assert result.status == "incomplete"
    assert result.coverage_note, "被拦下时也必须说明能力边界"
    assert result.coverage_note in format_incomplete_report(result)
