"""context —— 客户匹配 + 上下文组装（平台无关）。

## 铁律 4：客户匹配宁缺毋滥

对方名称与客户库的模糊匹配**低于阈值就按新客户处理**，禁止把任何既有客户的
历史上下文带进草稿。理由：把 A 客户的价格/需求说给 B 客户，是真实的业务事故
（不只是"串味"）—— 报价、MOQ、认证要求都可能对不上。

阈值取 0.62（`MATCH_THRESHOLD`）：向量/关键词检索的分数是 1/(1+distance)，
**无关向量的恒定正交基线是 0.4142** —— 阈值必须显著高于它，否则任何名字都能
"匹配"到某个客户。

## 检索用哪条路

- 客户：沿用 `trade.vec_search.search_customers`（按 company_id 过滤，向量优先、
  无向量时自动降级关键词）
- 客户历史：沿用 `trade.chat_memory.search_history`（同一公司归属口径）
- 产品库：沿用 `trade.library` 的既有读取路径
"""

from __future__ import annotations

import logging
from typing import Any

from trade.copilot.types import CustomerContext, SourceRef

_log = logging.getLogger(__name__)

# 客户匹配阈值（高于向量检索的正交基线 0.4142，低于它等于不过滤）
MATCH_THRESHOLD = 0.62

# 低于这个分数即便有候选也按新客户处理（多候选时的保守侧）
AMBIGUOUS_MARGIN = 0.05


def _normalize_name(name: str) -> str:
    """名字归一：去空白与常见分隔符，小写。

    聊天软件里的称呼常常带空格/点/破折号（"John Smith" / "john.smith" /
    "John-Smith"），归一后再比能显著提高命中率。
    """
    if not name:
        return ""
    text = name.strip().lower()
    for ch in (" ", "\t", ".", "_", "-", "·", "，", ","):
        text = text.replace(ch, "")
    return text


def _exact_name_hit(contact: str, customers: list[dict]) -> dict | None:
    """归一后完全相同 → 直接命中（不依赖向量分数，最可靠）。"""
    target = _normalize_name(contact)
    if not target:
        return None
    for cust in customers:
        if _normalize_name(str(cust.get("name") or "")) == target:
            return cust
    return None


def match_customer(
    contact: str,
    *,
    company_id: int,
    threshold: float = MATCH_THRESHOLD,
) -> CustomerContext:
    """在**当前公司**的客户库里匹配对方名称。

    Args:
        contact: 抽取到的对方名称/昵称。
        company_id: 当前公司（严格作用域，跨公司绝不查）。
        threshold: 匹配阈值。

    Returns:
        CustomerContext。未命中时 `matched=False` + `new_contact=True`，
        **不带任何历史**。
    """
    if not company_id or company_id <= 0:
        return CustomerContext(new_contact=True)

    name = (contact or "").strip()
    if not name:
        return CustomerContext(new_contact=True)

    customers = _list_company_customers(company_id)
    if not customers:
        return CustomerContext(new_contact=True)

    # ① 归一后完全相同 → 命中
    exact = _exact_name_hit(name, customers)
    if exact is not None:
        return CustomerContext(
            customer_id=int(exact.get("id") or 0),
            customer_name=str(exact.get("name") or name),
            matched=True,
            new_contact=False,
            match_score=1.0,
        )

    # ② 模糊检索（向量优先，无向量时降级关键词）
    hits = _fuzzy_search(name, company_id)
    if not hits:
        return CustomerContext(new_contact=True)

    best = hits[0]
    score = float(best.get("score") or 0.0)
    if score < threshold:
        return CustomerContext(
            customer_name=name,
            new_contact=True,
            match_score=score,
        )

    # ③ 多候选且分数接近 → 宁缺毋滥，按新客户处理
    if len(hits) > 1:
        second = float(hits[1].get("score") or 0.0)
        if second >= score - AMBIGUOUS_MARGIN:
            return CustomerContext(
                customer_name=name,
                new_contact=True,
                match_score=score,
            )

    cust = _get_customer(best["customer_id"], company_id)
    if not cust:
        return CustomerContext(customer_name=name, new_contact=True, match_score=score)

    return CustomerContext(
        customer_id=int(cust.get("id") or 0),
        customer_name=str(cust.get("name") or name),
        matched=True,
        new_contact=False,
        match_score=score,
    )


