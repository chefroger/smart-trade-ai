"""任务中止时的「未完成报告」（工单 P0-5）。

超时 / 客户端断连 / 用户停止时，Agent 往往已经跑完若干工具调用，却来不及
给最终回复。不写进历史 → 用户下次问起时这一段完全消失；写完整回答 → 编造。
折中：只把**实际完成的工具调用**列出来，明确标注「已查 / 未查渠道」，并标记
partial=true，让后续轮次知道这不是最终结论。

本模块只做数据整理，不发网络请求、不写库。
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

# 单次请求最多记录的工具调用数（防止长任务把内存撑大）
_MAX_ITEMS = 50
# 单条结果预览长度
_PREVIEW_CHARS = 240
# 总结提示里工具结果的总预算
_TRANSCRIPT_CHARS = 6000

# 工具名 → 中文标签（Hermes 注册名；未知工具回退原名）
TOOL_LABELS = {
    "read_file": "读取文件",
    "list_dir": "列目录",
    "web_search": "网页搜索",
    "web_fetch": "抓取网页",
    "browser_navigate": "浏览器访问",
    "terminal": "终端命令",
    "bash": "终端命令",
    "execute_code": "执行代码",
    "code_execution": "执行代码",
    "vision_analyze": "图像识别",
    "image_analyze": "图像识别",
}

# 参数里最有辨识度的键（按优先级）
_DETAIL_KEYS = ("path", "query", "q", "url", "command", "cmd", "code")

# 结果预览的隐私过滤（P1-F 规则）：客户索要与家庭成员信息不进未完成报告
_SENSITIVE_CJK = (
    "客户索要", "索要", "礼物", "太太", "妻子", "老婆", "丈夫", "老公",
    "儿子", "女儿", "孩子", "父母",
)
# 英文必须按词边界：裸 "son" 会命中 person/reason，把正常结果全隐藏
_SENSITIVE_EN_RE = re.compile(
    r"\b(?:wife|husband|son|daughter|kids|children)\b", re.IGNORECASE
)


def _safe_preview(text: str) -> str:
    """结果预览：命中隐私标记整条隐藏；否则截到 240 字（单行）。"""
    value = " ".join(str(text or "").split())[:240]
    if any(marker in value for marker in _SENSITIVE_CJK):
        return "[已按隐私规则隐藏]"
    if _SENSITIVE_EN_RE.search(value):
        return "[已按隐私规则隐藏]"
    return value


def _one_line(text: Any, limit: int) -> str:
    """压成单行并截断（报告里不出现换行/超长内容）。"""
    return " ".join(str(text).split())[:limit]


def _summarize_args(args: Any) -> str:
    """从工具参数里取最有辨识度的一项（路径 / 查询词 / URL / 命令）。"""
    if isinstance(args, str):
        return _one_line(args, 100)
    if not isinstance(args, dict):
        return ""
    for key in _DETAIL_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return _one_line(value, 100)
    return ""


def _stringify(result: Any) -> str:
    """把工具结果转成可截断的文本。"""
    if isinstance(result, str):
        return result
    if isinstance(result, (dict, list)):
        try:
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception:
            return str(result)
    return "" if result is None else str(result)


class CompletedToolTracker:
    """一次请求内**已完成**的工具调用（线程安全）。

    与 ReadEvidenceCollector 互补：后者只认文件读取（用于完整性门禁），
    这里记录所有工具，用于任务中止时写「已查渠道」以及只基于已有结果总结。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._completed: list[dict] = []

    def on_start(self, name: str, args: Any) -> None:  # noqa: ARG002
        """记录开始（目前只用于对称性；报告只列已完成的调用）。"""
        return None

    def on_complete(self, name: str, args: Any, result: Any) -> None:
        """记录一次完成的工具调用（超出上限后丢弃，保证内存有界）。"""
        with self._lock:
            if len(self._completed) >= _MAX_ITEMS:
                return
            self._completed.append({
                "name": str(name or "unknown"),
                "detail": _summarize_args(args),
                "preview": _one_line(_stringify(result), _PREVIEW_CHARS),
            })

    def has_completed(self) -> bool:
        """本轮是否至少完成过一次工具调用（决定要不要出未完成报告）。"""
        with self._lock:
            return bool(self._completed)

    def completed_count(self) -> int:
        with self._lock:
            return len(self._completed)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [dict(item) for item in self._completed]

    def transcript(self) -> str:
        """给总结调用用的工具结果清单（有长度上限）。"""
        items = self.snapshot()
        lines: list[str] = []
        used = 0
        for idx, item in enumerate(items, 1):
            label = TOOL_LABELS.get(item["name"], item["name"])
            detail = f"（{item['detail']}）" if item["detail"] else ""
            line = f"{idx}. {label}{detail}: {item['preview']}"
            if used + len(line) > _TRANSCRIPT_CHARS:
                lines.append(f"…（其余 {len(items) - idx + 1} 条结果已省略）")
                break
            lines.append(line)
            used += len(line)
        return "\n".join(lines)


