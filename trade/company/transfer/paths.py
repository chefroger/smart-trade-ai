"""跨机器路径重写。

导出包里的路径来自源机器（Unix 或 Windows），不能直接写到目标机。
这里只做“已知源前缀 → 目标前缀”的替换；未匹配的路径原样保留并由调用方
记录为 warning，绝不把包里的路径直接当成目标路径使用。
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def normalize_for_match(value: str) -> str:
    """把路径归一成可比较形式：反斜杠转正斜杠、合并重复分隔符、去尾分隔符。"""
    text = (value or "").strip().replace("\\", "/")
    text = re.sub(r"/+", "/", text)
    if len(text) > 2 and text.endswith("/"):
        text = text.rstrip("/")
    return text


class PathMapper:
    """按源前缀重写路径；最长前缀优先。"""

    def __init__(self, mappings: list[tuple[str, str]] | None = None):
        cleaned: list[tuple[str, str]] = []
        for src, dst in mappings or []:
            src_n = normalize_for_match(src)
            dst_n = normalize_for_match(dst)
            if src_n and dst_n:
                cleaned.append((src_n, dst_n))
        # 最长源前缀优先，避免 /a 抢在 /a/b 前面
        self._mappings = sorted(cleaned, key=lambda item: len(item[0]), reverse=True)

    def rewrite(self, value: str | None) -> str | None:
        if not value:
            return value
        text = normalize_for_match(value)
        for src, dst in self._mappings:
            if text == src:
                return dst
            if text.startswith(src + "/"):
                return dst + text[len(src):]
        return value

    def rewrite_files_read(self, raw: str | None) -> str:
        """重写 conversations.files_read JSON 里的绝对路径。"""
        if not raw:
            return raw or "[]"
        try:
            items = json.loads(raw)
        except (TypeError, ValueError):
            return raw
        if not isinstance(items, list):
            return raw
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in ("file", "path"):
                if isinstance(item.get(key), str):
                    item[key] = self.rewrite(item[key])
        return json.dumps(items, ensure_ascii=False)


def build_mapper(source_paths: dict, target_data_dir: str, target_work_dir: str,
                 target_libraries: dict[str, str] | None = None) -> PathMapper:
    """根据 manifest.paths 与目标机路径构造重写表。

    target_libraries: {source library name: target root_path}
    """
    mappings: list[tuple[str, str]] = []
    data_dir = source_paths.get("data_dir")
    work_dir = source_paths.get("work_dir")
    if data_dir:
        mappings.append((data_dir, target_data_dir))
    if work_dir:
        mappings.append((work_dir, target_work_dir))
    for lib in source_paths.get("libraries") or []:
        name = lib.get("name") or ""
        root = lib.get("root_path") or ""
        target = (target_libraries or {}).get(name)
        if root and target:
            mappings.append((root, target))
    return PathMapper(mappings)


def ensure_within(root: Path, candidate: Path) -> bool:
    """candidate 是否在 root 下（用于落盘前的最后一道校验）。"""
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
