"""`trade open` —— 桌面快捷方式双击后的行为。

规则：
  - 服务已在运行 → **不重复启动**，直接打开界面
  - 服务没运行 → 静默启动（带 --no-browser，避免服务自己也开一个标签页），
    等它就绪后再打开
  - 启动超时 → 如实报错 + 指出日志位置，**不假装成功**
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade import opener


class _Recorder:
    def __init__(self):
        self.spawned: list[list[str]] = []
        self.opened: list[str] = []

    def spawn(self, cmd):
        self.spawned.append(list(cmd))

    def open(self, url):
        self.opened.append(url)
        return True


class TestAlreadyRunning:
    def test_does_not_spawn_when_up(self):
        rec = _Recorder()

        msg = opener.open_trade(
            probe=lambda _u: True, spawn=rec.spawn, opener=rec.open, timeout=1.0
        )

        assert rec.spawned == [], "服务已在运行时不该再启动一个（会撞端口）"
        assert rec.opened == ["http://127.0.0.1:9119/trade"]
        assert "已在运行" in msg

    def test_opens_trade_path_not_root(self):
        """打开的必须是 /trade 界面，不是站点根。"""
        rec = _Recorder()

        opener.open_trade(probe=lambda _u: True, spawn=rec.spawn, opener=rec.open, timeout=1.0)

        assert rec.opened[0].endswith("/trade")


class TestColdStart:
    def test_spawns_then_opens(self, monkeypatch):
        rec = _Recorder()
        state = {"up": False}

        def probe(_u):
            return state["up"]

        def spawn(cmd):
            rec.spawn(cmd)
            state["up"] = True  # 启动后立刻就绪

        monkeypatch.setattr(opener, "_POLL_INTERVAL", 0.01)

        msg = opener.open_trade(probe=probe, spawn=spawn, opener=rec.open, timeout=5.0)

        assert len(rec.spawned) == 1
        assert rec.opened == ["http://127.0.0.1:9119/trade"]
        assert "已启动" in msg

    def test_spawns_with_no_browser(self, monkeypatch):
        """启动服务时必须带 --no-browser —— 浏览器由本命令开，否则会开出两个标签页。"""
        rec = _Recorder()
        state = {"up": False}
        monkeypatch.setattr(opener, "_POLL_INTERVAL", 0.01)

        opener.open_trade(
            probe=lambda _u: state["up"],
            spawn=lambda cmd: (rec.spawn(cmd), state.update(up=True)),
            opener=rec.open,
            timeout=5.0,
        )

        assert "--no-browser" in rec.spawned[0], f"缺少 --no-browser：{rec.spawned[0]}"
        assert rec.spawned[0][1].endswith("server.py"), "应直接跑 server.py 而不是依赖 PATH"


class TestFailureIsHonest:
    def test_timeout_reports_failure_not_success(self, monkeypatch):
        rec = _Recorder()
        monkeypatch.setattr(opener, "_POLL_INTERVAL", 0.01)

        msg = opener.open_trade(
            probe=lambda _u: False, spawn=rec.spawn, opener=rec.open, timeout=0.05
        )

        assert msg.startswith("✗"), f"超时却没说失败：{msg!r}"
        assert rec.opened == [], "服务没起来就不该打开浏览器（会显示无法连接）"
        assert "日志" in msg, "失败时要告诉用户去哪看日志"

    def test_missing_server_script_is_reported(self, monkeypatch):
        monkeypatch.setattr(opener, "_server_script_path", lambda: None)

        msg = opener.open_trade(probe=lambda _u: False, spawn=lambda _c: None, timeout=0.05)

        assert msg.startswith("✗")

    def test_spawn_exception_is_reported(self):
        def boom(_cmd):
            raise OSError("无权限")

        msg = opener.open_trade(probe=lambda _u: False, spawn=boom, timeout=0.05)

        assert msg.startswith("✗")
        assert "无权限" in msg


class TestProbe:
    def test_probe_false_when_nothing_listening(self):
        """真探测：本机 9 端口上没人听时必须返回 False（不抛异常）。"""
        assert opener.is_server_up("http://127.0.0.1:59999", timeout=0.3) is False
