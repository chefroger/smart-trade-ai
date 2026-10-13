"""
Trade AI Assistant — OSINT 模块：常量和共享工具。

包含个人邮箱域名黑名单、免费建站平台列表、制裁名单来源、
HTTP 工具函数等各子模块共享的数据。
"""

from __future__ import annotations

import logging
import urllib.request

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 个人邮箱域名黑名单（用于检测非企业邮箱）
# ─────────────────────────────────────────────────────────────────────────────

PERSONAL_EMAIL_DOMAINS: set[str] = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "live.com", "msn.com", "aol.com", "icloud.com", "me.com",
    "qq.com", "163.com", "126.com", "sina.com", "tom.com",
    "yeah.net", "sohu.com", "mail.com", "gmx.com", "protonmail.com",
    "yandex.com", "zoho.com", "fastmail.com", "tutanota.com",
    "foxmail.com", "139.com", "wo.cn", "189.cn",
    "googlemail.com", "ymail.com", "inbox.com", "mail.ru",
}

# ─────────────────────────────────────────────────────────────────────────────
# 免费/临时建站平台（技术栈红旗）
# ─────────────────────────────────────────────────────────────────────────────

FREE_PLATFORMS: set[str] = {
    "wordpress.com", "blogspot.com", "wix.com", "squarespace.com",
    "weebly.com", "shopify.com", "tilda.cc", "webflow.com",
    "blogger.com", "livejournal.com",
    "webnode.com", "site123.com", "strikingly.com", "duda.co",
    "carrd.co", "linktr.ee", "about.me", "format.com",
}
# 注意 **不要**把 wordpress.org 加回来：它是自建 WordPress 程序的官网，不是
# 「托管建站平台」。自建站的企业页脚常带 "Powered by WordPress"（链到
# wordpress.org）→ 会被误判成"免费建站、低预算"，污染这个红旗的语义。
# 自建 WordPress 的识别由 tech_stack 的技术检测负责（"WordPress" 进
# technologies / platforms，是中性信号，不是红旗）。

# ─────────────────────────────────────────────────────────────────────────────
# 制裁名单来源（公开 CSV URL，定期需更新）
# ─────────────────────────────────────────────────────────────────────────────

SANCTIONS_SOURCES: list[dict] = [
    {
        "name": "OFAC",
        "label": "美国 OFAC SDN 列表",
        "url": "https://ofac.treasury.gov/specially-designated-nationals-and-blocked-persons-list-sdn-human-readable-lists/sdn.csv",
        "encoding": "utf-8",
    },
    {
        "name": "UN",
        "label": "联合国安理会制裁名单",
        "url": "https://www.un.org/securitycouncil/sanctions/1267/aq_sanctionslist.shtml",
        "encoding": "utf-8",
    },
    {
        "name": "EU",
        "label": "欧盟制裁名单",
        "url": "https://data.europa.eu/euodp/en/data/dataset/consolidated-list-of-persons-groups-and-entities",
        "encoding": "utf-8",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# HTTP 工具函数（共享给 sanctions / tech_stack / linkedin）
# ─────────────────────────────────────────────────────────────────────────────

def _is_private_host(hostname: str) -> bool:
    """检查主机名是否解析到内网/保留 IP 地址（防 SSRF）。

    供 http_get() 和 tech_stack 等直接使用 urlopen 的模块共享。
    """
    import ipaddress
    import socket

    _BLOCKED_NETS = [
        ipaddress.ip_network(n) for n in (
            "10.0.0.0/8", "127.0.0.0/8", "169.254.0.0/16",
            "172.16.0.0/12", "192.168.0.0/16", "0.0.0.0/8",
            "224.0.0.0/4", "240.0.0.0/4",
        )
    ]
    try:
        try:
            addr = ipaddress.ip_address(hostname)
        except ValueError:
            addr = ipaddress.ip_address(socket.gethostbyname(hostname))
    except (ValueError, socket.gaierror, OSError):
        return False  # 无法解析时放行（让 urlopen 自己报错）
    return any(addr in net for net in _BLOCKED_NETS)


def http_get(url: str, timeout: int = 30) -> str | None:
    """通过 urllib 发送 HTTP GET 请求，返回响应正文。

    所有子模块统一使用此函数，失败时返回 None 而非抛异常。
    内置 SSRF 防护：通过 _is_private_host() 拒绝内网/保留 IP。
    """
    from urllib.parse import urlparse

    _host = urlparse(url).hostname or ""
    if _is_private_host(_host):
        logger.warning("SSRF blocked: %s", url)
        return None

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; Trade-AI/1.0; +https://github.com)",
                "Accept": "*/*",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")
    except Exception as e:
        logger.debug("HTTP GET 失败 [%s]: %s", url, e)
        return None
