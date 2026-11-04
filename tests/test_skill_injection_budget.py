"""技能注入文本的 token 预算回归（2026-11-04）。

5 个最大的注入提示词已压缩，完整规则移到 SKILL.md 正文，由 `skill_view` 按需加载。
这里钉住两件事：注入体积不反弹；被移走的详细内容确实还在正文里（不是删除）。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

# 技能 → (注入上限字符数, 正文里必须仍存在的原规则标记)
BUDGETS = {
    "b2b-linkedin-marketing": (1500, "7 天 LinkedIn 主页打造计划"),
    "b2b-platform": (1500, "量化异常诊断阈值"),
    "b2b-doc-generation": (1500, "标准外贸单证字段清单"),
    "b2b-customer-intel": (1500, "15 维度画像结构"),
    "b2b-cold-outreach": (1500, "6 封标准邮件推进序列"),
}


def _text(name: str) -> str:
    return (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


def _frontmatter(text: str) -> dict:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    assert match, "缺 frontmatter"
    return yaml.safe_load(match.group(1))


def test_injection_prompts_stay_within_budget():
    for name, (limit, _marker) in BUDGETS.items():
        prompt = _frontmatter(_text(name)).get("injection_prompt") or ""
        assert len(prompt) <= limit, f"{name} 注入 {len(prompt)} 字符，超过预算 {limit}"


def test_full_rules_moved_to_body_not_deleted():
    for name, (_limit, marker) in BUDGETS.items():
        text = _text(name)
        assert "## 详细规则（skill_view 按需加载）" in text, f"{name} 缺详细规则入口"
        assert marker in text, f"{name} 的详细规则标记丢失：{marker}"


def test_injection_points_to_skill_view():
    for name in BUDGETS:
        prompt = _frontmatter(_text(name)).get("injection_prompt") or ""
        assert "skill_view" in prompt, f"{name} 注入没有告诉模型去哪儿加载详细规则"


def test_total_budget_of_top5():
    total = sum(
        len(_frontmatter(_text(name)).get("injection_prompt") or "")
        for name in BUDGETS
    )
    assert total <= 4000, f"前 5 大注入合计 {total} 字符，超过预算 4000"
