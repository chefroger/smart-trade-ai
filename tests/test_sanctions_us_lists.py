"""OFAC SDN.CSV parsing and the US lists beyond the SDN.

SDN.CSV has no header row. Read with csv.DictReader, its first entity became the
header, no row had an "SDN_Name" key, and every download parsed to 0 entries, so
check_sanctions always fell back to the 2 built-in samples. The file is also about
6 MB, three times the 2 MB http_get cap, so even a correct parser saw a third of it.

The rows below are real rows from OFAC's SDN.CSV, the trade.gov Consolidated
Screening List CSV and us-restricted-parties all.csv of 2026-11-20 (long columns
trimmed).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SDN_CSV = (
    '36,"AEROCARIBBEAN AIRLINES",-0- ,"CUBA",-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0- \r\n'
    '306,"BANCO NACIONAL DE CUBA",-0- ,"CUBA",-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,"a.k.a. \'BNC\'."\r\n'
    "\x1a"
)

CSL_CSV = (
    '"_id","source","entity_number","type","programs","name","title","addresses",'
    '"federal_register_notice","start_date","end_date","standard_order","license_requirement",'
    '"license_policy","call_sign","vessel_type","gross_tonnage","gross_registered_tonnage",'
    '"vessel_flag","vessel_owner","remarks","source_list_url","alt_names","citizenships",'
    '"dates_of_birth","nationalities","places_of_birth","source_information_url","ids"\n'
    '"03af7d6d","Entity List (EL) - Bureau of Industry and Security","","","",'
    '"Huawei Technologies Co., Ltd.","","Tsim Sha Tsui, Kowloon, HK","84 FR 22963","2019-05-21",'
    '"","","","","","","","","","","","","","","","","","",""\n'
    '"ebb648a4","Military End User (MEU) List - Bureau of Industry and Security","","","",'
    '"Academy of Aerospace Solid Propulsion Technology (AASPT)","","Xian, China, CN",'
    '"85 FR 83799","2020-12-23","","","","","","","","","","","","","AASPT","","","","","",""\n'
    '"36","Specially Designated Nationals (SDN) - Treasury Department","36","Entity","CUBA",'
    '"AEROCARIBBEAN AIRLINES","","Havana, CU","","","","","","","","","","","","","","",'
    '"AERO-CARIBBEAN","","","","","",""\n'
)

FEED_CSV = (
    "RECORD_ID,NAME,NAME_TYPE,DATA_SOURCE,LIST_NAME,LISTED_ON,PARENT_NAME,SOURCE_URL\n"
    'us_dhs_uflpa-aksu-aodu-sugar-industry-co-ltd,"Aksu Aodu Sugar Industry Co., Ltd.",PRIMARY,'
    "US_DHS_UFLPA,UFLPA Entity List,2026-08-03,,https://www.federalregister.gov/\n"
    "us_fcc_covered-china-mobile-international-usa-inc,China Mobile International USA Inc,"
    "PRIMARY,US_FCC_COVERED,FCC Covered List (Secure and Trusted Communications Networks Act),"
    "2022-03-25,,https://www.fcc.gov/supplychain/coveredlist\n"
)


def test_sdn_csv_without_header_parses_every_row():
    from trade.osint.sanctions.loader import parse_sdn_csv

    rows = parse_sdn_csv(SDN_CSV)

    assert [r["name"] for r in rows] == ["AEROCARIBBEAN AIRLINES", "BANCO NACIONAL DE CUBA"]
    assert rows[0]["program"] == "CUBA"
    assert rows[0]["type"] == "", "-0- is OFAC's empty marker, not a value"


def test_csl_skips_sdn_rows_and_keeps_alt_names():
    from trade.osint.sanctions.loader import parse_us_csl_csv

    rows = parse_us_csl_csv(CSL_CSV)

    assert [(r["name"], r["label"]) for r in rows] == [
        ("Huawei Technologies Co., Ltd.", "Entity List (EL)"),
        (
            "Academy of Aerospace Solid Propulsion Technology (AASPT)",
            "Military End User (MEU) List",
        ),
        ("AASPT", "Military End User (MEU) List"),
    ]
    assert rows[0]["country"] == "HK"


def test_us_restricted_feed_rows():
    from trade.osint.sanctions.loader import parse_us_restricted_csv

    rows = parse_us_restricted_csv(FEED_CSV)

    assert [r["label"] for r in rows] == [
        "UFLPA Entity List",
        "FCC Covered List (Secure and Trusted Communications Networks Act)",
    ]


@pytest.fixture
def served(monkeypatch):
    """Serve the three files above from http_get, with no file cache."""
    from trade.osint.sanctions import loader

    monkeypatch.setattr(loader, "_sanctions_cache", {}, raising=False)
    monkeypatch.setattr(loader, "_sanctions_meta", {}, raising=False)
    monkeypatch.setattr(loader, "_load_from_file_cache", lambda _n: None, raising=False)
    monkeypatch.setattr(loader, "_load_from_file_cache_expired", lambda _n: None, raising=False)
    monkeypatch.setattr(loader, "_save_to_file_cache", lambda *_a, **_k: None, raising=False)
    monkeypatch.setattr(loader, "_MIN_OFAC_ENTRIES", 1)
    monkeypatch.setattr(loader, "_MIN_US_CSL_ENTRIES", 1)
    monkeypatch.setattr(loader, "_MIN_US_RESTRICTED_ENTRIES", 1)
    calls: list[tuple[str, int | None]] = []

    def fake_get(url, timeout=30, max_bytes=None):
        calls.append((url, max_bytes))
        if url == loader._US_CSL_URL:
            return CSL_CSV
        if url == loader._US_RESTRICTED_URL:
            return FEED_CSV
        return SDN_CSV

    monkeypatch.setattr(loader, "http_get", fake_get, raising=False)
    return calls


@pytest.mark.parametrize(
    ("query", "list_name", "label"),
    [
        ("BANCO NACIONAL DE CUBA", "OFAC", "OFAC SDN"),
        ("Huawei Technologies Co., Ltd.", "US_CSL", "Entity List (EL)"),
        ("Aksu Aodu Sugar Industry Co., Ltd.", "US_RESTRICTED", "UFLPA Entity List"),
        ("China Mobile International USA Inc", "US_RESTRICTED", "FCC Covered List"),
    ],
)
def test_party_on_each_list_is_a_hit(served, query, list_name, label):
    from trade.osint.sanctions import check_sanctions

    result = check_sanctions(query)

    assert result["is_sanctioned"] is True
    assert result["hits"][0]["list"] == list_name
    assert result["hits"][0]["list_label"].startswith(label)


def test_large_lists_are_fetched_whole(served):
    from trade.osint.sanctions import check_sanctions, loader

    check_sanctions("Some Random Trading LLC")

    caps = dict(served)
    assert caps[loader._OFAC_URL_CANDIDATES[0]] >= 6_000_000, "SDN.CSV is about 6 MB"
    assert caps[loader._US_CSL_URL] >= 17_000_000, "the CSL CSV is about 17 MB"


def test_failed_us_list_is_degraded_and_not_retried_per_lookup(monkeypatch, served):
    from trade.osint.sanctions import check_sanctions, loader

    real = loader.http_get
    csl_tries: list[str] = []

    def no_csl(url, timeout=30, max_bytes=None):
        if url == loader._US_CSL_URL:
            csl_tries.append(url)
            return None
        return real(url, timeout, max_bytes)

    monkeypatch.setattr(loader, "http_get", no_csl)
    first = check_sanctions("Huawei Technologies Co., Ltd.")
    check_sanctions("Huawei Technologies Co., Ltd.")

    assert first["is_sanctioned"] is False
    assert first["coverage"]["lists"]["US_CSL"]["degraded"] is True
    assert "未在任何制裁名单中发现匹配项" not in first["suggestion"]
    assert len(csl_tries) == 1, "a failed list must not be re-downloaded on every lookup"
