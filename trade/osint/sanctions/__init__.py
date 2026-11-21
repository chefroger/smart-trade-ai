"""制裁名单筛查（本地 SQLite 查询，工单 P0-1 重建）。

数据来源（全部官方公开渠道，后台每日刷新写入本地库）：
  - 美国 OFAC SDN 名单（SDN.CSV + ALT 别名 + ADD 地址/国家）
  - 美国 OFAC 非 SDN 名单（CONS_PRIM.CSV + ALT/ADD）
  - 美国综合筛查名单 CSL（data.trade.gov）
  - 联合国安理会制裁名单（consolidated.xml）
  - 欧盟制裁名单（fsf CSV，分号分隔）
  - 英国制裁名单（FCDO CSV）

**查询路径不下载任何东西**：`check_sanctions()` 只读本地库。名单由
`loader.start_background_refresh()` 在服务启动后每日刷新；从未成功下载过时
`coverage.degraded=True`，上层不得据此给出「无制裁记录」的结论。

匹配规则见 `store.search()`（精确 → 包含 → token 相似度；短名只接受精确）。
"""

from trade.osint.sanctions.loader import (
    get_cache,
    get_coverage,
    load_ofac_sanctions,
    load_un_sanctions,
    refresh_all,
    start_background_refresh,
)
from trade.osint.sanctions.store import search as _search

__all__ = [
    "check_sanctions",
    "get_cache",
    "get_coverage",
    "load_ofac_sanctions",
    "load_un_sanctions",
    "refresh_all",
    "start_background_refresh",
]


def check_sanctions(name: str, country: str | None = None) -> dict:
    """筛查制裁名单（本地库，OFAC / OFAC 非 SDN / CSL / UN / EU / UK）。

    匹配策略（按置信度降序）：
      1. token 集合完全一致（忽略大小写、标点、变音符号；
         "LAST, First" 与 "First Last" 视为同一）
      2. 一方是另一方的 token 子集 → score = 长度比 × 1.2（上限 0.95）
      3. token 集合 Jaccard ≥ 0.8（拼写差异）→ score = Jaccard × 0.9

    短查询（归一化后 < 8 字符）仅接受精确匹配，防止 "ABC" 误报大量无关实体。

    Args:
        name: 公司名或人名（支持中文和英文混合）
        country: 可选，目标国家代码（用于降低非相关国家命中权重）

    Returns:
        {
            "query": str,               # 原始查询名称
            "country": str | None,      # 传入的国家代码
            "hits": [                   # 匹配到的制裁信息（最多 20 条）
                {
                    "list": str,            # 名单代号 (OFAC/OFAC_NS/CSL/UN/EU/UK)
                    "list_label": str,      # 名单可读名称
                    "matched_field": str,   # exact_name/name_contains/name_contained_in_query/name_similar
                    "matched_value": str,   # 匹配到的实体名称
                    "score": float,         # 置信度 0.0-1.0
                    "country": str,         # 实体所在国家（有的名单不提供，为空）
                },
                ...
            ],
            "is_sanctioned": bool,      # True = 精确命中制裁名单
            "risk_level": str,          # "none" / "low" / "medium" / "high"
            "suggestion": str,          # 中文行动建议
            "coverage": dict,           # 数据源健康度（每份名单的 entries/fetched_at/degraded）
        }
    """
    hits = _search(name, country=country, limit=20)
    exact_match_found = any(hit["matched_field"] == "exact_name" for hit in hits)

    # ── 风险判定 ──────────────────────────────────────────────────────────
    if exact_match_found:
        risk_level = "high"
    elif len(hits) >= 3:
        risk_level = "medium"  # 多个模糊匹配，需人工核查
    elif hits:
        risk_level = "low"  # 极少数弱匹配
    else:
        risk_level = "none"

    # ── 数据源健康度 ──────────────────────────────────────────────────────
    coverage = get_coverage()

    # ── 行动建议 ──────────────────────────────────────────────────────────
    if exact_match_found:
        suggestion = "命中制裁名单（精确匹配），强烈建议拒绝交易或咨询法律部门。"
    elif risk_level == "medium":
        suggestion = "发现疑似匹配项，建议进一步人工核查，确认是否为同一家公司。"
    elif risk_level == "low":
        suggestion = "发现弱匹配（非精确），建议记录并持续观察。"
    elif coverage["degraded"]:
        # 关键分支：从未成功下载过名单时不得宣称「未发现匹配」。
        # 用户会拿这句结论去谈生意，必须让他知道这次筛查不是结论。
        missing = [
            info.get("label") or code
            for code, info in coverage["lists"].items()
            if info.get("degraded")
        ]
        suggestion = (
            "⚠️ 制裁名单尚未成功下载（" + "、".join(missing[:6]) + "），"
            "本次**不构成「无制裁记录」的结论**。请稍后重试，"
            "或通过官方渠道（OFAC/UN/EU/UK 官网）人工复核后再决策。"
        )
    else:
        suggestion = "未在任何制裁名单中发现匹配项。"

    return {
        "query": name,
        "country": country,
        "hits": hits[:20],  # 最多返回前 20 个命中，避免响应过大
        "is_sanctioned": exact_match_found,
        "risk_level": risk_level,
        "suggestion": suggestion,
        # 数据源健康度：让调用方（评分/报告）能区分「查过没有」与「没查成」
        "coverage": coverage,
    }
