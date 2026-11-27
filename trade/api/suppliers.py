"""
Trade AI Assistant — 供应商管理 API 路由（一期 · 第一批数据底座）。

端点：
  GET    /suppliers                              — 供应商名录（支持 q/status/supplier_type/is_starred）
  POST   /suppliers                              — 新建供应商（同名给软提醒不硬拦）
  GET    /suppliers/template                     — 下载 CSV 导入模板
  POST   /suppliers/bulk                         — CSV 模板批量导入（好行入库、坏行逐行报错）
  POST   /suppliers/extract                      — AI 文件夹抽取（落草稿确认区）
  PUT    /suppliers/contacts/{cid}               — 更新供应商联系人
  DELETE /suppliers/contacts/{cid}               — 删除供应商联系人
  GET    /suppliers/{supplier_id}                — 供应商详情（主表+联系人+能力+最近20条报价）
  PUT    /suppliers/{supplier_id}                — 更新供应商
  DELETE /suppliers/{supplier_id}                — 删除供应商（级联）
  POST   /suppliers/{supplier_id}/contacts       — 新增供应商联系人
  POST   /suppliers/{supplier_id}/products       — 产品能力 upsert
  POST   /suppliers/{supplier_id}/quotes         — 追加一条报价历史
  PUT    /supplier-products/{product_id}         — 更新产品能力行
  DELETE /supplier-products/{product_id}         — 删除产品能力行
  GET    /supplier-quotes/search                 — 三向查询（产品/供应商/客户）
  PUT    /supplier-quotes/{quote_id}             — 报价纠错
  DELETE /supplier-quotes/{quote_id}             — 删除报价
  GET    /supplier-compare                       — 产品比价（换算口径 + 不同单位分组）
  GET    /supplier-quote-drafts                  — 确认区草稿列表
  PUT    /supplier-quote-drafts/{draft_id}       — 编辑草稿字段
  POST   /supplier-quote-drafts/{draft_id}/approve — 批准入库
  POST   /supplier-quote-drafts/{draft_id}/reject  — 驳回留痕

注意：/suppliers/template、/suppliers/bulk、/suppliers/extract、/suppliers/contacts/{cid}
必须在 /suppliers/{supplier_id} 之前注册，避免 FastAPI 将字面路径当作 int 解析导致 422。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from trade import supplier as supplier_mod
from trade.api.customers import _find_static_dir
from trade.api.deps import require_company

router = APIRouter(tags=["suppliers"])


# ==============================================================================
# Pydantic 请求模型
# ==============================================================================


class SupplierCreateBody(BaseModel):
    name: str
    short_name: str = ""
    supplier_type: str = ""
    main_products: str = ""
    province: str = ""
    city: str = ""
    address: str = ""
    status: str = "候选"
    rating: Any = None
    is_starred: int = 0
    can_issue_vat: Any = 2
    tax_point: Any = None
    payment_terms: str = ""
    lead_time_days: Any = None
    source: str = "manual"
    note: str = ""
    extra1: Any = "{}"
    extra2: Any = "{}"
    extra3: Any = "{}"


class SupplierUpdateBody(BaseModel):
    name: str | None = None
    short_name: str | None = None
    supplier_type: str | None = None
    main_products: str | None = None
    province: str | None = None
    city: str | None = None
    address: str | None = None
    status: str | None = None
    rating: Any = None
    is_starred: int | None = None
    can_issue_vat: Any = None
    tax_point: Any = None
    payment_terms: str | None = None
    lead_time_days: Any = None
    source: str | None = None
    note: str | None = None
    extra1: Any = None
    extra2: Any = None
    extra3: Any = None


class SupplierContactCreateBody(BaseModel):
    name: str
    role: str = "其他"
    is_primary: int = 0
    phone: str = ""
    wechat: str = ""
    email: str = ""
    qq: str = ""
    note: str = ""


class SupplierContactUpdateBody(BaseModel):
    name: str | None = None
    role: str | None = None
    is_primary: int | None = None
    phone: str | None = None
    wechat: str | None = None
    email: str | None = None
    qq: str | None = None
    note: str | None = None


class SupplierProductUpsertBody(BaseModel):
    product_name: str
    spec_model: str = ""
    unit: str = ""
    is_self_produced: Any = 2
    quality_note: str = ""
    lead_time_days: Any = None
    lead_time_text: str = ""
    moq: Any = None
    packing_info: str = ""
    notes: str = ""
    extra1: Any = "{}"
    extra2: Any = "{}"
    extra3: Any = "{}"


class SupplierProductUpdateBody(BaseModel):
    product_name: str | None = None
    spec_model: str | None = None
    unit: str | None = None
    is_self_produced: Any = None
    quality_note: str | None = None
    lead_time_days: Any = None
    lead_time_text: str | None = None
    moq: Any = None
    packing_info: str | None = None
    notes: str | None = None
    extra1: Any = None
    extra2: Any = None
    extra3: Any = None


class SupplierQuoteCreateBody(BaseModel):
    product_name: str
    spec_model: str = ""
    unit: str = ""
    price_excl_tax: Any = None
    price_incl_tax: Any = None
    currency: str = "CNY"
    moq: Any = None
    quoted_at: str = ""
    valid_until: str = ""
    source_customer_id: Any = None
    supplier_product_id: Any = None
    source: str = "manual"
    source_ref: str = ""
    notes: str = ""
    extra1: Any = "{}"
    extra2: Any = "{}"
    extra3: Any = "{}"


class SupplierQuoteUpdateBody(BaseModel):
    product_name: str | None = None
    spec_model: str | None = None
    unit: str | None = None
    price_excl_tax: Any = None
    price_incl_tax: Any = None
    currency: str | None = None
    moq: Any = None
    quoted_at: str | None = None
    valid_until: str | None = None
    source_customer_id: Any = None
    supplier_product_id: Any = None
    source: str | None = None
    source_ref: str | None = None
    notes: str | None = None
    extra1: Any = None
    extra2: Any = None
    extra3: Any = None


class SupplierExtractBody(BaseModel):
    paths: list[str] = Field(default_factory=list)


class SupplierDraftUpdateBody(BaseModel):
    supplier_id: Any = None
    supplier_name_raw: str | None = None
    product_name: str | None = None
    spec_model: str | None = None
    unit: str | None = None
    price_excl_tax: Any = None
    price_incl_tax: Any = None
    currency: str | None = None
    quoted_at: str | None = None
    valid_until: str | None = None
    raw_excerpt: str | None = None


# ==============================================================================
# 供应商静态路径（必须注册在 /suppliers/{supplier_id} 之前）
# ==============================================================================


@router.get("/suppliers")
def list_suppliers_api(
    q: str = Query("", description="名称/简称/主营搜索"),
    status: str = Query("", description="状态筛选"),
    supplier_type: str = Query("", description="类型筛选"),
    is_starred: int | None = Query(None, description="星标筛选（0/1）"),
    cid: int = Depends(require_company),
):
    """列出当前公司的供应商名录。"""
    return supplier_mod.list_suppliers(
        cid,
        q=q,
        status=status,
        supplier_type=supplier_type,
        is_starred=is_starred,
    )


@router.post("/suppliers")
def create_supplier_api(
    body: SupplierCreateBody,
    cid: int = Depends(require_company),
):
    """新建供应商（归属当前公司）。"""
    try:
        return supplier_mod.create_supplier(cid, **body.model_dump())
    except supplier_mod.SupplierError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/suppliers/template")
def download_supplier_template():
    """下载供应商 CSV 导入模板。"""
    template_path = _find_static_dir() / "trade-supplier-template.csv"
    # 模板文件缺失时返回 404
    if not template_path.is_file():
        raise HTTPException(status_code=404, detail="供应商导入模板不存在")
    return FileResponse(
        str(template_path),
        media_type="text/csv",
        filename="trade-supplier-template.csv",
    )


@router.post("/suppliers/bulk")
async def bulk_import_suppliers_api(
    file: UploadFile,
    cid: int = Depends(require_company),
):
    """CSV 模板批量导入供应商（含联系人、能力行与首条报价）。"""
    # 仅接受 .csv 后缀文件
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="请上传 .csv 格式的文件")

    max_bytes = 10 * 1024 * 1024  # 10MB 上限
    f_size = getattr(file, "size", None)
    # 预检声明体积，防止超大文件读入内存
    if f_size is not None and f_size > max_bytes:
        raise HTTPException(status_code=413, detail="CSV 文件过大（上限 10MB）")

    content = await file.read()
    # 读完后再次校验实际字节数
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail="CSV 文件过大（上限 10MB）")

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="文件编码不是 UTF-8，请用 Excel 另存为 CSV UTF-8")

    try:
        return supplier_mod.bulk_import_csv(cid, text)
    except supplier_mod.SupplierError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/suppliers/extract")
async def extract_suppliers_api(
    body: SupplierExtractBody,
    cid: int = Depends(require_company),
):
    """AI 文件夹/文件抽取供应商报价，产物只落草稿确认区。"""
    # 至少传入一个文件或文件夹路径
    if not body.paths:
        raise HTTPException(status_code=400, detail="请至少选择一个文件或文件夹路径")
    try:
        return await supplier_mod.extract_files_to_drafts(cid, body.paths)
    except supplier_mod.SupplierError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/suppliers/contacts/{contact_id}")
def update_supplier_contact_api(
    contact_id: int,
    body: SupplierContactUpdateBody,
    cid: int = Depends(require_company),
):
    """更新供应商联系人（设主联系人时互斥清零同供应商其余联系人）。"""
    fields = body.model_dump(exclude_unset=True)
    try:
        updated = supplier_mod.update_contact(contact_id, cid, **fields)
    except supplier_mod.SupplierError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # 不存在或跨公司一律返回 404
    if not updated:
        raise HTTPException(status_code=404, detail="联系人不存在")
    return updated


@router.delete("/suppliers/contacts/{contact_id}")
def delete_supplier_contact_api(
    contact_id: int,
    cid: int = Depends(require_company),
):
    """删除供应商联系人。"""
    # 不存在或跨公司一律返回 404
    if not supplier_mod.delete_contact(contact_id, cid):
        raise HTTPException(status_code=404, detail="联系人不存在")
    return {"ok": True}


# ==============================================================================
# 供应商详情 / 更新 / 删除及子资源（{supplier_id} 通配路由）
# ==============================================================================


@router.get("/suppliers/{supplier_id}")
def get_supplier_api(
    supplier_id: int,
    cid: int = Depends(require_company),
):
    """获取供应商详情（主表 + 联系人 + 产品能力 + 最近 20 条报价）。"""
    detail = supplier_mod.get_supplier(supplier_id, cid)
    # 不存在或跨公司返回 404
    if not detail:
        raise HTTPException(status_code=404, detail="供应商不存在")
    return detail


@router.put("/suppliers/{supplier_id}")
def update_supplier_api(
    supplier_id: int,
    body: SupplierUpdateBody,
    cid: int = Depends(require_company),
):
    """更新供应商基本信息。"""
    fields = body.model_dump(exclude_unset=True)
    try:
        updated = supplier_mod.update_supplier(supplier_id, cid, **fields)
    except supplier_mod.SupplierError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # 不存在或跨公司返回 404
    if not updated:
        raise HTTPException(status_code=404, detail="供应商不存在")
    return updated


@router.delete("/suppliers/{supplier_id}")
def delete_supplier_api(
    supplier_id: int,
    cid: int = Depends(require_company),
):
    """删除供应商（级联删除联系人、能力、报价）。"""
    # 不存在或跨公司返回 404
    if not supplier_mod.delete_supplier(supplier_id, cid):
        raise HTTPException(status_code=404, detail="供应商不存在")
    return {"ok": True}


@router.post("/suppliers/{supplier_id}/contacts")
def create_supplier_contact_api(
    supplier_id: int,
    body: SupplierContactCreateBody,
    cid: int = Depends(require_company),
):
    """为指定供应商新增联系人。"""
    try:
        created = supplier_mod.create_contact(cid, supplier_id, **body.model_dump())
    except supplier_mod.SupplierError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # 供应商不存在或跨公司返回 404
    if not created:
        raise HTTPException(status_code=404, detail="供应商不存在")
    return created


@router.post("/suppliers/{supplier_id}/products")
def upsert_supplier_product_api(
    supplier_id: int,
    body: SupplierProductUpsertBody,
    cid: int = Depends(require_company),
):
    """为指定供应商保存产品能力（按唯一约束 upsert）。"""
    try:
        saved = supplier_mod.upsert_product(cid, supplier_id, **body.model_dump())
    except supplier_mod.SupplierError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # 供应商不存在或跨公司返回 404
    if not saved:
        raise HTTPException(status_code=404, detail="供应商不存在")
    return saved


@router.post("/suppliers/{supplier_id}/quotes")
def create_supplier_quote_api(
    supplier_id: int,
    body: SupplierQuoteCreateBody,
    cid: int = Depends(require_company),
):
    """为指定供应商追加一条报价记录（不覆盖历史）。"""
    try:
        created = supplier_mod.create_quote(cid, supplier_id, **body.model_dump())
    except supplier_mod.SupplierError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # 供应商不存在或跨公司返回 404
    if not created:
        raise HTTPException(status_code=404, detail="供应商不存在")
    return created


# ==============================================================================
# 产品能力行 / 报价行 / 三向查询 / 比价
# ==============================================================================


@router.put("/supplier-products/{product_id}")
def update_supplier_product_api(
    product_id: int,
    body: SupplierProductUpdateBody,
    cid: int = Depends(require_company),
):
    """更新产品能力行。"""
    fields = body.model_dump(exclude_unset=True)
    try:
        updated = supplier_mod.update_product(product_id, cid, **fields)
    except supplier_mod.SupplierError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # 不存在或跨公司返回 404
    if not updated:
        raise HTTPException(status_code=404, detail="产品能力记录不存在")
    return updated


@router.delete("/supplier-products/{product_id}")
def delete_supplier_product_api(
    product_id: int,
    cid: int = Depends(require_company),
):
    """删除产品能力行。"""
    # 不存在或跨公司返回 404
    if not supplier_mod.delete_product(product_id, cid):
        raise HTTPException(status_code=404, detail="产品能力记录不存在")
    return {"ok": True}


@router.get("/supplier-quotes/search")
def search_supplier_quotes_api(
    product_name: str = Query("", description="产品名模糊搜索"),
    supplier_id: int | None = Query(None, description="供应商 ID"),
    customer_id: int | None = Query(None, description="来源客户 ID"),
    limit: int = Query(200, ge=1, le=1000),
    cid: int = Depends(require_company),
):
    """三向查询供应商报价历史（按 quoted_at 倒序，附带 expired 标记）。"""
    return supplier_mod.search_quotes(
        cid,
        product_name=product_name,
        supplier_id=supplier_id,
        customer_id=customer_id,
        limit=limit,
    )


@router.put("/supplier-quotes/{quote_id}")
def update_supplier_quote_api(
    quote_id: int,
    body: SupplierQuoteUpdateBody,
    cid: int = Depends(require_company),
):
    """人工纠错修改报价记录。"""
    fields = body.model_dump(exclude_unset=True)
    try:
        updated = supplier_mod.update_quote(quote_id, cid, **fields)
    except supplier_mod.SupplierError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # 不存在或跨公司返回 404
    if not updated:
        raise HTTPException(status_code=404, detail="报价记录不存在")
    return updated


@router.delete("/supplier-quotes/{quote_id}")
def delete_supplier_quote_api(
    quote_id: int,
    cid: int = Depends(require_company),
):
    """删除报价记录。"""
    # 不存在或跨公司返回 404
    if not supplier_mod.delete_quote(quote_id, cid):
        raise HTTPException(status_code=404, detail="报价记录不存在")
    return {"ok": True}


@router.get("/supplier-compare")
def compare_supplier_product_api(
    product_name: str = Query(..., description="产品名称（模糊匹配）"),
    spec_model: str = Query("", description="规格型号（可选，模糊匹配）"),
    cid: int = Depends(require_company),
):
    """产品比价：按单位分组展示，单边价有 tax_point 时换算并标 converted=true。"""
    return supplier_mod.compare_product(
        cid,
        product_name=product_name,
        spec_model=spec_model,
    )


# ==============================================================================
# AI 抽取草稿确认区
# ==============================================================================


@router.get("/supplier-quote-drafts")
def list_supplier_drafts_api(
    status: str = Query("pending", description="草稿状态：pending/approved/rejected/all"),
    cid: int = Depends(require_company),
):
    """获取报价确认区草稿列表。"""
    return supplier_mod.list_drafts(cid, status=status)


@router.put("/supplier-quote-drafts/{draft_id}")
def update_supplier_draft_api(
    draft_id: int,
    body: SupplierDraftUpdateBody,
    cid: int = Depends(require_company),
):
    """批准前人工修改草稿字段。"""
    fields = body.model_dump(exclude_unset=True)
    try:
        updated = supplier_mod.update_draft(draft_id, cid, **fields)
    except supplier_mod.SupplierError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # 不存在或跨公司返回 404
    if not updated:
        raise HTTPException(status_code=404, detail="草稿不存在")
    return updated


@router.post("/supplier-quote-drafts/{draft_id}/approve")
def approve_supplier_draft_api(
    draft_id: int,
    cid: int = Depends(require_company),
):
    """批准草稿入正式报价库（自动匹配/新建供应商与待确认能力行）。"""
    try:
        res = supplier_mod.approve_draft(draft_id, cid)
    except supplier_mod.SupplierError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # 不存在或跨公司返回 404
    if not res:
        raise HTTPException(status_code=404, detail="草稿不存在")
    return res


@router.post("/supplier-quote-drafts/{draft_id}/reject")
def reject_supplier_draft_api(
    draft_id: int,
    cid: int = Depends(require_company),
):
    """驳回草稿（状态置为 rejected，留痕不删除）。"""
    res = supplier_mod.reject_draft(draft_id, cid)
    # 不存在或跨公司返回 404
    if not res:
        raise HTTPException(status_code=404, detail="草稿不存在")
    return res
