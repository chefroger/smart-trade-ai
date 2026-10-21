"""Gateway 存活判断：优先 Hermes 官方严格探测，失效才回退旧探测（2026-10-21）。

背景（见 COMPATIBILITY.md 的 0.22.2 行）：
- 0.22 起 api_server 未启用时 8642 不监听 → TCP 探测把已在跑的 gateway 判成没跑，
  每次启动多余 spawn 一次（无害但脏）；
- `pgrep -f hermes.*gateway` 会把 `hermes gateway status` / dashboard 这类兄弟命令
  误判成 gateway 在跑（假阳性 → 该启动时不启动，定时任务静默不跑，是更危险的方向）。
上游 `hermes gateway status` 内部用的就是 `find_gateway_pids()`（PID 文件 + 服务管理器
+ 严格 argv 扫描 + 排除调用链）—— Trade 直接复用同一判断，不依赖端口或进程名。
"""

import sys
import types

import pytest

from trade import app as trade_app


def _install_fake_hermes(monkeypatch, find_pids):
    """把假的 hermes_cli.gateway 放进 sys.modules（真实 Hermes 在 CI 里不存在）。"""
    fake_pkg = types.ModuleType("hermes_cli")
    fake_mod = types.ModuleType("hermes_cli.gateway")
    fake_mod.find_gateway_pids = find_pids
    monkeypatch.setitem(sys.modules, "hermes_cli", fake_pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.gateway", fake_mod)


class TestHermesDetectorPreferred:
    """有 Hermes 严格探测时，它的结论就是最终结论（不回退）。"""

    def test_pids_mean_running(self, monkeypatch):
        _install_fake_hermes(monkeypatch, lambda: [1234])
        monkeypatch.setattr(
            trade_app,
            "_gateway_running_fallback",
            lambda: pytest.fail("权威探测已给出结论，不应回退"),
        )
        assert trade_app._is_gateway_running() is True

    def test_empty_is_authoritative_negative(self, monkeypatch):
        """空列表 = 权威的"没跑"：必须回 False，不能回退到可能假阳性的 pgrep。"""
        _install_fake_hermes(monkeypatch, lambda: [])
        monkeypatch.setattr(
            trade_app,
            "_gateway_running_fallback",
            lambda: pytest.fail("权威探测已给出结论，不应回退"),
        )
        assert trade_app._is_gateway_running() is False

    def test_detector_exception_falls_back(self, monkeypatch):
        """探测函数本身抛错（上游内部变动）→ 返回 None → 回退旧探测。"""

        def boom():
            raise RuntimeError("upstream changed")

        _install_fake_hermes(monkeypatch, boom)
        monkeypatch.setattr(trade_app, "_gateway_running_fallback", lambda: True)
        assert trade_app._gateway_running_via_hermes() is None
        assert trade_app._is_gateway_running() is True


class TestFallbackWhenHermesUnavailable:
    def test_import_failure_falls_back(self, monkeypatch):
        """Hermes 不可导入（CI / 精简环境 / 旧版缺函数）→ 回退旧探测。"""
        for name in ("hermes_cli", "hermes_cli.gateway"):
            monkeypatch.delitem(sys.modules, name, raising=False)

        class _BlockHermes:
            def find_spec(self, name, path=None, target=None):
                if name == "hermes_cli" or name.startswith("hermes_cli."):
                    raise ImportError("blocked for test")
                return None

        monkeypatch.setattr(sys, "meta_path", [_BlockHermes(), *sys.meta_path])
        monkeypatch.setattr(trade_app, "_gateway_running_fallback", lambda: False)
        assert trade_app._gateway_running_via_hermes() is None
        assert trade_app._is_gateway_running() is False


class TestEnsureGatewayRunning:
    """启动时的 ensure 语义：在跑就不 spawn，没跑才 spawn `gateway run`。"""

    def test_skips_spawn_when_running(self, monkeypatch):
        monkeypatch.setattr(trade_app, "_is_gateway_running", lambda: True)
        monkeypatch.setattr(
            trade_app._sp,
            "Popen",
            lambda *a, **k: pytest.fail("gateway 已在跑，不该 spawn"),
        )
        trade_app._ensure_gateway_running()

    def test_spawns_when_not_running(self, monkeypatch):
        monkeypatch.setattr(trade_app, "_is_gateway_running", lambda: False)
        monkeypatch.setattr(trade_app, "_find_hermes_binary", lambda **k: "/fake/hermes")
        calls = []
        monkeypatch.setattr(
            trade_app._sp,
            "Popen",
            lambda args, **kwargs: calls.append((args, kwargs)),
        )
        trade_app._ensure_gateway_running()
        # Rosetta 分支会先用同一底层 Popen 跑一次 `uname -m`（x86_64 macOS 上）；
        # 这里只看 gateway 的 spawn，保证三平台断言一致。
        spawns = [args for args, _kwargs in calls if args and args[0] == "/fake/hermes"]
        assert spawns == [["/fake/hermes", "gateway", "run"]]
