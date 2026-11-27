"""
Trade AI Assistant — 采购询价单 API 路由（供应商管理一期 · 第二批）。

端点：
  GET    /rfqs                          — 采购询价列表（status/customer_id/inquiry_id/q 筛选）
  POST   /rfqs                          — 新建采购询价单头
  GET    /rfqs/inquiries                — 本公司客户询盘下拉列表（静态路径先于 /{rfq_id}）
  GET    /rfqs/{rfq_id}                 — 采购询价详情（单头 + 全部回复行）
  PUT    /rfqs/{rfq_id}                 — 更新采购询价单头
  DELETE /rfqs/{rfq_id}                 — 删除采购询价单（级联删回复行与沉淀报价）
  POST   /rfqs/{rfq_id}/responses       — 将供应商加入本单（重复加入返回既有行）
  PUT    /rfq-responses/{rid}           — 录入/修改回复并按 §2.3 同步沉淀报价
  DELETE /rfq-responses/{rid}           — 删除回复行并清理沉淀报价
  POST   /rfq-responses/{rid}/select    — 选定该供应商（唯一选中，单头置 decided）
  POST   /rfq-responses/{rid}/unselect  — 取消选定（单头回 open）
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from trade import rfq as rfq_mod
from trade.api.deps import require_company

router = APIRouter(tags=["rfqs"])


# ==============================================================================
# Pydantic 请求模型
# ==============================================================================


class RfqCreateBody(BaseModel):
    product_name: str
    title: str = ""
    spec_model: str = ""
    quantity: Any = None
    unit: str = ""
    target_delivery_date: str = ""
    inquiry_id: Any = None
    customer_id: Any = None
    status: str = "open"
    note: str = ""
    extra1: Any = "{}"
    extra2: Any = "{}"
    extra3: Any = "{}"


class RfqUpdateBody(BaseModel):
    product_name: str | None = None
    title: str | None = None
    spec_model: str | None = None
    quantity: Any = None
    unit: str | None = None
    target_delivery_date: str | None = None
    inquiry_id: Any = None
    customer_id: Any = None
    status: str | None = None
    note: str | None = None
    extra1: Any = None
    extra2: Any = None
    extra3: Any = None


class RfqResponseAddBody(BaseModel):
    supplier_id: Any


class RfqResponseUpdateBody(BaseModel):
    responded: Any = None
    responded_at: str | None = None
    price_excl_tax: Any = None
    price_incl_tax: Any = None
    currency: str | None = None
    lead_time_days: Any = None
    lead_time_text: str | None = None
    moq: Any = None
    notes: str | None = None
    extra1: Any = None
    extra2: Any = None
    extra3: Any = None


# ==============================================================================
# 静态路径（必须注册在 /rfqs/{rfq_id} 之前）
# ==============================================================================


@router.get("/rfqs")
def list_rfqs_api(
    status: str = Query("", description="状态筛选：open / decided"),
    customer_id: int | None = Query(None, description="关联客户 ID"),
    inquiry_id: int | None = Query(None, description="关联询盘 ID"),
    q: str = Query("", description="产品名或主题模糊搜索"),
    cid: int = Depends(require_company),
):
    """列出当前公司的采购询价单。"""
    return rfq_mod.list_rfqs(
        cid,
        status=status,
        customer_id=customer_id,
        inquiry_id=inquiry_id,
        q=q,
    )


@router.post("/rfqs")
def create_rfq_api(
    body: RfqCreateBody,
    cid: int = Depends(require_company),
):
    """新建采购询价单头。"""
    try:
        return rfq_mod.create_rfq(cid, **body.model_dump())
    except rfq_mod.RfqError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/rfqs/inquiries")
def list_rfq_inquiries_api(
    cid: int = Depends(require_company),
):
    """列出当前公司的客户询盘（附客户名），供采购询价表单下拉选择。"""
    return rfq_mod.list_company_inquiries(cid)


# ==============================================================================
# 单头详情 / 修改 / 删除与加入供应商
# ==============================================================================


@router.get("/rfqs/{rfq_id}")
def get_rfq_api(
    rfq_id: int,
    cid: int = Depends(require_company),
):
    """获取采购询价单详情（单头 + 回复行）。"""
    detail = rfq_mod.get_rfq(rfq_id, cid)
    # 不存在或跨公司一律返回 404
    if not detail:
        raise HTTPException(status_code=404, detail="采购询价单不存在")
    return detail


@router.put("/rfqs/{rfq_id}")
def update_rfq_api(
    rfq_id: int,
    body: RfqUpdateBody,
    cid: int = Depends(require_company),
):
    """更新采购询价单头。"""
    fields = body.model_dump(exclude_unset=True)
    try:
        updated = rfq_mod.update_rfq(rfq_id, cid, **fields)
    except rfq_mod.RfqError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # 不存在或跨公司一律返回 404
    if not updated:
        raise HTTPException(status_code=404, detail="采购询价单不存在")
    return updated


@router.delete("/rfqs/{rfq_id}")
def delete_rfq_api(
    rfq_id: int,
    cid: int = Depends(require_company),
):
    """删除采购询价单（级联删回复行并清理沉淀报价）。"""
    # 不存在或跨公司一律返回 404
    if not rfq_mod.delete_rfq(rfq_id, cid):
        raise HTTPException(status_code=404, detail="采购询价单不存在")
    return {"ok": True}


@router.post("/rfqs/{rfq_id}/responses")
def add_rfq_response_api(
    rfq_id: int,
    body: RfqResponseAddBody,
    cid: int = Depends(require_company),
):
    """将一家供应商加入采购询价单；重复加入返回既有行。"""
    try:
        resp = rfq_mod.add_rfq_response(rfq_id, cid, body.supplier_id)
    except rfq_mod.RfqError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # 询价单不存在或跨公司返回 404
    if not resp:
        raise HTTPException(status_code=404, detail="采购询价单不存在")
    return resp


# ==============================================================================
# 回复行操作与选定
# ==============================================================================


@router.put("/rfq-responses/{rid}")
def update_rfq_response_api(
    rid: int,
    body: RfqResponseUpdateBody,
    cid: int = Depends(require_company),
):
    """录入/修改回复行，并按 §2.3 同步沉淀报价。"""
    fields = body.model_dump(exclude_unset=True)
    try:
        updated = rfq_mod.update_rfq_response(rid, cid, **fields)
    except rfq_mod.RfqError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # 不存在或跨公司返回 404
    if not updated:
        raise HTTPException(status_code=404, detail="询价回复行不存在")
    return updated


@router.delete("/rfq-responses/{rid}")
def delete_rfq_response_api(
    rid: int,
    cid: int = Depends(require_company),
):
    """删除回复行并清理其沉淀报价。"""
    # 不存在或跨公司返回 404
    if not rfq_mod.delete_rfq_response(rid, cid):
        raise HTTPException(status_code=404, detail="询价回复行不存在")
    return {"ok": True}


@router.post("/rfq-responses/{rid}/select")
def select_rfq_response_api(
    rid: int,
    cid: int = Depends(require_company),
):
    """选定该供应商（同单其余清零，单头置 decided）。"""
    res = rfq_mod.select_rfq_response(rid, cid)
    # 不存在或跨公司返回 404
    if not res:
        raise HTTPException(status_code=404, detail="询价回复行不存在")
    return res


@router.post("/rfq-responses/{rid}/unselect")
def unselect_rfq_response_api(
    rid: int,
    cid: int = Depends(require_company),
):
    """取消选定该供应商（单头回 open）。"""
    res = rfq_mod.unselect_rfq_response(rid, cid)
    # 不存在或跨公司返回 404
    if not res:
        raise HTTPException(status_code=404, detail="询价回复行不存在")
    return res
