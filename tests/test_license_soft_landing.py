"""试用到期软着陆 + 价值小结（2026-10-26 方案）。

验收：
1. 试用期内行为不变；
2. 到期后 check_license=False（起草/新查询被挡），但状态为只读、数据仍可浏览；
3. 副驾草稿与视觉抽取到期后也不再产生新草稿/调用；
4. 第 20 天起价值小结算真实事件。
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def lic(tmp_path, monkeypatch):
    import trade.license as license_mod

    path = tmp_path / "data" / "license.json"
    monkeypatch.setattr(license_mod, "_LICENSE_FILE", path)

    def write(data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    return license_mod, write


def _days_ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


class TestLicenseState:
    def test_trial_unchanged(self, lic):
        license_mod, write = lic
        write({"first_launch_at": _days_ago(5)})

        assert license_mod.check_license()[0] is True
        assert license_mod.is_read_only() is False
        st = license_mod.status()
        assert st["status"] == "trial"
        assert st["read_only"] is False
        assert st["days_remaining"] == 25

    def test_expired_is_read_only_with_soft_message(self, lic):
        license_mod, write = lic
        write({"first_launch_at": _days_ago(31)})

        ok, msg = license_mod.check_license()
        assert ok is False
        assert "历史记录" in msg and "资料" in msg and "激活" in msg
        assert license_mod.is_read_only() is True

        st = license_mod.status()
        assert st["status"] == "expired"
        assert st["read_only"] is True
        assert st["request_code"].startswith("TRADE-REQ-")

    def test_tampered_license_is_read_only(self, lic):
        license_mod, write = lic
        write({
            "first_launch_at": _days_ago(3),
            "activated": True,
            "expires_at": "2099-01-01",
            "code": "not-a-real-code",
        })

        assert license_mod.check_license()[0] is False
        assert license_mod.is_read_only() is True
        assert license_mod.status()["status"] == "tampered"

    def test_ensure_license_state_recovers_corrupt_signature(self, lic, monkeypatch):
        """签名字段损坏但激活码仍在 → 中间件/写门控应能自恢复，不能一直 402。

        模拟升级后签名格式漂移：expires_at/code 完好，仅 signature 字节损坏。
        """
        try:
            import cryptography  # noqa: F401
        except ImportError:
            pytest.skip("cryptography 未安装")

        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519

        license_mod, write = lic
        pk = ed25519.Ed25519PrivateKey.generate()
        pub_raw = pk.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        monkeypatch.setattr(license_mod, "_PUBLIC_KEY_BYTES", pub_raw)
        monkeypatch.setattr(license_mod, "_load_private_key", lambda: pk)

        req = license_mod._make_request_code()
        code = license_mod._encode_activation_code(req, "2099-06-01")
        ok, _msg = license_mod.activate(code)
        assert ok is True

        # 只污染 signature，保留 code / expires_at —— 与「格式漂移」同构
        data = json.loads(license_mod._license_file_path().read_text(encoding="utf-8"))
        data["signature"] = "AAAA" + data["signature"][4:]
        write(data)

        assert license_mod.license_state()[0] == "tampered"
        state, _ = license_mod.ensure_license_state()
        assert state == "active", "自恢复后应回到 active，写接口才能放行"
        assert license_mod.is_read_only() is False
        assert license_mod.check_license()[0] is True


class TestTrialSummary:
    def test_summary_counts_real_events(self, lic, tmp_path, monkeypatch):
        license_mod, write = lic
        write({"first_launch_at": _days_ago(21)})

        import trade.database as _db
        monkeypatch.setattr(_db, "_get_db_path", lambda: tmp_path / "trade.db")
        from trade.database import get_connection, init_db

        init_db()
        conn = get_connection()
        try:
            for kind, n in (("draft", 2), ("inquiry", 3), ("product_lookup", 1)):
                for _ in range(n):
                    conn.execute(
                        "INSERT INTO trial_events (ts, company_id, kind) VALUES (?,?,?)",
                        (datetime.now(UTC).timestamp(), 7, kind),
                    )
            conn.commit()
        finally:
            conn.close()

        st = license_mod.status(7)

        assert st["trial_used"] >= 20
        assert st["trial_summary"]["drafts"] == 2
        assert st["trial_summary"]["inquiries"] == 3
        assert st["trial_summary"]["product_lookups"] == 1

    def test_no_summary_before_day_20(self, lic):
        license_mod, write = lic
        write({"first_launch_at": _days_ago(10)})
        assert "trial_summary" not in license_mod.status()


class TestCopilotGate:
    def test_draft_blocked_when_expired(self, lic, monkeypatch):
        _license_mod, write = lic
        write({"first_launch_at": _days_ago(31)})

        from trade.copilot import draft as draft_mod
        from trade.copilot.types import CustomerContext

        def _boom(*a, **k):  # noqa: ARG001
            raise AssertionError("到期后不应调用模型")

        monkeypatch.setattr(draft_mod, "_run_once", _boom)
        ctx = CustomerContext(matched=False, customer_id=None, customer_name="")

        result = draft_mod.generate_draft("你好", ctx, company_id=1)

        assert result.ok is False
        assert "到期" in result.error
        assert "草稿" in result.error

    @pytest.mark.asyncio
    async def test_extract_blocked_when_expired(self, lic, monkeypatch):
        _license_mod, write = lic
        write({"first_launch_at": _days_ago(31)})

        from trade.copilot import extract as extract_mod

        async def _boom(*a, **k):  # noqa: ARG001
            raise AssertionError("到期后不应调用模型")

        monkeypatch.setattr(extract_mod, "_call_extract", _boom)

        result = await extract_mod.extract_dialog_from_text("你好")

        assert result.error_kind == "license"
        assert "到期" in result.error


class TestWriteOnlyGateSource:
    def test_middleware_blocks_business_writes_but_allows_license_and_switch(self):
        root = Path(__file__).resolve().parent.parent
        src = (root / "trade" / "app.py").read_text(encoding="utf-8")

        assert '_license_read_only_guard' in src
        assert 'request.method in {"POST", "PUT", "PATCH", "DELETE"}' in src
        assert '"/api/trade/license/"' in src
        assert 'path.endswith("/switch")' in src
        # 必须走自恢复入口，不能只调只读的 license_state（会假 tampered 挡写入）
        assert "ensure_license_state" in src
