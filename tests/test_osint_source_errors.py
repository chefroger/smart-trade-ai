"""
M4 验收测试：OSINT 公开来源统一错误码、异常脱敏、状态不误报 miss、全源报错判 incomplete。

所有测试目标均为虚构夹具，不触网。
"""

from __future__ import annotations

import urllib.error
from unittest.mock import patch

import pytest

from trade.osint.orchestrator import osint_full_check
from trade.osint.scoring import compute_verdict
from trade.osint.sources import (
    TargetContext,
    ct,
    edgar,
    gdelt,
    github,
    gleif,
    gravatar,
    pdns,
    rdap,
    us_states,
    vies,
    wayback,
)
from trade.osint.sources.base import SourceResult, classify_http_status


def _http_err(code: int, msg: str = "err") -> urllib.error.HTTPError:
    """构造带状态码的模拟 HTTPError。"""
    return urllib.error.HTTPError(
        url="https://fictional.invalid/api",
        code=code,
        msg=msg,
        hdrs=None,  # type: ignore[arg-type]
        fp=None,
    )


@pytest.mark.parametrize(
    ("status_code", "expected_code", "expected_retryable"),
    [
        (429, "rate_limited", True),
        (401, "unauthorized", False),
        (403, "unauthorized", False),
        (400, "bad_request", False),
        (408, "timeout", True),
        (504, "timeout", True),
        (500, "upstream_unavailable", True),
        (503, "upstream_unavailable", True),
    ],
)
def test_classify_http_status_table(status_code: int, expected_code: str, expected_retryable: bool):
    """HTTP 状态码统一归类到错误码词表与可重试标记。"""
    code, retryable, msg = classify_http_status(status_code)
    assert code == expected_code
    assert retryable is expected_retryable
    assert msg


def test_pdns_quota_exceeded_is_error_rate_limited_retryable():
    """pdns 返回配额用尽文本 → status=error, error_code=rate_limited, retryable=True（不误报 miss）。"""
    ctx = TargetContext(target="fictional.de", target_type="domain", domain="fictional.de")
    res = pdns.run(ctx, fetch=lambda _u, _t: "API count exceeded - Increase Quota with Membership")
    assert res.status == "error"
    assert res.error_code == "rate_limited"
    assert res.retryable is True


def test_rdap_non_dict_is_error_parse_error():
    """rdap 返回非 dict JSON → status=error, error_code=parse_error（不误报 miss）。"""
    ctx = TargetContext(target="fictional.de", target_type="domain", domain="fictional.de")
    res = rdap.run(ctx, fetch=lambda _u, _t: '["unexpected", "list"]')
    assert res.status == "error"
    assert res.error_code == "parse_error"
    assert res.retryable is False


@pytest.mark.parametrize(
    ("module", "ctx_kwargs"),
    [
        (rdap, {"target": "fictional.de", "target_type": "domain", "domain": "fictional.de"}),
        (pdns, {"target": "fictional.de", "target_type": "domain", "domain": "fictional.de"}),
        (ct, {"target": "fictional.de", "target_type": "domain", "domain": "fictional.de"}),
        (wayback, {"target": "fictional.de", "target_type": "domain", "domain": "fictional.de"}),
        (gleif, {"target": "Fictional Co", "target_type": "company", "company_name": "Fictional Co"}),
        (edgar, {"target": "Fictional Co", "target_type": "company", "company_name": "Fictional Co", "contact_email": "ops@fictional.de"}),
        (gdelt, {"target": "Fictional Co", "target_type": "company", "company_name": "Fictional Co"}),
        (vies, {"target": "DE123456789", "target_type": "company", "company_name": "DE123456789"}),
        (gravatar, {"target": "ops@fictional.de", "target_type": "email", "email": "ops@fictional.de"}),
        (github, {"target": "Fictional Co", "target_type": "company", "company_name": "Fictional Co"}),
        (us_states, {"target": "Fictional Co", "target_type": "company", "company_name": "Fictional Co"}),
    ],
)
def test_all_sources_map_network_error_without_leaking_raw_exception(module, ctx_kwargs):
    """所有来源遇到 URLError 时均返回 status=error、error_code=network、retryable=True，且不透出原始 urlopen error。"""
    def _boom(_url, _timeout):
        raise urllib.error.URLError("urlopen error [Errno 61] Connection refused sk-testfakekey999999")

    ctx = TargetContext(**ctx_kwargs)
    res = module.run(ctx, fetch=_boom)
    assert res.status == "error"
    assert res.error_code == "network"
    assert res.retryable is True
    assert "urlopen error" not in (res.error or "")
    assert "Traceback" not in (res.error or "")
    assert "sk-testfakekey999999" not in (res.error or "")


def test_source_429_maps_to_rate_limited():
    """HTTP 429 映射为 rate_limited 且可重试。"""
    ctx = TargetContext(target="fictional.de", target_type="domain", domain="fictional.de")

    def _rate_limited(_url, _timeout):
        raise _http_err(429, "Too Many Requests")

    res = rdap.run(ctx, fetch=_rate_limited)
    assert res.status == "error"
    assert res.error_code == "rate_limited"
    assert res.retryable is True


def test_compute_verdict_all_sources_failed_is_incomplete_not_limited():
    """区分「全部报错（incomplete）」与「全部未命中（limited）」。"""
    score_err, rating_err, _ = compute_verdict(
        [],
        [],
        target_type="company",
        has_domain=False,
        public_hits=0,
        all_sources_failed=True,
    )
    assert score_err is None
    assert rating_err == "incomplete"

    score_miss, rating_miss, _ = compute_verdict(
        [],
        [],
        target_type="company",
        has_domain=False,
        public_hits=0,
        all_sources_failed=False,
    )
    assert score_miss is None
    assert rating_miss == "limited"


@pytest.mark.asyncio
async def test_osint_all_public_sources_network_error_yields_incomplete_and_notice():
    """所有公开来源打桩为网络错误 → 评级 incomplete，首屏有网络/代理提示，且 source_done 带 error_code/retryable。"""
    events: list[dict] = []

    def _clean_sanctions(_name: str) -> dict:
        return {
            "hits": [],
            "is_sanctioned": False,
            "risk_level": "none",
            "coverage": {"degraded": False, "total_entries": 1000, "lists": {"ofac": 1000}},
            "suggestion": "未命中",
        }

    def _net_err_run(module, ctx, fetcher):
        return SourceResult(
            source=module.NAME,
            status="error",
            error="网络或代理连接失败，其他数据源继续执行，可以稍后重试",
            error_code="network",
            retryable=True,
        ).to_dict()

    with (
        patch("trade.osint.orchestrator.check_sanctions", side_effect=_clean_sanctions),
        patch("trade.osint.orchestrator._run_public_source", side_effect=_net_err_run),
    ):
        report = await osint_full_check("Fictional Alpha Holdings Ltd", on_event=events.append)

    assert report["overall_rating"] == "incomplete"
    assert report["overall_score"] is None
    assert "公开来源全部没查成" in report.get("rating_note", "")
    assert "网络或代理" in report.get("rating_note", "")

    source_done_events = [e for e in events if e.get("event") == "source_done" and e.get("error_code") == "network"]
    assert source_done_events
    assert all(e.get("retryable") is True for e in source_done_events)
