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
    redirect_allowed,
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

    def test_csl_long_field_does_not_abort_parse(self):
        """W1 依赖 CSL 的人类型：字段超 131072 时不能整份名单解析失败。"""
        long_alias = "LONGALIAS" * 25_000  # 225000 字符 > csv 默认上限
        payload = (
            "name,type,alt_names\n"
            f"ACME TRADING LLC,Entity,{long_alias}\n"
        ).encode()
        parsed = parse_source(_source("CSL", "csl", ("csl.csv",)), [payload])
        assert parsed.primary == 1
        assert parsed.aliases == 1
        assert parsed.rows_total == 1

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
        kinds = {row[0]: row[2] for row in parsed.rows}
        names = list(kinds)
        # 4 行数据、1 组重复（同 Unique ID 同名）→ 3 条姓名
        assert parsed.rows_total == 4
        assert len(names) == 3
        assert "HAJI KHAIRULLAH MONEY EXCHANGE" in names
        assert "SMITH JOHN" in names
        assert parsed.aliases == 1
        # W1：Designation Type 明确区分个人与实体（个人别名同样标 person）
        assert kinds["SMITH JOHN"] == "person"
        assert kinds["JOHNNY SMITH"] == "person"
        assert kinds["HAJI KHAIRULLAH MONEY EXCHANGE"] == "entity"


# ── 重定向白名单（W4）─────────────────────────────────────────────────────


class TestRedirectAllowlist:
    OFAC_ENTRY = "sanctionslistservice.ofac.treas.gov"
    OFAC_BUCKET = (
        "https://wc2h-sls-prod-public-published.s3.us-gov-west-1.amazonaws.com"
        "/Published/SDN.CSV"
    )
    UN_HOST = "unsolprodfiles.blob.core.windows.net"

    def test_official_ofac_bucket_allowed(self):
        assert redirect_allowed(self.OFAC_ENTRY, self.OFAC_BUCKET) is True

    def test_same_suffix_attacker_bucket_rejected(self):
        """只校验后缀会被 attacker-bucket 绕过：必须精确主机。"""
        assert redirect_allowed(
            self.OFAC_ENTRY,
            "https://attacker-bucket.s3.us-gov-west-1.amazonaws.com/Published/evil.csv",
        ) is False

    def test_ofac_bucket_requires_published_prefix(self):
        assert redirect_allowed(
            self.OFAC_ENTRY,
            "https://wc2h-sls-prod-public-published.s3.us-gov-west-1.amazonaws.com/evil.csv",
        ) is False

    def test_un_blob_allowed(self):
        assert redirect_allowed(
            "scsanctions.un.org", f"https://{self.UN_HOST}/resources/xml/en/consolidated.xml"
        ) is True

    def test_cross_pairing_rejected(self):
        # OFAC 入口不允许跳到 UN 的 CDN，反向同样拒绝
        assert redirect_allowed(
            self.OFAC_ENTRY, f"https://{self.UN_HOST}/x.xml"
        ) is False
        assert redirect_allowed("scsanctions.un.org", self.OFAC_BUCKET) is False

    def test_http_and_same_host(self):
        assert redirect_allowed(
            self.OFAC_ENTRY,
            "http://wc2h-sls-prod-public-published.s3.us-gov-west-1.amazonaws.com/Published/SDN.CSV",
        ) is False
        assert redirect_allowed(
            self.OFAC_ENTRY,
            "https://sanctionslistservice.ofac.treas.gov/api/x.csv",
        ) is True


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

        # 工单验收：First Last 命中 LAST, First；个人姓名只给 possible/medium（W1）
        exact = check_sanctions("Mohammed Abu Teir")
        assert exact["is_sanctioned"] is False
        assert exact["risk_level"] == "medium"
        assert any(hit["matched_value"] == "ABU TEIR, Mohammed"
                   and hit["confirmation"] == "possible" for hit in exact["hits"])
        assert "拒绝" not in exact["suggestion"]

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
        assert result["hits"], "本地命中消失"

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

    def test_rejects_redirect_to_non_official_host(self, monkeypatch):
        """通用 opener 只拦内网；重定向到白名单外主机必须拒绝（审计 P2-8）。"""
        from trade.osint.sanctions import sources

        class _Resp:
            headers = {}

            def geturl(self):
                return "https://evil.example/payload.csv"

            def read(self, n):
                return b""

        class _Ctx:
            def __enter__(self):
                return _Resp()

            def __exit__(self, *a):
                return False

        class _Opener:
            def open(self, *a, **kw):
                return _Ctx()

        monkeypatch.setattr(sources, "_current_opener", lambda: _Opener())
        with pytest.raises(ValueError, match="重定向"):
            sources.download_official("https://sanctionslistservice.ofac.treas.gov/SDN.CSV")

    def test_background_refresh_can_be_disabled(self, monkeypatch):
        """测试 / 离线环境用 TRADE_SANCTIONS_REFRESH=off 关闭后台线程。"""
        monkeypatch.setenv("TRADE_SANCTIONS_REFRESH", "off")

        from trade.osint.sanctions import loader

        assert loader.start_background_refresh(delay=0, interval=0) is False


