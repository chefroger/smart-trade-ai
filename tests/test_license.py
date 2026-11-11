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
                # 进程内硬件缓存可能已被前面的用例填充，先清空
                with mock.patch("trade.license._HARDWARE_ID_CACHE", None):
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

    def test_save_failure_still_allows_chat(self, monkeypatch):
        """首次试用写盘失败不得返回 402——进程内记住起点并放行聊天。"""
        import trade.license as license_mod

        license_mod._PROCESS_FIRST_LAUNCH = None
        monkeypatch.setattr(license_mod, "_get_license_data", lambda cid=None: {})

        def boom(data, cid=None):
            raise OSError("disk full")

        monkeypatch.setattr(license_mod, "_save_license_data", boom)

        ok, msg = license_mod.check_license(company_id=1)
        assert ok is True
        assert msg == ""
        assert license_mod._PROCESS_FIRST_LAUNCH  # 进程内已记住试用起点

        # 第二次检查仍应放行，且不得重置试用（同一起点）
        stamp = license_mod._PROCESS_FIRST_LAUNCH
        ok2, _ = license_mod.check_license(company_id=1)
        assert ok2 is True
        assert license_mod._PROCESS_FIRST_LAUNCH == stamp
        license_mod._PROCESS_FIRST_LAUNCH = None

    def test_corrupt_first_launch_treated_as_trial(self, monkeypatch):
        """损坏的 first_launch_at 不得判到期——可用性优先按试用放行。"""
        import trade.license as license_mod

        license_mod._PROCESS_FIRST_LAUNCH = None
        saved = {}

        monkeypatch.setattr(
            license_mod,
            "_get_license_data",
            lambda cid=None: saved.get(cid, {"first_launch_at": "not-a-date"}),
        )

        def mock_save(data, cid=None):
            saved[cid] = data

        monkeypatch.setattr(license_mod, "_save_license_data", mock_save)

        ok, msg = license_mod.check_license(company_id=1)
        assert ok is True
        assert msg == ""
        # 应尝试重写为合法时间戳
        assert "first_launch_at" in saved.get(1, {})
        datetime.datetime.fromisoformat(saved[1]["first_launch_at"])
        license_mod._PROCESS_FIRST_LAUNCH = None


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


