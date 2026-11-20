"""Host 头校验（2026-11-20 审计 P1-1）。

端口固定 + /trade 页面免鉴权即可拿到 session token，而 /trade 只看客户端
IP 不看 Host 头 —— 恶意网页用 DNS rebinding 就能读走 token。
本机 Host 之外一律拒绝；TRADE_ALLOW_REMOTE_UI=1 时（用户显式接受风险）放行。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade import app as app_mod


def _build(monkeypatch, allow_remote=None):
    """最小 app + Host 守卫，不依赖真实业务路由。"""
    if allow_remote is None:
        monkeypatch.delenv("TRADE_ALLOW_REMOTE_UI", raising=False)
    else:
        monkeypatch.setenv("TRADE_ALLOW_REMOTE_UI", allow_remote)
    application = FastAPI()

    @application.get("/api/trade/probe")
    def probe():
        return {"ok": True}

    app_mod._install_host_guard(application)
    return TestClient(application)


class TestHostGuard:
    def test_localhost_host_allowed(self, monkeypatch):
        client = _build(monkeypatch)
        r = client.get("/api/trade/probe", headers={"Host": "127.0.0.1:9119"})
        assert r.status_code == 200

    def test_testserver_host_allowed(self, monkeypatch):
        """Starlette TestClient 默认 Host 是 testserver —— 必须放行，
        否则所有用 TestClient 打本 app 的既有测试都会红。"""
        client = _build(monkeypatch)
        r = client.get("/api/trade/probe")
        assert r.status_code == 200

    def test_foreign_host_rejected_on_api(self, monkeypatch):
        client = _build(monkeypatch)
        r = client.get("/api/trade/probe", headers={"Host": "attacker.example"})
        assert r.status_code == 400
        assert "ok" not in r.text

    def test_foreign_host_on_trade_is_403_without_token(self, monkeypatch):
        """伪造 Host 访问 /trade 必须拿不到 token。"""
        client = _build(monkeypatch)
        r = client.get("/trade", headers={"Host": "attacker.example:9119"})
        assert r.status_code == 403
        assert app_mod._SESSION_TOKEN not in r.text

    def test_remote_ui_mode_allows_any_host(self, monkeypatch):
        client = _build(monkeypatch, allow_remote="1")
        r = client.get("/api/trade/probe", headers={"Host": "attacker.example"})
        assert r.status_code == 200

    def test_allowed_hosts_helper(self):
        assert app_mod._host_is_allowed("127.0.0.1:9119")
        assert app_mod._host_is_allowed("localhost:9119")
        assert app_mod._host_is_allowed("[::1]:9119")
        assert app_mod._host_is_allowed("127.0.0.1")
        assert app_mod._host_is_allowed("testserver")
        assert not app_mod._host_is_allowed("attacker.example")
        assert not app_mod._host_is_allowed("attacker.example:9119")
        assert not app_mod._host_is_allowed("")