class TestMatchQuality:
    """工单 P1-G（11-22 P1-A）：停用词、confirmed/possible、短品牌名、中文后缀。"""

    def _seed(self, names: list[tuple[str, str]]):
        from trade.osint.sanctions.loader import refresh_all

        src = _source("OFAC", "ofac_sdn", ("ofac_sdn.csv",))
        parsed = ParsedList(
            label="quality", source_url=src.urls[0],
            primary=len(names), aliases=0, rows_total=len(names),
            rows=[(name, "", kind) for name, kind in names],
        )
        refresh_all(fetch=lambda source: parsed, sources=(src,))

    def test_legal_suffixes_do_not_create_hits(self, sanctions_db):
        from trade.osint.sanctions import check_sanctions

        self._seed([("SHENZHEN ABC TECHNOLOGY CO LTD", "entity")])
        result = check_sanctions("Shenzhen Technology Co Ltd")

        assert result["hits"] == [], "co/ltd/technology 这些泛词不应凑出疑似命中"
        assert result["risk_level"] == "none"

    def test_short_brand_hits_core_tokens(self, sanctions_db):
        from trade.osint.sanctions import check_sanctions

        self._seed([("HUAWEI TECHNOLOGIES CO LTD", "entity")])
        result = check_sanctions("HUAWEI")

        assert result["is_sanctioned"] is True
        assert result["hits"][0]["confirmation"] == "confirmed"
        assert result["risk_level"] == "high"

    def test_short_brand_does_not_match_different_token(self, sanctions_db):
        from trade.osint.sanctions import check_sanctions

        self._seed([("ABC HOLDINGS LTD", "entity")])
        assert check_sanctions("ABCDE")["hits"] == []

    def test_alias_exact_is_confirmed(self, sanctions_db):
        from trade.osint.sanctions import check_sanctions

        self._seed([("BOUT, Viktor Anatoljevitch", "entity"), ("Viktor Bout", "alias")])
        result = check_sanctions("Viktor Bout")

        assert result["is_sanctioned"] is True
        assert any(h["matched_value"] == "Viktor Bout" for h in result["hits"])

    def test_same_name_person_is_possible_not_confirmed(self, sanctions_db):
        """W1 推翻 11-22 的「个人也算 confirmed」：姓名一致不足以确认身份。"""
        from trade.osint.sanctions import check_sanctions

        self._seed([("WANG WEI", "entity")])
        result = check_sanctions("Wang Wei")

        assert result["is_sanctioned"] is False
        assert result["hits"][0]["confirmation"] == "possible"

    def test_person_names_are_possible_medium(self, sanctions_db):
        """W1：只有姓名一致时不能 high/拒绝；改为 possible + medium。"""
        from trade.osint.sanctions import check_sanctions

        self._seed([
            ("WANG WEI", "person"),
            ("ZHANG WEI", "person"),
            ("LI NA", "person"),
        ])
        for query in ("Wang Wei", "Zhang Wei", "Li Na"):
            result = check_sanctions(query)
            assert result["is_sanctioned"] is False, query
            assert result["risk_level"] == "medium", query
            assert result["hits"][0]["confirmation"] == "possible", query
            assert "拒绝" not in result["suggestion"], query
            assert "出生日期" in result["suggestion"], query

    def test_entities_remain_confirmed_high(self, sanctions_db):
        from trade.osint.sanctions import check_sanctions

        self._seed([
            ("HUAWEI TECHNOLOGIES CO LTD", "entity"),
            # 真实名单里有精确的 ROSNEFT 行；O-新1 后不再依赖子集确认
            ("ROSNEFT", "entity"),
            ("ISLAMIC REVOLUTIONARY GUARD CORPS", "entity"),
        ])
        for query in ("HUAWEI", "Rosneft", "Islamic Revolutionary Guard Corps"):
            result = check_sanctions(query)
            assert result["is_sanctioned"] is True, query
            assert result["risk_level"] == "high", query
            assert result["hits"][0]["confirmation"] == "confirmed", query

    def test_short_name_subset_is_possible_not_confirmed(self, sanctions_db):
        """O-新1：短名子集（London → MINGMEN LONDON LTD）只能是 possible。"""
        from trade.osint.sanctions import check_sanctions

        self._seed([
            ("MINGMEN LONDON LTD", "entity"),
            ("CHASCA LONDON LIMITED", "entity"),
            ("LLC MOSCOW ARMS COMPANY", "entity"),
        ])
        for query in ("London", "Moscow"):
            result = check_sanctions(query)
            assert result["is_sanctioned"] is False, query
            assert result["risk_level"] != "high", query
            assert all(h["confirmation"] == "possible" for h in result["hits"]), query

    def test_shenzhen_no_single_token_suspect(self, sanctions_db):
        from trade.osint.sanctions import check_sanctions

        self._seed([
            ("SHENZHEN", "entity"),
            ("SHENZHEN A TECHNOLOGY CO LTD", "entity"),
        ])
        result = check_sanctions("Shenzhen Technology Co Ltd")
        assert all(hit["matched_value"] != "SHENZHEN" for hit in result["hits"])

    def test_person_spelling_variant_is_possible(self, sanctions_db):
        """W1：Victor Bout 至少要有 possible（Victor ↔ Viktor）。"""
        from trade.osint.sanctions import check_sanctions

        self._seed([("BOUT, Viktor Anatolijevitch", "person")])
        result = check_sanctions("Victor Bout")
        assert result["hits"], "拼写变体完全没有命中"
        assert result["risk_level"] == "medium"
        assert result["hits"][0]["confirmation"] == "possible"

    def test_structural_person_heuristic(self, sanctions_db):
        """老库没有 person kind 时，'WANG, Wei' 这种结构按个人处理。"""
        from trade.osint.sanctions import check_sanctions

        self._seed([("WANG, Wei", "entity")])
        result = check_sanctions("Wang Wei")
        assert result["hits"][0]["confirmation"] == "possible"
        assert result["risk_level"] == "medium"

    def test_untyped_two_token_chinese_name_is_person(self, sanctions_db):
        """CSL 的 BIS 行没有 type：无逗号两段式中文姓名按个人处理。"""
        from trade.osint.sanctions import check_sanctions

        self._seed([("Wang Wei", "entity")])
        result = check_sanctions("Wang Wei")
        assert result["hits"][0]["confirmation"] == "possible"
        assert result["risk_level"] == "medium"
        assert "拒绝" not in result["suggestion"]

    def test_untyped_reverse_order_chinese_name_is_person(self, sanctions_db):
        """别名常是「名 姓」（Jack Wang），同样按个人处理。"""
        from trade.osint.sanctions import check_sanctions

        self._seed([("Jack Wang", "entity")])
        result = check_sanctions("Jack Wang")
        assert result["hits"][0]["confirmation"] == "possible"
        assert result["risk_level"] == "medium"

    def test_two_token_company_is_not_person(self, sanctions_db):
        """姓氏启发式不能把 'Samsung Electronics' 这类公司当个人。"""
        from trade.osint.sanctions import check_sanctions

        self._seed([("Samsung Electronics", "entity")])
        result = check_sanctions("Samsung Electronics")
        assert result["hits"][0]["confirmation"] == "confirmed"
        assert result["risk_level"] == "high"

    def test_chinese_company_suffix_stripped(self, sanctions_db):
        from trade.osint.sanctions import check_sanctions

        self._seed([("华为技术有限公司", "entity")])
        result = check_sanctions("华为")

        assert result["is_sanctioned"] is True
        assert result["hits"][0]["confirmation"] == "confirmed"