class TestMachineBinding:
    """付费许可绑定本机硬件（工单 C1）。"""

    def test_machine_id_prefers_hardware_and_rewrites_cache(self, monkeypatch):
        """缓存与硬件不一致时以硬件为准，并把缓存回写成硬件值。

        没有付费签名时允许回写；**有签名时不能回写**（绑定值是「签名签在哪台
        机器上」的凭据，覆盖了就没法区分拷机与篡改）—— 见下一个用例。
        """
        from trade import license as license_mod

        store = {"_machine_id": "test:old"}
        monkeypatch.setattr(license_mod, "_get_license_data", lambda cid=None: dict(store))
        monkeypatch.setattr(license_mod, "_save_license_data",
                            lambda data, cid=None: store.update(data))
        monkeypatch.setattr(license_mod, "_read_hardware_machine_id", lambda: "test:new")

        assert license_mod._machine_id() == "test:new"
        assert store["_machine_id"] == "test:new"

    def test_machine_id_does_not_overwrite_binding_with_signature(self, monkeypatch):
        """有付费签名时，绑定值不能被本机机器码覆盖。

        覆盖之后就再也分不清「文件从别的机器拷来 / 系统重装过」（应回落试用
        并给申请码）和「文件被篡改」（应报 tampered），付费用户会被误判
        （2026-11-11 审计）。
        """
        from trade import license as license_mod

        store = {"_machine_id": "test:old", "activated": True, "signature": "sig"}
        monkeypatch.setattr(license_mod, "_get_license_data", lambda cid=None: dict(store))
        monkeypatch.setattr(license_mod, "_save_license_data",
                            lambda data, cid=None: store.update(data))
        monkeypatch.setattr(license_mod, "_read_hardware_machine_id", lambda: "test:new")

        assert license_mod._machine_id() == "test:new"   # 本机当前机器码
        assert store["_machine_id"] == "test:old"        # 绑定值原样保留

    def test_machine_id_migrates_to_hardware_without_signature(self, monkeypatch):
        """没有付费签名时，hostname 兜底缓存可以迁移到硬件（新激活绑硬件）。"""
        from trade import license as license_mod

        store = {"_machine_id": "host:myhost"}
        monkeypatch.setattr(license_mod, "_get_license_data", lambda cid=None: dict(store))
        monkeypatch.setattr(license_mod, "_save_license_data",
                            lambda data, cid=None: store.update(data))
        monkeypatch.setattr(license_mod, "_read_hardware_machine_id", lambda: "test:hw")

        assert license_mod._machine_id() == "test:hw"
        assert store["_machine_id"] == "test:hw"

    def test_machine_id_falls_back_to_cache_when_hardware_fails(self, monkeypatch):
        """硬件读取失败不抛错、不拒绝启动，退回缓存。"""
        from trade import license as license_mod

        monkeypatch.setattr(license_mod, "_get_license_data",
                            lambda cid=None: {"_machine_id": "test:old"})
        monkeypatch.setattr(license_mod, "_read_hardware_machine_id", lambda: None)
        assert license_mod._machine_id() == "test:old"

    @_crypto_needed
    def test_copied_license_is_unactivated_not_tampered(self, monkeypatch):
        """整份 license.json 拷到另一台机器：按未激活回落试用，不判篡改。"""
        from trade import license as license_mod

        _setup_temp_ed25519_key(monkeypatch)
        store: dict = {}
        monkeypatch.setattr(license_mod, "_get_license_data", lambda cid=None: dict(store))
        monkeypatch.setattr(license_mod, "_save_license_data",
                            lambda data, cid=None: store.update(data))
        monkeypatch.setattr(license_mod, "_PROCESS_FIRST_LAUNCH", None)
        monkeypatch.setattr(license_mod, "_read_hardware_machine_id", lambda: "test:old")

        future = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=365)).isoformat()
        sig = license_mod._sign_license(future)
        store.update({
            "activated": True,
            "expires_at": future,
            "signature": sig,
            # _sign_license 已把 test:old 写入缓存
        })
        assert license_mod.license_state(1) == ("active", "")

        # 换到另一台机器：硬件码变了
        monkeypatch.setattr(license_mod, "_read_hardware_machine_id", lambda: "test:new")
        state, _msg = license_mod.license_state(1)
        assert state == "trial"  # 不是 tampered

        s = license_mod.status(1)
        assert s["machine_mismatch"] is True
        assert s["activated"] is False
        assert s["status"] != "tampered"
        assert s["request_code"].startswith("TRADE-REQ-")
        assert "还没激活" in s.get("message", "")

    @_crypto_needed
    def test_copied_license_stays_trial_not_tampered_on_repeated_status(self, monkeypatch):
        """拷机后反复查状态，必须一直是「未激活」，不能恶化成 tampered。

        绑定值被本机机器码覆盖过一次之后，原签名再也验不过，状态会从 trial
        变成「许可证数据异常」——付费用户看到的是被指责篡改（2026-11-11 审计）。
        """
        from trade import license as license_mod

        _setup_temp_ed25519_key(monkeypatch)
        store: dict = {}
        monkeypatch.setattr(license_mod, "_get_license_data", lambda cid=None: dict(store))
        monkeypatch.setattr(license_mod, "_save_license_data",
                            lambda data, cid=None: store.update(data))
        monkeypatch.setattr(license_mod, "_PROCESS_FIRST_LAUNCH", None)
        monkeypatch.setattr(license_mod, "_read_hardware_machine_id", lambda: "test:old")

        future = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=365)).isoformat()
        sig = license_mod._sign_license(future)
        store.update({"activated": True, "expires_at": future, "signature": sig})

        # 换到另一台机器：硬件码变了
        monkeypatch.setattr(license_mod, "_read_hardware_machine_id", lambda: "test:new")

        for _ in range(3):
            s = license_mod.status(1)
            assert s["status"] == "trial"          # 不是 tampered
            assert s["machine_mismatch"] is True
            assert s["activated"] is False
        # 绑定值没被本机机器码覆盖 —— 覆盖了就再也验不过原签名
        assert store["_machine_id"] == "test:old"

    @_crypto_needed
    def test_hostname_fallback_binding_stays_active_after_hardware_recovers(self, monkeypatch):
        """硬件恢复后，hostname 兜底绑定的付费用户仍然是 active（不是 tampered）。

        旧版在硬件读不到时会把 `host:<hostname>` 持久化进 license.json，付费
        签名就签在它上面。硬件恢复后若用机器码覆盖它，签名再也验不过 ——
        付费用户被误判成「许可证数据异常」（2026-11-11 审计）。
        """
        from trade import license as license_mod

        _setup_temp_ed25519_key(monkeypatch)
        store: dict = {}
        monkeypatch.setattr(license_mod, "_get_license_data", lambda cid=None: dict(store))
        monkeypatch.setattr(license_mod, "_save_license_data",
                            lambda data, cid=None: store.update(data))
        monkeypatch.setattr(license_mod, "_PROCESS_FIRST_LAUNCH", None)

        # 激活那一刻硬件读不到 → 机器码退回 hostname 兜底
        monkeypatch.setattr(license_mod, "_read_hardware_machine_id", lambda: None)
        monkeypatch.setattr("platform.node", lambda: "myhost")
        assert license_mod._machine_id() == "host:myhost"

        future = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=365)).isoformat()
        sig = license_mod._sign_license(future)
        store.update({"activated": True, "expires_at": future, "signature": sig})

        # 之后硬件恢复
        monkeypatch.setattr(license_mod, "_read_hardware_machine_id", lambda: "test:hw")
        monkeypatch.setattr(license_mod, "_HARDWARE_ID_CACHE", None)

        for _ in range(3):
            assert license_mod.license_state(1) == ("active", "")
            s = license_mod.status(1)
            assert s["status"] == "active"
            assert s["activated"] is True
            assert s["machine_mismatch"] is False
        # 绑定没被销毁：签名仍然验得过
        assert store["_machine_id"] == "host:myhost"


