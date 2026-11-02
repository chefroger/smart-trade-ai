"""中英双语的命令行文案（本 skill 自带，不跨目录 import）。

语言优先级：`--lang` > 环境变量 `TRADE_LANG` > 默认 `zh`。
"""

from __future__ import annotations

import os

_ZH = {
    "summary": (
        "清单 {items} 项；本地 {files} 个文件；匹配 {matched} 项，"
        "未匹配清单项 {unmatched} 项"
    ),
    "match_line": "  ✓ [{strategy}] #{no} {name} → {files}",
    "unmatched_line": "  ? 未匹配：#{no} {name}（候选文件 {candidates} 个，未擅自归档）",
    "plan_only": "（只出计划；确认后加 --apply 执行）",
    "verify_ok": "回读验证：通过",
    "verify_fail": "回读验证失败：{why}",
    "verify_root_count": "根目录文件数不符：期望 {expected}，实际 {actual}",
    "verify_total_count": "总文件数不符：期望 {expected}，实际 {actual}",
    # 匹配策略名
    "strategy.specified": "清单指定",
    "strategy.number": "编号精确",
    "strategy.name_equal": "名称相等",
    "strategy.name_contains": "名称互含",
}

_EN = {
    "summary": (
        "{items} item(s) in the list; {files} local file(s); "
        "matched {matched}, unmatched items {unmatched}"
    ),
    "match_line": "  ✓ [{strategy}] #{no} {name} -> {files}",
    "unmatched_line": (
        "  ? unmatched: #{no} {name} ({candidates} candidate file(s), none auto-filed)"
    ),
    "plan_only": "(plan only; re-run with --apply to execute)",
    "verify_ok": "Read-back check: OK",
    "verify_fail": "Read-back check failed: {why}",
    "verify_root_count": "root file count mismatch: expected {expected}, got {actual}",
    "verify_total_count": "total file count mismatch: expected {expected}, got {actual}",
    "strategy.specified": "listed files",
    "strategy.number": "number exact",
    "strategy.name_equal": "name equal",
    "strategy.name_contains": "name contains",
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
