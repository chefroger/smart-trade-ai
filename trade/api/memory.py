"""
Trade AI Assistant — 记忆与模型 API 路由。

端点：
  GET /memory/status         — Hindsight 长期记忆可用性
  GET /memory/recall         — 搜索长期记忆
  GET /models/providers      — 已配置的 LLM 提供商列表
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from trade import chat_memory
from trade.api.deps import opt_company

router = APIRouter(tags=["memory"])


# ── Hindsight 长期记忆 ────────────────────────────────────────────────────

@router.get("/memory/status")
def memory_status(cid: int | None = Depends(opt_company)):
    """检查 Hindsight 长期记忆是否可用。"""
    try:
        from trade.memory import is_available as hindsight_available
        return {
            "hindsight_available": hindsight_available(),
            "company_id": cid,
        }
    except ImportError:
        return {"hindsight_available": False, "company_id": None}


@router.get("/memory/recall")
def memory_recall(
    query: str,
    cid: int | None = Depends(opt_company),
):
    """搜索当前公司的长期记忆。使用公司专属 bank，确保数据隔离。"""
    if cid is None:
        return {"results": [], "query": query, "company_id": None,
                "hint": "请提供 X-Company-ID header 以按公司搜索记忆"}
    from trade.memory import _bank_id
    result = chat_memory.recall_context(query, bank_id=_bank_id(cid))
    if not result:
        return {"results": [], "query": query, "company_id": cid}
    return {"results": [result], "query": query, "company_id": cid}


# ── helpers ─────────────────────────────────────────────────────────────────

# _parse_model_string 已删除，统一使用 trade.helpers._parse_model_config_str


# ── LLM 提供商 ────────────────────────────────────────────────────────────

@router.get("/models/providers")
def list_providers():
    """列出已配置的 LLM 提供商及其可用模型。

    从 ~/.hermes/config.yaml 和 PROVIDER_REGISTRY 读取，
    返回每个提供商的模型列表、API Key 配置状态。
    """
    try:
        from trade.hermes_compat import current_model_config, list_provider_records

        active_provider, active_model = current_model_config()
        providers = []
        for record in list_provider_records():
            pid = record["id"]
            providers.append({
                **record,
                "is_active": pid == active_provider,
                "active_model": active_model if pid == active_provider else "",
            })

        return {
            "providers": providers,
            "active_provider": active_provider,
            "active_model": active_model,
        }
    except Exception as e:
        return {"providers": [], "error": str(e)}
