"""
Trade AI Assistant — OSINT Layer 3: 企业邮箱验证。

判断邮箱是企业邮箱 (@公司域名) 还是个人邮箱 (@gmail/@qq等)，
并通过 DNS MX 记录查询验证域名是否配置了邮件服务器。
"""

from __future__ import annotations

import logging
import re

from trade.osint.constants import PERSONAL_EMAIL_DOMAINS

logger = logging.getLogger(__name__)


def verify_corporate_email(email: str, website: str | None = None) -> dict:
    """验证企业邮箱 vs 个人邮箱。

    Args:
        email: 邮箱地址（如 "john@acme.com"）
        website: 可选，公司网站（用于域名交叉验证）

    Returns:
        {
            "email": str,
            "domain": str,                     # 邮箱域名
            "is_personal": bool,              # True = 🚩 个人邮箱
            "is_corporate": bool,             # True = ✅ 企业邮箱
            "risk_flag": bool,               # True = 🚩 红旗
            "domain_match": bool | None,      # website 提供时：域名是否一致
            "mx_found": bool,                # 是否检测到 MX 记录
            "mx_servers": list[str],         # MX 服务器列表
            "risk_flags": list[str],         # 风险标记详情
            "suggestion": str,                # 行动建议
        }
    """
    email = email.strip().lower()
    # 邮箱格式校验
    if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
        # 邮箱格式不合法，返回无效状态
        return {
            "email": email, "domain": "", "is_personal": False,
            "is_corporate": False, "risk_flag": False,
            "domain_match": None, "mx_found": False, "mx_servers": [],
            "risk_flags": [], "suggestion": "邮箱格式无效",
        }

    # 提取域名
    email_domain = email.split("@", 1)[1]
    email_domain = email_domain.lower()

    # 判断是否个人邮箱域名
    is_personal = email_domain in PERSONAL_EMAIL_DOMAINS

    # 企业邮箱：非个人域名，且有一定长度（排除如 "a.co" 等短域名误判）
    is_corporate = not is_personal and len(email_domain) > 4

    # MX 记录查询（通过 socket DNS-over-UDP）
    mx_found = False
    mx_servers: list[str] = []
    mx_error: str | None = None
    if is_corporate:
        mx_servers, mx_found, mx_error = _query_mx_records(email_domain)

    # 域名一致性验证（如果提供了 website）
    domain_match: bool | None = None
    if website:
        # 提取 website 的域名并与邮箱域名比较
        website_domain = _extract_domain(website)
        if website_domain:
            # 邮箱域名与网站域名一致则为 True，否则为 False
            domain_match = email_domain == website_domain

    # 综合判断红旗
    risk_flags: list[str] = []
    if is_personal:
        # 个人邮箱域名，红旗标记
        risk_flags.append("使用个人邮箱域名")
    if not mx_found and is_corporate and not mx_error:
        # 企业域名且**确实查过**、没有 MX 记录 → 可能是假域名。
        # mx_error 非空时说明查询本身失败了（DNS 抖动/被墙），此时不能下这个判断。
        risk_flags.append("域名未检测到 MX 记录（可能是假域名）")
    if domain_match is False:
        # 邮箱域名与网站域名不一致，红旗标记
        risk_flags.append("邮箱域名与网站域名不一致")

    # 行动建议（分场景）
    if is_personal:
        # 个人邮箱场景：建议要求企业邮箱
        suggestion = "要求对方提供企业邮箱后再深入谈判。个人邮箱无法确认公司真实性。"
    elif domain_match is False:
        # 域名不匹配场景：建议交叉验证
        suggestion = "邮箱域名与网站域名不匹配，建议交叉验证对方公司身份。"
    elif mx_error:
        # 查询失败场景：既不能夸也不能贬，如实说明未验证
        suggestion = f"MX 记录未能验证（{mx_error}），建议稍后重试或换网络环境再查。"
    elif not mx_found:
        # 无 MX 记录场景：建议谨慎
        suggestion = "域名未找到 MX 邮件服务器，建议谨慎跟进，要求更多公司证明文件。"
    else:
        # 所有验证通过场景
        suggestion = "企业邮箱验证通过，域名匹配且 MX 记录正常。"

    return {
        "email": email,
        "domain": email_domain,
        "is_personal": is_personal,
        "is_corporate": is_corporate,
        "risk_flag": bool(risk_flags),
        "domain_match": domain_match,
        "mx_found": mx_found,
        "mx_servers": mx_servers,
        # 查询失败的原因（None = 查询成功）。上层据此区分"没有记录"与"没查成"。
        "mx_error": mx_error,
        "risk_flags": risk_flags,
        "suggestion": suggestion,
    }


def _extract_domain(url_or_domain: str) -> str | None:
    """从 URL 或域名中提取干净的主域名。"""
    val = url_or_domain.strip().lower()
    val = re.sub(r"^https?://", "", val)
    val = val.rstrip("/").split("/")[0]
    val = re.sub(r"^www\.", "", val)
    if val and "." in val:
        return val
    # 没有点号分隔，不是合法域名
    return None


# ─────────────────────────────────────────────────────────────────────────────
# DNS MX 查询（dnspython，替代手动 RFC 1035 socket 实现）
# ─────────────────────────────────────────────────────────────────────────────

def _query_mx_records(domain: str) -> tuple[list[str], bool, str | None]:
    """查询 MX 记录。返回 ``(mx_servers, mx_found, mx_error)``。

    **mx_error 非空表示"查询本身失败"**（超时/无可用 DNS/dnspython 缺失），
    与"域名确实没有 MX 记录"（返回 ``([], False, None)``）必须区分开 ——
    否则一次 DNS 抖动就会被当成"假域名"信号，客户被误判。

    把 impl 单独拆出来是为了给测试一个稳定的接缝（monkeypatch 它即可覆盖
    两条分支，不必依赖真实 DNS）。
    """
    try:
        return _query_mx_records_impl(domain)
    except Exception as e:
        logger.debug("MX query failed for %s: %s", domain, e)
        return [], False, f"MX 查询失败：{e}"


def _query_mx_records_impl(domain: str) -> tuple[list[str], bool, str | None]:
    """真实查询实现。抛出的异常由 ``_query_mx_records`` 统一转成 mx_error。"""
    import dns.resolver  # ImportError 也由上层转成 mx_error（dnspython 缺失）

    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=5)
    except dns.resolver.NXDOMAIN:
        # 域名根本不存在 —— 这是真实的"查不到"，照常出红旗
        return [], False, None
    except dns.resolver.NoAnswer:
        # 域名存在但没有 MX 记录 —— 真实的假域名信号
        return [], False, None

    mx_servers = [str(r.exchange).rstrip(".") for r in answers]
    return mx_servers, len(mx_servers) > 0, None

