"""
Trade AI Assistant — 表格安全写出工具（防公式注入）。

按行业通行做法提供两类写出保护：
  1. `xlsx_text(value)`：openpyxl 只把以 `=` 开头的字符串解析为公式（`+`/`-`/`@` 均为
     普通字符串），对外部来源或用户输入的文本列做 `=` 前缀防护，避免生成被执行的公式；
  2. `csv_cell(value)`：面向 CSV 导出场景，对 `=` / `@` / 制表符 / 回车开头的值加前导单引号，
     对 `+` / `-` 开头的值区分真实号码/负数（如 `+86 138 0000 0000`、`-5`）与表达式。
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

# 允许原样保留的 +/- 开头号码或数值格式（如 +86 138 0000 0000、-12.5、+1 (555) 123-4567）
_SAFE_SIGNED_NUMBER_OR_PHONE_RE = re.compile(r"^[+-]\s*[0-9][0-9\s()\-.,]*$")


def xlsx_text(value: Any) -> Any:
    """安全处理写入 xlsx 文本单元格的值，防止外部输入被 openpyxl 解析为公式。

    - 数字（int/float，不含 bool）、日期时间（date/datetime）、None 原样返回；
    - 字符串以 `=` 开头（含前导空白后以 `=` 开头）时，加前导单引号按纯文本写入；
    - 其他字符串原样返回。
    """
    # None、纯数字、日期时间原样保留，不破坏数值计算与日期格式
    if value is None or isinstance(value, (date, datetime)):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    text = str(value)
    # openpyxl 仅将以 '=' 开头的字符串视为公式；加前导单引号确保按纯文本写入
    if text.lstrip().startswith("="):
        return "'" + text
    return text


def csv_cell(value: Any) -> Any:
    """安全处理写入 CSV 单元格的值，防止表格软件把外部文本当公式执行。

    - None 返回空串；纯数字（不含 bool）原样返回；
    - 以 `=`、`@`、`\t`、`\r` 开头的字符串加前导单引号；
    - 以 `+` 或 `-` 开头时，若符合纯负数或国际电话号码格式则原样保留，否则加前导单引号。
    """
    if value is None:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    text = str(value)
    if not text:
        return ""
    first = text[0]
    # 明确危险前缀一律转义
    if first in ("=", "@", "\t", "\r"):
        return "'" + text
    # +/- 开头：保留合法国际电话号码与纯负数，其余表达式转义
    if first in ("+", "-"):
        if _SAFE_SIGNED_NUMBER_OR_PHONE_RE.fullmatch(text.strip()):
            return text
        return "'" + text
    return text
