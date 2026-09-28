"""从 Hermes 工具回调收集文件读取证据。

为什么需要：完整性门禁要知道「哪些文件读全了」。Hermes 内部有读取追踪
（`_read_tracker`），但没有对外查询接口，且那是私有实现，会随版本变化。
改从公开的工具回调收集，只用工具结果里长期存在的字段：

  args.path                   读了哪个文件
  args.offset / args.limit    本次读的区间（模型不给时按 Hermes 默认值算）
  result.total_lines          文件总行数
  result.truncated            本次是否只读了一部分
  result.next_offset          字符预算截断时的续读位置
  result.error / is_binary    文件本身读不出来

这样公开版 Hermes 也能得到完整门禁，不需要往 Hermes 里装任何东西。
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

# Hermes read_file 的默认分页（模型不传 offset/limit 时按此计算覆盖范围）。
_DEFAULT_OFFSET = 1
_DEFAULT_LIMIT = 2000

# 能产出精确覆盖率（offset/limit/续读位置）的工具。
_TRACKED_TOOLS = frozenset({"read_file"})

# 通过 shell / 代码执行读文件的工具：能确认「读过」，但拿不到分页信息，
# 无法核验读到多少 —— 记为弱证据，交由门禁如实披露而不是判成漏读。
# 工具名取自 Hermes 侧注册名（terminal/bash/execute_code/code_execution）。
_WEAK_EVIDENCE_TOOLS = frozenset({
    "terminal", "bash", "execute_code", "code_execution",
})

# 弱证据工具的参数里，命令/代码可能出现在这些键下。
_COMMAND_ARG_KEYS = ("command", "cmd", "code", "script", "input")

# 从自由文本（用户提问 / shell 命令 / 代码片段）中提取路径候选。
# trade.helpers._extract_explicit_paths 与本模块共用它，避免两处正则漂移。
# 字符类排除引号与括号：否则 shell/代码里的 open('/x/y.pdf') 会让左最匹配
# 从引号处开始、把 "open('" 一并吞进路径。
EXPLICIT_PATH_RE = re.compile(
    r'(?:(?:文件|目录|路径|path|file|dir)\s*[：:]\s*)?'  # 可选前缀 "文件："
    r'(/(?:[^\s,，。；;、()\'"`]+/)*[^\s,，。；;、()\'"`]+'            # Unix 绝对路径
    r'|\b[A-Za-z]:\\(?:[^\s,，。；;、()\'"`]+\\)*[^\s,，。；;、()\'"`]+'  # Windows 绝对路径
    r'|[^\s,，。；;、()\'"`]+\.(?:xlsx?|csv|pdf|docx?|pptx?|txt|md|json|xml|html?|png|jpg|jpeg)'
    r')',
    re.IGNORECASE,
)


def extract_path_candidates(text: str) -> list[str]:
    """从自由文本里提取路径候选（不去重、不校验存在性，由调用方处理）。"""
    if not text:
        return []
    return EXPLICIT_PATH_RE.findall(text)


# 命令/代码里紧贴路径的引号、括号、重定向符等 —— 剥离后再解析。
# 剥离过度只会认不出路径（退回「无弱证据」的旧行为），不会造出假证据。
_PATH_JUNK = "'\"`)]}>|&*?!,，。；;、"


def _strip_path_junk(raw: str) -> str:
    """去掉路径候选两侧的命令语法字符。"""
    return raw.strip().strip(_PATH_JUNK)


def _command_text(args: Any) -> str:
    """取出工具参数里的命令/代码文本；取不到时返回空串。"""
    # 有些工具直接把命令当字符串传
    if isinstance(args, str):
        return args
    if not isinstance(args, dict):
        return ""
    # 常见键名都扫一遍，避免对具体工具的参数形状过度假设
    parts = [v for k, v in args.items() if k in _COMMAND_ARG_KEYS and isinstance(v, str)]
    return "\n".join(parts)


def _coerce_int(value: Any, fallback: int) -> int:
    """把 args 里的分页参数转成 int，非法值退回默认。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _missing_ranges(ranges: list[tuple[int, int]], total_lines: int) -> list[list[int]]:
    """返回 1..total_lines 内未被覆盖的区间。"""
    missing: list[list[int]] = []
    cursor = 1
    for start, end in ranges:
        if start > cursor:
            missing.append([cursor, min(start - 1, total_lines)])
        cursor = max(cursor, end + 1)
        if cursor > total_lines:
            break
    if cursor <= total_lines:
        missing.append([cursor, total_lines])
    return missing


def _merge(ranges: list[tuple[int, int]], new: tuple[int, int]) -> list[tuple[int, int]]:
    """合并重叠或相邻的区间。"""
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges + [new]):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


