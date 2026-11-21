"""代理环境下的 SSRF 校验（2026-11-21 审计 P0-3）。

系统代理模式（Clash 等 `HTTPS_PROXY=http://127.0.0.1:7890`）下，所有请求的对端
都是回环地址；旧实现只看对端 IP，把代理本身当内网拦掉，导致背调各层静默失败。

修复后：对端若是**本机配置的代理**就放行，目标主机仍由 `_is_private_host()`
在发请求前单独校验 —— 不能因此打开访问内网的缺口。

全部离线：测试里起一个假的 HTTP 代理，不访问外网。
"""

from __future__ import annotations

import socket
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade.osint import constants as c  # noqa: E402

_PROXY_ENV_KEYS = (
    "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy",
    "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy",
)


@pytest.fixture
def clean_proxy_env(monkeypatch):
    """清空所有代理相关环境变量，避免被宿主机配置干扰。"""
    for key in _PROXY_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def _use_proxy(monkeypatch, url: str) -> None:
    """设置代理并**重建 opener 快照**。

    ProxyHandler 在 build_opener 时快照代理配置；只改环境变量而不重建，
    opener 仍走旧代理，而校验用的是新快照 —— 两边会错配（实测踩过）。
    """
    monkeypatch.setenv("HTTP_PROXY", url)
    monkeypatch.setenv("http_proxy", url)
    opener, proxies = c._build_opener()
    monkeypatch.setattr(c, "_SAFE_OPENER", opener)
    monkeypatch.setattr(c, "_CONFIGURED_PROXIES", proxies)


class _FakeProxy:
    """最小 HTTP 代理：接受绝对地址请求，直接回 200（不真的转发）。"""

    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self.requests: list[bytes] = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                try:
                    data = conn.recv(65536)
                except OSError:
                    continue
                self.requests.append(data.split(b"\r\n", 1)[0])
                body = b"proxied-ok"
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
                    b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                    b"Connection: close\r\n\r\n" + body
                )

    def close(self) -> None:
        self.sock.close()


@pytest.fixture
def fake_proxy():
    proxy = _FakeProxy()
    yield proxy
    proxy.close()


class TestProxyDetection:
    def test_ip_literal_proxy_matches(self, clean_proxy_env):
        clean_proxy_env.setattr(c, "_CONFIGURED_PROXIES", {"http": "http://127.0.0.1:7890"})
        assert c._is_configured_proxy("127.0.0.1", 7890) is True

    def test_port_must_match(self, clean_proxy_env):
        """只比对 IP 是不够的：别的本机服务不能因为同 IP 被放行。"""
        clean_proxy_env.setattr(c, "_CONFIGURED_PROXIES", {"http": "http://127.0.0.1:7890"})
        assert c._is_configured_proxy("127.0.0.1", 8080) is False

    def test_other_private_ip_not_a_proxy(self, clean_proxy_env):
        clean_proxy_env.setattr(c, "_CONFIGURED_PROXIES", {"http": "http://127.0.0.1:7890"})
        assert c._is_configured_proxy("10.0.0.5", 7890) is False

    def test_ipv4_mapped_peer(self, clean_proxy_env):
        """macOS 上 getpeername 可能返回 ::ffff:127.0.0.1。"""
        clean_proxy_env.setattr(c, "_CONFIGURED_PROXIES", {"http": "http://127.0.0.1:7890"})
        assert c._is_configured_proxy("::ffff:127.0.0.1", 7890) is True

    def test_domain_form_proxy_resolves(self, clean_proxy_env, monkeypatch):
        clean_proxy_env.setattr(c, "_CONFIGURED_PROXIES", {"http": "http://myproxy.local:3128"})
        monkeypatch.setattr(c, "_resolve_addresses", lambda host: {"127.0.0.1"})
        assert c._is_configured_proxy("127.0.0.1", 3128) is True

    def test_no_proxy_configured(self, clean_proxy_env):
        assert c._is_configured_proxy("127.0.0.1", 7890) is False


class TestPeerVerification:
    class _Sock:
        def __init__(self, peer):
            self._peer = peer
            self.closed = False

        def getpeername(self):
            return self._peer

        def close(self):
            self.closed = True

    def _conn_with(self, peer):
        class _Conn(c._PeerVerifiedMixin):
            pass

        conn = _Conn()
        conn.sock = self._Sock(peer)
        return conn

    def test_private_peer_closed_when_not_proxy(self, clean_proxy_env):
        conn = self._conn_with(("10.0.0.5", 80))
        with pytest.raises(OSError):
            conn._verify_peer()
        assert conn.sock is None

    def test_proxy_peer_allowed(self, clean_proxy_env):
        clean_proxy_env.setattr(c, "_CONFIGURED_PROXIES", {"http": "http://127.0.0.1:7890"})
        conn = self._conn_with(("127.0.0.1", 7890))
        # 不抛异常，socket 保持连接
        conn._verify_peer()
        assert conn.sock is not None

    def test_same_ip_wrong_port_is_closed(self, clean_proxy_env):
        clean_proxy_env.setattr(c, "_CONFIGURED_PROXIES", {"http": "http://127.0.0.1:7890"})
        conn = self._conn_with(("127.0.0.1", 9999))
        with pytest.raises(OSError):
            conn._verify_peer()


class TestHttpGetThroughProxy:
    def test_request_goes_through_local_proxy(self, clean_proxy_env, fake_proxy):
        """端到端：设置系统代理后，http_get 能拿到响应而不是被拦死。"""
        _use_proxy(clean_proxy_env, f"http://127.0.0.1:{fake_proxy.port}")

        body = c.http_get("http://example.invalid/probe", timeout=5)

        assert body == "proxied-ok"
        # 请求确实是以绝对地址发给代理的
        assert fake_proxy.requests and b"example.invalid" in fake_proxy.requests[0]

    def test_private_target_still_blocked_with_proxy(self, clean_proxy_env, fake_proxy):
        """放行代理不能打开访问内网的口子：目标本身仍被拦。"""
        _use_proxy(clean_proxy_env, f"http://127.0.0.1:{fake_proxy.port}")

        assert c.http_get(f"http://127.0.0.1:{fake_proxy.port}/x", timeout=5) is None
        assert c.http_get("http://169.254.169.254/latest/meta-data", timeout=5) is None
        # 被拦的请求根本没发出去
        assert fake_proxy.requests == []

    def test_without_proxy_private_peer_still_blocked(self, clean_proxy_env):
        """没有配置代理时，直连内网的口子仍然关着。"""
        assert c.http_get("http://127.0.0.1:9/", timeout=2) is None