class TestRefreshBackoff:
    """工单 P1-G（11-22 P1-B）：5/15/60 分钟退避 + 20h 新鲜跳过。"""

    def test_next_delay_backoff_sequence(self):
        from trade.osint.sanctions.loader import _next_delay

        assert _next_delay(False, 3, 86400) == 86400
        assert _next_delay(True, 0, 86400) == 300
        assert _next_delay(True, 1, 86400) == 900
        assert _next_delay(True, 5, 86400) == 3600

    def test_skip_fresh_does_not_fetch(self, sanctions_db):
        from trade.osint.sanctions.loader import refresh_all

        src = _source("CSL", "csl", ("csl.csv",))
        refresh_all(fetch=lambda source: _parse(src), sources=(src,))
        calls: list[str] = []

        def _should_not_run(source):
            calls.append(source.name)
            raise AssertionError("20h 内已刷新过，不应再下载")

        results = refresh_all(fetch=_should_not_run, sources=(src,), skip_fresh=True)
        assert calls == []
        assert results["CSL"]["skipped"] is True

    def test_failed_source_is_retried_despite_skip_fresh(self, sanctions_db):
        from trade.osint.sanctions.loader import refresh_all

        src = _source("CSL", "csl", ("csl.csv",))

        def _boom(source):
            raise RuntimeError("network down")

        refresh_all(fetch=_boom, sources=(src,))
        results = refresh_all(
            fetch=lambda source: _parse(src), sources=(src,), skip_fresh=True)
        assert results["CSL"]["ok"] is True
        assert not results["CSL"].get("skipped")

    def test_missing_tokenizer_marker_forces_refresh(self, sanctions_db):
        """升级后归一化规则变化：没有新版标记时不能跳过刷新（否则旧 tkey 残留）。"""
        from trade.osint.sanctions import loader

        src = _source("CSL", "csl", ("csl.csv",))
        loader.refresh_all(fetch=lambda source: _parse(src), sources=(src,))
        loader._tokenizer_marker().unlink()
        calls: list[str] = []

        def _boom(source):
            calls.append(source.name)
            raise RuntimeError("should refresh")

        results = loader.refresh_all(fetch=_boom, sources=(src,), skip_fresh=True)
        assert calls == ["CSL"]
        assert results["CSL"]["ok"] is False


