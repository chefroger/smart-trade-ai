"""中英双语的命令行文案（本 skill 自带，不跨目录 import）。

语言优先级：`--lang` > 环境变量 `TRADE_LANG` > 默认 `zh`。
"""

from __future__ import annotations

import os

_ZH = {
    "manifest_empty": "清单为空或缺必填字段（name/url/size），未下载任何文件。",
    "ok_line": "✓ {name}（{size} 字节）已校验通过",
    "failed_line": "✗ {name}：{reason}",
    "summary": "完成 {ok}/{total}",
    # 失败原因
    "file_missing": "文件不存在",
    "size_mismatch": "大小不符：期望 {expected}，实际 {actual}",
    "digest_mismatch": "{kind} 不符：期望 {expected}，实际 {actual}",
    "range_unsupported": "服务端未返回 206（status={status}）",
    "chunk_failed": "分片 {start}-{end} 下载失败：{error}",
    "chunk_status": "UID {uid} 拉取失败：{status}",
    "lock_held": "已有下载器在跑（pid {pid}）：{name}",
}

_EN = {
    "manifest_empty": (
        "Manifest is empty or missing required fields (name/url/size); nothing downloaded."
    ),
    "ok_line": "✓ {name} ({size} bytes) verified",
    "failed_line": "✗ {name}: {reason}",
    "summary": "Completed {ok}/{total}",
    "file_missing": "file does not exist",
    "size_mismatch": "size mismatch: expected {expected}, got {actual}",
    "digest_mismatch": "{kind} mismatch: expected {expected}, got {actual}",
    "range_unsupported": "server did not return 206 (status={status})",
    "chunk_failed": "chunk {start}-{end} failed: {error}",
    "chunk_status": "UID {uid} fetch failed: {status}",
    "lock_held": "another downloader is running (pid {pid}): {name}",
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
