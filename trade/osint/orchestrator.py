"""
Trade AI Assistant — OSINT 编排器：完整尽职调查流程。

osint_full_check() 是 OSINT 模块的统一入口，接收邮箱/域名/公司名，
自动识别类型后依次执行 6 层检测，最终输出综合风险评分报告。
"""

from __future__ import annotations

import asyncio
import re

from trade import email_intel
from trade.osint.email_verify import verify_corporate_email
from trade.osint.linkedin_verify import linkedin_company_verify
from trade.osint.sanctions import check_sanctions
from trade.osint.scoring import compute_risk_score, generate_recommendations
from trade.osint.tech_stack import detect_tech_stack
from trade.osint.whois import domain_whois


async def osint_full_check(
    target: str,
    *,
    include_sanctions: bool = True,
    include_tech_stack: bool = True,
    include_linkedin: bool = True,
) -> dict:
    """完整 OSINT 尽职调查（异步编排，LLM 友好）。

    接收邮箱 / 域名 / 公司名，自动识别类型，依次执行各层检测，
    最终输出综合风险评分报告。

    Args:
        target: 邮箱 / 域名 / 公司名（自动识别）
        include_sanctions: 是否包含制裁名单筛查（默认 True）
        include_tech_stack: 是否包含技术栈检测（默认 True）
        include_linkedin: 是否包含 LinkedIn 验证（默认 True）

    Returns:
        完整报告 dict，结构见需求文档 3.11.8 节：
        {
            "target": str,
            "target_type": str,       # "email" | "domain" | "url" | "company"
            "overall_rating": str,    # "low" | "medium" | "high" | "unknown"
            "overall_score": int,     # 0-100
            "flags": list[str],       # 红旗标记列表
            "layers": {               # 各层检测结果
                "email_registration": dict | None,
                "domain_intel": dict,
                "email_verification": dict | None,
                "tech_stack": dict | None,
                "sanctions": dict | None,
                "linkedin": dict | None,
            },
            "recommendations": list[str],  # 行动建议
        }
    """
    target = target.strip()
    target_type = _detect_target_type(target)

    report: dict = {
        "target": target,
        "target_type": target_type,
        "overall_rating": "unknown",
        "overall_score": 0,
        "flags": [],
        "layers": {},
        "recommendations": [],
    }

    # ── 确定用于域名查询的目标 ──
    loop = asyncio.get_running_loop()

    if target_type == "email":
        # 从邮箱提取域名，用于后续各层检测
        domain_from_email = target.split("@", 1)[1]
    else:
        # 非邮箱目标，无需从邮箱提取域名
        domain_from_email = None

    lookup_domain = _extract_lookup_domain(target, target_type, domain_from_email)

    # ── Layer 1: Email registration (holehe) ─────────────────────────────
    if target_type == "email":
        # 目标为邮箱时，执行 holehe 注册检测
        email_result = await _run_email_check(target)
        report["layers"]["email_registration"] = email_result
    else:
        # 非邮箱目标，跳过邮箱注册检测
        report["layers"]["email_registration"] = None

    # ── Layer 2: WHOIS 域名查询（放入 executor 避免阻塞事件循环）─────────
    if lookup_domain:
        whois_result = await loop.run_in_executor(None, domain_whois, lookup_domain)
        report["layers"]["domain_intel"] = whois_result

        if whois_result.get("age_category") == "new":
            report["flags"].append("domain_age_new")
        if whois_result.get("days_old") and whois_result["days_old"] > 3650:
            report["flags"].append("domain_age_old")
    else:
        report["layers"]["domain_intel"] = {
            "skipped": True, "reason": "Company target — domain discovery requires web search first"
        }

    # ── Layer 3: 企业邮箱验证 ───────────────────────────────────────────
    if target_type == "email":
        # 目标为邮箱时，验证是否为企业邮箱
        # 放入 executor 以避免 DNS socket 调用阻塞事件循环
        email_verify_result = await loop.run_in_executor(None, verify_corporate_email, target)
        report["layers"]["email_verification"] = email_verify_result

        # 按**具体红旗**映射到评分用的标记名。
        # 历史上这里把任何 risk_flag 一律写成 "personal_email_domain" ——
        # 于是"域名没有 MX 记录"也被标成"个人邮箱"，扣分理由与事实不符。
        report["flags"].extend(_map_email_flags(email_verify_result.get("risk_flags") or []))
    else:
        # 非邮箱目标，跳过企业邮箱验证
        report["layers"]["email_verification"] = None

    # ── Layer 4 (可选): 技术栈检测 ─────────────────────────────────────
    if include_tech_stack and lookup_domain:
        # 用户选择检测技术栈且存在可查询域名时，执行 BuiltWith 风格检测
        # 放入 executor 以避免 HTTP 请求阻塞事件循环
        tech_result = await loop.run_in_executor(None, detect_tech_stack, f"https://{lookup_domain}")
        report["layers"]["tech_stack"] = tech_result

        if tech_result.get("is_free_platform"):
            # 网站使用免费建站工具（如 Wix/Shopify），可能为低预算公司
            report["flags"].append("free_platform")
    else:
        # 用户关闭技术栈检测或缺少域名，跳过此层
        report["layers"]["tech_stack"] = None

    # ── Layer 5 (可选): 制裁名单筛查 ───────────────────────────────────
    if include_sanctions:
        # 用户选择制裁筛查时，用域名或原始目标进行匹配
        sanctions_name = domain_from_email or target
        # 制裁筛查可能涉及文件下载，放入 executor
        sanctions_result = await loop.run_in_executor(None, check_sanctions, sanctions_name)
        report["layers"]["sanctions"] = sanctions_result

        if sanctions_result.get("is_sanctioned"):
            # 目标出现在制裁名单中，标记为严重风险
            report["flags"].append("sanctioned")
    else:
        # 用户关闭制裁筛查，跳过此层
        report["layers"]["sanctions"] = None

    # ── Layer 6: LinkedIn 验证（生成 browser_navigate 指令）─────────────
    if include_linkedin and lookup_domain:
        # 用户选择 LinkedIn 验证且存在可查询域名时，生成浏览器导航指令
        # 当 target 不是公司名时（如 email），用域名作为公司名线索
        _company_hint = target if target_type == "company" else lookup_domain
        linkedin_result = linkedin_company_verify(lookup_domain, _company_hint)
        report["layers"]["linkedin"] = linkedin_result
        # LinkedIn 验证通过 Hermes browser_navigate 执行，无网络请求风险
        # 此处不做自动评分（需 Agent 实际执行后人工/LLM 判断）
    else:
        # 用户关闭 LinkedIn 验证或缺少域名，跳过此层
        report["layers"]["linkedin"] = None

    # ── 综合评分 ───────────────────────────────────────────────────────
    score, rating = compute_risk_score(report["flags"])
    report["overall_score"] = score
    report["overall_rating"] = rating

    # ── 生成建议 ───────────────────────────────────────────────────────
    report["recommendations"] = generate_recommendations(report)

    return report


