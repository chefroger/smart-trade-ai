"""订单 API 路由。"""

from fastapi import APIRouter, Depends, HTTPException

from trade import order as order_module
from trade.api.deps import require_company
from trade.api.models import OrderCreate, OrderUpdate

router = APIRouter(tags=["orders"])


@router.get("/orders")
def list_orders(cid: int = Depends(require_company)):
    """列出当前公司的所有订单。"""
    return order_module.list_by_company(cid)


@router.get("/customers/{customer_id}/orders")
def list_customer_orders(customer_id: int, cid: int = Depends(require_company)):
    """列出指定客户的所有订单。"""
    from trade import customer as cust_module
    c = cust_module.get(customer_id, company_id=cid)
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    return order_module.list_by_customer(customer_id, company_id=cid)


@router.post("/orders")
def create_order(payload: OrderCreate, cid: int = Depends(require_company)):
    """创建订单。校验客户归属 + 金额一致性（总金额为空时自动算出）。"""
    from trade import customer as cust_module
    c = cust_module.get(payload.customer_id, company_id=cid)
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    try:
        quantity, unit_price, total_amount = order_module.reconcile_amounts(
            payload.quantity, payload.unit_price, payload.total_amount,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return order_module.create(
        company_id=cid,
        customer_id=payload.customer_id,
        product_name=payload.product_name,
        order_no=payload.order_no or "",
        quantity=quantity,
        unit=payload.unit or "",
        unit_price=unit_price,
        currency=payload.currency or "USD",
        total_amount=total_amount,
        status=payload.status or "报价中",
        delivery_date=payload.delivery_date or "",
        payment_terms=payload.payment_terms or "",
        notes=payload.notes or "",
    )


@router.get("/orders/{order_id}")
def get_order(order_id: int, cid: int = Depends(require_company)):
    """获取订单详情。"""
    o = order_module.get(order_id, company_id=cid)
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    return o


@router.put("/orders/{order_id}")
def update_order(order_id: int, payload: OrderUpdate, cid: int = Depends(require_company)):
    """更新订单。校验状态迁移与金额一致性（都以库里的当前值为基准）。"""
    changes = payload.model_dump(exclude_none=True)
    existing = order_module.get(order_id, company_id=cid)
    if not existing:
        raise HTTPException(status_code=404, detail="Order not found")

    new_status = changes.get("status")
    if new_status and not order_module.can_transition_status(existing.get("status") or "", new_status):
        raise HTTPException(
            status_code=400,
            detail=f"订单状态不能从「{existing.get('status') or '未知'}」变为「{new_status}」。",
        )

    # 只有真的改了金额字段才校验：旧记录本就可能不一致，改备注不该被它挡住
    if {"quantity", "unit_price", "total_amount"} & changes.keys():
        try:
            qty, price, total = order_module.reconcile_amounts(
                changes.get("quantity", existing.get("quantity")),
                changes.get("unit_price", existing.get("unit_price")),
                changes.get("total_amount", existing.get("total_amount")),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        changes.update(quantity=qty, unit_price=price, total_amount=total)

    result = order_module.update(order_id, company_id=cid, **changes)
    if not result:
        raise HTTPException(status_code=404, detail="Order not found")
    return result


@router.delete("/orders/{order_id}")
def delete_order(order_id: int, cid: int = Depends(require_company)):
    """删除订单。"""
    if not order_module.delete(order_id, company_id=cid):
        raise HTTPException(status_code=404, detail="Order not found")
    return {"ok": True}


@router.post("/orders/{order_id}/libraries/{library_id}")
def link_order_library(order_id: int, library_id: int, cid: int = Depends(require_company)):
    """关联文档库到订单。"""
    if not order_module.link_library(order_id, library_id, company_id=cid):
        raise HTTPException(status_code=404, detail="Order or library not found")
    return {"ok": True}


@router.delete("/orders/{order_id}/libraries/{library_id}")
def unlink_order_library(order_id: int, library_id: int, cid: int = Depends(require_company)):
    """取消订单的文档库关联。"""
    if not order_module.unlink_library(order_id, library_id, company_id=cid):
        raise HTTPException(status_code=404, detail="Association not found")
    return {"ok": True}
