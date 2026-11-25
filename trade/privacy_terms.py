"""家庭/私密称谓的唯一词表（W13 / S4）。

后端（profile / memo / partial_report / visit_plan / exporter）共用；
前端通过 `GET /api/trade/profile/privacy-terms` 取同一份。

原则：宁可多滤。分类由用户/模型决定，不可靠；只要内容里出现称谓，
即使写在「重要日期/喜好」里也不能进打印、长图、导出、AI 上下文和未完成报告。

S4（2026-11-24）：补全中/英/法/葡/西/日称谓；把 `partner / brother /
son / family` 这类日常词改成「所属语境才算」（my partner / John's son /
我们的 partner），避免「Brother Industries」「family business」被误伤。
"""

from __future__ import annotations

import re
from typing import Any

# 中文亲属称谓（子串匹配，含单字复合词）
FAMILY_TERMS_CJK = (
    # 伴侣。「先生/夫人」同时是泛称（王先生/王夫人），不能裸子串匹配，
    # 由 _SPOUSE_TITLE_RE 按所属语境识别（O-新5 / O-新21）。
    "太太", "妻子", "老婆", "爱人", "丈夫", "老公", "配偶",
    "男朋友", "女朋友", "未婚夫", "未婚妻",
    # 子女与孙辈
    "儿子", "女儿", "孩子", "宝宝", "小孩", "孙子", "孙女", "孙辈",
    # 父母与祖辈
    "父母", "爸爸", "妈妈", "父亲", "母亲", "岳父", "岳母", "公公", "婆婆",
    "奶奶", "爷爷", "外公", "外婆",
    # 兄弟姐妹与姻亲
    "兄弟", "姐妹", "哥哥", "弟弟", "姐姐", "妹妹",
    "女婿", "儿媳", "媳妇",
    # 晚辈与旁系
    "侄子", "侄女", "外甥", "外甥女",
    "叔叔", "阿姨", "舅舅", "姑姑",
    # 日文（一般用法，不含需要语境判断的「夫 / 娘」）
    "妻", "奥さん", "息子",
    # 泛称
    "家人", "家属",
)

# 中文里需要语境判断的单字：「夫」（工夫/功夫）与「娘」（姑娘/老板娘）
# 只有日语助词/所属语境或「夫妻/前夫」这类组合才算家庭信息。
FAMILY_TERMS_CJK_CONTEXT = ("夫", "娘")

# 英文/西欧语（按词边界匹配，避免 person/reason 里的 son）
FAMILY_TERMS_EN = (
    "spouse", "kid", "kids", "child", "children",
    "wife", "husband", "daughter", "father", "mother", "sister",
    "mom", "mum", "dad",
    "grandson", "granddaughter", "grandmother", "grandfather",
    "girlfriend", "boyfriend", "fiancé", "fiancée", "fiance", "fiancee",
    "niece", "nephew",
    "in-law", "in-laws", "in law",
)

# 法语 / 葡语 / 西语 / 德 / 俄
FAMILY_TERMS_OTHER = (
    "esposa", "esposo", "hijo", "hija",
    "frau", "sohn", "tochter",
    "жена", "муж", "сын", "дочь",
    "femme", "mari", "fils", "fille",
    "filho", "filha", "mujer", "marido",
)

# 日常英文词：只有所属/人称所有格语境才算（S4）
FAMILY_TERMS_EN_CONTEXT = ("partner", "brother", "son", "family")

# 客户索要/礼物：不进未完成报告的工具结果预览
GIFT_TERMS_CJK = ("客户索要", "索要", "礼物")

_FAMILY_LATIN_RE = re.compile(
    r"\b(?:" + "|".join(
        re.escape(term) for term in (*FAMILY_TERMS_EN, *FAMILY_TERMS_OTHER)
    ) + r")\b",
    re.IGNORECASE,
)

# 「my partner」「John's son」「我的 partner」——只有这种所属语境才算。
# 「我们的 partner 工厂 / our partner factory」是商业合作方，不能当家庭信息（S4 验收）。
_CONTEXT_EN_RE = re.compile(
    r"(?:\b(?:my|his|her|their|our|your)\s+partner\b"
    r"(?!\s+(?:factory|company|firm|plant|supplier))"
    # O-新27：「our son company」（子公司直译）/「our brother company」
    # 是商业实体，不是家庭成员；family 不加此排除（family business 仍是家事）。
    r"|\b(?:my|his|her|their|our|your)\s+(?:brother|son)\b"
    r"(?!\s+(?:company|firm|business|factory|plant|subsidiary|brand))"
    r"|\b(?:my|his|her|their|our|your)\s+family\b"
    r"|[A-Za-z]+(?:'s|’s)\s+(?:partner|brother|son|family)\b"
    r"|的\s*partner\b"
    r"(?!\s*(?:工厂|公司|企业|集团|供应商|客户|经销商|渠道|厂家))"
    r"|的\s*(?:brother|son|family)\b)",
    re.IGNORECASE,
)

# O-新5 / O-新21：「先生/夫人」只有出现在所属语境（我先生/我的夫人/和夫人/
# 行首/标点后）才按家庭称谓处理；「王先生是采购经理」是正常称呼，不能滤掉。
_SPOUSE_TITLE_RE = re.compile(
    r"(?:^|[我他她的\s：:，,。；;、和与跟陪])(?:先生|夫人)"
)

# S4：「夫 / 娘」在日语助词或所属语境下才算；避免 工夫/功夫/姑娘/老板娘 误伤。
_CJK_KIN_CONTEXT_RE = re.compile(
    r"(?:^|[私僕俺彼女我他她前的和与跟陪])\s*(?:夫|娘)"
    r"(?=$|[はがをにものでもさんですだ妻女\s，。、,\.：:])"
)


def contains_family_terms(text: Any) -> bool:
    """内容里是否出现家庭成员称谓（宁可多滤，不把家庭信息带出去）。"""
    value = str(text or "")
    if any(term in value for term in FAMILY_TERMS_CJK):
        return True
    if _SPOUSE_TITLE_RE.search(value):
        return True
    if _CJK_KIN_CONTEXT_RE.search(value):
        return True
    if _FAMILY_LATIN_RE.search(value):
        return True
    return bool(_CONTEXT_EN_RE.search(value))


def family_terms_payload() -> dict:
    """给前端的同一份词表（cjk 子串匹配，latin 走词边界正则）。"""
    return {
        "cjk": list(FAMILY_TERMS_CJK),
        "cjk_context": list(FAMILY_TERMS_CJK_CONTEXT),
        "latin": list(FAMILY_TERMS_EN + FAMILY_TERMS_OTHER),
        "context_latin": list(FAMILY_TERMS_EN_CONTEXT),
        "gift": list(GIFT_TERMS_CJK),
    }
