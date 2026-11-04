"""中英文自然说法的技能路由回归（2026-11-04）。

触发词精确命中的测试在 test_skill_router_logic.py；这里专门覆盖**用户真正会说的话**：
中英文、带修饰词、不同语序。发现的两类结构性限制用 xfail 标注，不假装已支持。
"""

from __future__ import annotations

import pytest

CASES = {
    # 中文
    "怎么回复询盘": "b2b-lead-generation",
    "客户嫌贵怎么办": "b2b-lead-generation",
    "客户压价怎么谈": "b2b-lead-generation",
    "客户拖着不下单": "b2b-sales-playbook",
    "客户已读不回怎么办": "b2b-sales-playbook",
    "检查这份PI": "b2b-doc-generation",
    "每天早上发简报": "b2b-daily-automation",
    "背调一下这家公司": "b2b-osint",
    "帮我找招标": "b2b-tender-info",
    "解压这些压缩包": "b2b-tender-archive",
    "查一下这个邮箱": "b2b-email-intel",
    # English
    "how should I reply to this inquiry": "b2b-lead-generation",
    "customer says our price is too high": "b2b-lead-generation",
    "customer is not responding after the quote": "b2b-sales-playbook",
    "check this proforma invoice": "b2b-doc-generation",
    "send me a daily brief every morning": "b2b-daily-automation",
    "run a due diligence on this company": "b2b-osint",
    "find customers in Germany": "b2b-lead-generation",
    "find public tenders for transformers": "b2b-tender-info",
    "unzip these archives": "b2b-tender-archive",
    "check this email address": "b2b-email-intel",
}

# 中文/英文在“找…客户”中间插入产品词时，关键词子串匹配无法覆盖。
# 需要正则触发词或语义兜底；在补齐前明确记为已知缺口。
KNOWN_GAPS = [
    "帮我找德国的阀门客户",
    "find valve customers in Germany",
]


@pytest.mark.parametrize("query,expected", CASES.items())
def test_natural_prompts_route_to_expected_skill(query, expected):
    from trade.skill_router import match_skills

    hits = [h["skill_name"] for h in match_skills(query)]
    assert hits and hits[0] == expected, f"{query!r} 命中 {hits}，期望 {expected}"


@pytest.mark.parametrize("query", KNOWN_GAPS)
@pytest.mark.xfail(
    reason="关键词子串路由不支持在“找客户”中间插入产品词；待正则触发词/语义兜底",
    strict=False,
)
def test_known_gap_product_word_inside_lead_phrase(query):
    from trade.skill_router import match_skills

    hits = [h["skill_name"] for h in match_skills(query)]
    assert hits and hits[0] == "b2b-lead-generation"
