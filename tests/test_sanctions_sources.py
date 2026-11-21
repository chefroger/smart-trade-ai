"""P0-1：官方名单解析、名称归一化、本地匹配与「查询不下载」。

夹具全部是官方文件的**真实切片**（含无表头 SDN、首行 Report Date 的 UK、
分号分隔 + BOM 的 EU），解析口径按文件真实格式钉住。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade.osint.sanctions.normalize import (  # noqa: E402
    normalize_name,
    token_key,
    tokens_of,
)
from trade.osint.sanctions.sources import (  # noqa: E402
    ParsedList,
    Source,
    parse_source,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "osint" / "sanctions"


def _source(name: str, kind: str, files: tuple[str, ...], label: str = "") -> Source:
    return Source(name, label or name, kind, tuple(str(FIX / f) for f in files))


def _parse(source: Source) -> ParsedList:
    return parse_source(source, [Path(url).read_bytes() for url in source.urls])


@pytest.fixture
def sanctions_db(monkeypatch, tmp_path):
    import trade.osint.sanctions.store as store

    path = tmp_path / "sanctions.db"
    monkeypatch.setattr(store, "db_path", lambda: path)
    return path


# ── 解析：每份名单的真实格式 ────────────────────────────────────────────────


class TestParsers:
    def test_ofac_sdn_has_no_header_and_counts_rows(self):
        parsed = _parse(_source(
            "OFAC", "ofac_sdn",
            ("ofac_sdn.csv", "ofac_alt.csv", "ofac_add.csv"),
        ))
        nonempty_lines = [
            line for line in (FIX / "ofac_sdn.csv").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert parsed.primary == len(nonempty_lines) == 3, "SDN.CSV 无表头：数据行即条目数"
        assert parsed.rows_total == 3
        assert parsed.rows[0][0] == "AEROCARIBBEAN AIRLINES"

    def test_ofac_aliases_and_countries(self):
        parsed = _parse(_source(
            "OFAC_NS", "ofac_cons",
            ("ofac_cons_prim.csv", "ofac_cons_alt.csv", "ofac_cons_add.csv"),
        ))
        names = [row[0] for row in parsed.rows]
        assert parsed.primary == 2
        assert parsed.aliases == 3
        assert "ABU TEIR, Mohammed" in names
        assert "ABU TAIR, Mohammed Mahmud" in names
        assert any(row[0] == "ABU TEIR, Mohammed" for row in parsed.rows)

    def test_csl_header_and_semicolon_aliases(self):
        parsed = _parse(_source("CSL", "csl", ("csl.csv",)))
        assert parsed.primary == 2
        assert parsed.rows_total == 2, "CSL 有表头：数据行数不含表头"
        assert parsed.aliases >= 2, "alt_names 用分号分隔多个别名"
        assert any("BANK VTB" in row[0].upper() for row in parsed.rows)

    def test_un_xml_names_and_aliases(self):
        parsed = _parse(_source("UN", "un", ("un.xml",)))
        names = [row[0] for row in parsed.rows]
        assert parsed.primary == 2
        assert parsed.aliases == 2
        assert "ERIC BADEGE" in names
        assert "ALLIED DEMOCRATIC FORCES" in names
        country = next(row[1] for row in parsed.rows if row[0] == "ERIC BADEGE")
        assert country == "Democratic Republic of the Congo"

    def test_eu_semicolon_and_bom(self):
        parsed = _parse(_source("EU", "eu", ("eu.csv",)))
        names = [row[0] for row in parsed.rows]
        assert parsed.primary == 3
        assert parsed.rows_total == 3, "EU 数据行数与源文件一致（不含表头）"
        assert "Saddam Hussein Al-Tikriti" in names
        assert "Abu Ali" in names
        assert "ACME HOLDINGS LTD" in names

    def test_uk_report_date_line_and_dedup(self):
        parsed = _parse(_source("UK", "uk", ("uk.csv",)))
        names = [row[0] for row in parsed.rows]
        # 4 行数据、1 组重复（同 Unique ID 同名）→ 3 条姓名
        assert parsed.rows_total == 4
        assert len(names) == 3
        assert "HAJI KHAIRULLAH MONEY EXCHANGE" in names
        assert "SMITH JOHN" in names
        assert parsed.aliases == 1


# ── 归一化与匹配规则 ────────────────────────────────────────────────────────


class TestNormalization:
    def test_last_first_equals_first_last(self):
        assert token_key(tokens_of(normalize_name("ABU TEIR, Mohammed"))) == token_key(
            tokens_of(normalize_name("Mohammed Abu Teir"))
        )

    def test_diacritics_are_stripped(self):
        assert normalize_name("Müller GmbH") == "muller gmbh"

    def test_abbreviation_tokens_merge(self):
        assert tokens_of(normalize_name("CIMEX, S.A.")) == ("cimex", "sa")

    def test_punctuation_and_case(self):
        assert normalize_name("  ACME-INT'L   CO.,LTD. ") == "acme int l co ltd"


class TestLocalMatching:
    def _seed_cons(self):
        from trade.osint.sanctions.loader import refresh_all

        cons = _source(
            "OFAC_NS", "ofac_cons",
            ("ofac_cons_prim.csv", "ofac_cons_alt.csv", "ofac_cons_add.csv"),
            label="OFAC 非 SDN",
        )
        refresh_all(fetch=lambda source: _parse(cons), sources=(cons,))
        return cons

    @pytest.mark.asyncio
    async def test_abu_teir_variants(self, sanctions_db):
        from trade.osint.sanctions import check_sanctions

        self._seed_cons()

        # 工单验收：First Last 命中 LAST, First
        exact = check_sanctions("Mohammed Abu Teir")
        assert exact["is_sanctioned"] is True
        assert any(hit["matched_value"] == "ABU TEIR, Mohammed" for hit in exact["hits"])

        # 别名（ALT.CSV）命中
        alias = check_sanctions("Mohammed Abu Tair")
        assert alias["hits"], "别名未参与匹配"
        assert any("ABU TAIR" in hit["matched_value"] for hit in alias["hits"])

    @pytest.mark.asyncio
    async def test_query_never_downloads(self, sanctions_db, monkeypatch):
        """查询路径只读本地库 —— 下载器被禁也能正常出结果。"""
        import trade.osint.sanctions.sources as sources

        self._seed_cons()

        def _boom(*_a, **_k):
            raise AssertionError("check_sanctions 不应触发下载")

        monkeypatch.setattr(sources, "download_official", _boom)
        monkeypatch.setattr(sources, "fetch_source", _boom)

        from trade.osint.sanctions import check_sanctions

        result = check_sanctions("Mohammed Abu Teir")
        assert result["is_sanctioned"] is True

    def test_offline_query_is_fast(self, sanctions_db):
        """本地查询目标 < 200ms（1 万条规模的代表性测试）。"""
        from trade.osint.sanctions import check_sanctions
        from trade.osint.sanctions.loader import refresh_all

        big = _source("OFAC", "ofac_sdn", ("ofac_sdn.csv",))
        names = [f"TEST SANCTIONED ENTITY NUMBER {i}" for i in range(10_000)]
        parsed = ParsedList(
            label="big", source_url=big.urls[0],
            primary=len(names), aliases=0, rows_total=len(names),
            rows=[(name, "", "entity") for name in names],
        )
        refresh_all(fetch=lambda source: parsed, sources=(big,))

        # 预热（FTS 建好后），再测稳定态
        check_sanctions("TEST SANCTIONED ENTITY NUMBER 1")

        timings = []
        for i in range(20):
            started = time.perf_counter()
            result = check_sanctions(f"Test Sanctioned Entity Number {i}")
            timings.append((time.perf_counter() - started) * 1000)
            assert result["is_sanctioned"] is True

        # 用中位数而不是平均值：整套测试并行跑时偶发一次 GC/调度尖峰
        # 会把平均值拉高。验收关心的是稳定态典型延迟（<200ms），
        # 另设一个宽松上限防止真的退化。
        timings.sort()
        median_ms = timings[len(timings) // 2]
        assert median_ms < 200, f"本地查询中位数 {median_ms:.1f}ms，超过 200ms 目标"
        assert timings[-1] < 1000, f"最慢一次 {timings[-1]:.1f}ms，疑似查询退化"


class TestDownloadGuard:
    def test_rejects_non_official_host(self):
        from trade.osint.sanctions.sources import download_official

        with pytest.raises(ValueError):
            download_official("https://example.com/sanctions.csv")
        with pytest.raises(ValueError):
            download_official("http://sanctionslistservice.ofac.treas.gov/SDN.CSV")

    def test_background_refresh_can_be_disabled(self, monkeypatch):
        """测试 / 离线环境用 TRADE_SANCTIONS_REFRESH=off 关闭后台线程。"""
        monkeypatch.setenv("TRADE_SANCTIONS_REFRESH", "off")

        from trade.osint.sanctions import loader

        assert loader.start_background_refresh(delay=0, interval=0) is False
