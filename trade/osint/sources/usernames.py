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
    error_result,
    fetch_page_final,
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

    def check(site: dict) -> tuple[str, dict | Exception | None]:
        uri = str(site.get("uri_check") or "")
        url = uri.replace("{account}", quote(username))
        pretty = str(site.get("uri_pretty") or uri).replace("{account}", quote(username))
        try:
            page = fetch_page_final(
                url,
                timeout=_PER_SITE_TIMEOUT,
                fetch=fetch,
                headers=site.get("headers") if isinstance(site.get("headers"), dict) else None,
            )
        except Exception as exc:  # noqa: BLE001 —— 单站失败记录异常，全失败时返回 error
            return "error", exc
        if page is None:
            return "miss", None
        code, text, final_url = page
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
            # 301/302 会被 opener 自动跟随到最终 200：只有**确实发生了跳转**
            # （最终 URL 与请求 URL 不同）才算该站点命中（W15 O-3）。
            # 直接返回 200 而 e_code 期望重定向 → 不算。
            redirect_followed = (
                expected in (301, 302, 303, 307, 308)
                and 200 <= code < 300
                and final_url != url
            )
            if not redirect_followed:
                return "miss", None
        if not text:
            return "miss", None
        marker = str(site.get("e_string") or "")
        if marker and marker not in text:
            return "miss", None
        return "hit", {"site": str(site.get("name") or ""), "url": pretty}

    found: list[dict] = []
    errors: list[Exception] = []
    completed = 0
    deadline = time.monotonic() + _TOTAL_SECONDS
    executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS)
    try:
        futures = [executor.submit(check, site) for site in sites]
        for future in as_completed(futures, timeout=max(0.1, deadline - time.monotonic())):
            try:
                kind, payload = future.result()
            except Exception as exc:  # noqa: BLE001
                completed += 1
                errors.append(exc)
                continue
            completed += 1
            if kind == "hit" and isinstance(payload, dict):
                found.append(payload)
            elif kind == "error" and isinstance(payload, Exception):
                errors.append(payload)
    except TimeoutError:
        pass  # 到总时限就返回已收集的命中
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    if not found:
        if completed > 0 and len(errors) >= completed:
            # 全部已返回站点均异常失败：返回 error 而非 miss（P2-6）
            return error_result(NAME, exc=errors[0])
        return SourceResult(
            NAME, "miss",
            error=f"用户名 {username} 在已检查的 {len(sites)} 个站点中未发现公开 profile",
        )

    found.sort(key=lambda item: item["site"].casefold())
    names = "、".join(item["site"] for item in found[:10])
    # 审计 P1-D：用户名相同 ≠ 同一个人，保留线索但标为候选。
    return SourceResult(
        NAME,
        "candidate",
        facts=[{
            "text": (
                f"同名候选，未核实（用户名跨站）：{username} 在 "
                f"{len(found)}/{len(sites)} 个站点存在公开 profile"
                f"（{names}）；是否同一人需人工确认"
            ),
            "url": found[0]["url"],
        }],
        data={"username": username, "found": found, "checked": len(sites)},
        error="用户名相同不等于同一人，未核实",
    )
