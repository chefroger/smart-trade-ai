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
