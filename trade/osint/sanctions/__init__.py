"""
Trade AI Assistant — OSINT Layer 4: 制裁名单筛查。

筛查 OFAC / UN / EU 制裁名单，支持精确匹配和模糊匹配。
CSV 数据通过 loader 模块管理持久化缓存（~/.trade/cache/sanctions/）。

二模块结构：
  - __init__.py: check_sanctions() 匹配逻辑（本文件）
  - loader.py: OFAC/UN 下载 + 文件缓存 + fallback 数据
"""

from trade.osint.sanctions.loader import (
    get_cache,
    get_coverage,
    load_ofac_sanctions,
    load_un_sanctions,
)

__all__ = [
    "check_sanctions",
    "get_cache",
    "get_coverage",
    "load_ofac_sanctions",
    "load_un_sanctions",
]


def check_sanctions(name: str, country: str | None = None) -> dict:
    """筛查制裁名单（OFAC / UN / EU / UK / 中国）。

    匹配策略（按置信度降序）：
      1. 精确匹配（忽略大小写）→ score = 1.0
      2. 全大写精确匹配（制裁名单常用格式）→ score = 1.0
      3. 查询名是名单实体的子串 → score = 长度比 × 1.2（上限 0.95）
      4. 名单实体是查询名的子串 → score = 长度比 × 1.2（上限 0.95）

    短查询（< 8 字符）仅接受精确匹配，防止 "ABC" 误报大量无关实体。

    Args:
        name: 公司名或人名（支持中文和英文混合）
        country: 可选，目标国家代码（用于降低非相关国家命中权重）

    Returns:
        {
            "query": str,               # 原始查询名称
            "country": str | None,      # 传入的国家代码
            "hits": [                   # 匹配到的制裁信息（最多 20 条）
                {
                    "list": str,            # 名单代号 (OFAC/UN/EU)
                    "list_label": str,      # 名单可读名称
                    "matched_field": str,   # 匹配方式 (exact_name/exact_name_upper/name_contains/name_contained_in_query)
                    "matched_value": str,   # 匹配到的实体名称
                    "score": float,         # 置信度 0.0-1.0
                    "country": str,         # 实体所在国家
                },
                ...
            ],
            "is_sanctioned": bool,      # True = 精确命中制裁名单
            "risk_level": str,          # "none" / "low" / "medium" / "high"
            "suggestion": str,          # 中文行动建议
        }
    """
    # 输入标准化（小写用于不区分大小写匹配，大写用于全大写制裁名单匹配）
    name_normalized = name.strip().lower()
    name_upper = name.strip().upper()
    hits: list[dict] = []

    # 懒加载：首次访问制裁名单时才触发下载/缓存读取
    _cache = get_cache()

    if not _cache.get("OFAC"):
        load_ofac_sanctions()

    if not _cache.get("UN"):
        load_un_sanctions()

    # ── 多级匹配引擎 ──────────────────────────────────────────────────────
    exact_match_found = False

    for list_name, entries in _cache.items():
        for entry in entries:
            entry_name = entry.get("name", "").strip().lower()
            entry_name_upper = entry.get("name", "").strip().upper()

            if not entry_name:
                continue  # 跳过缺名称的异常条目

            score = 0.0
            matched_field = ""

            # 策略 1：精确匹配（忽略大小写）
            if name_normalized == entry_name:
                score = 1.0
                matched_field = "exact_name"
                exact_match_found = True

            # 策略 2：全大写精确匹配（制裁名单通常全大写发布）
            elif name_upper == entry_name_upper:
                score = 1.0
                matched_field = "exact_name_upper"
                exact_match_found = True

            # 策略 3：查询名是名单实体的子串（如 "GAZ" ⊂ "GAZPROM"）
            elif name_normalized in entry_name:
                ratio = len(name_normalized) / len(entry_name) if entry_name else 0
                score = min(ratio * 1.2, 0.95)
                matched_field = "name_contains"

            # 策略 4：名单实体是查询名的子串（如 "IRAN" ⊂ "IRANIAN COMPANY"）
            elif entry_name in name_normalized:
                ratio = len(entry_name) / len(name_normalized) if name_normalized else 0
                score = min(ratio * 1.2, 0.95)
                matched_field = "name_contained_in_query"

            # 短查询保护：< 8 字符的查询仅接受精确匹配，防止误报
            is_short = len(name_normalized) < 8
            threshold = 1.0 if is_short else 0.75

            if score >= threshold:
                hits.append(
                    {
                        "list": list_name,
                        "list_label": entry.get("label", list_name),
                        "matched_field": matched_field,
                        "matched_value": entry.get("name", ""),
                        "score": round(score, 3),
                        "country": entry.get("country", ""),
                    }
                )

    # ── 国家过滤（降权非相关国家命中） ────────────────────────────────────
    if country and hits:
        country_lower = country.lower()
        for hit in hits:
            hit_country = hit.get("country", "").lower()
            if (
                hit_country
                and country_lower not in hit_country
                and hit_country not in country_lower
            ):
                hit["score"] *= 0.5  # 同名实体但是不同国家，置信度减半

    # 按置信度降序排列
    hits.sort(key=lambda x: x["score"], reverse=True)

    # ── 风险判定 ──────────────────────────────────────────────────────────
    is_sanctioned = exact_match_found

    if is_sanctioned:
        risk_level = "high"
    elif len(hits) >= 3:
        risk_level = "medium"  # 多个模糊匹配，需人工核查
    elif hits:
        risk_level = "low"  # 极少数弱匹配
    else:
        risk_level = "none"

    # ── 数据源健康度 ──────────────────────────────────────────────────────
    # 拿不到真名单时（下载失败 → 2 条内置样本），"没查到"绝不等于"没问题"。
    coverage = get_coverage()

    # ── 行动建议 ──────────────────────────────────────────────────────────
    if is_sanctioned:
        suggestion = "命中制裁名单（精确匹配），强烈建议拒绝交易或咨询法律部门。"
    elif risk_level == "medium":
        suggestion = "发现疑似匹配项，建议进一步人工核查，确认是否为同一家公司。"
    elif risk_level == "low":
        suggestion = "发现弱匹配（非精确），建议记录并持续观察。"
    elif coverage["degraded"]:
        # 关键分支：数据源不可用时不得宣称"未发现匹配"。
        # 用户会拿这句结论去谈生意，必须让他知道这次筛查不是结论。
        suggestion = (
            f"⚠️ 制裁名单数据源不可用：本次仅比对了 {coverage['total_entries']} 条内置样本，"
            "**不构成「无制裁记录」的结论**。请通过官方渠道（OFAC/UN 官网）人工复核后再决策。"
        )
    else:
        suggestion = "未在任何制裁名单中发现匹配项。"

    return {
        "query": name,
        "country": country,
        "hits": hits[:20],  # 最多返回前 20 个命中，避免响应过大
        "is_sanctioned": is_sanctioned,
        "risk_level": risk_level,
        "suggestion": suggestion,
        # 数据源健康度：让调用方（评分/报告）能区分「查过没有」与「没查成」
        "coverage": coverage,
    }