# ── 归一化升级窗口（W5）────────────────────────────────────────────────────


class TestTokenizerMigration:
    """归一化规则升级后、首次刷新前，旧库中文名不能漏查。"""

    def _legacy_db(self, path):
        import sqlite3

        from trade.osint.sanctions import store
        from trade.osint.sanctions.store import _now_iso

        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        store.ensure_writable_db(conn)
        # 旧口径：norm/tkey 保留「华为技术有限公司」整串（未剥后缀）
        conn.execute(
            "INSERT INTO entities(list, name, norm, tkey, country, kind) "
            "VALUES (?,?,?,?,?,?)",
            ("OFAC", "华为技术有限公司", "华为技术有限公司", "华为技术有限公司", "China", "entity"),
        )
        conn.execute(
            "INSERT INTO entities(list, name, norm, tkey, country, kind) "
            "VALUES (?,?,?,?,?,?)",
            ("OFAC", "HUAWEI TECHNOLOGIES CO., LTD.", "huawei technologies co ltd",
             "co huawei ltd technologies", "", "entity"),
        )
        # 所有名单都标健康（否则先命中 degraded 分支，测不到迁移提示）
        for source in store.SOURCES:
            conn.execute(
                "INSERT INTO lists(name, label, entries, aliases, rows_total, source_url, "
                "fetched_at, last_attempt_at) VALUES (?,?,?,?,?,?,?,?)",
                (source.name, source.label, 1, 0, 1, source.urls[0],
                 _now_iso(), _now_iso()),
            )
        conn.commit()
        conn.close()

    def test_legacy_db_migrates_on_first_query(self, sanctions_db):
        from trade.osint.sanctions import check_sanctions
        from trade.osint.sanctions.store import tokenizer_marker_path

        self._legacy_db(sanctions_db)
        assert not tokenizer_marker_path().is_file()

        for query in ("华为技术有限公司", "华为"):
            result = check_sanctions(query)
            assert result["hits"], query

        assert tokenizer_marker_path().is_file(), "迁移后必须写版本标记"

    def test_coverage_flags_legacy_before_migration(self, sanctions_db):
        from trade.osint.sanctions.store import get_coverage

        self._legacy_db(sanctions_db)
        coverage = get_coverage()
        assert coverage["tokenizer_legacy"] is True
        note = coverage["lists"]["OFAC"].get("note") or ""
        assert "迁移" in note and "漏查" in note

    def test_legacy_suggestion_when_migration_fails(self, sanctions_db, monkeypatch):
        import trade.osint.sanctions as sanctions_pkg

        self._legacy_db(sanctions_db)
        monkeypatch.setattr(sanctions_pkg, "_ensure_migrated", lambda: False)

        result = sanctions_pkg.check_sanctions("华为")
        assert result["hits"] == []
        assert "迁移" in result["suggestion"]
        assert "无制裁记录" in result["suggestion"]


