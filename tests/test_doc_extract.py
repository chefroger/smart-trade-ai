"""文档解析与提取测试（模型调用全部 mock，不联网、不读真实数据）。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade import doc_cache, doc_extract

# 提取器版本 → 提示词/分类规则指纹。
# 改提示词或分类规则：必须递增 doc_cache.EXTRACTOR_VERSION 并补一条新映射；
# 只改文本不改版本会直接失败（旧版本号对不上新指纹）。
TRADE_EXTRACTOR_FINGERPRINTS = {
    "5": "f00ed89d6b950c30158799bed773ce317a376a1bfbae6c5e731bd8edd844953c",
}


def _patch_model(monkeypatch, payload: str, calls: list | None = None):
    async def fake(messages, *, provider, model, timeout):
        if calls is not None:
            calls.append((provider, model, timeout))
        return payload

    monkeypatch.setattr(doc_extract, "_call_model", fake)
    monkeypatch.setattr(
        doc_extract, "resolve_extraction_model", lambda: ("provider", "model", "provider:model")
    )


@pytest.fixture
def txt_file(tmp_path):
    path = tmp_path / "quote.txt"
    path.write_text("报价单\n产品A：USD 3.50", encoding="utf-8")
    return path


class TestParsing:
    def test_text(self, txt_file):
        parsed = doc_extract.parse_document(txt_file)
        assert "USD 3.50" in parsed.text
        assert parsed.unsupported is False

    def test_xlsx_five_tuple_and_subtotal(self, tmp_path):
        import openpyxl

        path = tmp_path / "price.xlsx"
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "报价"
        sheet.append(["产品", "价格", "MOQ"])
        sheet.append(["A", "USD 3.50", 100])
        sheet.append(["合计", "USD 7.00", 200])
        workbook.save(path)

        parsed = doc_extract.parse_document(path)
        assert parsed.truncated is False
        assert "报价" in parsed.text
        first = parsed.facts[0]
        assert first["sheet"] == "报价"
        assert first["row"] == "A"
        assert first["column"] == "价格"
        assert first["value"] == "3.50"
        assert first["unit"] == "USD"
        assert first["location"] == {"sheet": "报价", "row": 2, "column": 2}
        assert first["subtotal"] is False
        assert any(f["subtotal"] for f in parsed.facts if f["row"] == "合计")

    def test_xlsx_large_sheet_is_truncated(self, tmp_path):
        import openpyxl

        path = tmp_path / "big.xlsx"
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["行", "数值"])
        for index in range(205):
            sheet.append([f"row{index}", index])
        workbook.save(path)

        parsed = doc_extract.parse_document(path)

        assert parsed.truncated is True
        assert len(parsed.facts) <= doc_extract._MAX_PARSED_FACTS

    def test_docx_large_table_is_truncated(self, tmp_path):
        import docx

        path = tmp_path / "big.docx"
        document = docx.Document()
        table = document.add_table(rows=205, cols=2)
        for row in table.rows:
            row.cells[0].text = "row"
            row.cells[1].text = "1"
        document.save(path)

        parsed = doc_extract.parse_document(path)

        assert parsed.truncated is True

    def test_xlsx_facts_cap_is_truncated(self, tmp_path):
        """facts 达到 500 条上限也是截断，不能写成 complete 缓存。"""
        import openpyxl

        path = tmp_path / "wide.xlsx"
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["产品"] + [f"c{i}" for i in range(10)])
        for row in range(80):
            sheet.append([f"p{row}"] + [row * 10 + col for col in range(10)])
        workbook.save(path)

        parsed = doc_extract.parse_document(path)
        assert parsed.truncated is True

        result = asyncio.run(doc_extract.extract_document(path))
        assert result.status == doc_cache.STATUS_FAILED
        assert result.error_code == "truncated"

    def test_xlsx_formula_without_cached_value_is_truncated(self, tmp_path):
        """公式格没有缓存值时不能当成空单元格写 complete 缓存。"""
        import openpyxl

        path = tmp_path / "formula.xlsx"
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["产品", "价格"])
        sheet.append(["A", "=1+2"])
        workbook.save(path)

        parsed = doc_extract.parse_document(path)
        assert parsed.truncated is True

        result = asyncio.run(doc_extract.extract_document(path))
        assert result.status == doc_cache.STATUS_FAILED
        assert result.error_code == "truncated"

    def test_huge_csv_field_returns_error(self, tmp_path):
        """超大单元格的 _csv.Error 也要转成 parsed.error，不能穿出去。"""
        path = tmp_path / "huge.csv"
        path.write_text("a," + "x" * 200000, encoding="utf-8")

        parsed = doc_extract.parse_document(path)

        assert parsed.error

    def test_corrupt_xlsx_returns_error_not_exception(self, tmp_path):
        path = tmp_path / "broken.xlsx"
        path.write_bytes(b"this is not a zip")

        parsed = doc_extract.parse_document(path)

        assert parsed.error
        assert parsed.truncated is False

    def test_docx_table(self, tmp_path):
        import docx

        path = tmp_path / "report.docx"
        document = docx.Document()
        document.add_paragraph("合格率报告")
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "指标"
        table.cell(0, 1).text = "数值"
        table.cell(1, 0).text = "合格率"
        table.cell(1, 1).text = "98%"
        document.save(path)

        parsed = doc_extract.parse_document(path)
        assert "合格率报告" in parsed.text
        fact = next(f for f in parsed.facts if f["row"] == "合格率")
        assert fact["value"] == "98"
        assert fact["unit"] == "%"
        assert fact["sheet"] == "表格 1"

    def test_pdf_pages_and_scanned(self, tmp_path):
        import fitz

        text_path = tmp_path / "doc.pdf"
        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), "hello pdf")
        document.save(text_path)
        document.close()

        parsed = doc_extract.parse_document(text_path)
        assert "[第 1 页]" in parsed.text
        assert "hello pdf" in parsed.text

        scanned_path = tmp_path / "scan.pdf"
        scanned = fitz.open()
        scanned.new_page()
        scanned.save(scanned_path)
        scanned.close()
        assert doc_extract.parse_document(scanned_path).needs_ocr is True

        # 混合 PDF：一页有文字、一页没有 → 不写缓存（无法确认整份读过）
        mixed_path = tmp_path / "mixed.pdf"
        mixed = fitz.open()
        mixed.new_page().insert_text((72, 72), "page one")
        mixed.new_page()
        mixed.save(mixed_path)
        mixed.close()
        assert doc_extract.parse_document(mixed_path).needs_ocr is True

    def test_unsupported_type(self, tmp_path):
        path = tmp_path / "raw.bin"
        path.write_bytes(b"\x00\x01")
        assert doc_extract.parse_document(path).unsupported is True

    def test_value_unit_split(self):
        assert doc_extract._split_value_unit("USD 3.50") == ("3.50", "USD")
        assert doc_extract._split_value_unit("3.50 USD") == ("3.50", "USD")
        assert doc_extract._split_value_unit("12%") == ("12", "%")
        assert doc_extract._split_value_unit("abc") == ("abc", "")


class TestExtraction:
    async def test_money_extraction(self, monkeypatch, txt_file):
        payload = json.dumps({
            "doc_kind": "money",
            "kind_reason": "含价格",
            "summary": "报价单",
            "facts": [{"name": "价格", "value": "3.50", "unit": "USD",
                       "location": {"page": 1}}],
        }, ensure_ascii=False)
        calls = []
        _patch_model(monkeypatch, payload, calls)

        result = await doc_extract.extract_document(txt_file)

        assert result.status == doc_cache.STATUS_COMPLETE
        assert result.doc_kind == doc_cache.KIND_MONEY
        assert result.summary == "报价单"
        assert result.facts[0]["value"] == "3.50"
        assert calls and calls[0][:2] == ("provider", "model")

    async def test_money_content_overrides_model_info(self, monkeypatch, txt_file):
        """模型把含金额的文档标成 info 时，代码兜底改回 money（审计 P2-1）。"""
        _patch_model(monkeypatch, json.dumps({
            "doc_kind": "info", "summary": "含单价 USD 3.50", "facts": [],
        }, ensure_ascii=False))
        result = await doc_extract.extract_document(txt_file)
        assert result.doc_kind == doc_cache.KIND_MONEY
        assert result.cacheable is False

    async def test_bare_unit_price_marks_money(self, monkeypatch, tmp_path):
        """「单价 3.5」没有货币符号也算金额结构（复审 P2-1）。"""
        path = tmp_path / "price.txt"
        path.write_text("产品A 单价 3.5", encoding="utf-8")
        _patch_model(monkeypatch, json.dumps({
            "doc_kind": "info", "summary": "价格", "facts": [],
        }, ensure_ascii=False))
        result = await doc_extract.extract_document(path)
        assert result.doc_kind == doc_cache.KIND_MONEY

    async def test_price_word_alone_does_not_force_money(self, monkeypatch, tmp_path):
        """只出现"价格"字样、没有金额结构时，保留模型给的 info（基准误杀修复）。"""
        path = tmp_path / "intro.txt"
        path.write_text("这是公司介绍，产品价格实惠，欢迎咨询。", encoding="utf-8")
        _patch_model(monkeypatch, json.dumps({
            "doc_kind": "info", "summary": "公司介绍", "facts": [],
        }, ensure_ascii=False))

        result = await doc_extract.extract_document(path)

        assert result.doc_kind == doc_cache.KIND_INFO
        assert result.cacheable is True

    async def test_unknown_kind_is_unclassified(self, monkeypatch, txt_file):
        _patch_model(monkeypatch, json.dumps({"doc_kind": "unknown", "summary": "x"}))
        result = await doc_extract.extract_document(txt_file)
        assert result.status == doc_cache.STATUS_UNCLASSIFIED
        assert result.doc_kind == doc_cache.KIND_UNKNOWN

    async def test_invalid_kind_falls_back_to_unknown(self, monkeypatch, txt_file):
        _patch_model(monkeypatch, json.dumps({"doc_kind": "weird", "summary": "x"}))
        result = await doc_extract.extract_document(txt_file)
        assert result.doc_kind == doc_cache.KIND_UNKNOWN
        assert result.status == doc_cache.STATUS_UNCLASSIFIED

    async def test_invalid_json_is_failed(self, monkeypatch, txt_file):
        _patch_model(monkeypatch, "not json at all")
        result = await doc_extract.extract_document(txt_file)
        assert result.status == doc_cache.STATUS_FAILED
        assert result.error_code == "parse_error"

    async def test_model_error_is_failed(self, monkeypatch, txt_file):
        async def boom(*_args, **_kwargs):
            raise RuntimeError("network down")

        monkeypatch.setattr(doc_extract, "_call_model", boom)
        monkeypatch.setattr(
            doc_extract, "resolve_extraction_model",
            lambda: ("provider", "model", "provider:model"),
        )
        result = await doc_extract.extract_document(txt_file)
        assert result.status == doc_cache.STATUS_FAILED
        assert result.error_code == "model_error"

    async def test_truncated_input_never_caches(self, monkeypatch, txt_file):
        monkeypatch.setattr(doc_extract, "_MAX_TEXT_CHARS", 4)
        calls = []
        _patch_model(monkeypatch, json.dumps({"doc_kind": "info"}), calls)
        result = await doc_extract.extract_document(txt_file)
        assert result.status == doc_cache.STATUS_FAILED
        assert result.error_code == "truncated"
        assert calls == [], "截断文件不得调用提取模型"

    async def test_unsupported_never_calls_model(self, monkeypatch, tmp_path):
        path = tmp_path / "raw.bin"
        path.write_bytes(b"\x00")
        calls = []
        _patch_model(monkeypatch, "{}", calls)
        result = await doc_extract.extract_document(path)
        assert result.error_code == "unsupported_type"
        assert calls == []


class TestWarmCache:
    def test_warm_writes_and_skips_existing(self, monkeypatch, tmp_path):
        import trade.database as db

        monkeypatch.setattr(db, "_get_db_path", lambda: tmp_path / "warm.db")
        db.init_db()
        path = tmp_path / "intro.txt"
        path.write_text("公司介绍", encoding="utf-8")
        _patch_model(monkeypatch, json.dumps(
            {"doc_kind": "info", "summary": "公司介绍", "facts": []}
        ))

        assert doc_extract.warm_cache([path], tenant_id=1) == 1

        digest = doc_cache.file_sha256(path)
        conn = db.get_connection()
        try:
            entry = doc_cache.get(
                conn, tenant_id=1, sha256=digest, model="provider:model"
            )
        finally:
            conn.close()
        assert entry is not None and entry.cacheable_info
        assert entry.summary_text == "公司介绍"

        # 已有 complete 行：不重复提取
        assert doc_extract.warm_cache([path], tenant_id=1) == 0

    def test_failed_attempts_cap_stops_retry(self, monkeypatch, tmp_path):
        import trade.database as db

        monkeypatch.setattr(db, "_get_db_path", lambda: tmp_path / "warm.db")
        db.init_db()
        path = tmp_path / "bad.txt"
        path.write_text("坏文件", encoding="utf-8")
        digest = doc_cache.file_sha256(path)
        conn = db.get_connection()
        try:
            doc_cache.save(conn, doc_cache.CacheEntry(
                tenant_id="1", sha256=digest, model="provider:model",
                extractor_version=doc_cache.EXTRACTOR_VERSION,
                extracted_at="2026-11-07T10:00:00+00:00",
                extraction_status=doc_cache.STATUS_FAILED,
                doc_kind=doc_cache.KIND_UNKNOWN,
                attempts=doc_extract.MAX_CACHE_ATTEMPTS,
                error_code="needs_ocr",
            ))
        finally:
            conn.close()
        calls = []
        _patch_model(monkeypatch, "{}", calls)

        assert doc_extract.warm_cache([path], tenant_id=1) == 0
        assert calls == [], "达到重试上限后不得再调用提取模型"

    def test_unclassified_is_retried_within_cap(self, monkeypatch, tmp_path):
        import trade.database as db

        monkeypatch.setattr(db, "_get_db_path", lambda: tmp_path / "warm.db")
        db.init_db()
        path = tmp_path / "intro.txt"
        path.write_text("公司介绍", encoding="utf-8")
        _patch_model(monkeypatch, json.dumps({"doc_kind": "unknown"}))
        assert doc_extract.warm_cache([path], tenant_id=1) == 1
        # unclassified 不是终点：下次仍会重试，attempts+1
        _patch_model(monkeypatch, json.dumps({"doc_kind": "info", "summary": "介绍"}))
        assert doc_extract.warm_cache([path], tenant_id=1) == 1
        digest = doc_cache.file_sha256(path)
        conn = db.get_connection()
        try:
            entry = doc_cache.get(
                conn, tenant_id=1, sha256=digest, model="provider:model"
            )
        finally:
            conn.close()
        assert entry.extraction_status == doc_cache.STATUS_COMPLETE
        assert entry.attempts == 2

    def test_kill_switch_disables_warm(self, monkeypatch, tmp_path):
        path = tmp_path / "intro.txt"
        path.write_text("公司介绍", encoding="utf-8")
        calls = []
        _patch_model(monkeypatch, "{}", calls)
        monkeypatch.setenv("TRADE_DOC_CACHE", "off")
        assert doc_extract.warm_cache([path], tenant_id=1) == 0
        assert calls == []


class TestCacheEntry:
    def test_complete_entry_keeps_facts(self):
        result = doc_extract.ExtractionResult(
            status=doc_cache.STATUS_COMPLETE,
            doc_kind=doc_cache.KIND_INFO,
            summary="介绍",
            facts=[{"name": "x", "value": "1"}],
        )
        entry = doc_extract.to_cache_entry(
            result, tenant_id=1, sha256="a" * 64, model=" Provider : Model ",
        )
        assert entry.model == "provider:model"
        assert entry.facts()["facts"] == [{"name": "x", "value": "1"}]
        assert entry.cacheable_info is True

    def test_failed_entry_has_no_content(self):
        result = doc_extract.ExtractionResult(
            status=doc_cache.STATUS_FAILED, error_code="needs_ocr",
            doc_kind=doc_cache.KIND_MONEY, summary="x", facts=[{"a": 1}],
        )
        entry = doc_extract.to_cache_entry(
            result, tenant_id=1, sha256="a" * 64, model="m",
        )
        assert entry.facts_json == "{}"
        assert entry.summary_text == ""
        assert entry.doc_kind == doc_cache.KIND_UNKNOWN
        assert entry.error_code == "needs_ocr"


def test_extractor_fingerprint_is_pinned_per_version():
    """提示词/分类规则一改，这里必须失败 —— 提醒同时递增 extractor_version。"""
    expected = TRADE_EXTRACTOR_FINGERPRINTS[doc_cache.EXTRACTOR_VERSION]
    assert doc_extract.extractor_fingerprint() == expected
