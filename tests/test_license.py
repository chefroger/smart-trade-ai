"""
许可证系统单元测试 — 试用期 + 激活码生成/验证/机器码绑定。
"""

import datetime
from pathlib import Path
from unittest import mock

import pytest

# CI 环境可能没有 cryptography 包，需要 Ed25519 的测试自动跳过
try:
    import cryptography  # noqa: F401
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False

_crypto_needed = pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography 未安装")


class TestMachineId:
    """机器码生成测试"""

    def test_machine_id_not_empty(self):
        from trade.license import _machine_id
        mid = _machine_id()
        assert mid
        assert ":" in mid
        assert len(mid) > 5

    def test_machine_id_stable(self):
        from trade.license import _machine_id
        a = _machine_id()
        b = _machine_id()
        assert a == b

    def test_machine_id_macos_format(self):
        """macOS 上应返回 mac:UUID 格式"""
        import platform
        if platform.system() != "Darwin":
            pytest.skip("非 macOS")
        from trade.license import _machine_id
        mid = _machine_id()
        assert mid.startswith("mac:")

    def test_machine_id_fallback_hostname(self):
        """模拟所有平台检测失败时的 hostname fallback"""
        with mock.patch("trade.license._get_license_data", return_value={}):
            with mock.patch("trade.license._save_license_data"):
                with mock.patch("platform.system", return_value="SunOS"):
                    with mock.patch("subprocess.run", side_effect=OSError):
                        with mock.patch("platform.node", return_value="myhost"):
                            from trade.license import _machine_id
                            mid = _machine_id()
                            assert mid == "host:myhost"


class TestRequestCode:
    """申请码生成测试"""

    def test_format(self):
        from trade.license import _make_request_code
        code = _make_request_code()
        assert code.startswith("TRADE-REQ-")
        # 完整 SHA256 64 hex + 分隔符 + 前缀
        assert len(code) > 80

    def test_deterministic(self):
        from trade.license import _make_request_code
        a = _make_request_code()
        b = _make_request_code()
        assert a == b  # 同一机器应生成相同申请码


