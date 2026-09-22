"""技能路由的自然语言回归测试。"""

import pytest


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("帮我查一下公司", "b2b-osint"),
        ("帮我查一下邮箱", "b2b-email-intel"),
        ("查一下公司的背景", "b2b-osint"),
        ("帮我写一封冷邮件", "b2b-cold-outreach"),
        ("write an outreach email", "b2b-cold-outreach"),
        ("Check whether this email is real", "b2b-email-intel"),
        ("Analyze this quotation document", "b2b-document"),
        ("Practice replying to a difficult inquiry", "b2b-inquiry-training"),
        ("分析这份报价单", "b2b-document"),
        ("分析一下买家画像", "b2b-buyer-persona"),
        ("设置每日简报", "b2b-daily-automation"),
        ("分析一个市场", "b2b-market-analysis"),
        ("做一个skill", "b2b-skill-generator"),
        ("帮我查客户资料", "b2b-customer-mgmt"),
        ("分析这家公司的市场", "b2b-market-analysis"),
        ("做一个商业提案", "b2b-guarantee-proposal"),
        ("buyer persona", "b2b-buyer-persona"),
        ("LinkedIn", "b2b-linkedin-marketing"),
        ("领英", "b2b-linkedin-marketing"),
        ("客户分析", "b2b-customer-intel"),
        ("客户跟进", "b2b-sales-pipeline"),
        ("市场调研", "b2b-market-analysis"),
        ("竞争对手分析", "b2b-market-analysis"),
        ("展会邀约", "b2b-exhibition"),
        ("follow-up email", "b2b-cold-outreach"),
        ("商业提案", "b2b-guarantee-proposal"),
        ("客户档案", "b2b-customer-mgmt"),
        ("customer profile", "b2b-customer-mgmt"),
        ("产品介绍", "b2b-product-description"),
        ("展会邀请", "b2b-exhibition"),
        ("市场调研", "b2b-market-analysis"),
        ("竞争对手分析", "b2b-market-analysis"),
        ("end to end lead generation", "auto-trade-customer-development"),
    ],
)
def test_natural_language_routes_to_specialized_skill(query, expected):
    """自然语言查询应命中最具体的业务技能，而不是泛技能或无匹配。"""
    from trade.skill_router import match_skill

    result = match_skill(query)

    assert result is not None
    assert result["name"] == expected


def test_specialized_outreach_beats_generic_lead_generation():
    """开发信写作应由专职冷 outreach 技能处理，而非客户开发总技能。"""
    from trade.skill_router import match_skill

    result = match_skill("写一封开发信给德国客户")

    assert result is not None
    assert result["name"] == "b2b-cold-outreach"


def test_alias_name_explicit_call_resolves_to_registered_skill():
    """显式使用注册表 alias 时，应解析到对应的实际 skill。"""
    from trade.skill_router import match_skill

    result = match_skill("用 memory")

    assert result is not None
    assert result["name"] == "chat-memory"


def test_alias_name_explicit_augmentation_uses_registered_skill():
    """通过 alias 显式注入时，也应加载对应 skill 的规则。"""
    from trade.skill_router import augment_query

    result = augment_query("查询上次讨论", skill_name="memory")

    assert "chat-memory" in result
    assert "SKILL AUGMENTATION" in result


def test_blocked_alias_does_not_resolve_to_another_skill():
    """被禁用的 auto-smtp-email alias 不能绕过封禁解析到自动开发流水线。"""
    from trade.skill_router import match_skill

    assert match_skill("用 auto-smtp-email") is None


def test_document_skill_does_not_include_generation_instructions():
    """文档分析 skill 不应包含与其职责冲突的文档生成指令。"""
    from pathlib import Path

    text = Path("skills/b2b-document/SKILL.md").read_text(encoding="utf-8")

    assert "## Document Generation" not in text
    assert "When the user asks you to create a business document" not in text


def test_qa_cache_reloads_when_reference_file_changes(monkeypatch, tmp_path):
    """QA 文件更新后，mtime 缓存不能继续返回旧内容。"""
    import os
    import time

    import trade.skill_router as router

    skill_dir = tmp_path / "skill"
    qa_path = skill_dir / "references" / "qa_pairs.md"
    qa_path.parent.mkdir(parents=True)
    monkeypatch.setattr(router, "_get_skill_dir", lambda _name: skill_dir)
    router._QA_CACHE.clear()

    qa_path.write_text("## Q1: 旧问题？\n**答案**: 旧答案。\n", encoding="utf-8")
    first = router._load_qa_pairs("test-skill")
    assert first[0]["a"] == "旧答案。"

    qa_path.write_text("## Q1: 新问题？\n**答案**: 新答案。\n", encoding="utf-8")
    future = time.time() + 2
    os.utime(qa_path, (future, future))
    second = router._load_qa_pairs("test-skill")

    assert second[0]["a"] == "新答案。"
