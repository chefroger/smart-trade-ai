"""成交三件套（询盘首响 / 报价异议 / 逼单 PI）的验收探针。

对应 2026-11-04 培训资料分析后的 P0 建议：这三个环节是 Trade 的执行缺口，
且必须与既有的询盘训练、报价单生成、销冠经验库划清路由边界。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIRS = {
    "b2b-inquiry-reply": ROOT / "skills" / "b2b-inquiry-reply",
    "b2b-quote-negotiation": ROOT / "skills" / "b2b-quote-negotiation",
    "b2b-closing-pi": ROOT / "skills" / "b2b-closing-pi",
}
CATEGORY_ENUM = {
    "客户开发", "客户管理", "文档管理", "数据分析", "平台运营", "内容营销",
    "销售转化", "履约运营", "合规风控", "自动化", "系统工具",
}


def _frontmatter(name: str) -> dict:
    text = (SKILL_DIRS[name] / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    assert match, f"{name} 缺 frontmatter"
    return yaml.safe_load(match.group(1))


class TestRegistration:
    def test_all_three_registered(self):
        from trade.skill_registry import get_skill_by_name

        for name in SKILL_DIRS:
            assert get_skill_by_name(name) is not None, f"{name} 未注册"

    def test_skill_dirs_have_skeleton(self):
        for name, path in SKILL_DIRS.items():
            for sub in ("scripts", "references", "assets"):
                assert (path / sub / "README.md").is_file(), f"{name} 缺 {sub}/README.md"

    def test_frontmatter_is_valid(self):
        for name in SKILL_DIRS:
            fm = _frontmatter(name)
            assert fm["name"] == name
            assert isinstance(fm.get("description"), str) and "\n" not in fm["description"]
            assert fm["category"] in CATEGORY_ENUM
            assert re.fullmatch(r"\d+\.\d+\.\d+", str(fm["version"]))
            assert fm.get("author")
            when = fm.get("when_to_use") or []
            assert 3 <= len(when) <= 10, f"{name} when_to_use 条数={len(when)}"
            assert any("不要用于" in str(x) for x in when), f"{name} 缺「不要用于」"
            assert len(fm.get("triggers") or []) >= 5
            assert (fm.get("injection_prompt") or "").strip(), f"{name} 缺注入文本"


class TestRouting:
    POSITIVE = {
        "怎么回复询盘": "b2b-inquiry-reply",
        "帮我回这封询盘": "b2b-inquiry-reply",
        "客户嫌贵怎么办": "b2b-quote-negotiation",
        "客户压价怎么谈": "b2b-quote-negotiation",
        "客户拖着不下单": "b2b-closing-pi",
        "客户已读不回怎么办": "b2b-closing-pi",
        "PI检查一下": "b2b-closing-pi",
    }
    # 既有能力的路由不能被新技能抢走
    BOUNDARY = {
        "询盘训练": "b2b-inquiry-training",
        "生成报价单": "b2b-doc-generation",
        "报价单模板": "b2b-doc-generation",
        "逼单技巧": "b2b-sales-playbook",
    }

    @pytest.mark.parametrize("query,expected", POSITIVE.items())
    def test_new_skills_are_reachable(self, query, expected):
        from trade.skill_router import match_skills

        hits = [h["skill_name"] for h in match_skills(query)]
        assert hits and hits[0] == expected, f"{query} 命中 {hits}，期望 {expected}"

    @pytest.mark.parametrize("query,expected", BOUNDARY.items())
    def test_existing_routes_keep_priority(self, query, expected):
        from trade.skill_router import match_skills

        hits = [h["skill_name"] for h in match_skills(query)]
        assert hits and hits[0] == expected, f"{query} 被抢走：{hits}"


class TestGuardrails:
    """三个技能都必须把「不编造 / 不越权承诺」写进生效的注入文本。"""

    def test_no_fabrication_and_no_unauthorized_promise(self):
        for name in SKILL_DIRS:
            prompt = _frontmatter(name)["injection_prompt"]
            assert ("不编造" in prompt or "不虚构" in prompt), f"{name} 缺反编造红线"
            assert ("授权" in prompt or "确认" in prompt), f"{name} 缺授权/确认要求"

    def test_quote_skill_forbids_fake_approval(self):
        prompt = _frontmatter("b2b-quote-negotiation")["injection_prompt"]
        assert "经理特批" in prompt and "不虚构" in prompt

    def test_closing_skill_forbids_private_commission(self):
        prompt = _frontmatter("b2b-closing-pi")["injection_prompt"]
        assert "回扣" in prompt and "双渠道" in prompt

    def test_source_and_verification_declared(self):
        """培训课程整理的方法必须标注来源与未验证状态，不能写成已验证结论。"""
        for name in SKILL_DIRS:
            text = (SKILL_DIRS[name] / "SKILL.md").read_text(encoding="utf-8")
            assert "来源" in text and "未经" in text and "实战验证" in text

    def test_quote_ladder_is_owner_confirmed(self):
        prompt = _frontmatter("b2b-quote-negotiation")["injection_prompt"]
        assert "5% → 3% → 1%" in prompt
        assert "负责人确认" in prompt

    def test_closing_red_lines_are_owner_confirmed(self):
        prompt = _frontmatter("b2b-closing-pi")["injection_prompt"]
        assert "负责人确认" in prompt and "硬红线" in prompt
