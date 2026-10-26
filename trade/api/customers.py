"""
Trade AI Assistant — 客户管理 API 路由。

端点：
  GET    /customers                              — 列出当前公司的客户
  POST   /customers                              — 创建客户
  GET    /customers/template                     — 下载 CSV 导入模板
  POST   /customers/bulk                         — 批量导入（CSV 文件上传）
  GET    /customers/{customer_id}                 — 获取客户详情
  PUT    /customers/{customer_id}                 — 更新客户
  DELETE /customers/{customer_id}                 — 删除客户
  POST   /customers/{customer_id}/libraries/{id}  — 关联文档库
  DELETE /customers/{customer_id}/libraries/{id}  — 取消关联
  GET    /customers/{customer_id}/libraries       — 列出关联的文档库

注意：/customers/template 和 /customers/bulk 必须在 /customers/{customer_id}
之前注册，否则 FastAPI 会把 "template" 当作 customer_id 解析导致 422。
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse

from trade import customer as customer_module
from trade.api.deps import require_company
from trade.api.models import CustomerCreate, CustomerUpdate

router = APIRouter(tags=["customers"])


# ── 客户 CRUD ──────────────────────────────────────────────────────────────

@router.get("/customers")
def list_customers(
    cid: int = Depends(require_company),
):
    """列出当前公司的所有客户。"""
    return customer_module.list_by_company(cid)


@router.post("/customers")
def create_customer(
    payload: CustomerCreate,
    cid: int = Depends(require_company),
):
    """创建新客户（归属于当前公司）。"""
    return customer_module.create(
        payload.name, payload.contact, payload.note, company_id=cid,
        country=payload.country, tier=payload.tier, linkedin_url=payload.linkedin_url,
        company_website=payload.company_website, social_media=payload.social_media,
        title=payload.title, email=payload.email, backup_email=payload.backup_email,
        phone=payload.phone, whatsapp=payload.whatsapp,
        wechat=payload.wechat, source=payload.source,
        buyer_type=payload.buyer_type, follow_up_note=payload.follow_up_note,
        main_category=payload.main_category, match_score=payload.match_score,
    )


# ── CSV 列名 → customer 字段映射（批量导入）──────────────────────────────
# 必须定义在路由装饰器之前

_CSV_FIELD_MAP = {
    "name": "name",
    "contact": "contact",
    "title": "title",
    "country": "country",
    "email": "email",
    "phone": "phone",
    "whatsapp": "whatsapp",
    "wechat": "wechat",
    "linkedin_url": "linkedin_url",
    "company_website": "company_website",
    "tier": "tier",
    "buyer_type": "buyer_type",
    "main_category": "main_category",
    "match_score": "match_score",
    "note": "note",
}


def _find_static_dir() -> Path:
    """查找静态文件目录，与 app.py 保持一致的查找逻辑。"""
    import os as _os
    import sys as _sys

    if getattr(_sys, "frozen", False) and hasattr(_sys, "_MEIPASS"):
        return Path(_sys._MEIPASS) / "static"
    # 运行时目录
    trade_home = _os.environ.get("TRADE_HOME", "").strip()
    if not trade_home:
        if _os.name == "nt":
            _local = _os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
            trade_home = str(Path(_local) / "trade")
        else:
            trade_home = str(Path.home() / ".trade")
    runtime_static = Path(trade_home) / "foreign-trade-assistant" / "static"
    if runtime_static.is_dir():
        return runtime_static
    # 开发目录
    return Path(__file__).resolve().parent.parent.parent / "static"


# ── 模板下载 + 批量导入（必须在 {customer_id} 路由之前注册）─────────────

@router.get("/customers/template")
def download_customer_template():
    """下载 CSV 客户导入模板。"""
    template_path = _find_static_dir() / "trade-customer-template.csv"
    if not template_path.is_file():
        raise HTTPException(status_code=404, detail="Template not found")
    return FileResponse(
        str(template_path),
        media_type="text/csv",
        filename="trade-customer-template.csv",
    )


@router.post("/customers/bulk")
async def bulk_import_customers(
    file: UploadFile,
    cid: int = Depends(require_company),
):
    """CSV 批量导入客户。

    接收 CSV 文件（UTF-8 编码），按表头列名映射到客户字段。
    跳过空名称行和重名行，返回导入统计。
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="请上传 .csv 格式的文件")

    # 预检文件大小，拒绝超大 CSV 防止内存耗尽
    _MAX_CSV_BYTES = 10 * 1024 * 1024  # 10MB
    f_size = getattr(file, "size", None)
    if f_size is not None and f_size > _MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="CSV 文件过大（上限 10MB）")

    content = await file.read()
    # 分块上传时 `file.size` 可能为 None，预检会被绕过 —— 读完后必须再量一次
    # 实际字节数（审计 P2-26）。
    if len(content) > _MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="CSV 文件过大（上限 10MB）")
    try:
        text = content.decode("utf-8-sig")  # utf-8-sig 兼容 BOM 头
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="文件编码不是 UTF-8，请用 Excel 另存为 CSV UTF-8")

    try:
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise HTTPException(status_code=400, detail="CSV 文件为空或缺少表头")
    except csv.Error:
        raise HTTPException(status_code=400, detail="CSV 格式解析失败")

    # 映射 CSV 列到内部字段
    customers = []
    for row in reader:
        cust = {}
        for csv_col, internal_key in _CSV_FIELD_MAP.items():
            if csv_col in row and row[csv_col]:
                cust[internal_key] = row[csv_col].strip()
        if cust.get("name"):
            # match_score 从 CSV 字符串转为整数
            if "match_score" in cust:
                try:
                    cust["match_score"] = int(cust["match_score"])
                except (ValueError, TypeError):
                    cust["match_score"] = 0
            customers.append(cust)

    if not customers:
        raise HTTPException(status_code=400, detail="CSV 中没有有效数据（至少需要 name 列）")

    result = customer_module.bulk_save(company_id=cid, customers=customers)
    return result


