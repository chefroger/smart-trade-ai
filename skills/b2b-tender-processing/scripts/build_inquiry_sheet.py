#!/usr/bin/env python3
"""生成 11 列询价单（xlsx）并建标准项目文件夹。

用法：
    python build_inquiry_sheet.py --spec items.json [--root <交付根目录>]

`items.json` 结构（占位符，按当次招标替换）：

    {
      "tender_no": "<招标编号，可空>",
      "buyer": "<采购方>",
      "project_name": "<项目名称 / 核心品名>",
      "deadline": "<截止日期>",
      "status": "待报价",                // 或 "已报价"
      "date": "2026-11-02",             // 可选，缺省取当天
      "skeleton": false,                 // 缺主文件时置 true
      "rows": [
        {"no": 1, "part_no": "<物料号>", "name_src": "<原文名称>",
         "name_zh": "<译文名称>", "qty": 10, "unit_weight": 12.5,
         "material": "<材质>"},
        {"no": 2, "part_no": "<部件图号>", "name_src": "...", "name_zh": "...",
         "unit_qty": 3, "units": 4, "unit_weight": 2.0, "material": "..."}
      ]
    }

列序固定，不因调用方参数改变：
    序号 | 物料号 | 名称（原文） | 名称（译文） | 数量 | 图纸单重 | 总重 | 材质 | 单价 | 总价 | 交货期
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date as _date
from pathlib import Path

import _i18n_processing as _i18n
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

#: 11 列固定表头（列序不得改）。
HEADERS = [
    "序号",
    "物料号",
    "名称（原文）",
    "名称（译文）",
    "数量",
    "图纸单重",
    "总重",
    "材质",
    "单价",
    "总价",
    "交货期",
]

#: 文件名非法字符。
_ILLEGAL = r'[<>:"/\\|?*\x00-\x1f]'


def _safe(name: str) -> str:
    """替换文件名非法字符并去掉首尾空格 / 点。"""
    return (re.sub(_ILLEGAL, "_", str(name or "")).strip(" .")) or "未命名"


def project_folder_name(spec: dict) -> str:
    """项目文件夹名：``<日期>-<招标编号><核心品名>-<状态>``。

    无招标编号时省略编号段（纯邮件询价）。
    """
    day = str(spec.get("date") or _date.today().isoformat())
    # 无招标编号（纯邮件询价）时省略编号段 —— 不能落成「未命名」
    raw_no = str(spec.get("tender_no") or "").strip()
    no = _safe(raw_no) if raw_no else ""
    name = _safe(spec.get("project_name") or "招标项目")
    status = _safe(spec.get("status") or "待报价")
    return f"{day}-{no}{name}-{status}"


def _row_quantity(row: dict, skeleton: bool) -> tuple[object, str]:
    """算数量与追踪注。

    装配体拆件：数量 = 单台数量 × 台数，译名后注明「（单台 N × M 台）」。
    缺主文件（skeleton）：数量标「待确认」。
    """
    if skeleton:
        return "待确认", ""
    unit_qty = row.get("unit_qty")
    units = row.get("units")
    if unit_qty is not None and units is not None:
        try:
            total = float(unit_qty) * float(units)
        except (TypeError, ValueError):
            return row.get("qty", ""), ""
        note = f"（单台 {unit_qty} × {units} 台）"
        return (int(total) if total.is_integer() else total), note
    return row.get("qty", ""), ""


def _row_weight(row: dict, skeleton: bool) -> object:
    """图纸单重：拿不到就写「按图纸」，不编造。"""
    if skeleton:
        return "按图纸"
    weight = row.get("unit_weight")
    if weight is None or weight == "":
        return "按图纸"
    return weight


def build_workbook(spec: dict) -> tuple[Workbook, list[str]]:
    """按 spec 生成工作簿，返回 (wb, 警告列表)。"""
    skeleton = bool(spec.get("skeleton"))
    rows = spec.get("rows") or []
    if not rows:
        # 缺主文件且没有任何行项：仍出骨架表头，数量留空由用户填
        rows = [{"no": 1}]
        skeleton = True

    wb = Workbook()
    ws = wb.active
    ws.title = "询价单"

    # 第 1 行即表头（不在表头前塞编号 / 采购方等元信息）
    ws.append(HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    try:
        from trade.sheet_safe import write_xlsx_text_cell
    except ImportError:
        # 脚本脱离 trade 包独立运行时内联同逻辑（权威实现见 trade/sheet_safe.py）
        def write_xlsx_text_cell(cell, value):  # type: ignore[misc]
            if value is None or isinstance(value, (int, float)) and not isinstance(value, bool):
                cell.value = value
                return value
            cell.value = str(value)
            if hasattr(cell, "data_type"):
                cell.data_type = "s"
            return cell.value

    warnings: list[str] = []
    for idx, row in enumerate(rows, start=1):
        qty, note = _row_quantity(row, skeleton)
        weight = _row_weight(row, skeleton)
        name_zh = str(row.get("name_zh") or "")
        if note:
            name_zh = f"{name_zh}{note}"

        excel_row = idx + 1  # 数据从第 2 行开始
        ws.append(
            [
                None,
                None,
                None,
                None,
                qty,
                weight,
                None,  # 总重：下面按需写公式
                None,
                None,  # 单价：留空
                None,  # 总价：留空
                None,  # 交货期：留空
            ]
        )
        # P3-19：文本列通过 write_xlsx_text_cell 置 data_type='s'，防公式执行且不留字面撇号
        write_xlsx_text_cell(ws.cell(excel_row, 1), row.get("no", idx))
        write_xlsx_text_cell(ws.cell(excel_row, 2), row.get("part_no", ""))
        write_xlsx_text_cell(ws.cell(excel_row, 3), row.get("name_src", ""))
        write_xlsx_text_cell(ws.cell(excel_row, 4), name_zh)
        write_xlsx_text_cell(ws.cell(excel_row, 8), row.get("material", "") if not skeleton else "按图纸")

        # 总重 = 数量 × 单重（公式）。单重不是数字时留空，避免 #VALUE!
        if isinstance(weight, (int, float)) and isinstance(qty, (int, float)):
            ws.cell(row=excel_row, column=7, value=f"=E{excel_row}*F{excel_row}")
        else:
            warnings.append(_i18n.t("row_non_numeric", row=idx))

    # 末行汇总：总重与总价用求和公式
    last_data = len(rows) + 1
    summary_row = last_data + 1
    ws.cell(row=summary_row, column=1, value="汇总")
    ws.cell(row=summary_row, column=7, value=f"=SUM(G2:G{last_data})")
    ws.cell(row=summary_row, column=10, value=f"=SUM(J2:J{last_data})")
    for col in (1, 7, 10):
        ws.cell(row=summary_row, column=col).font = Font(bold=True)

    # 列宽：只是可读性，不影响列序
    widths = [6, 14, 28, 28, 10, 12, 12, 14, 12, 12, 14]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"

    return wb, warnings


def build(spec: dict, root: str | Path) -> dict:
    """生成项目文件夹与询价单，返回结果摘要（供测试与 CLI 共用）。"""
    folder = Path(root).expanduser() / project_folder_name(spec)
    folder.mkdir(parents=True, exist_ok=True)

    wb, warnings = build_workbook(spec)
    out = folder / f"{_safe(spec.get('project_name') or '询价单')}.xlsx"
    wb.save(out)

    return {
        "folder": str(folder),
        "sheet": str(out),
        "rows": len(spec.get("rows") or []),
        "warnings": warnings,
        "skeleton": bool(spec.get("skeleton")),
    }


def main() -> int:
    """入口：读 spec → 生成 → 打印摘要。"""
    parser = argparse.ArgumentParser(description="生成 11 列询价单")
    parser.add_argument("--spec", required=True, help="行项 JSON 路径")
    parser.add_argument("--root", default="", help="交付根目录（缺省为桌面）")
    parser.add_argument("--lang", choices=("zh", "en"), default=None,
                        help="Output language (default: TRADE_LANG or zh)")
    args = parser.parse_args()
    _i18n.set_language(args.lang)

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    root = args.root or str(default_desktop())
    result = build(spec, root)

    print(_i18n.t("project_folder", path=result["folder"]))
    print(_i18n.t("sheet", path=result["sheet"]))
    if result["skeleton"]:
        print(_i18n.t("skeleton_notice"))
    for w in result["warnings"]:
        print(_i18n.t("warning", text=w))
    return 0


def default_desktop() -> Path:
    """默认交付根目录：桌面。

    **服务账户下不要依赖这个默认值** —— 服务会话的 `HOME` 可能不是当前登录
    用户的桌面。此时必须由用户显式传 `--root` 绝对路径。
    """
    import os

    home = os.environ.get("HOME") or os.environ.get("USERPROFILE")
    if not home:
        raise SystemExit(_i18n.t("no_desktop"))
    return Path(home) / "Desktop"


if __name__ == "__main__":
    sys.exit(main())
