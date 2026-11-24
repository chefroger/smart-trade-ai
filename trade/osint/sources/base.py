"""公开来源的统一基础设施（工单 P2-2）。

每个来源是独立模块：`run(ctx, fetch=None) -> SourceResult`。
`fetch` 可注入（测试用），默认走 `trade.osint.constants.http_get`（带 SSRF 防护、
2 MB 上限、系统代理配置）。

只接官方或有公开授权约定的接口；不绕登录、验证码、付费墙。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from trade.osint.constants import _current_opener

# fetch(url, timeout) -> 响应文本 | None；异常表示这次查询失败
Fetcher = Callable[[str, int], str | None]

# 单次响应上限（与 http_get 一致，防止异常大包）
MAX_BYTES = 2_000_000


@dataclass
class TargetContext:
    """一次背调的目标上下文（各来源只读）。"""

    target: str
    target_type: str          # email | domain | url | company | person
    domain: str | None = None
    email: str | None = None
    person_name: str | None = None
    company_name: str | None = None
    github_username: str | None = None
    username: str | None = None
    # 当前公司的联系邮箱（EDGAR 的 UA 要求），未绑定公司时为空
    contact_email: str | None = None


@dataclass
class SourceResult:
    """单个公开来源的结果。"""

    source: str
    status: str               # hit | miss | error | skipped
    facts: list[dict] = field(default_factory=list)   # [{text, url}]
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "status": self.status,
            "facts": list(self.facts),
            "data": dict(self.data),
            "error": self.error,
        }


def skipped(source: str, reason: str) -> SourceResult:
    """目标不适用时的统一结构（如没有域名就不查 RDAP）。"""
    return SourceResult(source=source, status="skipped", error=reason)


def fetch_text(
    url: str,
    *,
    timeout: int = 20,
    fetch: Fetcher | None = None,
    headers: dict[str, str] | None = None,
) -> str | None:
    """取文本；失败返回 None，不抛异常（异常由调用方按需转为 error）。"""
    if fetch is not None:
        return fetch(url, timeout)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; Trade-AI/1.0; +https://github.com)",
            "Accept": "*/*",
            **(headers or {}),
        },
    )
    # 复用带 SSRF 复查与系统代理的 opener（与 http_get 同一套）
    with _current_opener().open(request, timeout=timeout) as response:
        return response.read(MAX_BYTES).decode("utf-8", errors="replace")


def fetch_page(
    url: str,
    *,
    timeout: int = 20,
    fetch: Fetcher | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, str] | None:
    """取 (HTTP 状态码, 文本)；网络失败返回 None。

    与 `fetch_text` 的区别：非 2xx 的 HTTP 错误也把状态码和响应体带回来，
    供需要按状态码判定（WhatsMyName 的 e_code）的调用方使用。
    注入的 `fetch` 只返回文本（或 (code, text) 元组），默认按 200 处理。
    """
    if fetch is not None:
        value = fetch(url, timeout)
        if value is None:
            return None
        if isinstance(value, tuple):
            return int(value[0]), str(value[1])
        return 200, value
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; Trade-AI/1.0; +https://github.com)",
            "Accept": "*/*",
            **(headers or {}),
        },
    )
    try:
        # 复用带 SSRF 复查与系统代理的 opener（与 http_get 同一套）
        with _current_opener().open(request, timeout=timeout) as response:
            text = response.read(MAX_BYTES).decode("utf-8", errors="replace")
            return int(getattr(response, "status", 200)), text
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(MAX_BYTES).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 —— 读不到响应体时只保留状态码
            body = ""
        return int(exc.code), body
    except Exception:  # noqa: BLE001 —— 网络/DNS/SSRF 拦截都按未命中处理
        return None


def fetch_page_final(
    url: str,
    *,
    timeout: int = 20,
    fetch: Fetcher | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, str, str] | None:
    """与 fetch_page 相同，但额外返回最终 URL（W15 O-3）。

    用于区分「直接 200」与「301/302 被自动跟随后的 200」：后者才是
    WhatsMyName e_code 期望的重定向命中。注入的 fetch 无法得知跳转，
    按直接请求处理（final_url = url）。
    """
    if fetch is not None:
        value = fetch(url, timeout)
        if value is None:
            return None
        if isinstance(value, tuple):
            # 测试可给 (code, text, final_url) 模拟「被跟随的重定向」
            final = str(value[2]) if len(value) >= 3 else url
            return int(value[0]), str(value[1]), final
        return 200, value, url
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; Trade-AI/1.0; +https://github.com)",
            "Accept": "*/*",
            **(headers or {}),
        },
    )
    try:
        with _current_opener().open(request, timeout=timeout) as response:
            text = response.read(MAX_BYTES).decode("utf-8", errors="replace")
            return int(getattr(response, "status", 200)), text, str(response.geturl() or url)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(MAX_BYTES).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            body = ""
        return int(exc.code), body, str(getattr(exc, "url", "") or url)
    except Exception:  # noqa: BLE001
        return None


def fetch_json(
    url: str,
    *,
    timeout: int = 20,
    fetch: Fetcher | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    """取 JSON；网络失败/非 JSON 返回 None。"""
    text = fetch_text(url, timeout=timeout, fetch=fetch, headers=headers)
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def quote(value: str) -> str:
    """URL 编码（来源模块共用）。"""
    return urllib.parse.quote(str(value), safe="")
