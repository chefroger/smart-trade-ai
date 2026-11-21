"""制裁名单的名称归一化与 token 匹配（工单 P0-1）。

为什么单独成模块：多份名单（SDN/CSL/UN/EU/UK）的脏数据形态不同 ——
全大写、`LAST, First`、变音符号、`CIMEX, S.A.` 这类缩写都会让"看起来一样"
的名字匹配不上。统一在这里做，检查器只面对「归一化名 + token 集合」。
"""

from __future__ import annotations

import re
import unicodedata

# 标点/符号 → 空格（`\w` 保留字母、数字、下划线、CJK；下划线单独替换）
_PUNCT_RE = re.compile(r"[^\w\s]+|_+", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """归一化名称：NFKD 去变音 + 小写 + 标点转空格 + 压缩空白。

    "ABU TEIR, Mohammed" → "abu teir mohammed"
    "Müller GmbH"        → "muller gmbh"
    中文名（如 "华为技术有限公司"）原样保留（\\w 覆盖 CJK）。
    """
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = _PUNCT_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def tokens_of(normalized: str) -> tuple[str, ...]:
    """归一化名 → 排序后的 token 元组。

    连续的单字母 token 合并（"CIMEX, S.A." → cimex sa），避免缩写在 token 层
    被拆成 `s`、`a` 后与查询对不上；单个中间名首字母（"John F Kennedy"）保持原样。
    """
    raw = normalized.split() if normalized else []
    merged: list[str] = []
    run: list[str] = []
    for token in raw:
        if len(token) == 1 and token.isalpha():
            run.append(token)
            continue
        if run:
            merged.append("".join(run) if len(run) > 1 else run[0])
            run = []
        merged.append(token)
    if run:
        merged.append("".join(run) if len(run) > 1 else run[0])
    return tuple(sorted(set(merged)))


def token_key(tokens: tuple[str, ...]) -> str:
    """token 集合的规范化键（用于精确匹配索引）。"""
    return " ".join(tokens)


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    """两个 token 集合的 Jaccard 相似度。"""
    if not left or not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union)


# 拼写差异（缺字母/多字母）允许的最低相似度；低于它按"没匹配"处理。
FUZZY_THRESHOLD = 0.8
# 命中门槛：短名（< 8 字符）只接受精确匹配（沿用旧规则，防 "ABC" 误报）
SHORT_NAME_CHARS = 8
HIT_THRESHOLD = 0.75
