"""
Trade AI Assistant — REST API Router。

组装所有子路由模块，对外暴露统一的 router。
所有路由默认受 session token 保护。
server.py 通过 ``from trade.api import router`` 挂载到 /api/trade。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from trade.api.chat import router as chat_router
from trade.api.companies import router as companies_router
from trade.api.conversations import router as conversations_router
from trade.api.copilot import router as copilot_router
from trade.api.cron import router as cron_router
from trade.api.customers import router as customers_router
from trade.api.deps import opt_company, require_company, require_session
from trade.api.libraries import router as libraries_router
from trade.api.memory import router as memory_router
from trade.api.onboarding import router as onboarding_router
from trade.api.orders import router as orders_router
from trade.api.templates import router as templates_router


def _enforce_company_binding(
    request: Request,
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
) -> None:
    """session 级活跃公司绑定：防止修改 header 跨公司越权。

    作为全局 trade router 的依赖，在每个业务请求前自动执行。
    首次携带 company_id 的请求自动绑定 session 到该公司；
    后续请求必须携带匹配的 company_id。
    """
    from trade.api.deps import _ACTIVE_COMPANY, _company_bind_lock

    token = request.headers.get("X-Hermes-Session-Token", "")
    if not token:
        return  # 无 session token 不检查

    if not x_company_id or not x_company_id.strip():
        return  # 无 company_id 不检查（由 require_company 端点自行处理）

    try:
        cid = int(x_company_id.strip())
    except ValueError:
        return  # 无效 ID 由 require_company 处理

    # switch 端点允许携带不同于当前绑定的 company_id（因为它的语义就是切换）
    if "/switch" in request.url.path:
        return

    with _company_bind_lock:
        bound = _ACTIVE_COMPANY.get(token)
        if bound is not None and cid != bound:
            raise HTTPException(
                status_code=403,
                detail=f"X-Company-ID {cid} does not match active session. "
                       f"Use POST /api/trade/companies/{cid}/switch to switch.",
            )
        if bound is None:
            _ACTIVE_COMPANY[token] = cid


# 所有 /api/trade/* 路由默认要求 session token + 公司绑定
router = APIRouter(
    tags=["trade"],
    dependencies=[Depends(require_session), Depends(_enforce_company_binding)],
)

# 按业务域挂载子路由
router.include_router(companies_router)
router.include_router(onboarding_router)
router.include_router(orders_router)
router.include_router(libraries_router)
router.include_router(customers_router)
router.include_router(conversations_router)
router.include_router(chat_router)
router.include_router(memory_router)
router.include_router(cron_router)
router.include_router(templates_router)
router.include_router(copilot_router)

# 便捷导出
__all__ = [
    "router",
    "require_company",
    "opt_company",
    "require_session",
]
