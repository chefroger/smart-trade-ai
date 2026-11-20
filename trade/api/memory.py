"""
Trade AI Assistant — 记忆与模型 API 路由。

端点：
  GET /memory/status         — Hindsight 长期记忆可用性
  POST /memory/settings      — 长期记忆用户开关
  GET /memory/recall         — 搜索长期记忆
  GET /models/providers      — 已配置的 LLM 提供商列表
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from trade import chat_memory
from trade.api.deps import opt_company

router = APIRouter(tags=["memory"])


# ── Hindsight 长期记忆 ────────────────────────────────────────────────────

@router.get("/memory/status")
def memory_status(cid: int | None = Depends(opt_company), probe: bool = False):
    """检查 Hindsight 长期记忆状态。

    probe=true 时额外做一次网络探测（默认不做 —— 状态查询会被界面轮询，
    每次探 2 秒会拖慢界面）。
    """
    try:
        from trade.memory import health_check, is_available, is_enabled

        result = {
            "hindsight_available": is_available(),
            "hindsight_enabled": is_enabled(),
            "company_id": cid,
        }
        # 只有显式要求、且已开且可用时才探测
        if probe and result["hindsight_available"] and result["hindsight_enabled"]:
            result["hindsight_reachable"] = health_check()
        return result
    except ImportError:
        return {
            "hindsight_available": False,
            "hindsight_enabled": False,
            "company_id": None,
        }


class MemorySettingsBody(BaseModel):
    """长期记忆开关请求体。"""
    enabled: bool


@router.post("/memory/settings")
def update_memory_settings(body: MemorySettingsBody):
    """持久化长期记忆开关（默认开）。"""
    from trade.memory import set_enabled

    set_enabled(body.enabled)
    return {"hindsight_enabled": body.enabled}


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
