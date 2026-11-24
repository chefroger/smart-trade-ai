"""W13：家庭/私密称谓词表唯一化与覆盖度。

19 条 probe = 上轮 11 条（伴侣/子女/父母）+ 新增 8 条（兄弟姐妹/姻亲/孙辈/泛称）；
另含英文、西/德/俄语称谓与「正常内容不误伤」的反例。
"""

from __future__ import annotations

from trade.privacy_terms import (
    FAMILY_TERMS_CJK,
    FAMILY_TERMS_EN,
    FAMILY_TERMS_OTHER,
    contains_family_terms,
    family_terms_payload,
)

# 19 条 probe（全部必须 BLOCK）
PROBES_19 = [
    # 上轮 11 条
    "太太下个月生日",
    "妻子喜欢红茶",
    "老婆的手机号已更新",
    "丈夫在银行工作",
    "老公负责工厂验货",
    "儿子在伦敦读书",
    "女儿明年考大学",
    "孩子今年 6 岁",
    "父母住在杭州",
    "爸爸喜欢钓鱼",
    "妈妈是家庭主妇",
    # 新增 8 条
    "弟弟负责采购",
    "哥哥在上海开公司",
    "姐姐下月结婚",
    "妹妹刚上大学",
    "岳父的生日是 5 月 1 日",
    "岳母喜欢兰花",
    "宝宝刚出生",
    "家属随行两人",
]


def test_nineteen_probes_are_blocked():
    for probe in PROBES_19:
        assert contains_family_terms(probe) is True, f"未拦截：{probe}"


def test_all_cjk_terms_are_detected():
    for term in FAMILY_TERMS_CJK:
        assert contains_family_terms(f"备注：{term}相关") is True


def test_all_latin_terms_are_detected():
    for term in (*FAMILY_TERMS_EN, *FAMILY_TERMS_OTHER):
        assert contains_family_terms(f"note: {term} birthday") is True, term


def test_normal_business_content_is_not_blocked():
    for text in (
        "报价单已发送，等待客户确认",
        "采购经理下周来访，安排参观车间",
        "The customer asked for a quotation",
        "person: acme.com / reason: sample",
    ):
        assert contains_family_terms(text) is False, text


def test_payload_has_all_categories():
    payload = family_terms_payload()
    assert "太太" in payload["cjk"]
    assert "spouse" in payload["latin"]
    assert "esposa" in payload["latin"]
    assert "客户索要" in payload["gift"]


def test_spouse_title_requires_possessive_context():
    """O-新5：「先生/夫人」只在所属语境才算家庭信息。"""
    assert contains_family_terms("王先生是采购经理") is False
    assert contains_family_terms("王夫人负责采购") is False
    assert contains_family_terms("我先生下月出差") is True
    assert contains_family_terms("我的夫人喜欢兰花") is True
    assert contains_family_terms("先生生日是 5 月 1 日") is True
