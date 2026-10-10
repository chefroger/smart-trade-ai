"""`trade open` —— 桌面快捷方式双击后的行为。

规则：
  - 服务已在运行 → **不重复启动**，直接打开界面
  - 服务没运行 → 静默启动（带 --no-browser，避免服务自己也开一个标签页），
    等它就绪后再打开
  - 启动超时 → 如实报错 + 指出日志位置，**不假装成功**
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

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
            probe=lambda _u: True, spawn=rec.spawn, opener=rec.open,
            focuser=lambda _m: False, timeout=1.0,
        )

        assert rec.spawned == [], "服务已在运行时不该再启动一个（会撞端口）"
        assert rec.opened == ["http://127.0.0.1:9119/trade"]
        assert "已在运行" in msg

    def test_opens_trade_path_not_root(self):
        """打开的必须是 /trade 界面，不是站点根。"""
        rec = _Recorder()

        opener.open_trade(probe=lambda _u: True, spawn=rec.spawn, opener=rec.open,
                          focuser=lambda _m: False, timeout=1.0)

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

        msg = opener.open_trade(probe=probe, spawn=spawn, opener=rec.open,
                                focuser=lambda _m: False, timeout=5.0)

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
            focuser=lambda _m: False,
            timeout=5.0,
        )

        assert "--no-browser" in rec.spawned[0], f"缺少 --no-browser：{rec.spawned[0]}"
        assert rec.spawned[0][1].endswith("server.py"), "应直接跑 server.py 而不是依赖 PATH"


class TestFailureIsHonest:
    def test_timeout_reports_failure_not_success(self, monkeypatch):
        rec = _Recorder()
        monkeypatch.setattr(opener, "_POLL_INTERVAL", 0.01)

        msg = opener.open_trade(
            probe=lambda _u: False, spawn=rec.spawn, opener=rec.open,
            focuser=lambda _m: False, timeout=0.05,
        )

        assert msg.startswith("✗"), f"超时却没说失败：{msg!r}"
        assert rec.opened == [], "服务没起来就不该打开浏览器（会显示无法连接）"
        assert "日志" in msg, "失败时要告诉用户去哪看日志"

    def test_missing_server_script_is_reported(self, monkeypatch):
        monkeypatch.setattr(opener, "_server_script_path", lambda: None)

        msg = opener.open_trade(probe=lambda _u: False, spawn=lambda _c: None,
                                focuser=lambda _m: False, timeout=0.05)

        assert msg.startswith("✗")

    def test_spawn_exception_is_reported(self):
        def boom(_cmd):
            raise OSError("无权限")

        msg = opener.open_trade(probe=lambda _u: False, spawn=boom,
                                focuser=lambda _m: False, timeout=0.05)

        assert msg.startswith("✗")
        assert "无权限" in msg


class TestProbe:
    def test_probe_false_when_nothing_listening(self):
        """真探测：本机 9 端口上没人听时必须返回 False（不抛异常）。"""
        assert opener.is_server_up("http://127.0.0.1:59999", timeout=0.3) is False


class TestReuseExistingPage:
    """已打开的 Trade 页面要切过去，而不是每点一次多一个标签页。

    浏览器不向外部程序暴露「聚焦已有标签页」，只能按窗口标题找回
    （用户已确认采用这个方案）。
    """

    def test_focus_existing_does_not_open_new(self):
        rec = _Recorder()

        msg = opener.open_trade(
            probe=lambda _u: True, spawn=rec.spawn, opener=rec.open,
            focuser=lambda _m: True, timeout=1.0,
        )

        assert rec.opened == [], "已有页面时不该再开一个"
        assert "已切到" in msg

    def test_falls_back_to_opening_when_no_window(self):
        rec = _Recorder()

        opener.open_trade(
            probe=lambda _u: True, spawn=rec.spawn, opener=rec.open,
            focuser=lambda _m: False, timeout=1.0,
        )

        assert rec.opened == ["http://127.0.0.1:9119/trade"]

    def test_focuser_exception_does_not_block_opening(self):
        """聚焦失败不是错误，照常打开新页面。"""
        rec = _Recorder()

        def boom(_m):
            raise OSError("用户32 调用失败")

        opener.open_trade(
            probe=lambda _u: True, spawn=rec.spawn, opener=rec.open,
            focuser=boom, timeout=1.0,
        )

        assert rec.opened == ["http://127.0.0.1:9119/trade"]

    def test_focus_happens_after_server_is_ready(self):
        """必须先确保服务在跑再聚焦 —— 反了会把用户切到浏览器的错误页。"""
        order = []
        state = {"up": False}

        def probe(_u):
            order.append("probe")
            return state["up"]

        def spawn(_cmd):
            order.append("spawn")
            state["up"] = True

        def focus(_m):
            order.append("focus")
            return True

        opener.open_trade(probe=probe, spawn=spawn, opener=lambda _u: True,
                          focuser=focus, timeout=5.0)

        assert "focus" in order
        assert order.index("spawn") < order.index("focus"), f"顺序错了：{order}"


class TestWindowTitleMatching:
    def test_matches_browser_suffixed_title(self):
        """浏览器会在标题后追加自己的名字，所以用包含匹配。"""
        titles = [
            "某个无关窗口",
            "Trade AI Assistant — 智能外贸销售助手 - Google Chrome",
            "另一个窗口",
        ]

        assert opener.match_trade_window(titles) == (
            "Trade AI Assistant — 智能外贸销售助手 - Google Chrome"
        )

    def test_returns_none_when_absent(self):
        assert opener.match_trade_window(["微信", "记事本"]) is None

    def test_ignores_empty_titles(self):
        assert opener.match_trade_window(["", None]) is None

    def test_marker_matches_the_real_page_title(self):
        """标记必须真的出现在 static/trade_chat.html 的 <title> 里 ——
        否则改了页面标题就会静默失效：快捷方式每次都新开标签页，没人会注意到。
        """
        from pathlib import Path

        html = (Path(__file__).resolve().parent.parent / "static" / "trade_chat.html").read_text(
            encoding="utf-8"
        )
        assert opener.WINDOW_TITLE_MARKER in html, (
            f"页面标题里找不到 {opener.WINDOW_TITLE_MARKER!r} —— "
            "窗口匹配会永远失败，快捷方式每次都开新标签页"
        )


@pytest.mark.skipif(
    os.name == "nt",
    reason="这一组断言的是**非 Windows** 上的行为：Windows 上窗口枚举会真的返回窗口"
           "（CI 上就枚举到了任务管理器），聚焦也可能真的成功",
)
class TestNonWindowsBehaviour:
    """非 Windows 上的行为。

    **必须加平台守卫**：这些实现只在 Windows 上做事，在别的平台上返回空/False ——
    而 Windows CI 上它们会真的工作，断言"返回空表"必然失败。
    （与 os.name 那次同类：平台相关的断言漏了守卫。）
    """

    def test_focus_is_noop_off_windows(self):
        """非 Windows 上聚焦直接返回 False（照常打开页面），不抛异常。"""
        assert opener._focus_window_by_title(opener.WINDOW_TITLE_MARKER) is False

    def test_window_enumeration_empty_off_windows(self):
        assert opener._iter_window_titles() == []


class TestWindowsHelpersAreGuarded:
    """与平台无关的那半：这些函数在任何平台上都不能抛异常。

    上面那组只能非 Windows 跑，这组保证"调了不该调的东西"时是安全降级 ——
    没有 Win32 的环境下枚举/聚焦会走 except 分支返回空。
    """

    def test_enumeration_never_raises(self):
        assert isinstance(opener._iter_window_titles(), list)

    def test_focus_never_raises(self):
        assert isinstance(opener._focus_window_by_title("绝不存在的窗口标题"), bool)

    def test_focus_on_bogus_marker_is_false(self):
        assert opener._focus_window_by_title("绝不存在的窗口标题") is False