@router.get("/customers/duplicates")
def get_customer_duplicates(cid: int = Depends(require_company)):
    """查找当前公司内可能的重复客户（按 email / website 匹配）。"""
    return customer_module.find_duplicates(cid)


@router.get("/customers/search")
def search_customers(
    q: str,
    limit: int = 20,
    cid: int = Depends(require_company),
):
    """按语义搜索客户（向量优先，不可用/无命中时自动降级关键词）。

    注意必须声明在 `/customers/{customer_id}` 之前 —— 否则 "search" 会被
    当成 customer_id 去转 int。
    """
    from trade.database import get_connection
    from trade.vec_search import search_customers as _search

    query = (q or "").strip()
    if not query:
        return []
    conn = get_connection()
    try:
        hits = _search(conn, query, company_id=cid, top_k=max(1, min(limit, 100)))
        if not hits:
            return []
        # 一次取回所有命中客户（一条 IN 查询）——原先逐个 get()，
        # top_k=100 就是 101 个连接（2026-10-22 审计 P2）
        found = customer_module.get_by_ids(
            [h["customer_id"] for h in hits], company_id=cid,
        )
        out = []
        for h in hits:
            cust = found.get(h["customer_id"])
            if cust:
                # 用独立字段承载检索得分（0.41~1.0 的浮点），**不能写进 match_score** ——
                # 那是业务评级（int 0-5，前端是 0-5 输入框），覆盖后前端 parseInt("0.87")
                # 会得到 0，用户一保存就把真实评分清零（2026-10-21 审计发现）。
                cust["search_score"] = h.get("score")
                out.append(cust)
        return out
    finally:
        conn.close()


# ── 客户详情 / 更新 / 删除（{customer_id} 通配路由必须在字面路由之后）─

@router.get("/customers/{customer_id}")
def get_customer(
    customer_id: int,
    cid: int = Depends(require_company),
):
    """获取客户详情（必须属于当前公司）。"""
    cust = customer_module.get(customer_id, company_id=cid)
    if not cust:
        raise HTTPException(status_code=404, detail="Customer not found")
    return cust


@router.put("/customers/{customer_id}")
def update_customer(
    customer_id: int,
    payload: CustomerUpdate,
    cid: int = Depends(require_company),
):
    """更新客户字段（必须属于当前公司）。"""
    kwargs = payload.model_dump(exclude_none=True)
    result = customer_module.update(customer_id, company_id=cid, **kwargs)
    if not result:
        raise HTTPException(status_code=404, detail="Customer not found")
    return result


@router.delete("/customers/{customer_id}")
def delete_customer(
    customer_id: int,
    cid: int = Depends(require_company),
):
    """删除客户（必须属于当前公司）。"""
    if not customer_module.delete(customer_id, company_id=cid):
        raise HTTPException(status_code=404, detail="Customer not found")
    return {"ok": True}


# ── 客户 ↔ 文档库关联 ────────────────────────────────────────────────────

@router.post("/customers/{customer_id}/libraries/{library_id}")
def link_library_to_customer(
    customer_id: int,
    library_id: int,
    cid: int = Depends(require_company),
):
    """将文档库关联到客户（两者必须属于同一公司）。"""
    try:
        customer_module.link_library(customer_id, library_id, company_id=cid)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/customers/{customer_id}/libraries/{library_id}")
def unlink_library_from_customer(
    customer_id: int,
    library_id: int,
    cid: int = Depends(require_company),
):
    """取消文档库与客户的关联。"""
    try:
        if not customer_module.unlink_library(customer_id, library_id, company_id=cid):
            raise HTTPException(status_code=404, detail="Link not found")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}


@router.get("/customers/{customer_id}/libraries")
def get_customer_libraries(
    customer_id: int,
    cid: int = Depends(require_company),
):
    """列出客户关联的所有文档库。"""
    return customer_module.get_libraries(customer_id, company_id=cid)