def _setup_temp_ed25519_key(monkeypatch):
    """设置临时 Ed25519 测试密钥对，替换内置公钥 + 私钥加载函数。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    pk = ed25519.Ed25519PrivateKey.generate()
    pub_raw = pk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    monkeypatch.setattr("trade.license._PUBLIC_KEY_BYTES", pub_raw)
    monkeypatch.setattr("trade.license._load_private_key", lambda: pk)


class TestEncodeDecode:
    """激活码编解码 roundtrip"""

    def test_roundtrip(self, monkeypatch):
        _setup_temp_ed25519_key(monkeypatch)
        from trade.license import (
            _decode_activation_code,
            _encode_activation_code,
            _make_request_code,
        )

        req = _make_request_code()
        code = _encode_activation_code(req, "2027-06-01")
        assert code.startswith("TRADE-")
        assert len(code) > 40

        decoded = _decode_activation_code(code)
        assert decoded["expires_at"] == "2027-06-01"
        assert len(decoded["machine_hash"]) == 64  # 256 bit (new format)

    def test_decode_rejects_tampered_code(self, monkeypatch):
        _setup_temp_ed25519_key(monkeypatch)
        from trade.license import (
            _decode_activation_code,
            _encode_activation_code,
            _make_request_code,
        )

        req = _make_request_code()
        code = _encode_activation_code(req, "2027-06-01")
        parts = code.split("-")
        parts[-1] = "XXXX"
        tampered = "-".join(parts)
        with pytest.raises(ValueError):
            _decode_activation_code(tampered)

    def test_decode_rejects_wrong_length(self):
        from trade.license import _decode_activation_code
        with pytest.raises(ValueError):
            _decode_activation_code("TRADE-SHORT")

    def test_different_machines_different_hash(self, monkeypatch):
        """不同机器码应产生不同的激活码哈希"""
        _setup_temp_ed25519_key(monkeypatch)
        from trade.license import _decode_activation_code, _encode_activation_code

        code1 = _encode_activation_code("TRADE-REQ-AAAA-BBBB", "2027-06-01")
        code2 = _encode_activation_code("TRADE-REQ-CCCC-DDDD", "2027-06-01")
        d1 = _decode_activation_code(code1)
        d2 = _decode_activation_code(code2)
        assert d1["machine_hash"] != d2["machine_hash"]

    def test_produces_different_codes_for_same_hash_different_date(self, monkeypatch):
        """相同申请码不同日期应产生不同激活码"""
        _setup_temp_ed25519_key(monkeypatch)
        from trade.license import _encode_activation_code
        code1 = _encode_activation_code("TRADE-REQ-AAAA-BBBB", "2027-06-01")
        code2 = _encode_activation_code("TRADE-REQ-AAAA-BBBB", "2027-12-31")
        assert code1 != code2

    def test_encode_without_private_key_fails(self, monkeypatch):
        """没有私钥时编码应抛出异常"""
        monkeypatch.delenv("TRADE_LICENSE_PRIVATE_KEY", raising=False)
        with mock.patch.object(Path, "is_file", return_value=False):
            from trade.license import _encode_activation_code
            with pytest.raises(ValueError, match="私钥"):
                _encode_activation_code("TRADE-REQ-AAAA-BBBB", "2027-06-01")


class TestLicenseCheck:
    """许可证状态检查（mock 数据库调用）"""

    def test_first_launch(self, monkeypatch):
        """新安装：首次检查应通过"""

        # mock 数据库操作
        saved = {}

        def mock_get(cid=None):
            return saved.get(cid, {})
        def mock_save(data, cid=None):
            saved[cid] = data

        monkeypatch.setattr("trade.license._get_license_data", mock_get)
        monkeypatch.setattr("trade.license._save_license_data", mock_save)

        from trade.license import check_license
        ok, msg = check_license(company_id=1)
        assert ok
        assert "first_launch_at" in saved.get(1, {})

    def test_trial_still_valid(self, monkeypatch):
        """试用 10 天应仍然有效"""
        ten_days_ago = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=10)).isoformat()
        monkeypatch.setattr("trade.license._get_license_data",
                           lambda cid=None: {"first_launch_at": ten_days_ago})

        from trade.license import check_license
        ok, msg = check_license(company_id=1)
        assert ok

    def test_trial_expired(self, monkeypatch):
        """试用过期"""
        forty_days_ago = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=40)).isoformat()
        monkeypatch.setattr("trade.license._get_license_data",
                           lambda cid=None: {"first_launch_at": forty_days_ago})

        from trade.license import check_license
        ok, msg = check_license(company_id=1)
        assert not ok
        assert "到期" in msg

    def test_activated_valid(self, monkeypatch):
        """已激活且在有效期内 — mock _verify_license 跳过验签"""
        future = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=200)).isoformat()
        monkeypatch.setattr("trade.license._get_license_data",
                           lambda cid=None: {
                               "first_launch_at": "2026-01-01T00:00:00+00:00",
                               "activated": True,
                               "expires_at": future,
                           })
        # 签名校验由 TestLicenseSignature 专门测试，此处 mock 跳过
        monkeypatch.setattr("trade.license._verify_license", lambda data: True)

        from trade.license import check_license
        ok, msg = check_license(company_id=1)
        assert ok

    def test_activated_expired(self, monkeypatch):
        """已激活但过了有效期 — mock _verify_license 跳过验签"""
        monkeypatch.setattr("trade.license._get_license_data",
                           lambda cid=None: {
                               "first_launch_at": "2026-01-01T00:00:00+00:00",
                               "activated": True,
                               "expires_at": "2026-02-01T00:00:00+00:00",
                           })
        # 签名校验由 TestLicenseSignature 专门测试，此处 mock 跳过
        monkeypatch.setattr("trade.license._verify_license", lambda data: True)

        from trade.license import check_license
        ok, msg = check_license(company_id=1)
        assert not ok
        assert "到期" in msg


class TestDaysRemaining:
    """剩余天数计算"""

    def test_trial_days_remaining(self, monkeypatch):
        ten_days_ago = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=10)).isoformat()
        monkeypatch.setattr("trade.license._get_license_data",
                           lambda cid=None: {"first_launch_at": ten_days_ago})

        from trade.license import days_remaining
        remaining = days_remaining(company_id=1)
        assert 19 <= remaining <= 20

    def test_expired_returns_zero(self, monkeypatch):
        forty_days_ago = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=40)).isoformat()
        monkeypatch.setattr("trade.license._get_license_data",
                           lambda cid=None: {"first_launch_at": forty_days_ago})

        from trade.license import days_remaining
        assert days_remaining(company_id=1) == 0

    def test_active_returns_remaining(self, monkeypatch):
        future = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=100)).isoformat()
        monkeypatch.setattr("trade.license._get_license_data",
                           lambda cid=None: {
                               "first_launch_at": "2026-01-01T00:00:00+00:00",
                               "activated": True,
                               "expires_at": future,
                           })

        from trade.license import days_remaining
        remaining = days_remaining(company_id=1)
        assert 95 <= remaining <= 100

    def test_no_data_returns_trial_max(self, monkeypatch):
        monkeypatch.setattr("trade.license._get_license_data", lambda cid=None: {})
        from trade.license import days_remaining
        assert days_remaining(company_id=1) == 30


class TestLicenseStatus:
    """status 函数返回前端状态"""

    def test_trial_status(self, monkeypatch):
        monkeypatch.setattr("trade.license._get_license_data", lambda cid=None: {})
        from trade.license import status
        s = status(company_id=1)
        assert s["status"] == "trial"
        assert s["activated"] is False
        # 未激活状态下始终返回申请码（方便用户在试用期内提前申请激活）
        assert s["request_code"].startswith("TRADE-REQ-")

    def test_expired_shows_request_code(self, monkeypatch):
        forty_days_ago = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=40)).isoformat()
        monkeypatch.setattr("trade.license._get_license_data",
                           lambda cid=None: {"first_launch_at": forty_days_ago})

        from trade.license import status
        s = status(company_id=1)
        assert s["status"] == "expired"
        assert s["request_code"].startswith("TRADE-REQ-")

    def test_active_status(self, monkeypatch):
        # 激活状态需要有效签名（v0.6.9+ status() 会调用 _verify_license 验签）
        _setup_temp_ed25519_key(monkeypatch)
        from trade.license import _sign_license, status
        future = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=365)).isoformat()
        sig = _sign_license(future)
        monkeypatch.setattr("trade.license._get_license_data",
                           lambda cid=None: {
                               "first_launch_at": "2026-01-01T00:00:00+00:00",
                               "activated": True,
                               "expires_at": future,
                               "signature": sig,
                           })

        s = status(company_id=1)
        assert s["status"] == "active"
        assert s["activated"] is True


class TestRateLimit:
    """激活限流"""

    def test_allows_up_to_max(self):
        from trade.license import _MAX_ACTIVATE_ATTEMPTS, _check_activate_rate_limit
        for _ in range(_MAX_ACTIVATE_ATTEMPTS):
            assert _check_activate_rate_limit() is True

    def test_blocks_after_max(self):
        # 消耗掉所有配额（测试隔离：rate limit 计数器已被上一个测试填充）
        # 只测超过上限的行为
        import time

        from trade.license import _MAX_ACTIVATE_ATTEMPTS, _check_activate_rate_limit
        time.sleep(61)  # 等 60s 窗口过期
        for _ in range(_MAX_ACTIVATE_ATTEMPTS):
            _check_activate_rate_limit()
        assert _check_activate_rate_limit() is False


class TestActivate:
    """激活执行流程"""

    def test_activate_with_empty_code(self):
        from trade.license import activate
        ok, msg = activate("")
        assert not ok

    def test_activate_with_short_code(self):
        from trade.license import activate
        ok, msg = activate("X")
        assert not ok

    def test_activate_cross_machine_rejected(self, monkeypatch):
        """用不属于本机的哈希生成的激活码应被拒绝"""
        _setup_temp_ed25519_key(monkeypatch)
        from trade.license import _encode_activation_code, activate
        code = _encode_activation_code("TRADE-REQ-DEAD-BEEF", "2027-12-31")
        ok, msg = activate(code)
        assert not ok
        # DEADBEEF 哈希不在本地机器码中，会被拒绝（签名无效或机器码不匹配）
        assert not ok


class TestLicenseSignature:
    """运行时签名验签 — 防篡改核心机制"""

    def test_verify_with_valid_signature(self, monkeypatch):
        """有效签名应通过验签"""
        _setup_temp_ed25519_key(monkeypatch)
        from trade.license import _sign_license, _verify_license
        expires = "2027-12-31T00:00:00+00:00"
        sig = _sign_license(expires)
        assert sig
        assert _verify_license({"signature": sig, "expires_at": expires})

    def test_verify_rejects_tampered_expires(self, monkeypatch):
        """篡改 expires_at 后验签失败"""
        _setup_temp_ed25519_key(monkeypatch)
        from trade.license import _sign_license, _verify_license
        sig = _sign_license("2027-12-31T00:00:00+00:00")
        # 篡改到期日
        assert not _verify_license({
            "signature": sig,
            "expires_at": "2099-12-31T00:00:00+00:00",
        })

    def test_verify_rejects_missing_signature(self):
        """无签名字段应视为无效"""
        from trade.license import _verify_license
        assert not _verify_license({
            "activated": True,
            "expires_at": "2027-12-31T00:00:00+00:00",
        })

    def test_verify_rejects_empty_expires(self, monkeypatch):
        """expires_at 为空时验签失败"""
        _setup_temp_ed25519_key(monkeypatch)
        from trade.license import _sign_license, _verify_license
        sig = _sign_license("2027-12-31T00:00:00+00:00")
        assert not _verify_license({"signature": sig, "expires_at": ""})

    def test_check_license_rejects_tampered_data(self, monkeypatch):
        """已激活但签名无效 → check_license 拒绝"""
        _setup_temp_ed25519_key(monkeypatch)
        from trade.license import _sign_license
        # 用另一个日期签名
        sig = _sign_license("2027-06-01T00:00:00+00:00")
        # 但 data 中放篡改后的日期
        monkeypatch.setattr("trade.license._get_license_data",
                           lambda cid=None: {
                               "first_launch_at": "2026-01-01T00:00:00+00:00",
                               "activated": True,
                               "expires_at": "2099-12-31T00:00:00+00:00",
                               "signature": sig,
                           })
        from trade.license import check_license
        ok, msg = check_license(company_id=1)
        assert not ok
        assert "异常" in msg or "重新激活" in msg

    def test_sign_without_private_key_fails(self, monkeypatch):
        """无私钥时 _sign_license 抛出异常"""
        monkeypatch.delenv("TRADE_LICENSE_PRIVATE_KEY", raising=False)
        with mock.patch.object(Path, "is_file", return_value=False):
            from trade.license import _sign_license
            with pytest.raises(ValueError, match="私钥"):
                _sign_license("2027-12-31T00:00:00+00:00")


class TestResolveHermesHome:
    """Hermes 目录路径解析"""

    def test_env_var_priority(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "custom"))
        from trade.license import _resolve_hermes_home
        assert _resolve_hermes_home() == tmp_path / "custom"

    def test_default_path(self, monkeypatch):
        """验证 HERMES_HOME 未设置时返回非空目录"""
        monkeypatch.delenv("HERMES_HOME", raising=False)
        from trade.license import _resolve_hermes_home
        home = _resolve_hermes_home()
        assert home.name  # 不为空
        assert str(home)  # 不为空字符串


class TestActivationCodeErrorChain:
    """激活码解码失败时的异常链必须保留原始原因。

    _decode_activation_code 在签名验证失败时把 InvalidSignature 换成裸 ValueError，
    一度丢掉了 __cause__ —— 排查「为什么激活码无效」时线索断裂（B904）。
    """

    @_crypto_needed
    def test_bad_signature_preserves_cause(self):
        """签名不匹配时 ValueError 必须带 InvalidSignature 作为 __cause__。"""
        import base64

        from cryptography.exceptions import InvalidSignature

        from trade.license import _decode_activation_code

        # 构造 88 字节新格式：date(8) + hash(16) + 全零签名(64) → 签名一定验证失败
        raw = b"20261231" + b"a" * 16 + b"\x00" * 64
        code = "TRADE-" + base64.urlsafe_b64encode(raw).decode().rstrip("=")

        with pytest.raises(ValueError) as exc_info:
            _decode_activation_code(code)

        assert isinstance(exc_info.value.__cause__, InvalidSignature), (
            "签名验证失败应保留原始 InvalidSignature 异常链，否则排查激活失败时无法定位"
        )
