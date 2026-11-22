"""用户名跨站检索（工单 P2-2，WhatsMyName 数据集内置）。

只请求**公开 profile URL**，不登录、不发送消息、不绕过任何访问控制。
单次最多查 50 个站点（`TRADE_OSINT_USERNAME_SITES` 可调），并发 8，
每站 4 秒超时；命中只代表"该用户名在此站存在"，同名风险必须人工确认。

数据集：trade/osint/data/wmn-data.json（CC BY-SA 4.0，见同目录 WMN-NOTICE）。
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from trade.osint.sources.base import (
    Fetcher,
    SourceResult,
    TargetContext,
    fetch_page,
    quote,
    skipped,
)

NAME = "usernames"
LABEL = "用户名跨站检索"
DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "wmn-data.json"

_MAX_WORKERS = 8
_PER_SITE_TIMEOUT = 4
_TOTAL_SECONDS = 20
_DEFAULT_SITES = 50

_cache: list[dict] | None = None

# 高价值站点优先（数据集是随机顺序，不排序的话前 50 个可能一个常去的站都没有）
_PRIORITY = (
    "github", "reddit", "instagram", "x", "twitter", "tiktok", "youtube",
    "pinterest", "medium", "deviantart", "steam", "twitch", "soundcloud",
    "dribbble", "behance", "gitlab", "bitbucket", "keybase", "about.me",
    "linkedin",
)


def _priority_key(site: dict) -> tuple[int, str]:
    name = str(site.get("name") or "").casefold()
    for index, prefix in enumerate(_PRIORITY):
        if name.startswith(prefix):
            return index, name
    return len(_PRIORITY), name


def _load_sites() -> list[dict]:
    """懒加载 WhatsMyName 站点规则（测试可 monkeypatch）。"""
    global _cache
    if _cache is None:
        try:
            payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            _cache = [site for site in payload.get("sites") or []
                      if isinstance(site, dict) and "{account}" in str(site.get("uri_check") or "")]
            _cache.sort(key=_priority_key)
        except (OSError, ValueError):
            _cache = []
    return _cache


def _site_limit() -> int:
    raw = os.environ.get("TRADE_OSINT_USERNAME_SITES", "").strip()
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_SITES
    return max(1, min(value, 200))


def run(ctx: TargetContext, fetch: Fetcher | None = None) -> SourceResult:
    """按用户名查公开 profile；没有用户名线索返回 skipped。"""
    username = str(ctx.username or "").strip().lstrip("@")
    if not username:
        return skipped(NAME, "没有可检索的用户名")

    sites = _load_sites()[:_site_limit()]
    if not sites:
        return SourceResult(NAME, "miss", error="WhatsMyName 数据集不可用")

    def check(site: dict) -> dict | None:
        uri = str(site.get("uri_check") or "")
        url = uri.replace("{account}", quote(username))
        pretty = str(site.get("uri_pretty") or uri).replace("{account}", quote(username))
        try:
            page = fetch_page(
                url,
                timeout=_PER_SITE_TIMEOUT,
                fetch=fetch,
                headers=site.get("headers") if isinstance(site.get("headers"), dict) else None,
            )
        except Exception:  # noqa: BLE001 —— 单站失败按未命中
            return None
        if page is None:
            return None
        code, text = page
        # WhatsMyName 的 e_code：账号存在时该站返回的状态码（多数 200，也有
        # 301/400/403）。此前只看 e_string，非 2xx 的站点被 HTTPError 吞掉、
        # 永远不可能命中（2026-11-22 审计 P2-10）。
        expected = site.get("e_code")
        if expected is not None:
            try:
                expected = int(expected)
            except (TypeError, ValueError):
                expected = None
        if expected is not None and code != expected:
            # 301/302 会被 opener 自动跟随到最终 200：期望重定向时接受最终 2xx
            redirect_followed = expected in (301, 302, 303, 307, 308) and 200 <= code < 300
            if not redirect_followed:
                return None
        if not text:
            return None
        marker = str(site.get("e_string") or "")
        if marker and marker not in text:
            return None
        return {"site": str(site.get("name") or ""), "url": pretty}

    found: list[dict] = []
    deadline = time.monotonic() + _TOTAL_SECONDS
    executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS)
    try:
        futures = [executor.submit(check, site) for site in sites]
        for future in as_completed(futures, timeout=max(0.1, deadline - time.monotonic())):
            try:
                result = future.result()
            except Exception:  # noqa: BLE001
                continue
            if result:
                found.append(result)
    except TimeoutError:
        pass  # 到总时限就返回已收集的命中
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    if not found:
        return SourceResult(
            NAME, "miss",
            error=f"用户名 {username} 在已检查的 {len(sites)} 个站点中未发现公开 profile",
        )

    found.sort(key=lambda item: item["site"].casefold())
    names = "、".join(item["site"] for item in found[:10])
    return SourceResult(
        NAME,
        "hit",
        facts=[{
            "text": (
                f"用户名 {username}：在 {len(found)}/{len(sites)} 个站点存在公开 profile"
                f"（{names}）；同名风险需人工确认"
            ),
            "url": found[0]["url"],
        }],
        data={"username": username, "found": found, "checked": len(sites)},
    )