def _list_company_customers(company_id: int) -> list[dict]:
    try:
        from trade import customer as customer_module

        return customer_module.list_by_company(company_id) or []
    except Exception as exc:
        _log.warning("副驾读取客户库失败：%s", exc)
        return []


def _fuzzy_search(query: str, company_id: int) -> list[dict]:
    try:
        from trade.database import get_connection
        from trade.vec_search import search_customers

        conn = get_connection()
        try:
            return search_customers(conn, query, company_id=company_id, top_k=5) or []
        finally:
            conn.close()
    except Exception as exc:
        _log.warning("副驾客户模糊检索失败：%s", exc)
        return []


def _get_customer(customer_id: int, company_id: int) -> dict | None:
    try:
        from trade import customer as customer_module

        return customer_module.get(int(customer_id), company_id=company_id)
    except Exception as exc:
        _log.warning("副驾读取客户档案失败：%s", exc)
        return None


def load_history(ctx: CustomerContext, *, company_id: int, limit: int = 10) -> list[str]:
    """取该客户近期对话要点（**仅命中客户**才有）。

    未命中 → 返回空列表（铁律 4：绝不把别家客户的历史带进来）。
    """
    if not ctx.matched or not ctx.customer_id:
        return []
    try:
        from trade import chat_memory

        rows = chat_memory.search_history(
            company_id=company_id, time_range="all", limit=limit
        )
    except Exception as exc:
        _log.warning("副驾读取客户历史失败：%s", exc)
        return []

    out: list[str] = []
    for row in rows or []:
        query = str(row.get("query") or "").strip()
        if not query:
            continue
        # search_history 不按客户过滤（conversations 表没有 customer_id 列），
        # 所以这里**只做粗筛**：命中客户名或客户 id 的对话才算数。
        # 宁可少给历史，也不给错的历史。
        blob = f"{query} {row.get('response') or ''}"
        if str(ctx.customer_name) in blob or str(ctx.customer_id) in blob:
            out.append(query[:200])
    return out


def load_product_entries(
    keywords: str, *, company_id: int, limit: int = 8
) -> tuple[list[dict[str, Any]], list[SourceRef]]:
    """检索产品库相关条目，并抽出可引用的数字出处。

    Returns:
        (条目列表, 出处列表)。出处里的每个 value 都必须能在产品条目里找到 ——
        铁律 3：草稿里的数字只能来自这里。
    """
    entries: list[dict[str, Any]] = []
    if not (keywords or "").strip():
        return entries, []

    try:
        from trade import library as library_module

        libs = library_module.list_by_company(company_id) or []
    except Exception as exc:
        _log.warning("副驾读取文档库失败：%s", exc)
        return entries, []

    for lib in libs[:limit]:
        name = str(lib.get("name") or "")
        root = str(lib.get("root_path") or "")
        if not name or not root:
            continue
        entries.append({
            "label": name,
            "root_path": root,
            "library_id": lib.get("id"),
        })
    return entries, []


def build_context(
    contact: str,
    *,
    company_id: int,
    product_keywords: str = "",
    threshold: float = MATCH_THRESHOLD,
    with_history: bool = True,
) -> CustomerContext:
    """完整组装上下文：匹配客户 → 取历史 → 检索产品库。

    命中既有客户时带历史；未命中时 `new_contact=True` 且**不带任何既有上下文**。
    """
    ctx = match_customer(contact, company_id=company_id, threshold=threshold)
    if with_history and ctx.matched:
        ctx.history = load_history(ctx, company_id=company_id)
    ctx.product_entries, ctx.facts = load_product_entries(
        product_keywords, company_id=company_id
    )
    return ctx
