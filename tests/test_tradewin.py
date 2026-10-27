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
        # 端口信息在独立 .port 文件；其内容损坏同样视为无端口
        tradewin._port_file(lock).write_text("garbage", encoding="utf-8")
        assert tradewin._read_lock_port(lock) is None

    def test_write_failure_is_visible(self, tmp_path, capsys):
        """写端口失败不许静默吞（否则第二实例读不到端口）。"""
        lock = tmp_path / "tradewin.lock"
        assert tradewin._acquire_single_instance(lock) is True
        # 让目标路径变成目录，write_text 必抛 OSError
        tradewin._port_file(lock).mkdir()

        tradewin._write_lock_port(lock, 9123)

        err = capsys.readouterr().err
        assert "无法写入端口文件" in err

    def test_dead_pid_port_file_is_ignored(self, tmp_path, monkeypatch):
        """记录进程已退出的残留 .port 不能当成有效端口。"""
        lock = tmp_path / "tradewin.lock"
        tradewin._port_file(lock).write_text("12345 9123\n", encoding="utf-8")
        monkeypatch.setattr(tradewin, "_pid_alive", lambda pid: False)

        assert tradewin._read_lock_port(lock) is None

    def test_live_pid_port_file_is_read(self, tmp_path, monkeypatch):
        lock = tmp_path / "tradewin.lock"
        tradewin._port_file(lock).write_text("12345 9123\n", encoding="utf-8")
        monkeypatch.setattr(tradewin, "_pid_alive", lambda pid: True)

        assert tradewin._read_lock_port(lock) == 9123


class TestSecondInstanceOpensOrReports:
    def test_missing_port_reports_error_instead_of_9119(self, tmp_path, monkeypatch, capsys):
        """读不到端口时必须报错退出，不许静默打开 9119。"""
        opened = []
        monkeypatch.setattr(tradewin.webbrowser, "open", lambda url: opened.append(url))
        lock = tmp_path / "tradewin.lock"

        code = tradewin._open_or_report_existing(lock, "127.0.0.1")

        assert code == 1
        assert opened == [], "读不到端口时不得打开任何页面"
        err = capsys.readouterr().err
        assert "读不到它的端口信息" in err
        assert "9119" not in err

    def test_dead_pid_port_reports_error(self, tmp_path, monkeypatch, capsys):
        lock = tmp_path / "tradewin.lock"
        tradewin._port_file(lock).write_text("12345 9123\n", encoding="utf-8")
        monkeypatch.setattr(tradewin, "_pid_alive", lambda pid: False)
        opened = []
        monkeypatch.setattr(tradewin.webbrowser, "open", lambda url: opened.append(url))

        assert tradewin._open_or_report_existing(lock, "127.0.0.1") == 1
        assert opened == []
        assert "读不到它的端口信息" in capsys.readouterr().err

    def test_valid_port_opens_recorded_port(self, tmp_path, monkeypatch):
        lock = tmp_path / "tradewin.lock"
        tradewin._port_file(lock).write_text("12345 9123\n", encoding="utf-8")
        monkeypatch.setattr(tradewin, "_pid_alive", lambda pid: True)
        opened = []
        monkeypatch.setattr(tradewin.webbrowser, "open", lambda url: opened.append(url))

        assert tradewin._open_or_report_existing(lock, "127.0.0.1") == 0
        assert opened == ["http://127.0.0.1:9123/trade"]


class TestExitCode:
    def test_main_return_value_propagates(self):
        """main() 返回 1（读不到端口）时，进程退出码必须是 1 而不是 0。"""
        src = (
            Path(__file__).resolve().parent.parent / "tradewin.py"
        ).read_text(encoding="utf-8")
        assert "sys.exit(main())" in src


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
