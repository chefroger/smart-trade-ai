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


# ── S4 / O-新21：补词与减少误伤 ────────────────────────────────────────────

S4_BLOCK = [
    # 中文新增
    "奶奶生日 5 月 1 日",
    "爷爷喜欢下棋",
    "外公在上海",
    "外婆做饭好吃",
    "女婿负责报关",
    "儿媳在医院值班",
    "媳妇刚生完孩子",
    "侄子今年高考",
    "侄女在国外留学",
    "外甥周末来帮忙",
    "外甥女上初中",
    "叔叔是厂长",
    "阿姨喜欢兰花",
    "舅舅做物流",
    "姑姑在银行工作",
    "男朋友在工厂",
    "女朋友做设计",
    "未婚夫是德国人",
    "未婚妻负责财务",
    # 英文新增
    "mom called yesterday",
    "mum is visiting",
    "dad is retired",
    "his grandson is six",
    "her granddaughter is two",
    "grandmother lives with them",
    "grandfather was a sailor",
    "girlfriend is a doctor",
    "boyfriend works in sales",
    "fiancé is French",
    "fiancée is Spanish",
    "niece is eight",
    "nephew is at college",
    "my brother-in-law drives",
    # 法 / 葡 / 西
    "femme et enfants",
    "mari travaille ici",
    "fils aîné",
    "fille cadette",
    "filho mais velho",
    "filha mais nova",
    "mujer y hijos",
    "marido trabaja",
    # 日文
    "妻は会社員です",
    "奥さんが来ました",
    "夫は営業です",
    "娘が大学に行く",
    "息子は小学生",
    # O-新21：「和/与/跟/陪 + 夫人」
    "王先生和夫人一起来了",
    "和夫人一起来的王先生",
]

S4_PASS = [
    "合作伙伴 partner：ABC Trading",
    "Brother Industries 打印机报价",
    "S. C. Johnson & Son 询盘",
    "family business since 1980",
    "我们的 partner 工厂",
    "Son Heung-min 签名球衣",
    "王先生是采购经理",
    "王夫人是采购总监",
    # 单字「夫 / 娘」的常见误伤词
    "功夫不负有心人，客户很满意",
    "老板娘说下周到货",
    "姑娘负责前台",
    "新娘家在上海",
]


def test_s4_new_terms_are_blocked():
    for probe in S4_BLOCK:
        assert contains_family_terms(probe) is True, f"未拦截：{probe}"


def test_s4_false_positives_stay_passed():
    for text in S4_PASS:
        assert contains_family_terms(text) is False, f"误伤：{text}"


def test_context_dependent_english_terms():
    """partner/brother/son/family 只有所属语境才算（S4）。"""
    for text in (
        "my partner handles logistics",
        "his brother is the owner",
        "their family lives nearby",
        "John's son works at the plant",
        "他要求先见 X 的 partner",
        "我的 partner 在德国",
    ):
        assert contains_family_terms(text) is True, f"未拦截：{text}"
    for text in (
        "合作伙伴 partner：ABC Trading",
        "Brother Industries 打印机报价",
        "S. C. Johnson & Son 询盘",
        "family business since 1980",
        "Son Heung-min 签名球衣",
        # 「我们的 partner 工厂」是商业合作方，不是家庭成员（S4 验收）
        "我们的 partner 工厂",
        "our partner factory in Shenzhen",
    ):
        assert contains_family_terms(text) is False, f"误伤：{text}"


def test_o_new21_he_furen_is_household():
    """O-新21：「和夫人」是家庭信息，不再漏网。"""
    assert contains_family_terms("王先生和夫人一起来了") is True
    assert contains_family_terms("和夫人一起来的王先生") is True
    # N5 原有验收不变
    assert contains_family_terms("王先生是采购经理") is False
    assert contains_family_terms("王夫人是采购总监") is False


def test_payload_exposes_context_lists():
    payload = family_terms_payload()
    assert "partner" in payload["context_latin"]
    assert "夫" in payload["cjk_context"]
    assert "partner" not in payload["latin"]
    assert "夫" not in payload["cjk"]
