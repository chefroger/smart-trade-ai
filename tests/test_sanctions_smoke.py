"""S10：制裁下载冒烟必须覆盖全部名单，并在任一份失败时返回非 0。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import sanctions_smoke  # noqa: E402

import trade.osint.sanctions.sources as sanctions_sources  # noqa: E402


def _ok_probe(url, max_bytes=0):  # noqa: ARG001
    return {
        "ok": True, "bytes_read": 1024,
        "entry_host": "entry.example", "final_host": "entry.example", "error": "",
    }


def test_smoke_covers_every_list(monkeypatch):
    seen: list[str] = []

    def probe(url, max_bytes=0):  # noqa: ARG001
        seen.append(url)
        return _ok_probe(url)

    monkeypatch.setattr(sanctions_sources, "probe_official", probe)
    assert sanctions_smoke.main() == 0
    # 注册表里的每份名单都探测到（OFAC / OFAC_NS / CSL / UN / EU / UK）
    assert len(seen) == len(sanctions_sources.SOURCES)
    assert set(sanctions_smoke.TARGETS) == {s.name for s in sanctions_sources.SOURCES}


def test_smoke_fails_when_any_list_fails(monkeypatch):
    def probe(url, max_bytes=0):  # noqa: ARG001
        return {
            "ok": False, "bytes_read": 0,
            "entry_host": "entry.example", "final_host": "",
            "error": "HTTP 500",
        }

    monkeypatch.setattr(sanctions_sources, "probe_official", probe)
    assert sanctions_smoke.main() == 1


def test_smoke_fails_on_empty_body(monkeypatch):
    def probe(url, max_bytes=0):  # noqa: ARG001
        return {
            "ok": True, "bytes_read": 0,
            "entry_host": "entry.example", "final_host": "entry.example", "error": "",
        }

    monkeypatch.setattr(sanctions_sources, "probe_official", probe)
    assert sanctions_smoke.main() == 1
