"""Hermes provider 兼容层测试。"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def compat_module(monkeypatch):
    """加载兼容层并隔离 Hermes 模块。"""
    for name in list(sys.modules):
        if name == "trade.hermes_compat":
            del sys.modules[name]
    import trade.hermes_compat as compat
    return compat


def test_provider_catalog_uses_public_catalog_and_model_api(monkeypatch, compat_module):
    """新 Hermes 公开目录和模型 API 应成为主路径。"""
    catalog = [SimpleNamespace(slug="openai", label="OpenAI", auth_type="api_key", tab="keys")]
    auth = {"logged_in": True, "auth_type": "api_key"}
    monkeypatch.setattr(compat_module, "_public_provider_catalog", lambda: catalog)
    monkeypatch.setattr(compat_module, "_public_provider_models", lambda provider: ["gpt-5"])
    monkeypatch.setattr(compat_module, "_public_auth_status", lambda provider: auth)

    result = compat_module.list_provider_records()

    assert result == [{
        "id": "openai",
        "name": "OpenAI",
        "auth_type": "api_key",
        "auth_status": auth,
        "has_key": True,
        "models": ["gpt-5"],
    }]


def test_provider_catalog_falls_back_when_public_apis_missing(monkeypatch, compat_module):
    """旧版 Hermes 没有公开接口时应继续返回旧注册表数据。"""
    class Provider:
        name = "Legacy"
        display_name = "Legacy"
        auth_type = "api_key"
        api_key_env_vars = ["LEGACY_KEY"]
        base_url_env_var = ""

    monkeypatch.setattr(compat_module, "_public_provider_catalog", lambda: None)
    monkeypatch.setattr(compat_module, "_public_provider_models", lambda provider: None)
    monkeypatch.setattr(compat_module, "_public_auth_status", lambda provider: None)
    monkeypatch.setattr(compat_module, "_legacy_registry", lambda: {"legacy": Provider()})
    monkeypatch.setattr(compat_module, "_legacy_models", lambda provider: ["legacy-model"])
    monkeypatch.setenv("LEGACY_KEY", "configured")

    result = compat_module.list_provider_records()

    assert result[0]["id"] == "legacy"
    assert result[0]["has_key"] is True
    assert result[0]["models"] == ["legacy-model"]


def test_auth_status_does_not_require_api_key_for_oauth(monkeypatch, compat_module):
    """OAuth 已登录状态不能因没有 API key 环境变量而被误判。"""
    monkeypatch.setattr(compat_module, "_public_provider_catalog", lambda: [
        SimpleNamespace(slug="nous", label="Nous", auth_type="oauth_device_code", tab="accounts")
    ])
    monkeypatch.setattr(compat_module, "_public_provider_models", lambda provider: [])
    monkeypatch.setattr(compat_module, "_public_auth_status", lambda provider: {
        "logged_in": True, "auth_type": "oauth_device_code"
    })

    result = compat_module.list_provider_records()

    assert result[0]["has_key"] is True
    assert result[0]["auth_type"] == "oauth_device_code"


# ── Hermes 版本识别 ─────────────────────────────────────────────────────────
# 上游 main 把 hermes_cli.__version__ 改为「惰性读安装印章，读不到返回 "0.0.0"」
# （见 hermes_cli/__init__.py 的 __getattr__），而 Trade 用它做启动门禁。
# 占位值必须视为「未知」：否则会以 0.0.0 < 0.13.0 拒绝启动，且提示信息是误导的。


def test_version_prefers_new_version_info_api(monkeypatch, compat_module):
    """新版 get_version_info() 优先于旧的 __version__。"""
    monkeypatch.setattr(compat_module, "_public_version_info", lambda: "0.21.5")
    monkeypatch.setattr(compat_module, "_legacy_version", lambda: "0.21.4")

    assert compat_module.hermes_version() == "0.21.5"


def test_version_falls_back_to_legacy_literal(monkeypatch, compat_module):
    """旧版 Hermes 没有 version_info 时回退到 __version__ 字面量。"""
    monkeypatch.setattr(compat_module, "_public_version_info", lambda: None)
    monkeypatch.setattr(compat_module, "_legacy_version", lambda: "0.21.4")

    assert compat_module.hermes_version() == "0.21.4"


def test_version_falls_back_to_checkout_pyproject(monkeypatch, compat_module):
    """两个接口都取不到时，读 checkout 自带的 pyproject.toml。"""
    monkeypatch.setattr(compat_module, "_public_version_info", lambda: None)
    monkeypatch.setattr(compat_module, "_legacy_version", lambda: None)
    monkeypatch.setattr(compat_module, "_checkout_version", lambda: "0.20.0")

    assert compat_module.hermes_version() == "0.20.0"


@pytest.mark.parametrize("placeholder", ["0.0.0", "unknown", "", "none", "  "])
def test_placeholder_versions_are_treated_as_unknown(monkeypatch, compat_module, placeholder):
    """安装印章缺失时上游返回 0.0.0 —— 那是占位值，不是真实版本号。"""
    monkeypatch.setattr(compat_module, "_public_version_info", lambda: placeholder)
    monkeypatch.setattr(compat_module, "_legacy_version", lambda: placeholder)
    monkeypatch.setattr(compat_module, "_checkout_version", lambda: None)

    assert compat_module.hermes_version() is None


@pytest.mark.parametrize("bad", ["git.abc1234", "not-a-version", "v0.21.5-490-gabc1234"])
def test_unparseable_versions_are_treated_as_unknown(monkeypatch, compat_module, bad):
    """无法做 PEP 440 比较的字符串也按未知处理，避免启动时抛 InvalidVersion。"""
    monkeypatch.setattr(compat_module, "_public_version_info", lambda: bad)
    monkeypatch.setattr(compat_module, "_legacy_version", lambda: bad)
    monkeypatch.setattr(compat_module, "_checkout_version", lambda: None)

    assert compat_module.hermes_version() is None


class TestHermesVersionGate:
    """启动门禁：版本识别不到时警告并继续，而不是把用户锁死。"""

    def test_unknown_version_warns_and_continues(self, monkeypatch, capsys):
        """拿不到版本（如 main 上无安装印章）→ 打印警告但继续启动。"""
        import trade.hermes_compat as compat
        from trade import bootstrap

        monkeypatch.setattr(compat, "hermes_version", lambda: None)

        assert bootstrap.check_hermes_version() is True
        assert "无法确定" in capsys.readouterr().out

    @pytest.mark.parametrize("version", ["0.22.1", "0.12.0"])
    def test_out_of_range_version_is_rejected(self, monkeypatch, version):
        """真实版本越界时仍然拦截（不能因为放宽未知就放过越界）。"""
        import trade.hermes_compat as compat
        from trade import bootstrap

        monkeypatch.setattr(compat, "hermes_version", lambda: version)

        assert bootstrap.check_hermes_version() is False

    @pytest.mark.parametrize("version", ["0.13.0", "0.21.5"])
    def test_in_range_version_is_accepted(self, monkeypatch, version):
        """窗口内的真实版本正常通过。"""
        import trade.hermes_compat as compat
        from trade import bootstrap

        monkeypatch.setattr(compat, "hermes_version", lambda: version)

        assert bootstrap.check_hermes_version() is True
