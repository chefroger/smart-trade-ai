"""
Trade AI Assistant — 公共平台域名与网址分类器（M1）。

提供确定性的域名/URL 分类能力，服务于两类场景：
  1. 背调（OSINT）：识别公共邮箱、B2B 撮合平台、建站托管子域名、公共社媒平台，
     跳过仅对「目标自有域名」有意义的检测层（WHOIS / 技术栈 / RDAP / CT / Wayback / pDNS），
     避免把平台注册信息误当成目标公司证据；同时对平台店铺 URL 尝试推断候选店铺名。
  2. 找客户 / 找供应商（classify_urls 插件工具）：
     - purpose="customer"：给非企业官网来源打标签并折叠到「其他来源」，绝不静默删除；
     - purpose="supplier"：B2B 平台店铺标为「平台店铺」正常展示。

匹配纪律：
  - 域名全部按点分隔标签后缀精确匹配（如 alibaba.com 命中 abc.en.alibaba.com，
    但绝不误判 notalibaba.com）；无外部 publicsuffix 依赖，使用标签级后缀规则，
    局限在于非常规多段国别后缀需在清单中显式列出（如 europages.co.uk）。
  - 保留域名（example.* / .test / .invalid / .localhost）直接复用
    orchestrator.is_reserved_domain，不另写一份。
"""

from __future__ import annotations

import logging
import os
import re
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# ==============================================================================
# 内置兜底清单（数据文件损坏或缺失时回退，确保背调永不因配置失败）
# ==============================================================================

_BUILTIN_DATA_PATH = Path(__file__).resolve().parent / "data" / "platform_domains.toml"

_FALLBACK_DOMAINS: dict[str, tuple[str, ...]] = {
    "free_mail": (
        "gmail.com", "googlemail.com", "yahoo.com", "ymail.com",
        "hotmail.com", "outlook.com", "live.com", "msn.com",
        "aol.com", "icloud.com", "me.com",
        "qq.com", "foxmail.com", "163.com", "126.com", "yeah.net",
        "sina.com", "sohu.com", "tom.com", "139.com", "wo.cn", "189.cn",
        "mail.com", "gmx.com", "protonmail.com", "proton.me",
        "yandex.com", "zoho.com", "fastmail.com", "tutanota.com",
        "inbox.com", "mail.ru",
    ),
    "b2b_marketplace": (
        "alibaba.com", "1688.com", "made-in-china.com", "globalsources.com",
        "dhgate.com", "indiamart.com", "tradeindia.com", "tradekey.com",
        "ec21.com", "ecplaza.net", "europages.com", "europages.co.uk",
        "kompass.com", "thomasnet.com", "directindustry.com",
        "amazon.com", "amazon.co.uk", "amazon.de", "amazon.co.jp",
        "ebay.com", "aliexpress.com", "etsy.com", "walmart.com",
        "mercadolibre.com", "shopee.com", "lazada.com",
        "ozon.ru", "wildberries.ru", "faire.com",
    ),
    "trade_data": (
        "importyeti.com", "panjiva.com", "importgenius.com", "volza.com",
        "tendata.cn", "tridge.com", "eximpedia.app", "zauba.com",
        "exportgenius.in", "datamyne.com", "tradesparq.com", "seair.co.in",
        "customsinfo.com", "52wmb.com",
    ),
    "directory": (
        "yellowpages.com", "yelp.com", "dnb.com", "crunchbase.com",
        "zoominfo.com", "apollo.io", "opencorporates.com", "bbb.org",
        "manta.com", "hotfrog.com", "cylex.us.com", "yell.com",
        "trustpilot.com", "bizapedia.com", "f6s.com",
        "qcc.com", "tianyancha.com", "qixin.com", "aiqicha.baidu.com",
    ),
    "research_press": (
        "statista.com", "grandviewresearch.com", "marketsandmarkets.com",
        "fortunebusinessinsights.com", "mordorintelligence.com",
        "researchandmarkets.com", "imarcgroup.com", "precedenceresearch.com",
        "globenewswire.com", "prnewswire.com", "businesswire.com",
        "reuters.com", "bloomberg.com", "wikipedia.org",
        "medium.com", "substack.com", "forbes.com", "techcrunch.com",
    ),
    "site_builder_subdomain": (
        "wixsite.com", "blogspot.com", "wordpress.com", "weebly.com",
        "myshopify.com", "squarespace.com", "webflow.io", "strikingly.com",
        "carrd.co", "tilda.ws", "tilda.cc", "webnode.com", "site123.me",
        "github.io", "pages.dev", "netlify.app", "vercel.app",
        "notion.site", "sites.google.com", "linktr.ee", "about.me",
    ),
    "social_hosts": (
        "linkedin.com", "facebook.com", "instagram.com",
        "x.com", "twitter.com", "youtube.com", "tiktok.com",
        "reddit.com", "pinterest.com", "weibo.com", "zhihu.com", "quora.com",
    ),
    "recruitment_hosts": (
        "indeed.com", "glassdoor.com", "monster.com", "ziprecruiter.com",
        "bosszhipin.com", "zhaopin.com", "51job.com", "liepin.com",
        "lever.co", "greenhouse.io", "workday.com", "myworkdayjobs.com",
    ),
}

