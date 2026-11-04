"""成交能力并入现有技能后的回归（2026-11-04）。

培训资料提炼出的三个执行模块没有作为独立 skill 保留，按阶段并入：
- 询盘首响 + 报价异议 → b2b-lead-generation
- 单客户逼单决策 → b2b-sales-playbook
- PI 必填项检查 → b2b-doc-generation
注册表总数保持 45，路由不得抢走既有技能。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
MERGED_SKILLS = ("b2b-inquiry-reply", "b2b-quote-negotiation", "b2b-closing-pi")


def _frontmatter(name: str) -> dict:
    text = (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    assert match, f"{name} 缺 frontmatter"
    return yaml.safe_load(match.group(1))


def _effective_prompt(name: str) -> str:
    """与运行时一致：优先 SKILL.md injection_prompt，否则 registry augment_prompt。"""
    fm = _frontmatter(name)
    if (fm.get("injection_prompt") or "").strip():
        return fm["injection_prompt"]
    from trade.skill_registry import get_skill_by_name

    return get_skill_by_name(name)["augment_prompt"]


class TestStandaloneSkillsRemoved:
    def test_not_registered_and_dirs_removed(self):
        from trade.skill_registry import _SKILLS

        names = {s["name"] for s in _SKILLS}
        for name in MERGED_SKILLS:
            assert name not in names, f"{name} 仍留在注册表"
            assert not (ROOT / "skills" / name).exists(), f"{name} 目录未删除"

    def test_registry_count_back_to_45(self):
        from trade.skill_registry import _SKILLS

        assert len(_SKILLS) == 45


class TestMergedContent:
    def test_lead_generation_has_inquiry_and_quote_modules(self):
        prompt = _effective_prompt("b2b-lead-generation")
        assert "询盘首响" in prompt
        assert "报价与价格异议" in prompt
        assert "5%→3%→1%" in prompt or "5% → 3% → 1%" in prompt
        assert "未经" in prompt and "实战验证" in prompt

    def test_sales_playbook_has_closing_module(self):
        prompt = _effective_prompt("b2b-sales-playbook")
        assert "单客户逼单决策" in prompt
        assert "四前提" in prompt
        assert "双渠道" in prompt
        assert "未经" in prompt and "实战验证" in prompt

    def test_doc_generation_has_pi_check(self):
        prompt = _effective_prompt("b2b-doc-generation")
        assert "PI（形式发票）生成前检查" in prompt
        assert "银行信息变更必须双渠道核验" in prompt
        assert "未经" in prompt and "实战验证" in prompt

    def test_red_lines_kept(self):
        prompt = _effective_prompt("b2b-lead-generation") + _effective_prompt("b2b-sales-playbook")
        assert "不虚构" in prompt
        assert "经理特批" in prompt
        assert "回扣" in prompt


class TestRouting:
    POSITIVE = {
        "怎么回复询盘": "b2b-lead-generation",
        "帮我回这封询盘": "b2b-lead-generation",
        "客户嫌贵怎么办": "b2b-lead-generation",
        "客户压价怎么谈": "b2b-lead-generation",
        "客户拖着不下单": "b2b-sales-playbook",
        "客户已读不回怎么办": "b2b-sales-playbook",
        "PI检查一下": "b2b-doc-generation",
    }
    BOUNDARY = {
        "询盘训练": "b2b-inquiry-training",
        "生成报价单": "b2b-doc-generation",
        "报价单模板": "b2b-doc-generation",
        "逼单技巧": "b2b-sales-playbook",
    }

    @pytest.mark.parametrize("query,expected", POSITIVE.items())
    def test_merged_modules_are_reachable(self, query, expected):
        from trade.skill_router import match_skills

        hits = [h["skill_name"] for h in match_skills(query)]
        assert hits and hits[0] == expected, f"{query} 命中 {hits}，期望 {expected}"

    @pytest.mark.parametrize("query,expected", BOUNDARY.items())
    def test_existing_routes_keep_priority(self, query, expected):
        from trade.skill_router import match_skills

        hits = [h["skill_name"] for h in match_skills(query)]
        assert hits and hits[0] == expected, f"{query} 被抢走：{hits}"
