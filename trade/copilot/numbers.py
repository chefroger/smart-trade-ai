"""numbers —— 副驾里"数字"的统一识别与归一（铁律 3 的底座）。

为什么单独成模块：draft 要用它**剔除**草稿里没有出处的数字，context 要用它把
产品库里的数字**抽成**可引用出处。两边必须是同一套规则，否则"库里写 USD 3.50、
草稿写 $3.50"会被误判成没有出处（或反过来漏掉假数字）。

归一后的 key 分五类（比对只看 key，不看原始写法）：

    "$3.5"     金额 —— USD 3.50 / 3.50 USD / $3.50 / 50 dollars
    "$2000"    简写金额 —— USD 2K / 2K USD / 2.5K USD（K=千 M=百万 B=十亿）
    "10%"      百分比 —— 10% / 10 percent
    "30d"      时间 —— 30 days / 30 天 / 两周 / 2 weeks（**统一换算成天**）
    "40kg"     计量单位 —— 40 kg / 40mm / 24V / 33kV（单位属于数字身份）
    "40"       计数 / 裸数字 —— 500 pcs / MOQ 500 / 500个 / 五百
    "ip65"     IP 等级；"s304" / "q235" / "dn50" / "pn16" 牌号

## 为什么计量单位必须留在 key 里

早先 "40 kg" 和 "40 pcs" 都是 key "40" —— 库里写 `Weight 40 kg`，草稿写
`MOQ 40 pcs` 会被判成"有出处"。单位是数字身份的一部分：质量、长度、电压、
功率之间绝不互相背书。计数单位（pcs/pieces/sets/…）归回裸数字，因为
"MOQ 500" 与 "500 pcs" 在报价里指的是同一件事。

## 正则里四处容易踩的坑（都实测过）

1. **中文量词后面不能加 `\\b`**：Python 的 `\\w` 包含汉字，"30 天交期" 的
   天/交 之间没有词边界，加了 `\\b` 整条分支永远匹配不上。
2. **英文单位必须加右边界**：否则 "5 apple" 会被当成 "5 A"（安培），
   替换时把 "apple" 切成 "（待确认）pple"。用 `(?![A-Za-z0-9])` 而不是 `\\b`，
   这样 "40W的灯" 也能命中（汉字不算英文字母）。
3. **货币后缀必须有左边界**：否则 "E27 USD 1.25" 会从 E27 的 "27" 开始匹配成
   幻影价格 "$27"，真价 1.25 反而降格成裸数字、对不上草稿里的 "$1.25"。
4. **数字后不能接 `.数字`**：`1.5M` 若回溯成 `1`，替换后留下残文 `.5M`。
   裸数字分支加 `(?!\\.\\d)`，宁可整段不识别，也不留半截数字。
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# 货币代码 / 数字 / 中文数词
_CURRENCY_CODES = r"(?:USD|EUR|GBP|CNY|RMB|JPY|AUD|CAD|HKD|CHF)"
_NUM = r"\d[\d,]*(?:\.\d+)?"
_CN_NUMERALS = "一二两三四五六七八九十百千万零〇"

# 金额简写后缀：2K = 2000，3M = 3000000，1B = 1000000000
_MAGNITUDE = r"[KMB]"
_MAGNITUDES = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}

# 中文量级（跟在阿拉伯数字后面）：5千 = 5000、10万 = 100000、5千元 = $5000
_CN_MAG_WORDS = r"(?:千万|百万|十万|千|万)"
_CN_MAGNITUDES = {
    "千": 1_000,
    "万": 10_000,
    "十万": 100_000,
    "百万": 1_000_000,
    "千万": 10_000_000,
}

# 左/右边界只针对 ASCII 字母数字：汉字与数字相邻（"共500件"、"40W的灯"）
# 必须算边界，否则中文场景整片漏识别。
_ASCII_LEFT = r"(?<![A-Za-z0-9])"
_ASCII_RIGHT = r"(?![A-Za-z0-9])"

# 单位词表只写一份：MOQ 分支与单位分支共用，避免"MOQ 40 pcs"只吃掉 "MOQ 40"
# 而把 " pcs" 留在草稿里。顺序要紧：长词在前（mm 先于 m），否则会被短词截断。
_UNIT_WORDS = (
    r"(?:pcs|pieces?|sets?|units?|cartons?|boxes?|containers?"
    r"|tons?|tonnes?|kgs?|grams?|lbs?|lb|mm|cm|km|meters?|metres?"
    # 体积单位：毫升必须排在升前面，否则 "500ml" 会被截成 "500m"
    r"|milliliters?|millilitres?|ml|liters?|litres?|l"
    # 单字母单位强制小写（(?-i:…) 抵消外层的 IGNORECASE）：
    # 品牌 "3M"、制式 "5G" 不能被当成 3 米 / 5 克
    r"|kW|MW|kWh|kV|V|mA|Hz|(?-i:m)|(?-i:g)|(?-i:t))"
)

# 中文单位词表：长词在前（公斤 先于 斤；千克 先于 克），否则会被短词截断。
# 计量单位必须与英文走同一个 key（公斤 = kg），否则中文草稿会和英文库脱钩，
# 同时又会和计数事实（40 pcs）撞成同一个裸数字（复审 P1）。
# 长词在前：千米/千瓦 必须先于 千（量级）与 米（长度）匹配。
_CN_MEASURE_WORDS = r"(?:公斤|千克|千米|千瓦|克|吨|斤|毫米|厘米|毫升|米|升)"
_CN_COUNT_WORDS = r"(?:个|件|套|台|箱)"
_CN_TIME_WORDS = r"(?:个工作日|工作日|天|日|周|个月|年)"

# 单条正则覆盖所有"带语义的数字"形态；顺序要紧 —— 带单位/货币的分支必须排在
# 裸数字前面，否则 "30 天" 里的 30 会先被裸数字吃掉、丢掉"天"这个语义。
NUMBER_RE = re.compile(
    # MOQ 500 / MOQ: 500 / MOQ 500 pcs（带单位时整段吃掉，不留 " pcs" 尾巴）
    rf"(?:{_ASCII_LEFT}MOQ\s*[:：]?\s*{_NUM}(?:\s?{_UNIT_WORDS}{_ASCII_RIGHT})?)"
    # 货币前缀：USD 3.50 / USD 2K / $3.50 / ¥500
    rf"|(?:{_ASCII_LEFT}{_CURRENCY_CODES}\s?{_NUM}(?:\s?{_MAGNITUDE}{_ASCII_RIGHT})?)"
    rf"|(?:[$€£¥￥]\s?{_NUM}(?:\s?{_MAGNITUDE}{_ASCII_RIGHT})?)"
    # 货币后缀：3.50 USD / 2K USD / 50 dollars / 500 元
    # 左边界防止从型号中间开始（E27 USD → 幻影 $27）
    rf"|(?:{_ASCII_LEFT}{_NUM}(?:\s?{_MAGNITUDE}{_ASCII_RIGHT})?\s?"
    rf"(?:{_CURRENCY_CODES}|dollars?|yuan|元|块))"
    # 百分比：10% / 10 %
    rf"|(?:{_NUM}\s?%)"
    rf"|(?:{_NUM}\s?(?:percent|per\s?cent))"
    # 电气/照明规格（字母与数字粘连）：DC24V / 40W / 3000K / 100lm
    rf"|(?:{_ASCII_LEFT}(?:DC|AC)\s?{_NUM}\s?V{_ASCII_RIGHT})"
    rf"|(?:{_ASCII_LEFT}IP\s?{_NUM}{_ASCII_RIGHT})"
    rf"|(?:{_ASCII_LEFT}{_NUM}\s?W{_ASCII_RIGHT})"
    rf"|(?:{_ASCII_LEFT}{_NUM}\s?K{_ASCII_RIGHT})"
    rf"|(?:{_ASCII_LEFT}{_NUM}\s?lm{_ASCII_RIGHT})"
    # 材质/管件牌号：S304 / Q235 / DN50 / PN16（字母前缀 + 数字后缀）
    # 数字位数收窄：Q3 是季度、不是牌号，不能被当成数字剔除。
    rf"|(?:{_ASCII_LEFT}(?:DN|PN)\s?\d{{1,4}}{_ASCII_RIGHT})"
    rf"|(?:{_ASCII_LEFT}[SQ]\d{{3,4}}{_ASCII_RIGHT})"
    # 中文时间单位（不能加 \b，见模块 docstring）
    rf"|(?:{_NUM}\s?{_CN_TIME_WORDS})"
    # 英文时间单位
    rf"|(?:{_NUM}\s?(?:days?|weeks?|months?|years?){_ASCII_RIGHT})"
    # 计量 / 计数单位
    rf"|(?:{_NUM}\s?{_UNIT_WORDS}{_ASCII_RIGHT})"
    # 温度
    rf"|(?:{_NUM}\s?(?:°C|℃))"
    # 阿拉伯数字 + 中文计量/计数单位：40 公斤 / 200 箱（时间量词已在上面处理）
    rf"|(?:{_NUM}\s?{_CN_MEASURE_WORDS})"
    rf"|(?:{_NUM}\s?{_CN_COUNT_WORDS})"
    # 阿拉伯数字 + 中文量级：5千 / 10万 / 5千元（必须排在中文数词分支前，
    # 否则 "千元" 会被当成中文数词 1000）
    rf"|(?:{_NUM}\s?{_CN_MAG_WORDS}(?:\s?(?:元|块|美元|美金))?)"
    # 中文数词 + 量词：三天 / 五百个 / 四十公斤
    rf"|(?:[{_CN_NUMERALS}]+\s?"
    rf"(?:{_CN_TIME_WORDS}|{_CN_MEASURE_WORDS}|{_CN_COUNT_WORDS}|元|块))"
    # 裸中文数词（带百/千/万）：五千 / 一万 / 十万 / 一万五
    # 没有量级的单字（一/三/十）在正文里太常见，不认；"万物"也不会命中。
    # 「千万」单独出现多是副词（千万不要），必须有 1-9 或 十/百 打头才算数词。
    rf"|(?<![{_CN_NUMERALS}])(?:"
    rf"[一二两三四五六七八九十百千]*[一二两三四五六七八九]"
    rf"[一二两三四五六七八九十百千]*万[一二两三四五六七八九十零〇]*"
    rf"|[十百][十百]*万[一二两三四五六七八九十零〇]*"
    rf"|[一二两三四五六七八九十]+[百千][一二两三四五六七八九十零〇]*"
    rf")(?![{_CN_NUMERALS}])"
    # 裸 M 简写（无币种）：1.5M = 1,500,000；"3M" 是品牌，不认（审计 P1-12）
    rf"|(?:{_ASCII_LEFT}(?!(?:3(?:\.0+)?)\s?(?-i:M){_ASCII_RIGHT})"
    rf"{_NUM}\s?(?-i:M){_ASCII_RIGHT})"
    # 裸数字兜底：500 / 3.50 / 共500件
    # (?!\.\d)：不许把 1.5M 回溯成 1 而留下 ".5M" 残文
    rf"|(?:{_ASCII_LEFT}{_NUM}(?!\.\d){_ASCII_RIGHT})",
    re.IGNORECASE,
)

# 计量单位 → 归一写法（保留在 key 里，防止跨维度背书）
_MEASURE_UNITS = {
    "kg": "kg", "kgs": "kg", "g": "g", "gram": "g", "grams": "g",
    "t": "t", "ton": "t", "tons": "t", "tonne": "t", "tonnes": "t",
    "lb": "lb", "lbs": "lb",
    "mm": "mm", "cm": "cm", "m": "m", "km": "km",
    "meter": "m", "meters": "m", "metre": "m", "metres": "m",
    "w": "w", "kw": "kw", "mw": "mw", "kwh": "kwh",
    "v": "v", "kv": "kv", "ma": "ma", "hz": "hz", "lm": "lm",
    # 体积：升 / 毫升
    "l": "l", "liter": "l", "liters": "l", "litre": "l", "litres": "l",
    "ml": "ml", "milliliter": "ml", "milliliters": "ml",
    "millilitre": "ml", "millilitres": "ml",
    # 色温：3000K 与 3000 不是同一个规格
    "k": "k",
}

# 单字母单位要求**小写**（正则里用 (?-i:…) 已保证，这里再兜一层，
# 防止将来有人改动正则时把大小写规则改回去）。
_CASE_SENSITIVE_UNITS = frozenset({"m", "g", "t"})

# 中文计量单位 → (英文单位, 换算倍数)。斤按 0.5 kg 换算：
# 库写 "40 kg" 必须能给草稿 "80 斤" 背书，反之亦然。
_CN_MEASURE_UNITS: dict[str, tuple[str, Decimal]] = {
    "公斤": ("kg", Decimal("1")),
    "千克": ("kg", Decimal("1")),
    "克": ("g", Decimal("1")),
    "吨": ("t", Decimal("1")),
    "斤": ("kg", Decimal("0.5")),
    "毫米": ("mm", Decimal("1")),
    "厘米": ("cm", Decimal("1")),
    "米": ("m", Decimal("1")),
    "千米": ("km", Decimal("1")),
    "千瓦": ("kw", Decimal("1")),
    "毫升": ("ml", Decimal("1")),
    "升": ("l", Decimal("1")),
}
# 计数单位：归回裸数字（"MOQ 500" 与 "500 pcs" 是同一件事）
_COUNT_UNITS = frozenset({
    "pcs", "piece", "pieces", "set", "sets", "unit", "units",
    "carton", "cartons", "box", "boxes", "container", "containers",
})

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
    saw_wan = False
    zero_after_wan = False
    for char in text:
        if char in _CN_DIGITS:
            if char in ("零", "〇") and saw_wan:
                zero_after_wan = True
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
            saw_wan = True
        else:
            return None
    # 口语简写："一万五" = 15000（万后单个数字默认带千位），"一万零五" = 10005
    if saw_wan and number and not zero_after_wan and section == 0:
        return total + number * 1000
    return total + section + number


def normalize_digits(digits: str) -> str:
    """数字归一：去千分位、去小数尾零（3.50 → 3.5，500 → 500）。"""
    text = (digits or "").replace(",", "")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _scale_value(num: str, factor: int | Decimal) -> str:
    """数字乘以倍数（2 × 1000 → 2000；80 斤 × 0.5 → 40）。"""
    factor_value = Decimal(str(factor))
    if factor_value == 1:
        return num
    try:
        value = Decimal(num) * factor_value
    except (InvalidOperation, ValueError):
        return num
    if value == value.to_integral_value():
        return str(int(value))
    return format(value.normalize(), "f")


def _time_factor(text: str, lowered: str) -> int | None:
    """判断时间单位并给出换算成天的倍数；不是时间 → None。"""
    # 年份不是时长："2025年交货" 里的 2025 不能被换算成 73 万天。
    # 只拦 1900–2099 的四位数字 + 年，避免误伤 "30年质保"。
    year = re.fullmatch(r"(\d{4})\s*年", text.strip())
    if year is not None and 1900 <= int(year.group(1)) <= 2099:
        return None
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


def _cn_magnitude_factor(text: str) -> int:
    """中文量级倍数（5千 → 1000，10万 → 10000）；没有量级 → 1。"""
    match = re.search(rf"({_CN_MAG_WORDS})", text)
    return _CN_MAGNITUDES.get(match.group(1), 1) if match else 1


def _trailing_unit(text: str) -> tuple[str | None, str]:
    """取匹配串末尾的英文单位词，返回 (小写单位, 原始写法)。"""
    match = re.search(r"([A-Za-z]+)\s*$", text)
    if match is None:
        return None, ""
    return match.group(1).lower(), match.group(1)


def _trailing_cn_unit(text: str) -> str | None:
    """取匹配串末尾的中文计量单位（长词优先，公斤 先于 斤）。"""
    match = re.search(
        r"(公斤|千克|千米|千瓦|克|吨|斤|毫米|厘米|毫升|米|升)\s*$", text
    )
    return match.group(1) if match else None


def number_key(raw: str) -> str | None:
    """把一处数字写法归成可比较的 key（$3.5 / $2000 / 30d / 40kg / 500）。

    认不出数字（例如纯符号）→ None，调用方据此忽略该匹配。
    """
    text = (raw or "").strip()
    if not text:
        return None
    lowered = text.lower()

    digits = re.search(r"\d[\d,]*(?:\.\d+)?", text)
    has_arabic = digits is not None
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
        or re.search(r"dollars?|yuan|美元|美金|元|块", lowered)
    ):
        # 简写金额换算：USD 2K → $2000（只在货币上下文里换算，
        # 避免把品牌 "3M" 或色温 "3000K" 当成数字）
        magnitude = re.search(
            rf"\d[\d,]*(?:\.\d+)?\s?({_MAGNITUDE}){_ASCII_RIGHT}", text, re.IGNORECASE
        )
        if magnitude:
            factor = _MAGNITUDES[magnitude.group(1).lower()]
        else:
            # 中文量级只对阿拉伯数字生效：一万五 已经由 chinese_to_int
            # 算成 15000，再乘一次 10000 会变成 1.5 亿
            factor = _cn_magnitude_factor(text) if has_arabic else 1
        return f"${_scale_value(num, factor)}"
    # 裸 M 简写（无币种）：1.5M = 1500000。必须在单位判断之前 ——
    # 否则 _trailing_unit 会把大写 M 当成品牌，只留下裸数字 "1.5"。
    bare_m = re.fullmatch(r"(\d[\d,]*(?:\.\d+)?)\s?M", text)
    if bare_m is not None:
        return _scale_value(normalize_digits(bare_m.group(1)), 1_000_000)
    # 时间：统一换算成天
    factor = _time_factor(text, lowered)
    if factor is not None:
        return f"{_scale_value(num, factor)}d"
    # IP 防护等级单独成 key（IP65 不能给草稿里的 65 pcs 背书）
    ip = re.search(rf"{_ASCII_LEFT}IP\s?(\d[\d,]*)", text, re.IGNORECASE)
    if ip is not None:
        return "ip" + normalize_digits(ip.group(1))
    # 材质/管件牌号：保留前缀，DN50 不能给 "50 pcs" 背书
    grade = re.search(
        rf"{_ASCII_LEFT}(DN|PN|S|Q)\s?{_NUM}{_ASCII_RIGHT}", text, re.IGNORECASE
    )
    if grade is not None:
        prefix = re.sub(r"\s+", "", grade.group(1)).lower()
        return f"{prefix}{num}"
    # 中文计量单位：与英文同 key（公斤 = kg；斤 × 0.5 换算成 kg）
    cn_unit = _trailing_cn_unit(text)
    if cn_unit is not None:
        normalized, factor = _CN_MEASURE_UNITS[cn_unit]
        return f"{_scale_value(num, factor)}{normalized}"
    # 单位：计量单位保留身份，计数单位归回裸数字
    unit, raw_unit = _trailing_unit(text)
    if unit is not None:
        # "3M"/"5G" 大写的单字母是品牌/制式，不是米/克
        if unit in _CASE_SENSITIVE_UNITS and raw_unit.isupper():
            return num
        if unit in _COUNT_UNITS:
            return num
        normalized = _MEASURE_UNITS.get(unit)
        if normalized is not None:
            return f"{num}{normalized}"
    # 其余（计数/裸数字）—— 中文量级只对阿拉伯数字展开：10万 → 100000
    factor = _cn_magnitude_factor(text) if has_arabic else 1
    return _scale_value(num, factor)


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
