"""
Trade AI Assistant — OSINT Layer 5: 技术栈检测（BuiltWith-style）。

通过 HTTP 响应头和 HTML 内容正则匹配，检测网站使用的技术栈、
平台类型和 SSL 状态。纯 urllib + re 实现，无需第三方库。
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request

from trade.osint.constants import FREE_PLATFORMS, _is_private_host


def detect_tech_stack(url: str) -> dict:
    """BuiltWith 风格技术栈检测。

    通过 HTTP 请求获取页面 HTML 和响应头，用正则匹配检测技术栈特征。

    Args:
        url: 网站 URL（如 "https://example.com"，自动补全协议）

    Returns:
        {
            "url": str,
            "technologies": list[str],        # 检测到的技术列表
            "platforms": list[str],           # 平台类型（Shopify / WordPress 等）
            "is_free_platform": bool,        # True = 🚩 免费建站工具
            "is_enterprise": bool,            # True = ✅ 企业级平台
            "ssl_valid": bool,               # SSL 证书是否有效
            "server": str | None,            # 服务器类型（如 nginx/apache）
            "error": str | None,
        }
    """
    # 自动补全协议
    if not url.startswith(("http://", "https://")):
        # 用户未输入协议前缀，默认添加 HTTPS
        url = "https://" + url

    result: dict = {
        "url": url,
        "technologies": [],
        "platforms": [],
        "is_free_platform": False,
        # 默认 False：只有真的抓到页面并检出企业级技术时才置 True（见下方
        # `any(t in technologies for t in enterprise_indicators)`）。
        # 历史上这里默认 True —— 抓取失败时 except 只写 error、不改这个值，
        # 于是报告输出「✅ 网站使用企业级技术栈，可信度 +1」：**域名被墙反而加分**。
        "is_enterprise": False,
        "ssl_valid": False,
        "server": None,
        "error": None,
    }

    try:
        # SSRF 防护：拒绝访问内网/保留 IP
        parsed = urllib.parse.urlparse(url)
        hostname = parsed.hostname or ""
        if _is_private_host(hostname):
            result["error"] = f"Blocked: {hostname} resolves to a private/reserved IP"
            return result

        # 防御性 socket 超时（urlopen timeout=15 已覆盖大部分场景）
        import socket
        socket.setdefaulttimeout(15)

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Trade-AI/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result["ssl_valid"] = True
            # 从响应头提取服务器信息
            server_header = resp.headers.get("Server", "")
            if server_header:
                # HTTP 响应头中包含 Server 字段，记录服务器类型
                result["server"] = server_header

            html_content = resp.read().decode("utf-8", errors="replace")

        # 从 HTML 中检测技术栈特征
        technologies = _detect_technologies(html_content)

        # 判断是否为免费建站平台
        free_platforms_detected = [
            t for t in technologies
            if t.lower() in [p.lower() for p in FREE_PLATFORMS]
        ]
        result["is_free_platform"] = len(free_platforms_detected) > 0

        # 识别建站平台类别
        platform_names = {
            "Shopify", "WooCommerce", "Wix", "Squarespace", "WordPress", "Drupal",
            "Joomla", "Webflow", "Strikingly",
        }
        result["platforms"] = [t for t in technologies if t in platform_names]

        # 企业级判断：有 Stripe/PayPal/HubSpot/Salesforce 等企业级服务
        enterprise_indicators = [
            "Stripe", "PayPal", "HubSpot", "Salesforce", "Marketo",
            "Zendesk", "Cloudflare", "Akamai",
        ]
        # 检测到企业级服务（Stripe/PayPal/HubSpot/Salesforce 等），标注为企业级客户
        result["is_enterprise"] = any(t in technologies for t in enterprise_indicators)

        result["technologies"] = technologies[:30]  # 最多 30 个

    except Exception as exc:
        # HTTP 请求失败（超时、DNS 解析错误、SSL 问题等），记录错误信息
        result["error"] = str(exc)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 技术栈检测模式表
# ─────────────────────────────────────────────────────────────────────────────

# 支持的技术检测模式：正则 → 技术名
_TECH_PATTERNS: list[tuple[str, str]] = [
    # 建站平台
    (r"shopify", "Shopify"),
    (r"wp-content|wp-includes|wordpress", "WordPress"),
    (r"wix\.com", "Wix"),
    (r"squarespace", "Squarespace"),
    (r"strikingly", "Strikingly"),
    (r"woocommerce", "WooCommerce"),
    (r"drupal", "Drupal"),
    (r"joomla", "Joomla"),
    (r"laravel", "Laravel"),
    # 前端框架
    (r"react|reactjs", "React"),
    (r"vue\.js|vuejs", "Vue.js"),
    (r"angular", "Angular"),
    (r"next\.js", "Next.js"),
    (r"bootstrap", "Bootstrap"),
    (r"tailwind", "Tailwind CSS"),
    (r"jquery", "jQuery"),
    # CDN / 安全
    (r"cloudflare", "Cloudflare"),
    (r"akamai", "Akamai"),
    (r"fastly", "Fastly"),
    # 支付
    (r"stripe", "Stripe"),
    (r"paypal", "PayPal"),
    # 分析 / 营销
    (r"google-tag-manager|googletagmanager", "Google Tag Manager"),
    (r"google-analytics|analytics\.js|ga\.js", "Google Analytics"),
    (r"facebook\.com/tr", "Facebook Pixel"),
    (r"hotjar", "Hotjar"),
    (r"hubspot", "HubSpot"),
    (r"marketo", "Marketo"),
    # CRM / 客服
    (r"zendesk", "Zendesk"),
    (r"salesforce", "Salesforce"),
    (r"shopify-api|shopify-checkout", "Shopify API"),
]


def _detect_technologies(html_content: str) -> list[str]:
    """从 HTML 内容中检测技术栈特征。

    Args:
        html_content: 网页 HTML 文本

    Returns:
        去重后的技术名列表
    """
    html_lower = html_content.lower()
    technologies: list[str] = []

    for pattern, tech_name in _TECH_PATTERNS:
        if re.search(pattern, html_lower, re.IGNORECASE):
            # 正则匹配到技术特征，且尚未添加到列表时，追加技术名
            if tech_name not in technologies:
                technologies.append(tech_name)

    return technologies
