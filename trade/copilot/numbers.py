"""numbers —— 副驾里"数字"的统一识别与归一（铁律 3 的底座）。

为什么单独成模块：draft 要用它**剔除**草稿里没有出处的数字，context 要用它把
产品库里的数字**抽成**可引用出处。两边必须是同一套规则，否则"库里写 USD 3.50、
草稿写 $3.50"会被误判成没有出处（或反过来漏掉假数字）—— 这正是复审里
「数字归一不对称」的修复。

归一后的 key 只有四类（比对只看 key，不看原始写法）：

    "$3.5"   金额 —— USD 3.50 / 3.50 USD / $3.50 / 50 dollars 全部归一
    "10%"    百分比 —— 10% / 10 percent
    "30d"    时间 —— 30 days / 30 天 / 三周
    "500"    数量、规格、裸数字 —— 500 pcs / 500 pieces / MOQ 500 / 33kV / 500

## 正则里两处容易踩的坑（都实测过）

1. **中文量词后面不能加 `\\b`**：Python 的 `\\w` 包含汉字，"30 天交期" 的
   天/交 之间没有词边界，加了 `\\b` 整条分支永远匹配不上。
2. **英文单位必须加 `\\b`**：否则 "5 apple" 会被当成 "5 A"（安培），
   替换时把 "apple" 切成 "（待确认）pple"。
"""

from __future__ import annotations

import re

# 货币代码 / 数字 / 中文数词
_CURRENCY_CODES = r"(?:USD|EUR|GBP|CNY|RMB|JPY|AUD|CAD|HKD|CHF)"
_NUM = r"\d[\d,]*(?:\.\d+)?"
_CN_NUMERALS = "一二两三四五六七八九十百千万零〇"

# 单条正则覆盖所有"带语义的数字"形态；顺序要紧 —— 带单位/货币的分支必须排在
# 裸数字前面，否则 "30 天" 里的 30 会先被裸数字吃掉、丢掉"天"这个语义。
NUMBER_RE = re.compile(
    # MOQ 500 / MOQ: 500
    rf"(?:\bMOQ\s*[:：]?\s*{_NUM})"
    # 货币前缀：USD 3.50 / $3.50 / ¥500
    rf"|(?:\b{_CURRENCY_CODES}\s?{_NUM})"
    rf"|(?:[$€£¥￥]\s?{_NUM})"
    # 货币后缀：3.50 USD / 50 dollars / 500 元
    rf"|(?:{_NUM}\s?(?:{_CURRENCY_CODES}|dollars?|yuan|元|块))"
    # 百分比：10% / 10 %
    rf"|(?:{_NUM}\s?%)"
    rf"|(?:{_NUM}\s?(?:percent|per\s?cent))"
    # 中文时间单位（不能加 \b，见模块 docstring）
    rf"|(?:{_NUM}\s?(?:个工作日|工作日|天|日|周|个月|年))"
    # 英文时间单位（必须加 \b）
    rf"|(?:{_NUM}\s?(?:days?|weeks?|months?))\b"
    # 数量 / 规格单位
    rf"|(?:{_NUM}\s?(?:pcs|pieces?|sets?|units?|cartons?|boxes?|containers?"
    rf"|tons?|tonnes?|kgs?|grams?|lbs?|mm|cm|km|meters?|metres?"
    rf"|kW|MW|kWh|kV|V|mA|Hz))\b"
    # 温度
    rf"|(?:{_NUM}\s?(?:°C|℃))"
    # 中文数词 + 量词：三天 / 五百个 / 两周
    rf"|(?:[{_CN_NUMERALS}]+\s?"
    rf"(?:个工作日|工作日|天|日|周|个月|年|个|件|套|台|箱|吨|公斤|元|块))"
    # 裸数字兜底：500 / 3.50
    rf"|(?:\b{_NUM}\b)",
    re.IGNORECASE,
)


def normalize_digits(digits: str) -> str:
    """数字归一：去千分位、去小数尾零（3.50 → 3.5，500 → 500）。"""
    text = (digits or "").replace(",", "")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def number_key(raw: str) -> str | None:
    """把一处数字写法归成可比较的 key（$3.5 / 10% / 30d / 500）。

    认不出数字（例如纯符号）→ None，调用方据此忽略该匹配。
    """
    text = (raw or "").strip()
    if not text:
        return None
    lowered = text.lower()

    digits = re.search(r"\d[\d,]*(?:\.\d+)?", text)
    if digits is not None:
        num = normalize_digits(digits.group(0))
    else:
        # 中文数词不做数值换算（五百 ≠ 500 会在比对时被当作不同数字 → 走
        # "（待确认）"的安全侧），但必须识别出来，否则中文数字会完全漏网。
        chinese = re.search(rf"[{_CN_NUMERALS}]+", text)
        if chinese is None:
            return None
        num = chinese.group(0)

    # 百分比
    if "%" in text or re.search(r"per\s?cent|percent", lowered):
        return f"{num}%"
    # 金额（代码 / 符号 / 单词 任一出现都算）
    if (
        re.search(r"[$€£¥￥]", text)
        # 子模式本身是大写，而 lowered 已小写 —— 必须显式 IGNORECASE，
        # 否则 "3.50 USD" 会漏掉金额归类（复审 P0 的形态之一）。
        or re.search(rf"\b{_CURRENCY_CODES}\b", text, re.IGNORECASE)
        or re.search(r"dollars?|yuan|元|块", lowered)
    ):
        return f"${num}"
    # 时间
    if re.search(r"个工作日|工作日|天|日|周|个月|年|days?\b|weeks?\b|months?\b", lowered):
        return f"{num}d"
    # 其余（数量/规格/裸数字）
    return num


def extract_numbers(text: str) -> set[str]:
    """抽出一段文本里所有数字的归一 key。"""
    if not text:
        return set()
    keys: set[str] = set()
    for match in NUMBER_RE.finditer(text):
        key = number_key(match.group(0))
        if key:
            keys.add(key)
    return keys