_FALLBACK_PATHS: dict[str, tuple[str, ...]] = {
    "recruitment": (
        "/careers", "/career", "/jobs", "/job",
        "/hiring", "/join-us", "/vacancies", "/recruitment", "/open-positions",
    ),
    "social_content": (
        "/posts", "/post", "/feed", "/reel", "/reels",
        "/status", "/watch", "/shorts", "/p", "/groups", "/r", "/comments", "/pulse",
    ),
}

# 背调时应跳过「目标自有域名专属层」（WHOIS / 技术栈 / RDAP / CT / Wayback / pDNS）的类别
PLATFORM_SKIP_DOMAIN_CATEGORIES: frozenset[str] = frozenset({
    "free_mail",
    "b2b_marketplace",
    "site_builder_subdomain",
    "social_content",
})

# 面向用户的中文类型标签（供 classify_urls 工具与前端/报告展示）
CATEGORY_LABELS: dict[str, str] = {
    "normal": "企业官网",
    "reserved": "保留示例域名",
    "free_mail": "公共邮箱",
    "b2b_marketplace": "B2B 平台",
    "trade_data": "贸易数据站",
    "directory": "企业目录/黄页",
    "research_press": "研究报告/媒体",
    "recruitment_page": "招聘页",
    "social_content": "社媒内容页",
    "site_builder_subdomain": "免费建站子域",
}

# 从平台子域名推断店铺名时应忽略的通用前缀
_GENERIC_STORE_SUBDOMAINS: frozenset[str] = frozenset({
    "www", "m", "en", "cn", "es", "fr", "de", "jp", "kr", "ru", "pt", "ar",
    "shop", "store", "mall", "detail", "offer", "product", "products",
    "buyer", "seller", "supplier", "suppliers", "trade", "app", "web", "mobile",
})


# ==============================================================================
# 清单加载（支持用户追加/删除，损坏时安全回退）
# ==============================================================================


