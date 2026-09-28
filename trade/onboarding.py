"""
Trade AI Assistant — 首次运行引导模块。

职责：
  首次启动时引导用户完成公司注册和 Agent 身份配置，一步到位。
  提供「一体化」API，将公司创建、agent 身份配置合并为单个原子操作，
  避免用户分两步操作导致状态不完整。

调用方式：
  POST /api/trade/onboarding/first-company
    Body: {
        "company_name": "ABC Trading Co.",
        "contact_name": "张经理",
        "contact_email": "zhang@example.com",
        "agent_identity": {
            "role": "AI 销售助手",
            "products": "工业电机、发电机",
            "differentiation": "源头工厂、价格有竞争力",
            "target_region": "东南亚、欧洲"
        }
    }
    Returns: { "company": {...}, "trade_company": {...} }
"""

from __future__ import annotations

from trade import company as _company_module
from trade.database import get_connection

# ─────────────────────────────────────────────────────────────────────────────
# onboarding state — lightweight in-memory flag to prevent double-triggering
# ─────────────────────────────────────────────────────────────────────────────

# 是否已完成首次引导的全局标志（进程级，非持久化）。
# 服务器重启后归零，不影响用户已创建数据。
# 用途：前端首次打开时检测是否需要显示引导界面。
_onboarding_done: bool = False


def is_onboarding_done() -> bool:
    """检查系统是否已完成首次引导（至少有一家活跃公司）。

    检测逻辑：
      1. 查 companies 表是否有 is_active=1 的记录
      2. 如果有 → False（已完成引导，系统已初始化）
      3. 如果没有 → True（需要引导）
    """
    global _onboarding_done
    if _onboarding_done:
        return True

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM companies WHERE is_active = 1"
        ).fetchone()
        count = row[0] if row else 0
        _onboarding_done = (count > 0)
        return _onboarding_done
    finally:
        conn.close()


def reset_onboarding_flag() -> None:
    """重置引导标志（用于测试或调试）。"""
    global _onboarding_done
    _onboarding_done = False


# ─────────────────────────────────────────────────────────────────────────────
# Agent identity 模板（用户未填时使用默认值）
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_AGENT_IDENTITY_TEMPLATE = """# Agent 身份配置 — 高级外贸业务经理

## 你是谁

你是 {company_name} 的高级外贸业务经理，负责公司的海外市场开拓和客户关系维护。

## 核心职责

1. **新客户开发** — 通过 B2B 平台、LinkedIn、海关数据、行业展会等渠道拓展海外客户
2. **询盘跟进** — 及时响应客户询盘，提供专业的产品方案和报价
3. **客户维护** — 定期跟进老客户，了解采购动态，挖掘复购机会
4. **市场洞察** — 跟踪目标市场的行业动态、汇率变化、竞争对手动向

## 产品与优势

- **主营产品**：{products}
- **核心优势**：{differentiation}
- **目标市场**：{target_region}

## 沟通原则

- **专业、简洁、真诚** — 说人话，不堆砌术语，不编造信息
- **先了解需求，再给方案** — 不要一上来就报价，先问清楚客户需要什么
- **数据说话** — 引用具体数字和历史案例，而不是空泛的"我们是最好的"
- **主动创造价值** — 每次沟通都要让客户觉得跟你是值得的，无论是行业信息、采购建议还是技术支持
- **坦诚面对不确定** — 不知道就说不知道，确认后第一时间同步客户

## 工作习惯

- **今日事今日毕** — 当天询盘当天回复，不隔夜
- **跟进有节奏** — 初次联系 3 天后跟进，之后每周一次，不要过度骚扰
- **记录要完整** — 每次客户沟通后更新客户档案，下次打开一目了然
- **报价要规范** — 注明有效期、贸易术语、付款方式、交货期

## 禁止行为

- **禁止编造数据** — 汇率、价格、库存必须实时查询，不得凭空编造
- **禁止过度承诺** — 不要答应无法做到的付款条件、交期或定制需求
- **禁止泄露客户隐私** — 不在与客户 A 的对话中提及客户 B 的任何信息
- **禁止空泛回复** — 每个答案都要有依据（搜索结果 / 文件内容 / 数据库记录）

## 回复格式偏好

- 客户问题 → 直接回答，再补充细节和建议
- 开发信 → 痛点引入 → 方案展示 → 证据支撑 → 明确 CTA
- 报价单 → 产品规格 → 单价（含贸易术语）→ 有效期 → 交货期 → 付款方式
- 市场简报 → 关键指标（汇率/行情）→ 市场动态 → 客户提醒 → 今日待办
""".strip()


def _build_agent_identity(company_name: str, identity_data: dict) -> str:
    """根据用户输入构建 agent_identity_md 文本。

    参数：
        identity_data: {
            "role": "AI 销售助手",
            "products": "...",
            "differentiation": "...",
            "target_region": "..."
        }
        如果任何字段为空，使用默认值。
    """
    return _DEFAULT_AGENT_IDENTITY_TEMPLATE.format(
        company_name=company_name or "（公司名称未设置）",
        products=identity_data.get("products", "各类工业产品"),
        differentiation=identity_data.get("differentiation", "源头工厂，性价比高"),
        target_region=identity_data.get("target_region", "全球市场"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# One-step onboarding: 创建公司 + 配置 Agent 身份
# ─────────────────────────────────────────────────────────────────────────────

def create_first_company(
    company_name: str,
    contact_name: str = "",
    contact_email: str = "",
    identity_data: dict | None = None,
    *,
    work_dir_name: str = "",
) -> dict:
    """创建第一个公司并配置其 Agent 身份（原子操作）。

    参数：
        company_name: 公司名称（必填）
        contact_name: 联系人姓名（可选）
        contact_email: 联系人邮箱（可选）
        identity_data: Agent 身份配置字典（可选），
            含 role/products/differentiation/target_region
        work_dir_name: 桌面工作目录名称（目录已存在时用户指定的新名字）

    返回：
        {"company": {...}, "trade_company": {...}}

    异常：
        ValueError: company_name 为空，或公司已存在
    """
    if not company_name or not company_name.strip():
        raise ValueError("company_name 不能为空")

    # 构建 agent_identity_md（用模板 + 用户输入填充）
    agent_identity = _build_agent_identity(
        company_name.strip(),
        identity_data or {},
    )

    # Step 1: 创建公司记录 + 桌面工作目录 + 文档库
    company = _company_module.create(
        name=company_name.strip(),
        contact_name=contact_name.strip(),
        contact_email=contact_email.strip(),
        work_dir_name=work_dir_name,
    )

    # Step 2: 将 agent_identity_md 写入 trade_companies（覆盖空值）
    trade_company = _company_module.update_trade_company(
        company_id=company["id"],
        agent_identity_md=agent_identity,
    )

    # Step 3: 将 agent_identity 写入公司目录下的标准文件
    # 路径由 trade.prompts.write_agent_identity 统一决定（~/.trade/{slug}/companies/{slug}/agent-identity.md），
    # 这里不自己拼路径 —— 历史上两边各拼一份、拼出不同结果，导致读取方永远读不到写入的文件
    slug = company.get("slug", "")
    if slug:
        from trade.prompts import write_agent_identity
        write_agent_identity(slug, agent_identity)

    # 更新进程级标志
    global _onboarding_done
    _onboarding_done = True

    return {
        "company": company,
        "trade_company": trade_company,
    }
