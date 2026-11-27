"""
Trade AI Assistant — 采购单与拼柜看板 API 路由（供应商管理一期 · 第三批）。

采购单端点（静态路径必须先于 /{po_id} 注册）：
  GET    /purchase-orders                      — 列表（supplier_id/order_id/status/q，q 同时匹配 po_no 与客户 order_no）
  POST   /purchase-orders                      — 新建（po_no 空则回填 PO{id}）
  GET    /purchase-orders/alerts               — 交期提醒（逾期在前，其次交期升序）
  POST   /purchase-orders/from-rfq             — 从已选厂采购询价单生成采购单
  GET    /purchase-orders/orders               — 本公司客户订单下拉列表（供新建/编辑关联）
  GET    /purchase-orders/{po_id}              — 详情（单头 + 主联系人 + 关联订单 + 所在拼柜）
  PUT    /purchase-orders/{po_id}              — 更新（po_no 创建后不可改）
  DELETE /purchase-orders/{po_id}              — 删除（级联删拼柜明细，柜本身不动）
  POST   /purchase-orders/{po_id}/followup-draft — 催货话术纯文本草稿（upcoming/overdue/cutoff，零写库零发送）

拼柜端点（静态路径 /consolidations/pool 必须先于 /{consolidation_id} 注册）：
  GET    /consolidations                       — 拼柜列表（含明细数、截关倒计时 days_to_cutoff）
  POST   /consolidations                       — 新建拼柜（code 空则回填 CG{id}）
  GET    /consolidations/pool                  — 待拼池（已下单/生产中/待出货且未入任何柜）
  GET    /consolidations/{cid}                 — 拼柜详情（柜信息 + 明细）
  PUT    /consolidations/{cid}                 — 更新拼柜
  DELETE /consolidations/{cid}                 — 删除拼柜（级联删明细，采购单本身不动）
  POST   /consolidations/{cid}/items           — 采购单入柜（重复加入返回既有明细行）
  DELETE /consolidations/{cid}/items/{item_id} — 移出拼柜
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from trade import purchase as purchase_mod
from trade.api.deps import require_company

router = APIRouter(tags=["purchase"])


# ==============================================================================
# Pydantic 请求模型
# ==============================================================================


class PurchaseOrderCreateBody(BaseModel):
    supplier_id: Any
    product_name: str
    po_no: str = ""
    order_id: Any = None
    rfq_id: Any = None
    spec_model: str = ""
    quantity: Any = None
    unit: str = ""
    amount: Any = None
    currency: str = "CNY"
    ordered_at: str = ""
    promised_date: str = ""
    status: str = "已下单"
    note: str = ""
    extra1: Any = "{}"
    extra2: Any = "{}"
    extra3: Any = "{}"


class PurchaseOrderUpdateBody(BaseModel):
    po_no: str | None = None
    supplier_id: Any = None
    order_id: Any = None
    rfq_id: Any = None
    product_name: str | None = None
    spec_model: str | None = None
    quantity: Any = None
    unit: str | None = None
    amount: Any = None
    currency: str | None = None
    ordered_at: str | None = None
    promised_date: str | None = None
    status: str | None = None
    note: str | None = None
    extra1: Any = None
    extra2: Any = None
    extra3: Any = None


class FromRfqBody(BaseModel):
    rfq_id: int


class FollowupDraftBody(BaseModel):
    variant: str


class ConsolidationCreateBody(BaseModel):
    code: str = ""
    cutoff_date: str = ""
    destination_port: str = ""
    carrier: str = ""
    etd: str = ""
    status: str = "组货中"
    note: str = ""
    extra1: Any = "{}"
    extra2: Any = "{}"
    extra3: Any = "{}"


class ConsolidationUpdateBody(BaseModel):
    code: str | None = None
    cutoff_date: str | None = None
    destination_port: str | None = None
    carrier: str | None = None
    etd: str | None = None
    status: str | None = None
    note: str | None = None
    extra1: Any = None
    extra2: Any = None
    extra3: Any = None


class ConsolidationItemAddBody(BaseModel):
    purchase_order_id: Any
    note: str = ""


# ==============================================================================
# 采购单静态路径（必须先于 /purchase-orders/{po_id} 注册）
# ==============================================================================


@router.get("/purchase-orders")
def list_purchase_orders_api(
    supplier_id: int | None = Query(None, description="供应商 ID"),
    order_id: int | None = Query(None, description="关联客户订单 ID"),
    status: str = Query("", description="状态筛选"),
    q: str = Query("", description="采购单号 / 产品名 / 客户订单号搜索"),
    cid: int = Depends(require_company),
):
    """列出当前公司的采购单。"""
    return purchase_mod.list_purchase_orders(
        cid,
        supplier_id=supplier_id,
        order_id=order_id,
        status=status,
        q=q,
    )


@router.post("/purchase-orders")
def create_purchase_order_api(
    body: PurchaseOrderCreateBody,
    cid: int = Depends(require_company),
):
    """新建采购单（po_no 空则自动回填 PO{id}）。"""
    try:
        return purchase_mod.create_purchase_order(cid, **body.model_dump())
    except purchase_mod.PurchaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/purchase-orders/alerts")
def get_delivery_alerts_api(
    cid: int = Depends(require_company),
):
    """获取当前公司的交期提醒（逾期优先，其次按约定交期升序）。"""
    return purchase_mod.get_delivery_alerts(cid)


@router.post("/purchase-orders/from-rfq")
def create_po_from_rfq_api(
    body: FromRfqBody,
    cid: int = Depends(require_company),
):
    """从已选厂的采购询价单生成采购单。"""
    try:
        created = purchase_mod.create_purchase_order_from_rfq(cid, body.rfq_id)
    except purchase_mod.PurchaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # 询价单不存在或跨公司返回 404
    if not created:
        raise HTTPException(status_code=404, detail="采购询价单不存在")
    return created


@router.get("/purchase-orders/orders")
def list_company_orders_for_po_api(
    cid: int = Depends(require_company),
):
    """列出本公司客户订单（附显示号与客户名），供采购单表单下拉关联。"""
    return purchase_mod.list_company_orders(cid)


# ==============================================================================
# 采购单详情 / 修改 / 删除与催货话术
# ==============================================================================


@router.get("/purchase-orders/{po_id}")
def get_purchase_order_api(
    po_id: int,
    cid: int = Depends(require_company),
):
    """获取采购单详情（单头 + 主联系人 + 关联订单 + 所在拼柜）。"""
    detail = purchase_mod.get_purchase_order(po_id, cid)
    # 不存在或跨公司返回 404
    if not detail:
        raise HTTPException(status_code=404, detail="采购单不存在")
    return detail


@router.put("/purchase-orders/{po_id}")
def update_purchase_order_api(
    po_id: int,
    body: PurchaseOrderUpdateBody,
    cid: int = Depends(require_company),
):
    """更新采购单（采购单号创建后不可修改）。"""
    fields = body.model_dump(exclude_unset=True)
    try:
        updated = purchase_mod.update_purchase_order(po_id, cid, **fields)
    except purchase_mod.PurchaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # 不存在或跨公司返回 404
    if not updated:
        raise HTTPException(status_code=404, detail="采购单不存在")
    return updated


@router.delete("/purchase-orders/{po_id}")
def delete_purchase_order_api(
    po_id: int,
    cid: int = Depends(require_company),
):
    """删除采购单（级联删拼柜明细，柜本身不动）。"""
    # 不存在或跨公司返回 404
    if not purchase_mod.delete_purchase_order(po_id, cid):
        raise HTTPException(status_code=404, detail="采购单不存在")
    return {"ok": True}


@router.post("/purchase-orders/{po_id}/followup-draft")
def followup_draft_api(
    po_id: int,
    body: FollowupDraftBody,
    cid: int = Depends(require_company),
):
    """生成确定性催货话术纯文本草稿（零写库、永不发送）。"""
    try:
        res = purchase_mod.build_followup_draft(po_id, cid, body.variant)
    except purchase_mod.PurchaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # 不存在或跨公司返回 404
    if not res:
        raise HTTPException(status_code=404, detail="采购单不存在")
    return res


# ==============================================================================
# 拼柜看板静态路径（/consolidations/pool 必须先于 /{consolidation_id} 注册）
# ==============================================================================


@router.get("/consolidations")
def list_consolidations_api(
    status: str = Query("", description="状态筛选：组货中/已截关/已发运"),
    cid: int = Depends(require_company),
):
    """列出本公司拼柜看板列表（含明细数与截关倒计时）。"""
    return purchase_mod.list_consolidations(cid, status=status)


@router.post("/consolidations")
def create_consolidation_api(
    body: ConsolidationCreateBody,
    cid: int = Depends(require_company),
):
    """新建拼柜（code 空则自动回填 CG{id}）。"""
    try:
        return purchase_mod.create_consolidation(cid, **body.model_dump())
    except purchase_mod.PurchaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/consolidations/pool")
def list_consolidation_pool_api(
    cid: int = Depends(require_company),
):
    """获取待拼池（已下单/生产中/待出货且未出现在任何拼柜明细中的采购单）。"""
    return purchase_mod.list_consolidation_pool(cid)


# ==============================================================================
# 拼柜详情 / 修改 / 删除与明细操作
# ==============================================================================


@router.get("/consolidations/{consolidation_id}")
def get_consolidation_api(
    consolidation_id: int,
    cid: int = Depends(require_company),
):
    """获取拼柜详情（柜头 + 明细列表）。"""
    detail = purchase_mod.get_consolidation(consolidation_id, cid)
    # 不存在或跨公司返回 404
    if not detail:
        raise HTTPException(status_code=404, detail="拼柜不存在")
    return detail


@router.put("/consolidations/{consolidation_id}")
def update_consolidation_api(
    consolidation_id: int,
    body: ConsolidationUpdateBody,
    cid: int = Depends(require_company),
):
    """更新拼柜信息。"""
    fields = body.model_dump(exclude_unset=True)
    try:
        updated = purchase_mod.update_consolidation(consolidation_id, cid, **fields)
    except purchase_mod.PurchaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # 不存在或跨公司返回 404
    if not updated:
        raise HTTPException(status_code=404, detail="拼柜不存在")
    return updated


@router.delete("/consolidations/{consolidation_id}")
def delete_consolidation_api(
    consolidation_id: int,
    cid: int = Depends(require_company),
):
    """删除拼柜（级联删明细，采购单本身不动）。"""
    # 不存在或跨公司返回 404
    if not purchase_mod.delete_consolidation(consolidation_id, cid):
        raise HTTPException(status_code=404, detail="拼柜不存在")
    return {"ok": True}


@router.post("/consolidations/{consolidation_id}/items")
def add_consolidation_item_api(
    consolidation_id: int,
    body: ConsolidationItemAddBody,
    cid: int = Depends(require_company),
):
    """将采购单加入拼柜；重复加入返回既有明细行。"""
    try:
        item = purchase_mod.add_consolidation_item(
            consolidation_id, cid, body.purchase_order_id, note=body.note,
        )
    except purchase_mod.PurchaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # 拼柜不存在或跨公司返回 404
    if not item:
        raise HTTPException(status_code=404, detail="拼柜不存在")
    return item


@router.delete("/consolidations/{consolidation_id}/items/{item_id}")
def remove_consolidation_item_api(
    consolidation_id: int,
    item_id: int,
    cid: int = Depends(require_company),
):
    """将采购单移出拼柜（采购单本身不动）。"""
    # 不存在或跨公司返回 404
    if not purchase_mod.remove_consolidation_item(consolidation_id, item_id, cid):
        raise HTTPException(status_code=404, detail="拼柜明细不存在")
    return {"ok": True}
