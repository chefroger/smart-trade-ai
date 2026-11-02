"""中英双语的命令行文案（本 skill 自带，不跨目录 import）。

语言优先级：`--lang` > 环境变量 `TRADE_LANG` > 默认 `zh`。
"""

from __future__ import annotations

import os

_ZH = {
    "stats": "摸底：{count} 个压缩包，共 {bytes} 字节，0 字节损坏 {zero} 个",
    "stopped": "⚠ {reason}",
    "summary": "解压成功 {ok}，失败 {failed}，移入回收站 {trashed}，共 {rounds} 轮",
    "failed_line": "  ✗ {path}：{reason}",
    "plan_folder": "文件夹 `{name}` → 改为纯数字编号（冲突时合并）",
    "plan_file": "平放文件 `{name}` → 按编号前缀归入对应数字文件夹",
    "no_grouping": "（无需归组）",
    # 原因
    "dir_missing": "目录不存在：{path}",
    "unstable": "目录在变化（{before} → {after}），可能有进程正在写入，已停止",
    "rounds_cap": "达到上限 {rounds} 轮仍有残留（防止死循环）",
    "skip_nonempty": "已存在且非空，跳过",
    "need_7z": "需要系统已安装 7z（未找到）",
    "need_unrar": "需要系统已安装 unrar（未找到）",
    "encrypted": "包可能加密，需用户提供密码",
    "unsupported": "不支持的压缩格式",
    "extract_failed": "解压失败：{error}",
    "trash_failed": "解压成功，但原包未能移入回收站（未删除，请手动处理）",
    "dry_run": "dry-run（只统计，未动文件）",
}

_EN = {
    "stats": "Scan: {count} archive(s), {bytes} bytes total, {zero} zero-byte",
    "stopped": "⚠ {reason}",
    "summary": (
        "Extracted {ok}, failed {failed}, moved to trash {trashed}, {rounds} round(s)"
    ),
    "failed_line": "  ✗ {path}: {reason}",
    "plan_folder": "Folder `{name}` -> rename to a numeric id (merge on conflict)",
    "plan_file": "Loose file `{name}` -> move into the folder matching its number prefix",
    "no_grouping": "(nothing to regroup)",
    "dir_missing": "directory does not exist: {path}",
    "unstable": "directory is changing ({before} -> {after}); another process may be writing. Stopped.",
    "rounds_cap": "still {rounds}+ nested archives after the round cap (loop guard)",
    "skip_nonempty": "target exists and is not empty; skipped",
    "need_7z": "7z is required but not found on PATH",
    "need_unrar": "unrar is required but not found on PATH",
    "encrypted": "archive may be encrypted; ask the user for the password",
    "unsupported": "unsupported archive format",
    "extract_failed": "extraction failed: {error}",
    "trash_failed": (
        "extracted, but the archive could not be moved to the recycle bin "
        "(NOT deleted - handle manually)"
    ),
    "dry_run": "dry-run (scan only, nothing touched)",
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
