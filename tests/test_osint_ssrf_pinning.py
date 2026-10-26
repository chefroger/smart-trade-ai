"""SSRF：建连后校验对端 IP，堵住 DNS 重绑定（审计 P1-4）。

主机名检查与真正建连是两次独立解析；攻击者可让第二次解析返回内网地址。
这里在 TCP 建连后、发出 HTTP 请求前检查 `getpeername()`，命中内网/保留段
立即断开。
"""

from __future__ import annotations

import http.server
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade.osint import constants as c


class _FakeSock:
    def __init__(self, peer):
        self._peer = peer
        self.closed = False

    def getpeername(self):
        return (self._peer, 12345)

    def close(self):
        self.closed = True


class TestPeerVerification:
    @pytest.mark.parametrize("peer", [
        "127.0.0.1", "10.1.2.3", "192.168.1.1", "169.254.169.254",
        "100.100.100.200", "::1", "::ffff:127.0.0.1",
    ])
    def test_private_peer_is_rejected(self, peer):
        conn = c._PinnedHTTPConnection("example.com")
        sock = _FakeSock(peer)
        conn.sock = sock
        with pytest.raises(OSError, match="SSRF blocked"):
            conn._verify_peer()
        assert sock.closed
        assert conn.sock is None

    @pytest.mark.parametrize("peer", ["8.8.8.8", "1.1.1.1", "::ffff:8.8.8.8"])
    def test_public_peer_is_allowed(self, peer):
        conn = c._PinnedHTTPConnection("example.com")
        conn.sock = _FakeSock(peer)
        conn._verify_peer()  # 不抛
        assert conn.sock is not None

    def test_no_socket_is_noop(self):
        conn = c._PinnedHTTPConnection("example.com")
        conn.sock = None
        conn._verify_peer()


class TestOpenerUsesPinnedHandlers:
    def test_safe_opener_has_both_handlers(self):
        handlers = [type(h) for h in c._SAFE_OPENER.handlers]
        assert c._SafeHTTPHandler in handlers
        assert c._SafeHTTPSHandler in handlers

    def test_open_localhost_is_blocked_at_peer_check(self):
        """即使绕过主机名预检直接 open，对端检查也会在发请求前断开。"""
        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"secret")

            def log_message(self, *a):  # 静音
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with pytest.raises(Exception) as exc:
                c._SAFE_OPENER.open(f"http://127.0.0.1:{port}/", timeout=3)
            assert "SSRF" in str(exc.value) or "private address" in str(exc.value)
        finally:
            server.shutdown()
            server.server_close()
