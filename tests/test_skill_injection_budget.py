"""技能注入文本的 token 预算回归（2026-11-04，2026-11-12 改口径）。

5 个最大的注入提示词已压缩，完整规则移到 SKILL.md 正文，由 `skill_view` 按需加载。
这里钉住三件事：注入体积不反弹；被移走的详细内容确实还在正文里（不是删除）；
以及**运行时实际注入量**（injection_prompt + when_to_use 段）在预算内。

2026-11-12 口径（Lau 选 A）：
- 前 5 大**运行时**合计 ≤ 5000。原 4000 只量 frontmatter 的 injection_prompt，
  漏掉 `augment_query()` 追加的 when_to_use 段，实际运行时 4812 —— 旧测试
  测不到真正的花费。
- 单技能上限仍是 1500，但同样按运行时量（当前最大 1200）。
  这条**只对这 5 个**生效：全仓最大是 b2b-inquiry-training（约 4277），
  它不在受控名单里，扩到全仓会立刻红。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

# 技能 → (运行时上限字符数, 正文里必须仍存在的原规则标记)
BUDGETS = {
    "b2b-linkedin-marketing": (1500, "7 天 LinkedIn 主页打造计划"),
    "b2b-platform": (1500, "量化异常诊断阈值"),
    "b2b-doc-generation": (1500, "标准外贸单证字段清单"),
    "b2b-customer-intel": (1500, "15 维度画像结构"),
    "b2b-cold-outreach": (1500, "6 封标准邮件推进序列"),
}

# 与 trade/skill_router.augment_query() 里的段头保持一致。
# 若实现改了措辞，test_runtime_matches_augment_query() 会先红。
_WHEN_HEADER = "\n\n适用场景（用户这样说时启用本技能）：\n"
TOTAL_BUDGET = 5000


def _text(name: str) -> str:
    return (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


def _frontmatter(text: str) -> dict:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    assert match, "缺 frontmatter"
    return yaml.safe_load(match.group(1)) or {}


def _when_block(frontmatter: dict) -> str:
    """复刻 augment_query() 拼的 when_to_use 段（含跳过条件）。"""
    raw = frontmatter.get("when_to_use") or []
    items = (raw,) if isinstance(raw, str) else raw
    values = [str(item).strip() for item in items if str(item).strip()]
    if not values:
        return ""
    return _WHEN_HEADER + "\n".join(f"- {item}" for item in values) + "\n"


def _runtime_injection(name: str) -> str:
    """运行时注入的近似值：injection_prompt（或 registry 兜底）+ when 段。"""
    fm = _frontmatter(_text(name))
    prompt = fm.get("injection_prompt") or ""
    if not prompt:
        # 与 load_injection_prompt() 一致：SKILL.md 没有 injection_prompt 时
        # 降级到 registry 的 augment_prompt
        from trade.skill_registry import _SKILLS

        skill = next((item for item in _SKILLS if item["name"] == name), None)
        prompt = (skill or {}).get("augment_prompt", "") or ""
    # 与 augment_query() 一致：注入里已有「适用场景」就不再追加
    if "适用场景" in prompt:
        return prompt
    return prompt + _when_block(fm)


def test_runtime_stays_within_per_skill_budget():
    for name, (limit, _marker) in BUDGETS.items():
        size = len(_runtime_injection(name))
        assert size <= limit, f"{name} 运行时注入 {size} 字符，超过预算 {limit}"


def test_full_rules_moved_to_body_not_deleted():
    for name, (_limit, marker) in BUDGETS.items():
        text = _text(name)
        assert "## 详细规则（skill_view 按需加载）" in text, f"{name} 缺详细规则入口"
        assert marker in text, f"{name} 的详细规则标记丢失：{marker}"


def test_injection_points_to_skill_view():
    for name in BUDGETS:
        prompt = _frontmatter(_text(name)).get("injection_prompt") or ""
        assert "skill_view" in prompt, f"{name} 注入没有告诉模型去哪儿加载详细规则"


def test_total_runtime_budget_of_top5():
    total = sum(len(_runtime_injection(name)) for name in BUDGETS)
    assert total <= TOTAL_BUDGET, (
        f"前 5 大运行时注入合计 {total} 字符，超过预算 {TOTAL_BUDGET}"
    )


def test_runtime_matches_augment_query():
    """测试复刻的 when 段必须与真实注入一致，防止两边漂移。"""
    from trade.skill_router import augment_query

    name = "b2b-doc-generation"
    fm = _frontmatter(_text(name))
    items = fm.get("when_to_use") or []
    assert items, f"{name} 应有 when_to_use"

    injected = augment_query("做一份价值 BOM", skill_name=name)
    assert _WHEN_HEADER in injected, "注入里缺 when_to_use 段头（措辞漂移？）"
    assert str(items[0]).strip() in injected, "注入里缺 when_to_use 条目"
