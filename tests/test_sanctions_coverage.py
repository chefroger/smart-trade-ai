"""制裁筛查必须区分「查过、没有」与「没查成」（工单 P0-1 重建后的口径）。

- 从未成功下载 → coverage.degraded=True，不得输出「未发现匹配」；
- 有历史数据但本次刷新失败 → 沿用旧数据，degraded=False，附失败原因；
- 数据源正常 → 允许给出「未发现匹配」的绿色结论。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def sanctions_db(monkeypatch, tmp_path):
    """把制裁库指到临时路径（每个测试独立）。"""
    import trade.osint.sanctions.store as store

    path = tmp_path / "sanctions.db"
    monkeypatch.setattr(store, "db_path", lambda: path)
    return path


def _parsed(source, names, *, alias_names=()):
    from trade.osint.sanctions.sources import ParsedList

    rows = [(name, "", "entity") for name in names]
    rows += [(name, "", "alias") for name in alias_names]
    return ParsedList(
        label=source.label,
        source_url=source.urls[0],
        primary=len(names),
        aliases=len(alias_names),
        rows_total=len(rows),
        rows=rows,
    )


class TestNeverDownloaded:
    def test_reports_degraded(self, sanctions_db):
        from trade.osint.sanctions import check_sanctions

        result = check_sanctions("Some Random Trading LLC")

        assert result["coverage"]["degraded"] is True
        assert result["coverage"]["total_entries"] == 0

    def test_does_not_claim_clean(self, sanctions_db):
        """核心断言：从未成功下载时，不得输出「未发现匹配」。"""
        from trade.osint.sanctions import check_sanctions

        result = check_sanctions("Some Random Trading LLC")

        assert "未在任何制裁名单中发现匹配项" not in result["suggestion"]
        assert "不构成" in result["suggestion"]


class TestRefreshLifecycle:
    def test_successful_refresh_makes_coverage_healthy(self, sanctions_db):
        from trade.osint.sanctions import check_sanctions
        from trade.osint.sanctions.loader import refresh_all
        from trade.osint.sanctions.sources import SOURCES

        results = refresh_all(fetch=lambda source: _parsed(source, ["ACME CORP"]))
        assert all(item["ok"] for item in results.values())

        coverage = check_sanctions("Some Random Trading LLC")["coverage"]
        assert coverage["degraded"] is False
        assert coverage["total_entries"] == len(SOURCES)
        for source in SOURCES:
            assert coverage["lists"][source.name]["entries"] == 1
            assert coverage["lists"][source.name]["fetched_at"]

        assert "未在任何制裁名单中发现匹配项" in check_sanctions("Random Name Ltd")["suggestion"]

    def test_exact_hit_reports_high_risk(self, sanctions_db):
        from trade.osint.sanctions import check_sanctions
        from trade.osint.sanctions.loader import refresh_all

        refresh_all(fetch=lambda source: _parsed(source, ["ACME CORP"]))
        result = check_sanctions("acme corp")

        assert result["is_sanctioned"] is True
        assert result["risk_level"] == "high"

    def test_failure_after_success_keeps_old_data(self, sanctions_db):
        """本次刷新失败 → 沿用上次成功的数据，degraded 仍为 False。"""
        from trade.osint.sanctions import check_sanctions
        from trade.osint.sanctions.loader import refresh_all
        from trade.osint.sanctions.sources import SOURCES

        refresh_all(fetch=lambda source: _parsed(source, ["ACME CORP"]))

        def _boom(source):
            raise RuntimeError("network down")

        refresh_all(fetch=_boom)

        coverage = check_sanctions("ACME CORP")["coverage"]
        assert coverage["degraded"] is False, "有历史数据时不应判 degraded"
        assert coverage["total_entries"] == len(SOURCES)
        first = coverage["lists"][SOURCES[0].name]
        assert "本次刷新失败" in first["note"]
        assert "network down" in first["note"]
        # 旧数据仍能命中
        assert check_sanctions("ACME CORP")["is_sanctioned"] is True

    def test_first_failure_marks_that_list_degraded(self, sanctions_db):
        from trade.osint.sanctions.loader import refresh_all
        from trade.osint.sanctions.sources import SOURCES

        def _partly(source):
            if source is SOURCES[0]:
                raise RuntimeError("blocked")
            return _parsed(source, [f"{source.name} ENTITY"])

        results = refresh_all(fetch=_partly)
        assert results[SOURCES[0].name]["ok"] is False

        from trade.osint.sanctions.store import get_coverage

        coverage = get_coverage()
        assert coverage["degraded"] is True
        assert coverage["lists"][SOURCES[0].name]["degraded"] is True
        assert coverage["lists"][SOURCES[0].name]["entries"] == 0
        assert coverage["lists"][SOURCES[1].name]["degraded"] is False


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
                "coverage": {"degraded": True, "total_entries": 0, "lists": {}},
            }
        )
        joined = "\n".join(recs)

        assert "✅ 未在任何制裁名单中发现匹配项" not in joined
        assert "⚠️" in joined or "不可用" in joined

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
        recs = self._recs({"hits": [], "is_sanctioned": False, "risk_level": "none"})
        assert "✅ 未在任何制裁名单中发现匹配项" not in "\n".join(recs)


class TestEmptyParseDoesNotWipeLists:
    """2026-11-22 审计 P1-1：解析“成功返回 0 行”不得清空名单、更不得判干净。"""

    def _empty(self, source):
        from trade.osint.sanctions.sources import ParsedList

        return ParsedList(
            label=source.label, source_url=source.urls[0],
            primary=0, aliases=0, rows_total=0, rows=[],
        )

    def test_empty_after_success_keeps_old_data(self, sanctions_db):
        from trade.osint.sanctions import check_sanctions
        from trade.osint.sanctions.loader import refresh_all
        from trade.osint.sanctions.sources import SOURCES

        refresh_all(fetch=lambda source: _parsed(source, ["ACME CORP"]))
        results = refresh_all(fetch=self._empty)
        assert all(item["ok"] is False for item in results.values())

        result = check_sanctions("ACME CORP")
        assert result["is_sanctioned"] is True, "空解析把旧名单清掉了"
        coverage = result["coverage"]
        assert coverage["degraded"] is False, "旧数据仍在，应沿用而不是降级"
        assert coverage["total_entries"] == len(SOURCES)
        assert "解析结果为空" in coverage["lists"][SOURCES[0].name]["note"]

    def test_first_empty_parse_is_degraded_and_never_clean(self, sanctions_db):
        from trade.osint.sanctions import check_sanctions
        from trade.osint.sanctions.loader import refresh_all

        results = refresh_all(fetch=self._empty)
        assert all(item["ok"] is False for item in results.values())

        result = check_sanctions("ACME CORP")
        assert result["coverage"]["degraded"] is True
        assert result["coverage"]["total_entries"] == 0
        assert "未在任何制裁名单中发现匹配项" not in result["suggestion"]

    def test_save_list_rejects_empty_payload_without_deleting(self, sanctions_db):
        from trade.osint.sanctions import check_sanctions, store
        from trade.osint.sanctions.loader import refresh_all
        from trade.osint.sanctions.sources import SOURCES

        refresh_all(fetch=lambda source: _parsed(source, ["ACME CORP"]))
        conn = store._connect(write=True)
        try:
            with pytest.raises(ValueError):
                store.save_list(conn, SOURCES[0], self._empty(SOURCES[0]))
        finally:
            conn.close()
        assert check_sanctions("ACME CORP")["is_sanctioned"] is True

    def test_zero_entries_row_is_degraded(self, sanctions_db):
        """历史库若已有 fetched_at 但 entries=0，也必须判降级（不只是刷新路径）。"""
        from trade.osint.sanctions import store
        from trade.osint.sanctions.loader import refresh_all
        from trade.osint.sanctions.sources import SOURCES

        refresh_all(fetch=lambda source: _parsed(source, ["ACME CORP"]))
        conn = store._connect(write=True)
        try:
            conn.execute(
                "UPDATE lists SET entries = 0 WHERE name = ?", (SOURCES[0].name,))
            conn.commit()
        finally:
            conn.close()

        coverage = store.get_coverage()
        assert coverage["degraded"] is True
        assert coverage["lists"][SOURCES[0].name]["degraded"] is True
        assert "0 条" in coverage["lists"][SOURCES[0].name]["note"]

    def test_naive_fetched_at_does_not_crash(self, sanctions_db):
        """无时区 fetched_at 不能让整个制裁层抛 TypeError（审计 P2-7）。"""
        from trade.osint.sanctions import store
        from trade.osint.sanctions.loader import refresh_all
        from trade.osint.sanctions.sources import SOURCES

        refresh_all(fetch=lambda source: _parsed(source, ["ACME CORP"]))
        conn = store._connect(write=True)
        try:
            conn.execute(
                "UPDATE lists SET fetched_at = ? WHERE name = ?",
                ("2026-11-22T00:00:00", SOURCES[0].name),
            )
            conn.commit()
        finally:
            conn.close()

        coverage = store.get_coverage()   # 不应抛 TypeError
        assert coverage["lists"][SOURCES[0].name]["entries"] == 1


class TestStaleUpperBounds:
    """审计 P0-A：72 小时标 stale，超过 7 天按 degraded 处理。"""

    def _set_age_hours(self, hours: float) -> None:
        from datetime import UTC, datetime, timedelta

        from trade.osint.sanctions import store
        from trade.osint.sanctions.sources import SOURCES

        fetched = (datetime.now(UTC) - timedelta(hours=hours)).isoformat(timespec="seconds")
        conn = store._connect(write=True)
        try:
            conn.execute(
                "UPDATE lists SET fetched_at = ? WHERE name = ?",
                (fetched, SOURCES[0].name),
            )
            conn.commit()
        finally:
            conn.close()

    def _refresh(self) -> None:
        from trade.osint.sanctions.loader import refresh_all

        refresh_all(fetch=lambda source: _parsed(source, ["ACME CORP"]))

    def test_72h_is_stale_but_still_usable(self, sanctions_db):
        from trade.osint.sanctions import check_sanctions
        from trade.osint.sanctions.sources import SOURCES

        self._refresh()
        self._set_age_hours(73)

        result = check_sanctions("Random Name Ltd")
        info = result["coverage"]["lists"][SOURCES[0].name]

        assert info["stale"] is True
        assert info["stale_hours"] >= 72
        assert info["degraded"] is False, "72h 只标过期，不判未完成"
        assert result["coverage"]["stale"] is True
        assert "过期" in result["suggestion"], "建议里必须写明名单已过期"
        assert "小时未更新" in result["suggestion"]

    def test_over_7_days_is_degraded(self, sanctions_db):
        from trade.osint.sanctions import check_sanctions
        from trade.osint.sanctions.sources import SOURCES
        from trade.osint.sanctions.store import get_coverage

        self._refresh()
        self._set_age_hours(24 * 8)

        coverage = get_coverage()
        info = coverage["lists"][SOURCES[0].name]

        assert info["degraded"] is True
        assert info["stale"] is True
        assert coverage["degraded"] is True, "过期一周以上必须整体降级"
        assert "超过 7 天" in info["note"]
        assert "未在任何制裁名单中发现匹配项" not in check_sanctions("Random Ltd")["suggestion"]

    def test_under_72h_is_not_stale(self, sanctions_db):
        from trade.osint.sanctions.sources import SOURCES
        from trade.osint.sanctions.store import get_coverage

        self._refresh()
        self._set_age_hours(24)

        info = get_coverage()["lists"][SOURCES[0].name]

        assert "stale" not in info
        assert "stale_hours" not in info
