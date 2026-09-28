"""从 Hermes 工具回调收集读取证据的测试。

这条路径不依赖 Hermes 的私有接口，因此公开版 Hermes 也能工作。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade.read_evidence import ReadEvidenceCollector


def _read(collector, path, *, offset=None, limit=None):
    """模拟一次 read_file 调用（args 只带模型实际给的参数）。"""
    args = {"path": str(path)}
    if offset is not None:
        args["offset"] = offset
    if limit is not None:
        args["limit"] = limit
    return args


def _result(**fields):
    """模拟 read_file 的 JSON 结果。"""
    return json.dumps(fields, ensure_ascii=False)


def test_single_full_read_is_complete(tmp_path):
    """一次读完整个文件。"""
    c = ReadEvidenceCollector()
    f = tmp_path / "a.txt"
    c.on_complete("1", "read_file", _read(c, f), _result(total_lines=30, truncated=False))

    entry = c.snapshot()[str(f.resolve())]

    assert entry["status"] == "complete"
    assert entry["complete"] is True
    assert entry["ranges"] == [[1, 30]]
    assert entry["missing_ranges"] == []


def test_paged_reads_merge_to_complete(tmp_path):
    """分页读取合并后覆盖全文。"""
    c = ReadEvidenceCollector()
    f = tmp_path / "a.txt"
    c.on_complete("1", "read_file", _read(c, f, offset=1, limit=1000),
                  _result(total_lines=1500, truncated=True, next_offset=1001))
    c.on_complete("2", "read_file", _read(c, f, offset=1001, limit=1000),
                  _result(total_lines=1500, truncated=False))

    entry = c.snapshot()[str(f.resolve())]

    # 相邻区间合并成一段
    assert entry["ranges"] == [[1, 1500]]
    assert entry["complete"] is True
    assert entry["status"] == "complete"


def test_gap_keeps_entry_partial(tmp_path):
    """中间缺一段时不能算完整。"""
    c = ReadEvidenceCollector()
    f = tmp_path / "a.txt"
    c.on_complete("1", "read_file", _read(c, f, offset=1, limit=100),
                  _result(total_lines=300, truncated=True, next_offset=101))
    c.on_complete("2", "read_file", _read(c, f, offset=201, limit=100),
                  _result(total_lines=300, truncated=False))

    entry = c.snapshot()[str(f.resolve())]

    assert entry["complete"] is False
    assert entry["missing_ranges"] == [[101, 200]]
    assert entry["status"] == "partial"


def test_byte_truncation_uses_next_offset(tmp_path):
    """字符预算截断靠 next_offset 定位已覆盖范围。"""
    c = ReadEvidenceCollector()
    f = tmp_path / "big.txt"
    c.on_complete("1", "read_file", _read(c, f, offset=1),
                  _result(total_lines=5000, truncated=True, truncated_by="bytes", next_offset=401))

    entry = c.snapshot()[str(f.resolve())]

    assert entry["ranges"] == [[1, 400]]
    assert entry["complete"] is False


def test_error_result_recorded_as_failed(tmp_path):
    """读取失败记为 failed，调用方据此披露而不是判漏读。"""
    c = ReadEvidenceCollector()
    f = tmp_path / "坏文件.xlsx"
    c.on_complete("1", "read_file", _read(c, f),
                  _result(error="document extraction failed"))

    entry = c.snapshot()[str(f.resolve())]

    assert entry["status"] == "failed"
    assert "extraction failed" in entry["error"]


def test_binary_result_recorded_as_failed(tmp_path):
    """二进制文件记为 failed。"""
    c = ReadEvidenceCollector()
    f = tmp_path / "图.txt"
    c.on_complete("1", "read_file", _read(c, f), _result(is_binary=True))

    assert c.snapshot()[str(f.resolve())]["status"] == "failed"


def test_extracted_document_reports_kind(tmp_path):
    """走解析器的文档要留下 kind，供上层识别「没真正解析」的情况。"""
    c = ReadEvidenceCollector()
    f = tmp_path / "合同.xlsx"
    c.on_complete("1", "read_file", _read(c, f),
                  _result(total_lines=20, truncated=False, extracted_document=True))

    entry = c.snapshot()[str(f.resolve())]

    assert entry["document_metadata"] == {"kind": "xlsx"}
    assert entry["source"] == "callbacks"


def test_tools_without_recognisable_evidence_are_ignored(tmp_path):
    """无关工具不产生证据；terminal 只在认得出真实存在文件时才留弱证据。"""
    c = ReadEvidenceCollector()
    c.on_complete("1", "search_files", {"pattern": "x"}, _result(total_lines=5))
    # "cat a" 里没有可识别的文件路径 → 不留任何证据
    c.on_complete("2", "terminal", {"command": "cat a"}, "output")

    assert c.snapshot() == {}


def test_invalid_result_json_does_not_crash(tmp_path):
    """结果不是 JSON 时忽略该次调用，不能让请求崩掉。"""
    c = ReadEvidenceCollector()
    f = tmp_path / "a.txt"
    c.on_complete("1", "read_file", _read(c, f), "not json at all")

    assert c.snapshot() == {}


def test_missing_path_is_ignored():
    """args 里没有 path 时忽略。"""
    c = ReadEvidenceCollector()
    c.on_complete("1", "read_file", {}, _result(total_lines=3))

    assert c.snapshot() == {}


def test_default_pagination_when_model_omits_args(tmp_path):
    """模型不带 offset/limit 时按 Hermes 的默认值计算覆盖范围。"""
    c = ReadEvidenceCollector()
    f = tmp_path / "a.txt"
    c.on_complete("1", "read_file", _read(c, f), _result(total_lines=30, truncated=False))

    assert c.snapshot()[str(f.resolve())]["ranges"] == [[1, 30]]


def test_truncated_without_total_lines_stays_incomplete(tmp_path):
    """拿不到总行数时不能判定为完整。"""
    c = ReadEvidenceCollector()
    f = tmp_path / "a.txt"
    c.on_complete("1", "read_file", _read(c, f), _result(truncated=True))

    entry = c.snapshot()[str(f.resolve())]

    assert entry["complete"] is False
    assert entry["status"] == "partial"


def test_unknown_path_is_normalized(tmp_path):
    """同一文件的相对写法要归一到同一把键上。"""
    c = ReadEvidenceCollector()
    f = tmp_path / "a.txt"
    c.on_complete("1", "read_file", {"path": f"{tmp_path}/sub/../a.txt"},
                  _result(total_lines=5, truncated=False))

    assert list(c.snapshot()) == [str(f.resolve())]


# ── 弱证据：terminal / 代码执行读过文件 ──────────────────────────────────────
# 这些工具没有 offset/limit，只能确认「读过」，不能核验读到多少。
# 记为弱证据，交由门禁如实披露，而不是判成 agent 漏读（那会误杀）。


def test_weak_tool_marks_file_as_unverified(tmp_path):
    """terminal 读过的文件记为弱证据：确认读过，但不冒充完整。"""
    c = ReadEvidenceCollector()
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF-1.4")

    c.on_complete("1", "terminal", {"command": f"pdftotext {f} -"}, "ok")

    entry = c.snapshot()[str(f.resolve())]
    assert entry["weak"] is True
    assert entry["status"] == "unverified"
    assert entry["complete"] is None, "弱证据不能断言文件已读完"


def test_all_shell_and_code_tool_names_are_weak_tracked(tmp_path):
    """terminal / bash / execute_code / code_execution 都要被弱证据覆盖。"""
    f = tmp_path / "b.xlsx"
    f.write_bytes(b"PK")

    for name in ("terminal", "bash", "execute_code", "code_execution"):
        c = ReadEvidenceCollector()
        c.on_complete("1", name, {"command": f"python -c \"open('{f}')\""}, "ok")
        assert c.snapshot()[str(f.resolve())]["weak"] is True, f"{name} 未被弱证据覆盖"


def test_read_file_evidence_wins_over_weak_touch(tmp_path):
    """同一文件既有 read_file 精确证据、又有弱触碰时，以精确证据为准。"""
    c = ReadEvidenceCollector()
    f = tmp_path / "a.txt"

    c.on_complete("1", "terminal", {"command": f"cat {f}"}, "ok")
    c.on_complete("2", "read_file", {"path": str(f)}, _result(total_lines=5, truncated=False))

    entry = c.snapshot()[str(f.resolve())]
    assert entry.get("weak") is not True
    assert entry["complete"] is True
    assert entry["total_lines"] == 5


def test_weak_tool_without_recognisable_path_leaves_nothing(tmp_path):
    """命令里认不出文件路径时不留下任何证据（不能凭空造证据）。"""
    c = ReadEvidenceCollector()
    c.on_complete("1", "terminal", {"command": "ls -la && echo hello"}, "ok")

    assert c.snapshot() == {}
