"""审计 P0-A：制裁名单重定向只放行成对的官方 CDN。

2026-11-23 审计实测：OFAC 两份名单 302 到
`*.s3.us-gov-west-1.amazonaws.com/Published/...`，UN 302 到
`unsolprodfiles.blob.core.windows.net`；旧代码要求最终主机仍在入口白名单，
三份名单因此永远下载不下来。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade.osint.sanctions import sources  # noqa: E402

OFAC_ENTRY = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV"
UN_ENTRY = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"


class _Resp:
    """最小 HTTP 响应桩：只需 geturl/read/headers/close。"""

    def __init__(self, final_url: str, body: bytes = b"payload"):
        self._final = final_url
        self._body = body
        self.headers = {}

    def geturl(self) -> str:
        return self._final

    def read(self, n: int) -> bytes:
        chunk, self._body = self._body[:n], self._body[n:]
        return chunk

    def close(self) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> bool:
        self.close()
        return False


class _Opener:
    def __init__(self, final_url: str, body: bytes = b"payload"):
        self._resp = _Resp(final_url, body)

    def open(self, *_a, **_kw):
        return self._resp


def _patch(monkeypatch, final_url: str, body: bytes = b"payload"):
    monkeypatch.setattr(sources, "_current_opener", lambda: _Opener(final_url, body))


class TestRedirectWhitelist:
    def test_ofac_to_gov_s3_published_is_allowed(self, monkeypatch):
        final = (
            "https://wc2h-sls-prod-public-published.s3.us-gov-west-1.amazonaws.com"
            "/Published/SDN.CSV"
        )
        _patch(monkeypatch, final)

        assert sources.download_official(OFAC_ENTRY) == b"payload"

    def test_ofac_to_other_bucket_path_is_rejected(self, monkeypatch):
        final = (
            "https://wc2h-sls-prod-public-published.s3.us-gov-west-1.amazonaws.com"
            "/Private/SDN.CSV"
        )
        _patch(monkeypatch, final)

        with pytest.raises(ValueError, match="重定向"):
            sources.download_official(OFAC_ENTRY)

    def test_ofac_crossing_to_un_blob_is_rejected(self, monkeypatch):
        """入口是 OFAC、却跳到 UN 的 CDN：跳转必须按入口主机成对匹配。"""
        final = "https://unsolprodfiles.blob.core.windows.net/consolidated.xml"
        _patch(monkeypatch, final)

        with pytest.raises(ValueError, match="重定向"):
            sources.download_official(OFAC_ENTRY)

    def test_un_to_azure_blob_is_allowed(self, monkeypatch):
        final = "https://unsolprodfiles.blob.core.windows.net/consolidated.xml"
        _patch(monkeypatch, final)

        assert sources.download_official(UN_ENTRY) == b"payload"

    def test_un_crossing_to_gov_s3_is_rejected(self, monkeypatch):
        final = (
            "https://wc2h-sls-prod-public-published.s3.us-gov-west-1.amazonaws.com"
            "/Published/SDN.CSV"
        )
        _patch(monkeypatch, final)

        with pytest.raises(ValueError, match="重定向"):
            sources.download_official(UN_ENTRY)

    def test_same_host_redirect_is_allowed(self, monkeypatch):
        final = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV"
        _patch(monkeypatch, final)

        assert sources.download_official(OFAC_ENTRY) == b"payload"

    def test_http_final_url_is_rejected(self, monkeypatch):
        final = (
            "http://wc2h-sls-prod-public-published.s3.us-gov-west-1.amazonaws.com"
            "/Published/SDN.CSV"
        )
        _patch(monkeypatch, final)

        with pytest.raises(ValueError, match="重定向"):
            sources.download_official(OFAC_ENTRY)

    def test_max_bytes_stops_early_without_error(self, monkeypatch):
        """冒烟只读前 N 字节：文件更大也不报错。"""
        final = (
            "https://wc2h-sls-prod-public-published.s3.us-gov-west-1.amazonaws.com"
            "/Published/SDN.CSV"
        )
        _patch(monkeypatch, final, body=b"x" * 5000)

        data = sources.download_official(OFAC_ENTRY, max_bytes=100)

        assert len(data) == 100


class TestProbeOfficial:
    def test_success_reports_hosts_and_bytes(self, monkeypatch):
        final = (
            "https://wc2h-sls-prod-public-published.s3.us-gov-west-1.amazonaws.com"
            "/Published/SDN.CSV"
        )
        _patch(monkeypatch, final, body=b"y" * 300)

        result = sources.probe_official(OFAC_ENTRY, max_bytes=128)

        assert result["ok"] is True
        assert result["entry_host"] == "sanctionslistservice.ofac.treas.gov"
        assert result["final_host"].endswith("s3.us-gov-west-1.amazonaws.com")
        assert result["bytes_read"] == 128

    def test_failure_is_returned_not_raised(self, monkeypatch):
        _patch(monkeypatch, "https://evil.example/payload.csv")

        result = sources.probe_official(OFAC_ENTRY)

        assert result["ok"] is False
        assert result["final_host"] == "evil.example"
        assert "重定向" in result["error"]