# ── 刷新/匹配安全（W15 O-1/O-2/O-5）───────────────────────────────────────


class TestRefreshSafety:
    def _make_db(self, path, *, fetched_at: str, entries: int = 10):
        import sqlite3

        from trade.osint.sanctions import store
        from trade.osint.sanctions.store import _now_iso

        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        store.ensure_writable_db(conn)
        conn.execute(
            "INSERT INTO lists(name, label, entries, aliases, rows_total, source_url, "
            "fetched_at, last_attempt_at) VALUES (?,?,?,?,?,?,?,?)",
            ("OFAC", "美国 OFAC SDN 名单", entries, 0, entries,
             "https://example.test/x.csv", fetched_at,
             _now_iso()),
        )
        conn.execute(
            "INSERT INTO entities(list, name, norm, tkey, country, kind) VALUES (?,?,?,?,?,?)",
            ("OFAC", "ACME TRADING", "acme trading", "acme trading", "", "entity"),
        )
        conn.commit()
        conn.close()

    def test_corrupt_fetched_at_is_degraded(self, sanctions_db):
        """O-1：损坏时间戳不能回落成「刚抓过」。"""
        from trade.osint.sanctions.store import get_coverage

        self._make_db(sanctions_db, fetched_at="not-a-date")
        cov = get_coverage()
        assert cov["lists"]["OFAC"]["degraded"] is True
        assert cov["degraded"] is True
        assert "无法解析" in (cov["lists"]["OFAC"].get("note") or "")

    def test_save_list_refuses_sharp_shrink(self, sanctions_db):
        """O-2：解析条目剧烈缩水时保留旧数据。"""
        import sqlite3

        from trade.osint.sanctions import store
        from trade.osint.sanctions.sources import ParsedList, Source

        self._make_db(sanctions_db, fetched_at="2026-11-23T00:00:00+00:00", entries=1000)
        src = Source("OFAC", "OFAC", "ofac_sdn", ("https://example.test/x.csv",))
        parsed = ParsedList(
            label="OFAC", source_url=src.urls[0], primary=1, aliases=0,
            rows_total=1, rows=[("ACME TRADING", "", "entity")],
        )
        conn = sqlite3.connect(str(sanctions_db))
        conn.row_factory = sqlite3.Row
        try:
            store.ensure_writable_db(conn)
            with pytest.raises(ValueError, match="缩水"):
                store.save_list(conn, src, parsed)
        finally:
            conn.close()

    def test_candidate_cap_follows_up_with_and_query(self, sanctions_db, monkeypatch):
        """O-5：候选达到上限时用 AND 补查，真命中不被挤出。"""
        import sqlite3

        from trade.osint.sanctions import store

        conn = sqlite3.connect(str(sanctions_db))
        conn.row_factory = sqlite3.Row
        try:
            store.ensure_writable_db(conn)
            conn.executemany(
                "INSERT INTO entities(list, name, norm, tkey, country, kind) "
                "VALUES (?,?,?,?,?,?)",
                [
                    ("OFAC", "ACME OTHER", "acme other", "acme other", "", "entity"),
                    ("OFAC", "ACME TRADING", "acme trading", "acme trading", "", "entity"),
                ],
            )
            store.rebuild_fts(conn)
            conn.commit()
            monkeypatch.setattr(store, "_CANDIDATE_LIMIT", 1)
            rows = store._candidates(conn, frozenset({"acme", "trading"}))
            names = {row["name"] for row in rows}
            assert "ACME TRADING" in names
        finally:
            conn.close()
