"""TradeWin 单实例与端口顺延（审计 P2-21）。"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tradewin


class TestSingleInstance:
    def test_second_launch_is_refused(self, tmp_path):
        lock = tmp_path / "tradewin.lock"

        assert tradewin._acquire_single_instance(lock) is True
        assert tradewin._acquire_single_instance(lock) is False

    def test_port_is_recorded_and_read_back(self, tmp_path):
        lock = tmp_path / "tradewin.lock"
        assert tradewin._acquire_single_instance(lock)

        tradewin._write_lock_port(lock, 9123)

        assert tradewin._read_lock_port(lock) == 9123

    def test_missing_or_corrupt_lock_returns_none(self, tmp_path):
        lock = tmp_path / "x.lock"
        assert tradewin._read_lock_port(lock) is None
        lock.write_text("garbage", encoding="utf-8")
        assert tradewin._read_lock_port(lock) is None


class TestPortFallback:
    def test_busy_preferred_port_is_skipped(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen(1)
            used = busy.getsockname()[1]

            picked = tradewin._pick_free_port("127.0.0.1", preferred=used, tries=5)

            assert picked is not None
            assert picked != used

    def test_all_ports_busy_returns_none(self):
        sockets = []
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", 0))
                base = probe.getsockname()[1]
            for port in range(base, base + 2):
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.bind(("127.0.0.1", port))
                s.listen(1)
                sockets.append(s)

            assert tradewin._pick_free_port("127.0.0.1", preferred=base, tries=2) is None
        finally:
            for s in sockets:
                s.close()
