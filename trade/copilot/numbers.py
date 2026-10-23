"""numbers —— 副驾里"数字"的统一识别与归一（铁律 3 的底座）。

为什么单独成模块：draft 要用它**剔除**草稿里没有出处的数字，context 要用它把
产品库里的数字**抽成**可引用出处。两边必须是同一套规则，否则"库里写 USD 3.50、
草稿写 $3.50"会被误判成没有出处（或反过来漏掉假数字）。

归一后的 key 分五类（比对只看 key，不看原始写法）：

    "$3.5"    金额 —— USD 3.50 / 3.50 USD / $3.50 / 50 dollars
    "10%"     百分比 —— 10% / 10 percent
    "30d"     时间 —— 30 days / 30 天 / 两周 / 2 weeks（**统一换算成天**）
    "24v"     电气/照明规格 —— DC24V / 33kV / 40W / 3000K / 100lm
    "ip65"    IP 防护等级 —— IP65 / IP 65
    "500"     数量、裸数字 —— 500 pcs / MOQ 500 / 500个 / 五百

时间必须换算：只比 "2d" 会让库里的 "2 weeks" 给草稿的 "2 days" 背书 ——
交期被悄悄改短还带着出处。

## 正则里三处容易踩的坑（都实测过）

1. **中文量词后面不能加 `\\b`**：Python 的 `\\w` 包含汉字，"30 天交期" 的
   天/交 之间没有词边界，加了 `\\b` 整条分支永远匹配不上。
2. **英文单位必须加右边界**：否则 "5 apple" 会被当成 "5 A"（安培），
   替换时把 "apple" 切成 "（待确认）pple"。用 `(?![A-Za-z0-9])` 而不是 `\\b`，
   这样 "40W的灯" 也能命中（汉字不算英文字母）。
3. **货币后缀必须有左边界**：否则 "E27 USD 1.25" 会从 E27 的 "27" 开始匹配成
   幻影价格 "$27"，真价 1.25 反而降格成裸数字、对不上草稿里的 "$1.25"。
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# 货币代码 / 数字 / 中文数词
_CURRENCY_CODES = r"(?:USD|EUR|GBP|CNY|RMB|JPY|AUD|CAD|HKD|CHF)"
_NUM = r"\d[\d,]*(?:\.\d+)?"
_CN_NUMERALS = "一二两三四五六七八九十百千万零〇"

# 左/右边界只针对 ASCII 字母数字：汉字与数字相邻（"共500件"、"40W的灯"）
# 必须算边界，否则中文场景整片漏识别。
_ASCII_LEFT = r"(?<![A-Za-z0-9])"
_ASCII_RIGHT = r"(?![A-Za-z0-9])"

# 单条正则覆盖所有"带语义的数字"形态；顺序要紧 —— 带单位/货币的分支必须排在
# 裸数字前面，否则 "30 天" 里的 30 会先被裸数字吃掉、丢掉"天"这个语义。
NUMBER_RE = re.compile(
    # MOQ 500 / MOQ: 500
    rf"(?:{_ASCII_LEFT}MOQ\s*[:：]?\s*{_NUM})"
    # 货币前缀：USD 3.50 / $3.50 / ¥500
    rf"|(?:{_ASCII_LEFT}{_CURRENCY_CODES}\s?{_NUM})"
    rf"|(?:[$€£¥￥]\s?{_NUM})"
    # 货币后缀：3.50 USD / 50 dollars / 500 元
    # 左边界防止从型号中间开始（E27 USD → 幻影 $27）
    rf"|(?:{_ASCII_LEFT}{_NUM}\s?"
    rf"(?:{_CURRENCY_CODES}|dollars?|yuan|元|块))"
    # 百分比：10% / 10 %
    rf"|(?:{_NUM}\s?%)"
    rf"|(?:{_NUM}\s?(?:percent|per\s?cent))"
    # 电气/照明规格（字母与数字粘连）：DC24V / 40W / 3000K / IP65 / 100lm
    rf"|(?:{_ASCII_LEFT}(?:DC|AC)\s?{_NUM}\s?V{_ASCII_RIGHT})"
    rf"|(?:{_ASCII_LEFT}IP\s?{_NUM}{_ASCII_RIGHT})"
    rf"|(?:{_ASCII_LEFT}{_NUM}\s?W{_ASCII_RIGHT})"
    rf"|(?:{_ASCII_LEFT}{_NUM}\s?K{_ASCII_RIGHT})"
    rf"|(?:{_ASCII_LEFT}{_NUM}\s?lm{_ASCII_RIGHT})"
    # 中文时间单位（不能加 \b，见模块 docstring）
    rf"|(?:{_NUM}\s?(?:个工作日|工作日|天|日|周|个月|年))"
    # 英文时间单位
    rf"|(?:{_NUM}\s?(?:days?|weeks?|months?|years?){_ASCII_RIGHT})"
    # 数量 / 规格单位
    rf"|(?:{_NUM}\s?(?:pcs|pieces?|sets?|units?|cartons?|boxes?|containers?"
    rf"|tons?|tonnes?|kgs?|grams?|lbs?|mm|cm|km|meters?|metres?"
    rf"|kW|MW|kWh|kV|V|mA|Hz){_ASCII_RIGHT})"
    # 温度
    rf"|(?:{_NUM}\s?(?:°C|℃))"
    # 阿拉伯数字 + 中文量词：500个 / 200箱（时间量词已在上面处理）
    rf"|(?:{_NUM}\s?(?:个|件|套|台|箱|吨|公斤))"
    # 中文数词 + 量词：三天 / 五百个 / 两周
    rf"|(?:[{_CN_NUMERALS}]+\s?"
    rf"(?:个工作日|工作日|天|日|周|个月|年|个|件|套|台|箱|吨|公斤|元|块))"
    # 裸数字兜底：500 / 3.50 / 共500件
    rf"|(?:{_ASCII_LEFT}{_NUM}{_ASCII_RIGHT})",
    re.IGNORECASE,
)

# 规格单位的 key 后缀（必须与正则里的粘连分支保持一致）
_SPEC_UNITS = frozenset({"kwh", "kw", "kv", "mw", "ma", "hz", "v", "w", "lm", "k"})

_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}


def chinese_to_int(text: str) -> int | None:
    """把简单中文数词转成整数（五百 → 500，二十五 → 25）；认不出 → None。

    只处理个/十/百/千/万，够覆盖"三天""五百个""两千箱"这类量词场景；
    复杂写法（"半"、"三分之一"）返回 None，由调用方按原文保留（安全侧）。
    """
    if not text:
        return None
    total = 0
    section = 0
    number = 0
    for char in text:
        if char in _CN_DIGITS:
            number = _CN_DIGITS[char]
        elif char in _CN_UNITS:
            # "十二" 的十前面没有数字 → 按 1 算
            section += (number or 1) * _CN_UNITS[char]
            number = 0
        elif char == "万":
            section += number
            total += section * 10000
            section = 0
            number = 0
        else:
            return None
    return total + section + number


def normalize_digits(digits: str) -> str:
    """数字归一：去千分位、去小数尾零（3.50 → 3.5，500 → 500）。"""
    text = (digits or "").replace(",", "")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _scale_days(num: str, factor: int) -> str:
    """把数量换算成天（2 weeks → 14；1.5 months → 45）。"""
    if factor == 1:
        return num
    try:
        value = Decimal(num) * factor
    except (InvalidOperation, ValueError):
        return num
    if value == value.to_integral_value():
        return str(int(value))
    return format(value.normalize(), "f")


def _time_factor(text: str, lowered: str) -> int | None:
    """判断时间单位并给出换算成天的倍数；不是时间 → None。"""
    # 顺序：长单位在前，避免 "个工作日" 被裸 "日" 抢先（两者倍数都是 1，
    # 但 weeks/months/years 必须先于 days 判断）
    if re.search(rf"weeks?{_ASCII_RIGHT}", lowered) or "周" in text:
        return 7
    if re.search(rf"months?{_ASCII_RIGHT}", lowered) or "个月" in text:
        return 30
    if re.search(rf"years?{_ASCII_RIGHT}", lowered) or "年" in text:
        return 365
    if (
        re.search(rf"个工作日|工作日|days?{_ASCII_RIGHT}", lowered)
        or re.search(r"[天日]", text)
    ):
        return 1
    return None


def _trailing_unit(text: str) -> str | None:
    """取匹配串末尾的规格单位（40W → w，DC24V → v，33kV → kv）。"""
    match = re.search(r"([A-Za-z]+)\s*$", text)
    if match is None:
        return None
    unit = match.group(1).lower()
    return unit if unit in _SPEC_UNITS else None


def number_key(raw: str) -> str | None:
    """把一处数字写法归成可比较的 key（$3.5 / 10% / 30d / 24v / 500）。

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
        chinese = re.search(rf"[{_CN_NUMERALS}]+", text)
        if chinese is None:
            return None
        # 中文数词转成阿拉伯数字再比：五百 与 500 必须互认
        converted = chinese_to_int(chinese.group(0))
        num = str(converted) if converted is not None else chinese.group(0)

    # 百分比
    if "%" in text or re.search(r"per\s?cent|percent", lowered):
        return f"{num}%"
    # 金额（代码 / 符号 / 单词 任一出现都算）
    if (
        re.search(r"[$€£¥￥]", text)
        # 子模式本身是大写 —— 必须显式 IGNORECASE；右界只挡字母不挡数字，
        # 这样 "USD1.25"（无空格）也算金额。
        or re.search(
            rf"{_ASCII_LEFT}{_CURRENCY_CODES}(?![A-Za-z])",
            text, re.IGNORECASE,
        )
        or re.search(r"dollars?|yuan|元|块", lowered)
    ):
        return f"${num}"
    # 时间：统一换算成天
    factor = _time_factor(text, lowered)
    if factor is not None:
        return f"{_scale_days(num, factor)}d"
    # IP 防护等级单独成 key（IP65 不能给草稿里的 65 pcs 背书）
    ip = re.search(rf"{_ASCII_LEFT}IP\s?(\d[\d,]*)", text, re.IGNORECASE)
    if ip is not None:
        return "ip" + normalize_digits(ip.group(1))
    # 电气/照明规格：保留单位，避免 40W 与 40 pcs 互认
    unit = _trailing_unit(text)
    if unit is not None:
        return f"{num}{unit}"
    # 其余（数量/裸数字）
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
