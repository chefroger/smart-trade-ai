"""trade.sheet_safe 表格防公式注入测试（M5）。"""

from __future__ import annotations

from datetime import date, datetime

import openpyxl
import pytest

from trade.sheet_safe import csv_cell, xlsx_text


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("=HYPERLINK(\"http://x\",\"a\")", "'=HYPERLINK(\"http://x\",\"a\")"),
        ("  =SUM(A1:A10)", "'  =SUM(A1:A10)"),
        ("normal text", "normal text"),
        ("+86 138 0000 0000", "+86 138 0000 0000"),
        ("-5", "-5"),
        ("@SUM(A1)", "@SUM(A1)"),
        (123, 123),
        (45.6, 45.6),
        (None, None),
        (date(2026, 11, 28), date(2026, 11, 28)),
        (datetime(2026, 11, 28, 9, 0), datetime(2026, 11, 28, 9, 0)),
    ],
)
def test_xlsx_text_cases(raw, expected):
    """xlsx_text 仅对 = 开头字符串加前导单引号，保留数字/日期/普通文本。"""
    assert xlsx_text(raw) == expected


def test_xlsx_text_prevents_formula_datatype_in_openpyxl():
    """经 xlsx_text 处理后的 =HYPERLINK 写入 openpyxl 单元格类型为文本 s 而非公式 f。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([xlsx_text('=HYPERLINK("http://x","a")'), xlsx_text(10)])
    assert ws["A1"].data_type == "s"
    assert ws["B1"].value == 10


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("=1+1", "'=1+1"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tcmd", "'\tcmd"),
        ("\rcmd", "'\rcmd"),
        ("+cmd|' /C calc'!A0", "'+cmd|' /C calc'!A0"),
        ("-1+1", "'-1+1"),
        ("+86 138 0000 0000", "+86 138 0000 0000"),
        ("+1 (555) 123-4567", "+1 (555) 123-4567"),
        ("-5", "-5"),
        ("-12.5", "-12.5"),
        (None, ""),
        ("", ""),
        (42, 42),
    ],
)
def test_csv_cell_cases(raw, expected):
    """csv_cell 防公式注入同时保留合法国际电话与纯负数。"""
    assert csv_cell(raw) == expected
