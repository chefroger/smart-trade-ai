"""S3：名单不全（coverage.degraded）时不能藏掉已查到的命中。

背景（2026-11-24 审计 N3）：交付兜底只要看到 degraded 就整段写「未执行」，
哪怕 OFAC/CSL 已经精确命中 —— 用户会漏掉一个真实的高风险结论。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade.api import chat  # noqa: E402


def _degraded(monkeypatch, *, hits, sanctioned):
    """mock 一个 degraded 覆盖：EU 未就绪，OFAC_NS/CSL 正常。"""
    monkeypatch.setattr(
        "trade.osint.sanctions.check_sanctions",
        lambda name, country=None: {
            "hits": hits, "is_sanctioned": sanctioned,
            "coverage": {
                "degraded": True,
                "total_entries": 100,
                "lists": {
                    "OFAC_NS": {"label": "美国 OFAC 非 SDN 名单", "degraded": False},
                    "CSL": {"label": "美国综合筛查名单 (CSL)", "degraded": False},
                    "EU": {"label": "欧盟制裁名单", "degraded": True},
                },
            },
        },
    )


def test_confirmed_hit_is_reported_with_missing_lists(monkeypatch):
    _degraded(monkeypatch, hits=[
        {"list_label": "美国 OFAC 非 SDN 名单", "matched_value": "HUAWEI",
         "confirmation": "confirmed"},
        {"list_label": "美国综合筛查名单 (CSL)", "matched_value": "HUAWEI",
         "confirmation": "confirmed"},
    ], sanctioned=True)

    text = chat._sanctions_fallback_text("帮我查一下 HUAWEI")

    assert "⚠️ 命中" in text
    assert "欧盟制裁名单未就绪" in text


def test_possible_only_is_reported_with_missing_lists(monkeypatch):
    _degraded(monkeypatch, hits=[
        {"list_label": "美国综合筛查名单 (CSL)", "matched_value": "HUAWEI TECH",
         "confirmation": "possible"},
    ], sanctioned=False)

    text = chat._sanctions_fallback_text("帮我查一下 HUAWEI")

    assert "疑似匹配" in text
    assert "欧盟制裁名单未就绪" in text


def test_no_hit_stays_not_executed(monkeypatch):
    _degraded(monkeypatch, hits=[], sanctioned=False)

    text = chat._sanctions_fallback_text("帮我查一下 HUAWEI")

    assert "未执行" in text and "不构成" in text


@pytest.mark.parametrize("query", ["华为有没有被制裁", "天津赛得"])
def test_cjk_target_without_hits_stays_chinese_name_message(monkeypatch, query):
    """S2 与 S3 的交叉：中文无命中仍写「未执行（中文名）」，不因 degraded 改写。"""
    _degraded(monkeypatch, hits=[], sanctioned=False)

    text = chat._sanctions_fallback_text(query)

    assert "中文名称无法比对" in text