def build_partial_report(
    reason: str,
    tools: CompletedToolTracker | None,
    evidence=None,
) -> str:
    """生成「⚠️ 未完成报告（已查/未查渠道）」。

    只写实际发生过的事实：做过的工具调用、读取失败的文件、以及「最终回答
    没有产出」这一状态。不推测未完成的渠道查到了什么。
    """
    items = tools.snapshot() if tools is not None else []
    lines = [f"⚠️ 未完成报告（本轮已中止：{reason}）", ""]

    if not items:
        lines.append("已查渠道：无 —— 本轮在完成任何工具调用之前就被中途中止。")
        lines.append("未查渠道：全部。")
        return "\n".join(lines)

    lines.append(f"## 已查渠道（实际完成的工具调用，共 {len(items)} 次）")
    grouped: dict[str, list[dict]] = {}
    for item in items:
        grouped.setdefault(item["name"], []).append(item)
    for name, group in grouped.items():
        label = TOOL_LABELS.get(name, name)
        details = "；".join(i["detail"] for i in group if i["detail"])
        detail_text = f"：{details[:200]}" if details else ""
        lines.append(f"- {label} ×{len(group)}{detail_text}")
        # 每个工具最多 2 行结果预览（工单 P1-G）：总结调用失败时用户手里
        # 至少还有查到的东西，而不是只有一份「搜过哪些词」的清单。
        for item in group[:2]:
            preview = _safe_preview(item.get("preview") or "")
            if preview:
                lines.append(f"  · 结果：{preview}")

    # 文件读取失败单独列出：它们是「查过但没查成」，与「没查」不同
    if evidence is not None:
        try:
            snapshot = evidence.snapshot()
        except Exception:
            snapshot = {}
        failures = [
            (path, info.get("error"))
            for path, info in snapshot.items()
            if info.get("status") == "failed"
        ]
        if failures:
            lines.append("")
            lines.append("读取失败的文件：")
            for path, error in failures[:5]:
                lines.append(f"- {Path(path).name}（{error}）")

    lines.append("")
    lines.append("## 未查渠道 / 未完成")
    lines.append("- Agent 在给出最终结论前被中止：完整回答、结论与建议没有产出。")
    lines.append("- 需要继续时请重新提问；上面列出的调用已经完成，不会自动补查未完成的渠道。")
    lines.append("")
    lines.append("（本报告由 Trade 在任务中止时自动生成，只列出实际完成的工具调用，不含推测。）")
    return "\n".join(lines)


def build_summary_prompt(query: str, tools: CompletedToolTracker) -> str:
    """「只基于已有结果出总结」的一次调用所用的提示词。

    工具在总结调用里被禁用（enabled_toolsets=[]），所以不会重复执行工具。
    """
    return (
        "上一轮任务在给出最终回答前被中止了。下面是这一轮**已经实际完成**的"
        "工具调用与结果（内容可能被截断）。请只依据这些结果回答用户的问题：\n"
        "- 不要调用任何工具，也不要编造结果之外的信息；\n"
        "- 信息不足时如实说明还缺什么，不要用常识补全；\n"
        "- 分点作答，简洁，与用户提问的语言一致。\n\n"
        f"用户问题：{query}\n\n"
        f"已完成工具结果：\n{tools.transcript()}"
    )
