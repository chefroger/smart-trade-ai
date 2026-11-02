"""中英双语的命令行文案（本 skill 自带，不跨目录 import）。

语言优先级：`--lang` > 环境变量 `TRADE_LANG` > 默认 `zh`。
注意：询价单**表头与单元格取值**（「待确认」「按图纸」）按任务书固定为中文，
这里只翻译命令行输出。
"""

from __future__ import annotations

import os

_ZH = {
    "project_folder": "项目文件夹：{path}",
    "sheet": "询价单：{path}",
    "skeleton_notice": "提示：缺主文件，本次为骨架询价单（数量标「待确认」，单重/材质标「按图纸」）",
    "warning": "警告：{text}",
    "row_non_numeric": "第 {row} 行：单重或数量非数值，总重留空（需人工核对）",
    "no_desktop": "无法确定桌面路径，请用 --root 指定交付目录",
}

_EN = {
    "project_folder": "Project folder: {path}",
    "sheet": "Inquiry sheet: {path}",
    "skeleton_notice": (
        "Note: main tender file missing - skeleton sheet only "
        "(quantity 'TBC', weight/material 'per drawing')"
    ),
    "warning": "Warning: {text}",
    "row_non_numeric": (
        "Row {row}: weight or quantity is non-numeric; total weight left blank "
        "(needs manual check)"
    ),
    "no_desktop": "Cannot determine the Desktop path; pass --root <dir>",
}

_LANG = "zh"


def set_language(value: str | None) -> None:
    """设置输出语言（zh / en）。"""
    global _LANG
    if value and str(value).lower() in ("zh", "en"):
        _LANG = str(value).lower()


def current_language() -> str:
    """当前语言（先看显式设置，再看 TRADE_LANG）。"""
    return _LANG if _LANG != "zh" else (os.environ.get("TRADE_LANG") or "zh").lower()


def t(key: str, **kw) -> str:
    """取一条文案并格式化。"""
    table = _EN if current_language() == "en" else _ZH
    template = table.get(key) or _ZH.get(key) or key
    try:
        return template.format(**kw)
    except (KeyError, IndexError):
        return template