# ─────────────────────────────────────────────────────────────────────────────
# 内部 helpers
# ─────────────────────────────────────────────────────────────────────────────

# 邮箱验证的中文红旗 → 评分用的标记名。
# 必须逐条对应：不同红旗的证据强度不同、扣分也不同（见 scoring._deductions）。
_EMAIL_FLAG_MAP = {
    "使用个人邮箱域名": "personal_email_domain",
    "域名未检测到 MX 记录（可能是假域名）": "no_mx_record",
    "邮箱域名与网站域名不一致": "email_domain_mismatch",
}


def _map_email_flags(risk_flags: list[str]) -> list[str]:
    """把邮箱验证层的中文红旗翻译成评分层的标记名。

    未识别的红旗不丢弃：转成 ``email_<hash>`` 会污染评分表，改为忽略并
    依赖该层自己的 suggestion 字段披露（scoring 是白名单制，未知标记本就扣默认分，
    这里选择不臆造语义）。
    """
    return [_EMAIL_FLAG_MAP[f] for f in risk_flags if f in _EMAIL_FLAG_MAP]


def _extract_lookup_domain(target: str, target_type: str, domain_from_email: str | None) -> str | None:
    """从目标中提取用于 WHOIS / 技术栈检测的域名。

    公司名无法直接提取域名（需先搜索发现官网），返回 None。
    URL 使用 urllib.parse 精确解析，避免路径参数残留。
    """
    if domain_from_email:
        return domain_from_email

    if target_type == "url":
        from urllib.parse import urlparse
        parsed = urlparse(target)
        netloc = parsed.netloc.lower().removeprefix("www.")
        return netloc or None

    if target_type == "domain":
        return target.lower().removeprefix("www.")

    # company / unknown — 无法直接提取域名
    return None


def _detect_target_type(target: str) -> str:
    """自动识别目标类型：email / domain / url / company。

    识别规则：
      - 含 @ → email
      - 含 http(s):// → url
      - 符合域名格式 (含 . 和合法 TLD) → domain
      - 否则 → company
    """
    target = target.strip()
    if "@" in target and "." in target.split("@", 1)[1]:
        # 含 @ 且 @ 后有 . → 视为邮箱地址
        return "email"
    if target.startswith(("http://", "https://")):
        # 以 http(s):// 开头 → 视为 URL
        return "url"
    if re.match(r"^[a-z0-9]([a-z0-9-]+\.)+[a-z]{2,}$", target.lower()):
        # 符合标准域名格式（如 example.com）→ 视为域名
        return "domain"
    # 以上都不匹配 → 视为公司名称
    return "company"


async def _run_email_check(email: str) -> dict:
    """在线程池中运行 holehe 邮箱检测（同步 → 异步适配）。

    email_intel.email_background_check 是同步的，不适合在 async 上下文中直接调用，
    所以放到 executor 中执行。
    """
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None, email_intel.email_background_check, email
        )
        return result
    except Exception as e:
        # holehe 执行失败（网络超时、API 异常等），返回带错误信息的空结果
        return {"error": str(e), "checked_count": 0, "found_count": 0}
