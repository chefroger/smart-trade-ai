"""
Trade AI Assistant — API 请求/响应模型（Pydantic）。

将所有创建/更新类接口的 query params 替换为请求体模型，
自动校验类型、长度，生成正确的 OpenAPI schema。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# ── Company ────────────────────────────────────────────────────────────────────

class CompanyCreate(BaseModel):
    name: str = Field(..., description="公司名称")
    slug: str | None = Field(None, description="URL 标识（省略时自动生成）")
    logo_url: str = Field("", description="Logo URL")
    website: str = Field("", description="公司网站")
    contact_name: str = Field("", description="联系人姓名")
    contact_email: str = Field("", description="联系人邮箱")
    address: str = Field("", description="地址")
    work_dir_name: str = Field("", description="桌面工作目录名称（目录存在时可用此改名）")


class CompanyUpdate(BaseModel):
    name: str | None = Field(None, description="公司名称")
    logo_url: str | None = Field(None, description="Logo URL")
    website: str | None = Field(None, description="公司网站")
    contact_name: str | None = Field(None, description="联系人姓名")
    contact_email: str | None = Field(None, description="联系人邮箱")
    address: str | None = Field(None, description="地址")
    is_active: bool | None = Field(None, description="是否激活")


class AgentIdentityUpdate(BaseModel):
    agent_identity_md: str = Field("", description="Agent 身份配置 (Markdown)")


class OnboardingFirstCompany(BaseModel):
    company_name: str = Field(..., description="公司名称")
    contact_name: str = Field("", description="联系人姓名")
    contact_email: str = Field("", description="联系人邮箱")
    identity_data: dict | None = Field(None, description="Agent 身份配置")
    work_dir_name: str = Field("", description="桌面工作目录名称")


# ── Library ────────────────────────────────────────────────────────────────────

class LibraryCreate(BaseModel):
    name: str = Field(..., description="文档库名称")
    root_path: str = Field(..., description="本地目录绝对路径")
    description: str = Field("", description="文档库描述")


class LibraryUpdate(BaseModel):
    name: str | None = Field(None, description="文档库名称")
    root_path: str | None = Field(None, description="本地目录绝对路径")
    description: str | None = Field(None, description="文档库描述")


# ── Customer ───────────────────────────────────────────────────────────────────

class CustomerCreate(BaseModel):
    name: str = Field(..., description="客户名称")
    contact: str = Field("", description="联系方式")
    note: str = Field("", description="备注")
    country: str = Field("", description="国家")
    tier: str = Field("", description="客户等级 (A/B/C)")
    linkedin_url: str = Field("", description="LinkedIn URL")
    company_website: str = Field("", description="公司网站")
    social_media: dict | None = Field(None, description="社媒联系方式 {facebook, instagram, tiktok, youtube, twitter}")
    title: str = Field("", description="联系人职位 (CEO/Purchasing Manager 等)")
    email: str = Field("", description="邮箱")
    backup_email: str = Field("", description="备用邮箱")
    phone: str = Field("", description="电话")
    whatsapp: str = Field("", description="WhatsApp")
    wechat: str = Field("", description="微信")
    source: str = Field("", description="客户来源 (manual/agent/import)")
    buyer_type: str = Field("", description="买家类型 (品牌商/分销商/代理商/安装商/维保商/同行)")
    follow_up_note: str = Field("", description="AI 跟进建议")
    main_category: str = Field("", description="主营品类 (客户主营产品/行业)")
    match_score: int = Field(0, description="匹配度评分 (0-5)")


class CustomerUpdate(BaseModel):
    name: str | None = Field(None, description="客户名称")
    contact: str | None = Field(None, description="联系方式")
    note: str | None = Field(None, description="备注")
    country: str | None = Field(None, description="国家")
    tier: str | None = Field(None, description="客户等级 (A/B/C)")
    linkedin_url: str | None = Field(None, description="LinkedIn URL")
    company_website: str | None = Field(None, description="公司网站")
    social_media: dict | None = Field(None, description="社媒联系方式")
    title: str | None = Field(None, description="联系人职位")
    email: str | None = Field(None, description="邮箱")
    backup_email: str | None = Field(None, description="备用邮箱")
    phone: str | None = Field(None, description="电话")
    whatsapp: str | None = Field(None, description="WhatsApp")
    wechat: str | None = Field(None, description="微信")
    buyer_type: str | None = Field(None, description="买家类型 (品牌商/分销商/代理商/安装商/维保商/同行)")
    follow_up_note: str | None = Field(None, description="AI 跟进建议")
    main_category: str | None = Field(None, description="主营品类 (客户主营产品/行业)")
    match_score: int | None = Field(None, description="匹配度评分 (0-5)")


# ── Conversation Rating ────────────────────────────────────────────────────────

class ConversationRate(BaseModel):
    rating: int = Field(..., ge=1, le=5, description="评分 1-5")
    feedback: str | None = Field(None, description="可选反馈文字")


# ── Customer Duplicates ────────────────────────────────────────────────────────


class CustomerDuplicateGroup(BaseModel):
    reason: str = Field(..., description="重复判定原因（email_match / website_match）")
    detail: str = Field("", description="匹配的具体值")
    customers: list[dict] = Field(..., description="重复客户列表")


# ── Order ─────────────────────────────────────────────────────────────────────


class OrderCreate(BaseModel):
    customer_id: int = Field(..., description="客户 ID")
    product_name: str = Field(..., description="品名")
    order_no: str | None = Field(None, description="订单号")
    quantity: float | None = Field(None, ge=0, description="数量（≥0）")
    unit: str | None = Field(None, description="单位")
    unit_price: float | None = Field(None, ge=0, description="单价（≥0）")
    currency: str | None = Field(None, description="币种")
    total_amount: float | None = Field(None, ge=0, description="总金额（≥0）")
    status: Literal["报价中", "已下单", "已出货", "已完成", "已取消"] | None = Field(None, description="状态")
    delivery_date: str | None = Field(None, description="交期")
    payment_terms: str | None = Field(None, description="付款方式")
    notes: str | None = Field(None, description="备注")


class OrderUpdate(BaseModel):
    customer_id: int | None = Field(None, description="客户 ID")
    product_name: str | None = Field(None, description="品名")
    order_no: str | None = Field(None, description="订单号")
    quantity: float | None = Field(None, ge=0, description="数量（≥0）")
    unit: str | None = Field(None, description="单位")
    unit_price: float | None = Field(None, ge=0, description="单价（≥0）")
    currency: str | None = Field(None, description="币种")
    total_amount: float | None = Field(None, ge=0, description="总金额（≥0）")
    status: Literal["报价中", "已下单", "已出货", "已完成", "已取消"] | None = Field(None, description="状态")
    delivery_date: str | None = Field(None, description="交期")
    payment_terms: str | None = Field(None, description="付款方式")
    notes: str | None = Field(None, description="备注")


# ── Conversation ───────────────────────────────────────────────────────────────

class ConversationSave(BaseModel):
    library_id: int | None = Field(None, description="关联的文档库 ID")
    query: str = Field(..., description="用户问题")
    response: str = Field("", description="Agent 回复")
    files_read: list[dict] = Field(default_factory=list, description="读取的文件列表")
    library_name: str = Field("", description="文档库名称（用于上下文标注）")
    context: str = Field("", description="聊天上下文 (daily/lead/platform/...)")

    @field_validator("library_id", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if v == "" or v is None:
            return None
        return v


class ConversationUpdate(BaseModel):
    response: str = Field(..., description="更新后的回复内容")


# ── Chat ───────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=100000, description="用户问题（1-100000 字符）")
    library_id: int | None = Field(None, description="关联的文档库 ID")
    customer_id: int | None = Field(None, description="关联的客户 ID")
    context: str = Field("", description="聊天上下文 (daily/lead/platform/...)")
    language: str = Field("zh", description="界面语言 zh/en")

    @field_validator("library_id", "customer_id", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        """前端 select 未选中时可能传空字符串 ''，统一转 None 避免 422 int_parsing。"""
        if v == "" or v is None:
            return None
        return v
