"""公开来源的统一基础设施（工单 P2-2）。

每个来源是独立模块：`run(ctx, fetch=None) -> SourceResult`。
`fetch` 可注入（测试用），默认走 `trade.osint.constants.http_get`（带 SSRF 防护、
2 MB 上限、系统代理配置）。

只接官方或有公开授权约定的接口；不绕登录、验证码、付费墙。
"""

from __future__ import annotations

import json
import logging
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from trade.osint.constants import _current_opener

logger = logging.getLogger(__name__)

# ==============================================================================
# 统一数据源错误码词表（M4：供 OSINT 公开来源、文档抽取与前端等待面板共用）
# ==============================================================================

# code -> (用户可读中文说明, 是否允许稍后重试)
ERROR_CODE_META: dict[str, tuple[str, bool]] = {
    "timeout": ("请求超时，其他数据源继续执行，可以稍后重试", True),
    "rate_limited": ("接口限流或配额用尽（429），其他数据源继续执行，可以稍后重试", True),
    "unauthorized": ("鉴权失败或拒绝访问，请检查配置或权限", False),
    "bad_request": ("请求参数不被上游接受", False),
    "upstream_unavailable": ("上游服务暂不可用，其他数据源继续执行，可以稍后重试", True),
    "network": ("网络或代理连接失败，其他数据源继续执行，可以稍后重试", True),
    "parse_error": ("上游响应格式异常，无法解析", False),
    "not_applicable": ("当前目标不适用此数据源", False),
    "unsupported_type": ("不支持的目标或文件类型", False),
    "unknown": ("内部错误，已写入日志", False),
}

_SOURCE_DISPLAY_NAMES: dict[str, str] = {
    "rdap": "RDAP",
    "ct": "证书透明（CT）",
    "wayback": "Wayback",
    "pdns": "被动 DNS",
    "github": "GitHub",
    "gleif": "GLEIF",
    "vies": "VIES",
    "us_states": "美国州登记",
    "edgar": "EDGAR",
    "gdelt": "GDELT",
    "gravatar": "Gravatar",
    "usernames": "用户名检索",
    "registries_misc": "多国登记库",
}

_KEY_LIKE_RE = re.compile(r"\b(?:sk|tvly|ghp|gho|Bearer\s+)[A-Za-z0-9._-]{8,}\b")


def redact_error_detail(text: str) -> str:
    """写日志前脱敏异常中的疑似密钥片段，不把明文 Key 写入日志。"""
    raw = str(text or "")
    try:
        from trade.doctor import _redact_api_key

        # 复用 doctor 脱敏器对任意已知环境变量 Key 做二次脱敏
        for env_name in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "TAVILY_API_KEY"):
            import os

            val = os.environ.get(env_name, "").strip()
            if val:
                raw = _redact_api_key(raw, val)
    except Exception:  # noqa: BLE001
        pass
    return _KEY_LIKE_RE.sub("[REDACTED]", raw)


def classify_http_status(status_code: int) -> tuple[str, bool, str]:
    """将 HTTP 状态码映射为 (error_code, retryable, 中文提示)。"""
    code = int(status_code)
    if code == 429:
        ec = "rate_limited"
    elif code in (401, 403):
        ec = "unauthorized"
    elif code == 400:
        ec = "bad_request"
    elif code in (408, 504):
        ec = "timeout"
    elif 500 <= code < 600:
        ec = "upstream_unavailable"
    else:
        ec = "bad_request"
    msg, retryable = ERROR_CODE_META[ec]
    return ec, retryable, msg


def classify_exception(exc: BaseException) -> tuple[str, bool, str]:
    """将 Python 异常归类为统一 (error_code, retryable, 中文提示)。"""
    if isinstance(exc, urllib.error.HTTPError):
        return classify_http_status(int(exc.code))
    if isinstance(exc, (TimeoutError, socket.timeout)):
        msg, retryable = ERROR_CODE_META["timeout"]
        return "timeout", retryable, msg
    if isinstance(exc, (json.JSONDecodeError, ValueError)):
        msg, retryable = ERROR_CODE_META["parse_error"]
        return "parse_error", retryable, msg
    if isinstance(exc, (urllib.error.URLError, ConnectionError, OSError)):
        low = str(exc).lower()
        if "429" in low or "rate limit" in low or "quota" in low:
            msg, retryable = ERROR_CODE_META["rate_limited"]
            return "rate_limited", retryable, msg
        if "timed out" in low or "timeout" in low:
            msg, retryable = ERROR_CODE_META["timeout"]
            return "timeout", retryable, msg
        msg, retryable = ERROR_CODE_META["network"]
        return "network", retryable, msg
    low = str(exc).lower()
    if "timed out" in low or "timeout" in low:
        msg, retryable = ERROR_CODE_META["timeout"]
        return "timeout", retryable, msg
    if "429" in low or "rate limit" in low or "quota" in low:
        msg, retryable = ERROR_CODE_META["rate_limited"]
        return "rate_limited", retryable, msg
    if any(tok in low for tok in ("urlopen", "connection", "ssl", "dns", "proxy", "socket", "refused", "reset")):
        msg, retryable = ERROR_CODE_META["network"]
        return "network", retryable, msg
    msg, retryable = ERROR_CODE_META["unknown"]
    return "unknown", retryable, msg


def error_result(
    source: str,
    exc: BaseException | None = None,
    *,
    code: str | None = None,
    detail: str = "",
) -> SourceResult:
    """构造统一错误 SourceResult：原始异常脱敏后只写日志，返回用户可读中文提示。"""
    if code and code in ERROR_CODE_META:
        err_code = code
        user_msg, retryable = ERROR_CODE_META[err_code]
    elif exc is not None:
        err_code, retryable, user_msg = classify_exception(exc)
    else:
        err_code = "network"
        user_msg, retryable = ERROR_CODE_META[err_code]

    if exc is not None:
        # 原始异常只写日志（脱敏后），绝不拼进给用户看的 error 字段
        logger.warning(
            "osint source %s failed [%s]: %s",
            source,
            err_code,
            redact_error_detail(f"{type(exc).__name__}: {exc}"),
        )
    elif detail:
        logger.warning(
            "osint source %s failed [%s]: %s",
            source,
            err_code,
            redact_error_detail(detail),
        )

    label = _SOURCE_DISPLAY_NAMES.get(source, source)
    return SourceResult(
        source=source,
        status="error",
        error=f"{label}：{user_msg}",
        error_code=err_code,
        retryable=retryable,
    )

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
    status: str               # hit | miss | error | skipped | not_applicable | candidate
    facts: list[dict] = field(default_factory=list)   # [{text, url}]
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    error_code: str | None = None
    retryable: bool = False

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "status": self.status,
            "facts": list(self.facts),
            "data": dict(self.data),
            "error": self.error,
            "error_code": self.error_code,
            "retryable": self.retryable,
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