def _load_toml_safe(path: Path) -> dict[str, Any] | None:
    """安全读取 TOML 文件；缺失或损坏时记录告警并返回 None。"""
    if not path.exists() or not path.is_file():
        return None  # 文件不存在，交由调用方回退
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        return data if isinstance(data, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取平台域名清单失败（%s），将回退内置清单: %s", path, exc)
        return None


def _user_override_path() -> Path | None:
    """返回用户自定义平台域名覆盖文件路径（环境变量优先，其次 ~/.trade/platform_domains.toml）。"""
    env_path = os.environ.get("TRADE_PLATFORM_DOMAINS_FILE", "").strip()
    if env_path:
        return Path(env_path)  # 显式环境变量指定的覆盖文件
    trade_home = os.environ.get("TRADE_HOME", "").strip()
    if trade_home:
        return Path(trade_home) / "platform_domains.toml"  # TRADE_HOME 下的用户覆盖文件
    return Path.home() / ".trade" / "platform_domains.toml"


def load_domain_lists(
    *,
    builtin_path: Path | None = None,
    override_path: Path | None = None,
) -> tuple[dict[str, frozenset[str]], dict[str, tuple[str, ...]]]:
    """加载域名与路径分类清单（内置 TOML + 用户覆盖；异常自动回退内置常量）。"""
    base_raw = _load_toml_safe(builtin_path or _BUILTIN_DATA_PATH)

    # 1) 构建基础域名集合：优先内置 TOML，读取失败时回退内置 Python 常量
    domains_map: dict[str, set[str]] = {}
    raw_domains = (base_raw or {}).get("domains") if isinstance(base_raw, dict) else None
    for key, fallback_vals in _FALLBACK_DOMAINS.items():
        if isinstance(raw_domains, dict) and isinstance(raw_domains.get(key), list):
            # 内置 TOML 提供该类别列表时，清洗为小写无尾点域名集合
            domains_map[key] = {
                str(item).strip().lower().rstrip(".")
                for item in raw_domains[key]
                if str(item).strip()
            }
        else:
            # 缺失或损坏时回退内置兜底集合
            domains_map[key] = set(fallback_vals)

    # 2) 构建基础路径规则
    paths_map: dict[str, list[str]] = {}
    raw_paths = (base_raw or {}).get("paths") if isinstance(base_raw, dict) else None
    for key, fallback_vals in _FALLBACK_PATHS.items():
        if isinstance(raw_paths, dict) and isinstance(raw_paths.get(key), list):
            paths_map[key] = [
                str(item).strip().lower()
                for item in raw_paths[key]
                if str(item).strip()
            ]
        else:
            paths_map[key] = list(fallback_vals)

    # 3) 叠加用户覆盖文件（支持 [add] 与 [remove]）
    user_path = override_path if override_path is not None else _user_override_path()
    user_raw = _load_toml_safe(user_path) if user_path is not None else None
    if isinstance(user_raw, dict):
        add_sec = user_raw.get("add")
        if isinstance(add_sec, dict):
            # 用户追加自定义域名
            for key, items in add_sec.items():
                if key in domains_map and isinstance(items, list):
                    for item in items:
                        cleaned = str(item).strip().lower().rstrip(".")
                        if cleaned:
                            domains_map[key].add(cleaned)
        rem_sec = user_raw.get("remove")
        if isinstance(rem_sec, dict):
            # 用户移除误判域名
            for key, items in rem_sec.items():
                if key in domains_map and isinstance(items, list):
                    for item in items:
                        cleaned = str(item).strip().lower().rstrip(".")
                        if cleaned:
                            domains_map[key].discard(cleaned)

    frozen_domains = {k: frozenset(v) for k, v in domains_map.items()}
    frozen_paths = {k: tuple(v) for k, v in paths_map.items()}
    return frozen_domains, frozen_paths


# ==============================================================================
# 域名解析与标签级后缀匹配
# ==============================================================================


def _parse_host_and_path(value: str) -> tuple[str, str]:
    """从域名、URL 或邮箱中提取小写主机名与路径。"""
    raw = str(value or "").strip()
    if not raw:
        return "", ""

    # 邮箱形式：取 @ 右侧作为主机名，路径为空
    if "@" in raw and "://" not in raw and "/" not in raw:
        host = raw.split("@", 1)[1].strip().lower().rstrip(".")
        return host, ""

    # 补齐 scheme 以便 urlsplit 准确拆分 host 与 path
    candidate = raw if "://" in raw else f"https://{raw}"
    parsed = urlsplit(candidate)
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    path = (parsed.path or "").strip().lower()
    return host, path


def _matches_domain_suffix(host: str, domain_set: frozenset[str]) -> str | None:
    """按点分隔标签后缀精确匹配域名集合；命中返回匹配到的基础域名，否则 None。

    例：host="abc.en.alibaba.com" 命中 "alibaba.com"；
        host="notalibaba.com" 不命中 "alibaba.com"。
    """
    if not host:
        return None
    if host in domain_set:
        return host  # 完全一致命中
    parts = host.split(".")
    # 从最长父域到最短父域逐级检查后缀（至少保留 2 段）
    for idx in range(1, len(parts) - 1):
        suffix = ".".join(parts[idx:])
        if suffix in domain_set:
            return suffix
    return None


def _matches_path_prefix(path: str, prefixes: tuple[str, ...]) -> str | None:
    """判断路径中是否包含指定段前缀（如 /careers、/jobs/123、/posts/abc）。"""
    if not path or path == "/":
        return None
    segments = [seg for seg in path.split("/") if seg]
    if not segments:
        return None
    for prefix in prefixes:
        target_seg = prefix.strip("/")
        if not target_seg:
            continue
        # 任意路径段精确匹配（避免把 /my-jobs-guide 误判为 /jobs）
        if target_seg in segments:
            return prefix
    return None


def _infer_store_name(host: str, path: str, base_domain: str) -> str | None:
    """从 B2B 平台或建站托管子域名 URL 中推断候选店铺名。

    例：
      - https://abc.en.alibaba.com/ → "abc"
      - https://myshop.myshopify.com/ → "myshop"
      - https://www.made-in-china.com/showroom/acme-lighting/ → "acme-lighting"
    """
    # 1) 优先从子域名段提取（去掉 base_domain 后过滤通用前缀如 www/en/m）
    if host and base_domain and host != base_domain and host.endswith(f".{base_domain}"):
        sub_part = host[: -(len(base_domain) + 1)]
        sub_labels = [lb for lb in sub_part.split(".") if lb and lb not in _GENERIC_STORE_SUBDOMAINS]
        if sub_labels:
            cand = sub_labels[0]
            if len(cand) >= 2 and re.fullmatch(r"[a-z0-9][a-z0-9_-]*", cand):
                return cand

    # 2) 其次从常见店铺路径段提取（/company/<slug>、/showroom/<slug>、/supplier/<slug>、/store/<slug>）
    segments = [seg for seg in (path or "").split("/") if seg]
    for idx, seg in enumerate(segments[:-1]):
        if seg in {"company", "showroom", "supplier", "suppliers", "store", "shop", "member"}:
            cand = segments[idx + 1]
            if len(cand) >= 2 and cand not in _GENERIC_STORE_SUBDOMAINS:
                return cand
    return None


# ==============================================================================
# 核心分类函数与批量工具函数
# ==============================================================================


def classify_domain_or_url(
    value: str,
    *,
    builtin_path: Path | None = None,
    override_path: Path | None = None,
) -> dict[str, Any]:
    """对单个域名、URL 或邮箱进行确定性分类。

    Args:
        value: 域名、完整 URL 或邮箱地址
        builtin_path: 可选内置 TOML 路径（仅供测试注入）
        override_path: 可选用户覆盖 TOML 路径（仅供测试注入）

    Returns:
        {
            "category": str,             # reserved / free_mail / b2b_marketplace / trade_data /
                                         # directory / research_press / recruitment_page /
                                         # social_content / site_builder_subdomain / normal
            "reason": str,               # 面向用户的中文原因说明
            "domain": str,               # 规范化后的主机名
            "matched_base": str | None,  # 命中的基础平台域名（如有）
            "inferred_store_name": str | None,  # 平台店铺 URL 推断出的候选店铺名（如有）
        }
    """
    host, path = _parse_host_and_path(value)
    if not host:
        return {
            "category": "normal",
            "reason": "未解析出有效域名",
            "domain": "",
            "matched_base": None,
            "inferred_store_name": None,
        }

    # 1) 保留示例/测试域名：直接复用 PR #27 的 orchestrator.is_reserved_domain
    from trade.osint.orchestrator import is_reserved_domain

    if is_reserved_domain(host):
        return {
            "category": "reserved",
            "reason": f"{host} 是保留示例或测试域名，不代表真实公司",
            "domain": host,
            "matched_base": host,
            "inferred_store_name": None,
        }

    domains_map, paths_map = load_domain_lists(
        builtin_path=builtin_path,
        override_path=override_path,
    )

    # 2) 公共邮箱域名
    matched = _matches_domain_suffix(host, domains_map["free_mail"])
    if matched:
        return {
            "category": "free_mail",
            "reason": f"{host} 是公共邮箱服务，域名信息不代表目标公司",
            "domain": host,
            "matched_base": matched,
            "inferred_store_name": None,
        }

    # 3) 社媒站点：区分公司主页（normal）与招聘页/社媒内容页/裸社媒域名
    matched_social = _matches_domain_suffix(host, domains_map["social_hosts"])
    if matched_social:
        # 社媒上的招聘路径（如 linkedin.com/jobs/...）优先判为招聘页
        if _matches_path_prefix(path, paths_map["recruitment"]):
            return {
                "category": "recruitment_page",
                "reason": f"{host} 招聘页面，非企业官网主体",
                "domain": host,
                "matched_base": matched_social,
                "inferred_store_name": None,
            }
        # LinkedIn 公司主页（linkedin.com/company/<slug> 且非帖子/动态路径）是有用企业证据，判为 normal
        if (
            matched_social == "linkedin.com"
            and path.startswith("/company/")
            and not _matches_path_prefix(path, paths_map["social_content"])
        ):
            return {
                "category": "normal",
                "reason": "LinkedIn 公司主页，可作为有效企业证据",
                "domain": host,
                "matched_base": None,
                "inferred_store_name": None,
            }
        # 社媒内容页（posts/reel/status/watch/groups/r 等）或裸社媒域名
        if _matches_path_prefix(path, paths_map["social_content"]) or not path or path == "/":
            return {
                "category": "social_content",
                "reason": f"{host} 是公共社媒平台，域名或内容页不代表目标公司自有官网",
                "domain": host,
                "matched_base": matched_social,
                "inferred_store_name": None,
            }
        # 其他社媒非公司页（如个人主页、未知子路径）同样按社媒内容页处理
        return {
            "category": "social_content",
            "reason": f"{host} 是公共社媒平台页面，不代表目标公司自有官网",
            "domain": host,
            "matched_base": matched_social,
            "inferred_store_name": None,
        }

    # 4) 招聘站点或任意站点上的招聘路径
    matched_recruit = _matches_domain_suffix(host, domains_map["recruitment_hosts"])
    if matched_recruit:
        return {
            "category": "recruitment_page",
            "reason": f"{host} 是招聘平台，不代表目标公司官网",
            "domain": host,
            "matched_base": matched_recruit,
            "inferred_store_name": None,
        }
    if _matches_path_prefix(path, paths_map["recruitment"]):
        return {
            "category": "recruitment_page",
            "reason": f"{host}{path} 是招聘页面，非企业官网首页",
            "domain": host,
            "matched_base": None,
            "inferred_store_name": None,
        }

    # 5) 免费建站/托管平台子域名（如 foo.wixsite.com / foo.blogspot.com / foo.myshopify.com）
    matched_builder = _matches_domain_suffix(host, domains_map["site_builder_subdomain"])
    if matched_builder:
        store = _infer_store_name(host, path, matched_builder)
        return {
            "category": "site_builder_subdomain",
            "reason": f"{host} 是建站托管平台子域名，域名注册信息属于平台而非目标公司",
            "domain": host,
            "matched_base": matched_builder,
            "inferred_store_name": store,
        }

    # 6) B2B 撮合与电商平台（如 abc.en.alibaba.com / made-in-china.com）
    matched_b2b = _matches_domain_suffix(host, domains_map["b2b_marketplace"])
    if matched_b2b:
        store = _infer_store_name(host, path, matched_b2b)
        return {
            "category": "b2b_marketplace",
            "reason": f"{host} 是 B2B/电商撮合平台，域名注册信息属于平台而非目标公司",
            "domain": host,
            "matched_base": matched_b2b,
            "inferred_store_name": store,
        }

    # 7) 贸易/海关数据站
    matched_trade = _matches_domain_suffix(host, domains_map["trade_data"])
    if matched_trade:
        return {
            "category": "trade_data",
            "reason": f"{host} 是贸易数据聚合站，非目标公司官网",
            "domain": host,
            "matched_base": matched_trade,
            "inferred_store_name": None,
        }

    # 8) 企业目录/黄页/工商聚合站
    matched_dir = _matches_domain_suffix(host, domains_map["directory"])
    if matched_dir:
        return {
            "category": "directory",
            "reason": f"{host} 是企业目录或黄页聚合站，非目标公司官网",
            "domain": host,
            "matched_base": matched_dir,
            "inferred_store_name": None,
        }

    # 9) 行业研究报告/新闻稿/媒体站
    matched_research = _matches_domain_suffix(host, domains_map["research_press"])
    if matched_research:
        return {
            "category": "research_press",
            "reason": f"{host} 是研究报告或媒体站点，非目标公司官网",
            "domain": host,
            "matched_base": matched_research,
            "inferred_store_name": None,
        }

    return {
        "category": "normal",
        "reason": "独立企业域名",
        "domain": host,
        "matched_base": None,
        "inferred_store_name": None,
    }


def classify_urls_batch(
    urls: list[str],
    *,
    purpose: str = "customer",
    builtin_path: Path | None = None,
    override_path: Path | None = None,
) -> dict[str, Any]:
    """批量分类候选网址，按业务用途分组打标（只打标签与折叠，绝不删除任何条目）。

    Args:
        urls: 待分类的网址或域名列表
        purpose: "customer"（找客户，默认）或 "supplier"（找供应商）

    Returns:
        包含 primary（主表正常展示）与 other_sources（默认折叠到「其他来源」小节）的完整分组结果，
        items 列表保留原始顺序与完整数量。
    """
    norm_purpose = str(purpose or "customer").strip().lower()
    if norm_purpose not in {"customer", "supplier"}:
        norm_purpose = "customer"  # 未知用途回退默认找客户口径

    items: list[dict[str, Any]] = []
    primary: list[dict[str, Any]] = []
    other_sources: list[dict[str, Any]] = []

    for raw_url in urls:
        url_str = str(raw_url or "").strip()
        info = classify_domain_or_url(
            url_str,
            builtin_path=builtin_path,
            override_path=override_path,
        )
        cat = info["category"]

        # 按业务用途决定展示分组与中文标签：找供应商时 B2B 平台店铺属于合理来源，正常展示
        if cat == "normal":
            label = CATEGORY_LABELS["normal"]
            group = "primary"
            collapsed = False
        elif norm_purpose == "supplier" and cat == "b2b_marketplace":
            label = "平台店铺"
            group = "primary"
            collapsed = False
        else:
            label = CATEGORY_LABELS.get(cat, "其他来源")
            group = "other_sources"
            collapsed = True

        entry = {
            "url": url_str,
            "domain": info["domain"],
            "category": cat,
            "label": label,
            "reason": info["reason"],
            "group": group,
            "collapsed": collapsed,
            "inferred_store_name": info["inferred_store_name"],
        }
        items.append(entry)
        if group == "primary":
            primary.append(entry)
        else:
            other_sources.append(entry)

    return {
        "purpose": norm_purpose,
        "total": len(items),
        "primary_count": len(primary),
        "other_count": len(other_sources),
        "items": items,
        "primary": primary,
        "other_sources": other_sources,
    }
