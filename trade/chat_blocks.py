"""从 AI 回复中解析 ```trade-json 结构化块（W10）。

解析失败静默降级为纯文本；成功则从 text 中移除整段围栏。
next_actions 的 action 枚举 v1 只放行 gen_pi / customs_lookup（add_todo 待办未做）。
"""

from __future__ import annotations

import json
import re

# 贪婪匹配到最后一个结束围栏：草稿正文里含 ``` 时不会被首个围栏截断
_FENCE_RE = re.compile(
    r"```trade-json\s*\r?\n(.*)```\s*$",
    re.DOTALL | re.IGNORECASE,
)

# v1 允许的 action；add_todo 未落地，返回了也点不动，直接过滤掉
_ALLOWED_ACTIONS = frozenset({"gen_pi", "customs_lookup"})


def parse_trade_json_blocks(text: str) -> tuple[str, dict | None]:
    """解析回复末尾的 trade-json 围栏。

    Returns:
        (clean_text, blocks|None)。无围栏或 JSON 非法时返回原文 + None。
    """
    if not text:
        return text or "", None

    match = _FENCE_RE.search(text)
    if not match:
        return text, None

    raw = (match.group(1) or "").strip()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        # 非法围栏：不挡聊天、不剥除原文，交给前端当纯文本
        return text, None

    if not isinstance(data, dict):
        return text, None

    blocks: dict = {}

    facts = data.get("facts")
    if isinstance(facts, list):
        cleaned_facts = []
        for item in facts:
            if not isinstance(item, dict):
                continue
            cleaned_facts.append({
                "label": str(item.get("label") or ""),
                "value": str(item.get("value") or ""),
            })
            if len(cleaned_facts) >= 8:
                break
        if cleaned_facts:
            blocks["facts"] = cleaned_facts

    draft = data.get("draft")
    if isinstance(draft, dict):
        blocks["draft"] = {
            "lang": str(draft.get("lang") or ""),
            "subject": str(draft.get("subject") or ""),
            "body": str(draft.get("body") or ""),
        }

    actions = data.get("next_actions")
    if isinstance(actions, list):
        cleaned_actions = []
        for item in actions:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or "").strip()
            # 只放行 v1 已接线的 action
            if action not in _ALLOWED_ACTIONS:
                continue
            cleaned_actions.append({
                "label": str(item.get("label") or ""),
                "action": action,
            })
            if len(cleaned_actions) >= 6:
                break
        if cleaned_actions:
            blocks["next_actions"] = cleaned_actions

    # 只有解析出可用块才剥除围栏；块全被过滤时保留原文，避免内容静默消失
    if not blocks:
        return text, None
    clean = (text[: match.start()] + text[match.end() :]).rstrip()
    return clean, blocks
