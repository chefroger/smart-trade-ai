"""家庭/私密称谓的唯一词表（W13）。

后端（profile / memo / partial_report / visit_plan / exporter）共用；
前端通过 `GET /api/trade/profile/privacy-terms` 取同一份。

原则：宁可多滤。分类由用户/模型决定，不可靠；只要内容里出现称谓，
即使写在「重要日期/喜好」里也不能进打印、长图、导出、AI 上下文和未完成报告。
"""

from __future__ import annotations

import re
from typing import Any

# 中文亲属称谓（子串匹配，含单字复合词）
FAMILY_TERMS_CJK = (
    # 伴侣（先生/夫人 也用于泛称，按审计要求从严过滤）
    "太太", "妻子", "老婆", "夫人", "爱人", "先生", "丈夫", "老公", "配偶",
    # 子女与孙辈
    "儿子", "女儿", "孩子", "宝宝", "小孩", "孙子", "孙女", "孙辈",
    # 父母与姻亲
    "父母", "爸爸", "妈妈", "父亲", "母亲", "岳父", "岳母", "公公", "婆婆",
    # 兄弟姐妹
    "兄弟", "姐妹", "哥哥", "弟弟", "姐姐", "妹妹",
    # 泛称
    "家人", "家属",
)

# 英文（按词边界匹配，避免 person/reason 里的 son）
FAMILY_TERMS_EN = (
    "spouse", "partner", "kid", "kids", "child", "children",
    "wife", "husband", "son", "daughter", "father", "mother",
    "brother", "sister", "family",
)

# 常见外语（西/德/俄）
FAMILY_TERMS_OTHER = (
    "esposa", "esposo", "hijo", "hija",
    "frau", "sohn", "tochter",
    "жена", "муж", "сын", "дочь",
)

# 客户索要/礼物：不进未完成报告的工具结果预览
GIFT_TERMS_CJK = ("客户索要", "索要", "礼物")

_FAMILY_LATIN_RE = re.compile(
    r"\b(?:" + "|".join(
        re.escape(term) for term in (*FAMILY_TERMS_EN, *FAMILY_TERMS_OTHER)
    ) + r")\b",
    re.IGNORECASE,
)


def contains_family_terms(text: Any) -> bool:
    """内容里是否出现家庭成员称谓（宁可多滤，不把家庭信息带出去）。"""
    value = str(text or "")
    if any(term in value for term in FAMILY_TERMS_CJK):
        return True
    return bool(_FAMILY_LATIN_RE.search(value))


def family_terms_payload() -> dict:
    """给前端的同一份词表（cjk 子串匹配，latin 走词边界正则）。"""
    return {
        "cjk": list(FAMILY_TERMS_CJK),
        "latin": list(FAMILY_TERMS_EN + FAMILY_TERMS_OTHER),
        "gift": list(GIFT_TERMS_CJK),
    }