class TestLicenseWriteFailure:
    """写盘失败时的试用起点一致性（工单 C2）。"""

    def test_process_start_expired_blocks_check_and_state(self, monkeypatch):
        """同进程内起点已 31 天：check_license 与 license_state 必须都到期。"""
        from trade import license as license_mod

        old = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=31)).isoformat()
        monkeypatch.setattr(license_mod, "_PROCESS_FIRST_LAUNCH", old)
        monkeypatch.setattr(license_mod, "_get_license_data", lambda cid=None: {})

        def boom(_data, _cid=None):
            raise OSError("disk full")

        monkeypatch.setattr(license_mod, "_save_license_data", boom)

        ok, msg = license_mod.check_license(1)
        assert not ok
        assert "到期" in msg
        state, _ = license_mod.license_state(1)
        assert state == "expired"

    def test_write_error_is_exposed_in_status(self, monkeypatch):
        """写盘失败仍放行，但 status() 带上可定位的错误提示。"""
        from trade import license as license_mod

        monkeypatch.setattr(license_mod, "_PROCESS_FIRST_LAUNCH", None)
        monkeypatch.setattr(license_mod, "_LICENSE_WRITE_ERROR", "")
        monkeypatch.setattr(license_mod, "_get_license_data", lambda cid=None: {})

        def boom(_data, _cid=None):
            raise OSError("disk full")

        monkeypatch.setattr(license_mod, "_save_license_data", boom)

        ok, _msg = license_mod.check_license(1)
        assert ok  # 未到期时写盘失败不挡聊天
        s = license_mod.status(1)
        assert "写不进去" in s.get("license_file_error", "")
        assert "license.json" in s.get("license_file_error", "")

    def test_corrupt_timestamp_expired_agrees_between_check_and_state(self, monkeypatch):
        """时间戳损坏时，check_license 与 license_state 必须同一结论。

        之前两边分裂：check_license 看到「进程内起点已超期」就拦起草，
        license_state 却因为读不出磁盘上的时间戳而按试用处理 —— 用户看到
        「⏳ 试用」，一发消息就被拦（2026-11-11 审计）。
        """
        from trade import license as license_mod

        old = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=31)).isoformat()
        monkeypatch.setattr(license_mod, "_PROCESS_FIRST_LAUNCH", old)
        # 磁盘上的时间戳损坏（读出来不是 ISO 格式）
        monkeypatch.setattr(license_mod, "_get_license_data",
                            lambda cid=None: {"first_launch_at": "损坏的时间戳!!!"})
        monkeypatch.setattr(license_mod, "_save_license_data", lambda data, cid=None: None)

        ok, msg = license_mod.check_license(1)
        assert not ok
        assert "到期" in msg
        state, _ = license_mod.license_state(1)
        assert state == "expired"

    def test_corrupt_timestamp_within_trial_agrees_between_check_and_state(self, monkeypatch):
        """时间戳损坏但进程内起点未超期：两边都必须放行（可用性优先）。"""
        from trade import license as license_mod

        recent = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=5)).isoformat()
        monkeypatch.setattr(license_mod, "_PROCESS_FIRST_LAUNCH", recent)
        monkeypatch.setattr(license_mod, "_get_license_data",
                            lambda cid=None: {"first_launch_at": "损坏的时间戳!!!"})
        monkeypatch.setattr(license_mod, "_save_license_data", lambda data, cid=None: None)

        ok, _msg = license_mod.check_license(1)
        assert ok
        state, _ = license_mod.license_state(1)
        assert state == "trial"


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
