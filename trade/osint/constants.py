"""
Trade AI Assistant — OSINT 模块：常量和共享工具。

包含个人邮箱域名黑名单、免费建站平台列表、制裁名单来源、
HTTP 工具函数等各子模块共享的数据。
"""

from __future__ import annotations

import http.client
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

import ipaddress
import socket
import urllib.parse

# 内网 / 保留 / 云元数据网段（IPv4 + IPv6）。
# 100.64.0.0/10 是运营商级 NAT，阿里云元数据 100.100.100.200 就在这里。
_BLOCKED_NETS = [
    ipaddress.ip_network(n) for n in (
        # IPv4
        "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
        "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.168.0.0/16",
        # 注意：不要加 198.18.0.0/15 —— 部分代理/基准测试环境用它解析公网域名，
        # 加进来会把全部正常站点误杀（本机实测：所有域名都解析到 198.18.x.x）。
        "224.0.0.0/4", "240.0.0.0/4",
        # IPv6
        "::/128", "::1/128", "fc00::/7", "fe80::/10", "ff00::/8",
    )
]

# 单次响应最多读 2MB，防止恶意站点用超大 body 撑爆内存
_MAX_BODY_BYTES = 2_000_000


def _resolve_addresses(hostname: str) -> set[str]:
    """解析主机名的全部 A/AAAA 地址（不只第一个 IPv4）。"""
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError):
        return set()
    return {info[4][0] for info in infos if info[4]}


def _is_blocked_address(address: str) -> bool:
    """单个 IP 是否落在内网/保留网段（IPv4-mapped IPv6 先还原）。"""
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(ip in net for net in _BLOCKED_NETS)


def _is_private_host(hostname: str) -> bool:
    """检查主机名是否解析到内网/保留 IP 地址（防 SSRF）。

    - IP 字面量直接判；
    - 域名查 getaddrinfo 的**全部** A/AAAA（旧实现只看 gethostbyname 的
      第一个 IPv4，仅 AAAA 的域名会直接放行）；
    - 解析失败返回 False：连都连不上，构不成 SSRF。残余的 DNS rebinding
      （检查与连接两次解析结果不同）由重定向复查 + 失败即断缓解。
    """
    hostname = (hostname or "").strip().strip("[]").rstrip(".")
    if not hostname:
        return True
    try:
        return _is_blocked_address(hostname)
    except ValueError:
        pass
    addresses = _resolve_addresses(hostname)
    if not addresses:
        return False
    return any(_is_blocked_address(addr) for addr in addresses)


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """跟随重定向前逐跳复查目标，防止公网域名 302 到内网。"""

    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme not in ("http", "https"):
            logger.warning("Blocked redirect to unsupported scheme: %s", newurl)
            return None
        if _is_private_host(parsed.hostname or ""):
            logger.warning("SSRF blocked on redirect: %s -> %s", req.full_url, newurl)
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _PeerVerifiedMixin:
    """TCP 建连后校验对端 IP，堵住 DNS 重绑定（TOCTOU，审计 P1-4）。

    检查主机名时解析一次，`create_connection` 建连时又解析一次 —— 攻击者可以让
    第一次解析返回公网 IP、第二次返回内网 IP（DNS rebinding）。这里不接管解析
    （否则要自己处理 SNI/证书），而是在拿到 socket 后看 `getpeername()`：
    对端若是内网/保留地址，在发出任何 HTTP 请求前断开。
    """

    def _verify_peer(self) -> None:
        sock = getattr(self, "sock", None)
        if sock is None:
            return
        try:
            peer = sock.getpeername()[0]
        except OSError:
            return
        if peer and _is_blocked_address(peer):
            try:
                sock.close()
            finally:
                self.sock = None
            raise OSError(f"SSRF blocked: connected to private address {peer}")


class _PinnedHTTPConnection(_PeerVerifiedMixin, http.client.HTTPConnection):
    def connect(self) -> None:
        super().connect()
        self._verify_peer()


class _PinnedHTTPSConnection(_PeerVerifiedMixin, http.client.HTTPSConnection):
    def connect(self) -> None:
        # TLS 握手可能已发生，但业务请求尚未发出；证书校验针对原域名
        super().connect()
        self._verify_peer()


class _SafeHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PinnedHTTPConnection, req)


class _SafeHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PinnedHTTPSConnection, req, context=self._context)


_SAFE_OPENER = urllib.request.build_opener(
    _SafeRedirectHandler(), _SafeHTTPHandler(), _SafeHTTPSHandler(),
)


def http_get(url: str, timeout: int = 30) -> str | None:
    """通过 urllib 发送 HTTP GET 请求，返回响应正文。

    所有子模块统一使用此函数，失败时返回 None 而非抛异常。
    SSRF 防护：初始 URL + 每次重定向都检查内网/保留 IP。
    """
    host = urllib.parse.urlparse(url).hostname or ""
    if _is_private_host(host):
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
        with _SAFE_OPENER.open(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read(_MAX_BODY_BYTES).decode(charset, errors="replace")
    except Exception as e:
        logger.debug("HTTP GET 失败 [%s]: %s", url, e)
        return None
