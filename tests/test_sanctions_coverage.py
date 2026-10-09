"""制裁筛查必须区分「查过、没有」与「没查成」。

## 为什么（业务风险最高的一条）

`load_un_sanctions()` 无条件返回 2 条硬编码数据；`load_ofac_sanctions()` 的下载
URL 实测 **HTTP 404**（返回的是 30KB HTML 错误页），解析不出任何条目 → 落到 2 条
内置 fallback。也就是说**全新安装时，制裁筛查实际上只在比对 4 个字符串**。

而 `check_sanctions` 的返回里没有任何「数据源健康度」信息：`risk_level: "none"`
与「真的比对过上万条 SDN 记录」在响应里完全同形。于是报告输出绿色的
「✅ 未在任何制裁名单中发现匹配项」—— 被制裁的公司也会被判「干净」。
用户会拿这条结论去谈生意。

修法：loader 记录每份名单的 `{entries, source, degraded}`，`check_sanctions`
把它作为 `coverage` 一并返回；数据源降级时**不得**给出「未发现匹配」的结论。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def fresh_sanctions(monkeypatch):
    """重置 sanctions 模块的缓存与元数据，并把文件缓存指到临时目录。"""
    from trade.osint.sanctions import loader

    monkeypatch.setattr(loader, "_sanctions_cache", {}, raising=False)
    monkeypatch.setattr(loader, "_sanctions_meta", {}, raising=False)
    monkeypatch.setattr(loader, "_load_from_file_cache", lambda _n: None, raising=False)
    monkeypatch.setattr(
        loader, "_load_from_file_cache_expired", lambda _n: None, raising=False
    )
    monkeypatch.setattr(loader, "_save_to_file_cache", lambda *_a, **_k: None, raising=False)
    # http_get 一律失败 → 强制走 fallback 路径（模拟"下载不到"的真实处境）
    monkeypatch.setattr(loader, "http_get", lambda *_a, **_k: None, raising=False)
    return loader


class TestDegradedIsVisible:
    """数据源降级必须体现在返回值里。"""

    def test_fallback_reports_degraded(self, fresh_sanctions):
        from trade.osint.sanctions import check_sanctions

        result = check_sanctions("Some Random Trading LLC")

        assert "coverage" in result, "返回值必须带数据源健康度（否则无法区分「没查到」与「没查成」）"
        assert result["coverage"]["degraded"] is True, "走 fallback 时 degraded 必须为 True"

    def test_fallback_does_not_claim_clean(self, fresh_sanctions):
        """核心断言：数据源不可用时，不得输出「未发现匹配」这种结论。"""
        from trade.osint.sanctions import check_sanctions

        result = check_sanctions("Some Random Trading LLC")

        assert "未在任何制裁名单中发现匹配项" not in result["suggestion"], (
            "数据源降级时仍宣称「未发现匹配」—— 被制裁的公司会被判干净"
        )
        assert "数据源" in result["suggestion"] or "不可用" in result["suggestion"]

    def test_coverage_reports_entry_counts(self, fresh_sanctions):
        from trade.osint.sanctions import check_sanctions

        result = check_sanctions("Some Random Trading LLC")
        cov = result["coverage"]

        assert cov["total_entries"] >= 0
        assert isinstance(cov.get("lists"), dict), "应能看出每份名单各加载了多少条"


class TestHealthySourceStillWorks:
    """数据源正常时，行为和以前一致（别把好路径改坏）。"""

    def test_healthy_source_can_claim_clean(self, fresh_sanctions):
        # 直接预置缓存：check_sanctions 只在缓存为空时才调 loader，
        # 这样既模拟了"数据源健康"，也不必去改已绑定的模块引用。
        big_list = [{"name": f"ENTITY NUMBER {i}", "label": "OFAC SDN"} for i in range(500)]
        fresh_sanctions._mark_loaded("OFAC", big_list, "network")
        fresh_sanctions._mark_loaded("UN", big_list, "network")

        from trade.osint.sanctions import check_sanctions

        result = check_sanctions("Some Random Trading LLC")

        assert result["coverage"]["degraded"] is False
        assert result["coverage"]["total_entries"] == 1000
        assert "未在任何制裁名单中发现匹配项" in result["suggestion"]

    def test_hit_still_reports_high_risk_when_degraded(self, fresh_sanctions):
        """降级也不能掩盖真命中 —— fallback 里的真实实体要照常报高风险。"""
        from trade.osint.sanctions import loader

        # 用 fallback 数据里真实存在的名字
        fallback = loader._get_fallback_ofac_entries()
        target = fallback[0]["name"]

        from trade.osint.sanctions import check_sanctions

        result = check_sanctions(target)

        assert result["is_sanctioned"] is True, f"命中 {target!r} 却未判为受制裁"
        assert result["risk_level"] == "high"


class TestScoringRespectsCoverage:
    """报告的建议列表也必须看 coverage —— 否则用户读到的仍是绿色结论。"""

    def _recs(self, sanctions_layer: dict) -> list[str]:
        from trade.osint.scoring import generate_recommendations

        return generate_recommendations({"layers": {"sanctions": sanctions_layer}})

    def test_degraded_does_not_emit_green_check(self):
        recs = self._recs(
            {
                "hits": [],
                "is_sanctioned": False,
                "risk_level": "none",
                "suggestion": "…",
                "coverage": {"degraded": True, "total_entries": 4, "lists": {}},
            }
        )
        joined = "\n".join(recs)

        assert "✅ 未在任何制裁名单中发现匹配项" not in joined, (
            "数据源降级时报告仍打绿勾 —— 用户会以为已核查通过"
        )
        assert "⚠️" in joined or "不可用" in joined, "应给出警示而非绿勾"

    def test_healthy_source_still_emits_green_check(self):
        recs = self._recs(
            {
                "hits": [],
                "is_sanctioned": False,
                "risk_level": "none",
                "suggestion": "…",
                "coverage": {"degraded": False, "total_entries": 12000, "lists": {}},
            }
        )

        assert "✅ 未在任何制裁名单中发现匹配项" in "\n".join(recs)

    def test_missing_coverage_is_treated_as_degraded(self):
        """老版本报告里没有 coverage 字段 —— 保守处理，不冒充已验证。"""
        recs = self._recs({"hits": [], "is_sanctioned": False, "risk_level": "none"})

        assert "✅ 未在任何制裁名单中发现匹配项" not in "\n".join(recs)