class ReadEvidenceCollector:
    """一次请求内的读取证据收集器（线程安全）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ranges: dict[str, list[tuple[int, int]]] = {}
        self._total_lines: dict[str, int | None] = {}
        self._failures: dict[str, str] = {}
        self._kinds: dict[str, dict[str, Any]] = {}
        # 弱证据：terminal / 代码执行触碰过的路径（无分页信息）
        self._weak: set[str] = set()

    # ── 回调入口 ──────────────────────────────────────────────────────────

    def on_start(self, tool_call_id, name, args) -> None:  # noqa: ARG002
        """工具开始回调；读取证据在完成时才有内容，这里无需处理。"""
        return None

    def on_complete(self, tool_call_id, name, args, result) -> None:  # noqa: ARG002
        """工具完成回调：解析 read_file 的结果并累积覆盖率。"""
        # 弱证据工具（shell / 代码执行）：从命令文本里认文件，只记「读过」
        if name in _WEAK_EVIDENCE_TOOLS:
            self._record_weak_touches(args)
            return
        if name not in _TRACKED_TOOLS or not isinstance(args, dict):
            return
        resolved = self._resolve(args.get("path"))
        if resolved is None:
            return
        payload = self._parse(result)
        if payload is None:
            return

        # 文件本身读不出来（损坏、二进制、越权等）：记为失败，
        # 上层据此披露，而不是当成 agent 漏读。
        if payload.get("error") or payload.get("is_binary"):
            reason = str(payload.get("error") or "binary_content")
            with self._lock:
                self._failures[resolved] = reason
            return

        start = _coerce_int(args.get("offset"), _DEFAULT_OFFSET)
        start = max(start, 1)
        limit = max(_coerce_int(args.get("limit"), _DEFAULT_LIMIT), 1)
        total = payload.get("total_lines")
        total = total if isinstance(total, int) and total > 0 else None

        if payload.get("truncated"):
            # 字符预算截断会给出续读位置；否则按请求区间估算。
            next_offset = payload.get("next_offset")
            end = (_coerce_int(next_offset, start + limit) - 1) if next_offset else start + limit - 1
        else:
            # 没截断说明读到了文件末尾。
            end = total if total is not None else start + limit - 1
        end = max(end, start)

        with self._lock:
            self._ranges[resolved] = _merge(self._ranges.get(resolved, []), (start, end))
            if total is not None:
                self._total_lines[resolved] = total
            if payload.get("extracted_document"):
                # 走了解析器：留下 kind，供上层识别「没真正解析」的情况。
                self._kinds[resolved] = {"kind": Path(resolved).suffix.lower().lstrip(".")}
            self._failures.pop(resolved, None)

    def _record_weak_touches(self, args: Any) -> None:
        """从命令/代码文本里认出文件路径，记为弱证据（无分页信息）。"""
        text = _command_text(args)
        if not text:
            return
        for raw in extract_path_candidates(text):
            resolved = self._resolve(_strip_path_junk(raw))
            if resolved is None:
                continue
            # 只认磁盘上真实存在的路径：命令文本里顺带提到的名字不该变成证据
            if not Path(resolved).is_file():
                continue
            with self._lock:
                self._weak.add(resolved)

    # ── 查询 ─────────────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """返回与 Hermes 快照同结构的结果，交由 DocumentTask 判定。"""
        with self._lock:
            ranges_by_path = {p: list(r) for p, r in self._ranges.items()}
            totals = dict(self._total_lines)
            failures = dict(self._failures)
            kinds = {p: dict(k) for p, k in self._kinds.items()}
            weak = set(self._weak)

        snapshot: dict[str, dict[str, Any]] = {}
        for path, ranges in ranges_by_path.items():
            total = totals.get(path)
            missing = _missing_ranges(ranges, total) if total else []
            complete = bool(total and not missing)
            snapshot[path] = {
                "status": "complete" if complete else "partial",
                "complete": complete,
                "total_lines": total,
                "ranges": [[s, e] for s, e in ranges],
                "missing_ranges": missing,
                "document_metadata": kinds.get(path, {}),
                # 标记来源：回调路径没有页数/Sheet/扫描页这类结构化元数据，
                # 上层不能对这些项做校验，否则会把正常文件误判成未解析。
                "source": "callbacks",
            }
        for path, reason in failures.items():
            # 已被后续成功读取覆盖的路径不算失败。
            if path in snapshot:
                continue
            snapshot[path] = {
                "status": "failed",
                "complete": False,
                "total_lines": None,
                "ranges": [],
                "missing_ranges": [],
                "document_metadata": {},
                "error": reason,
                "source": "callbacks",
            }
        # 弱证据最后落盘：精确证据与失败记录都优先于它，避免弱证据覆盖更可靠的信息。
        for path in weak:
            if path in snapshot:
                continue
            snapshot[path] = {
                "status": "unverified",
                "complete": None,  # 既不断言读完，也不断言漏读
                "total_lines": None,
                "ranges": [],
                "missing_ranges": [],
                "document_metadata": {},
                "source": "callbacks",
                "weak": True,
            }
        return snapshot

    # ── 内部 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve(path: Any) -> str | None:
        """把路径归一到绝对形式；缺失或非法时返回 None。"""
        text = str(path or "").strip()
        if not text:
            return None
        try:
            return str(Path(text).resolve())
        except (OSError, ValueError):
            return None

    @staticmethod
    def _parse(result: Any) -> dict[str, Any] | None:
        """解析工具结果；不是 JSON 对象时返回 None（忽略该次调用）。"""
        if isinstance(result, dict):
            return result
        if not isinstance(result, str):
            return None
        try:
            payload = json.loads(result)
        except (json.JSONDecodeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None
