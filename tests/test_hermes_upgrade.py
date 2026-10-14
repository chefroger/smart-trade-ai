"""Hermes 升级编排（trade.hermes_upgrade）与共存端点测试。

这里钉住三件最容易出错、且出错代价最高的事：
  1. **网络不通绝不起升级进程** —— 半途失败会同时弄坏 Hermes 和 Trade；
  2. 升级子进程的环境必须剔除 Trade 自己的懒加载开关，否则 `hermes update` 装不了依赖；
  3. 接口在不能升级时必须给出**可照做**的步骤（用户群是电脑小白）。
"""

from __future__ import annotations

import json

import pytest


class FakePopen:
    """假的 `hermes update` 子进程：可控输出与退出码，并记录调用参数。"""

    instances: list[dict] = []
    returncode = 0
    lines: tuple[str, ...] = ("Updating Hermes...\n",)

    def __init__(self, args, **kwargs):
        FakePopen.instances.append({"args": args, "kwargs": kwargs})
        self.stdout = iter(FakePopen.lines)
        self._rc = FakePopen.returncode

    def wait(self) -> int:
        return self._rc


@pytest.fixture(autouse=True)
def _fresh_upgrade_state():
    """每个用例都从干净的状态机开始（模块级全局会被上一个用例污染）。"""
    from trade import hermes_upgrade

    hermes_upgrade.reset_for_tests()
    yield
    hermes_upgrade.reset_for_tests()


@pytest.fixture
def hu(monkeypatch):
    """加载升级模块，并把「找启动器 / 探网络 / 起进程」换成可控的替身。"""
    from trade import hermes_upgrade

    FakePopen.instances = []
    FakePopen.returncode = 0
    monkeypatch.setattr(hermes_upgrade, "_hermes_launcher", lambda: "/usr/local/bin/hermes")
    monkeypatch.setattr(hermes_upgrade.subprocess, "Popen", FakePopen)
    return hermes_upgrade


def _run(hu) -> None:
    """等后台升级线程跑完（超时即失败，避免用例挂死）。"""
    assert hu._thread is not None
    hu._thread.join(timeout=10)
    assert not hu._thread.is_alive(), "升级线程未在超时内结束"


# ── 编排：网络前置 ──────────────────────────────────────────────────────────


def test_offline_never_starts_upgrade(hu, monkeypatch):
    """网络不通时一个进程都不许起 —— 这是「别把用户唯一能用的 Hermes 弄坏」的底线。"""
    monkeypatch.setattr(hu, "check_github_reachable", lambda: False)

    hu.start_upgrade()
    _run(hu)

    assert hu.status()["status"] == hu.OFFLINE
    assert FakePopen.instances == []


def test_offline_message_tells_user_to_enable_proxy(hu, monkeypatch):
    """文案必须给出动作（开代理），而不是只说「失败」。"""
    monkeypatch.setattr(hu, "check_github_reachable", lambda: False)

    hu.start_upgrade()
    _run(hu)

    assert "代理" in hu.status()["message"]


# ── 编排：执行与结果 ────────────────────────────────────────────────────────


def test_success_calls_hermes_update_with_clean_env(hu, monkeypatch):
    """成功路径：命令正确，且子进程环境里剔除了 Trade 的懒加载开关。"""
    monkeypatch.setattr(hu, "check_github_reachable", lambda: True)
    monkeypatch.setenv("HERMES_DISABLE_LAZY_INSTALLS", "1")

    hu.start_upgrade()
    _run(hu)

    assert hu.status()["status"] == hu.DONE
    call = FakePopen.instances[0]
    assert call["args"] == ["/usr/local/bin/hermes", "update"]
    # 带着这个开关，`hermes update` 会装不了依赖而在中途失败
    assert "HERMES_DISABLE_LAZY_INSTALLS" not in call["kwargs"]["env"]


def test_nonzero_exit_is_failed(hu, monkeypatch):
    """非零退出必须落成 failed，界面才有依据显示重试。"""
    monkeypatch.setattr(hu, "check_github_reachable", lambda: True)
    FakePopen.returncode = 3

    hu.start_upgrade()
    _run(hu)

    assert hu.status()["status"] == hu.FAILED
    assert hu.status()["returncode"] == 3


def test_missing_launcher_reports_install_guidance(hu, monkeypatch):
    """连 hermes 都找不到时，问题不是「过旧」而是「没装」，指引必须不同。"""
    monkeypatch.setattr(hu, "_hermes_launcher", lambda: None)

    hu.start_upgrade()

    assert hu.status()["status"] == hu.FAILED
    assert "安装" in hu.status()["message"]


def test_running_upgrade_is_idempotent(hu, monkeypatch):
    """升级进行中重复调用不得起第二个进程。"""
    monkeypatch.setattr(hu, "check_github_reachable", lambda: True)

    hu.start_upgrade()
    first = hu._thread
    hu.start_upgrade()

    assert hu._thread is first
    _run(hu)


def test_success_hook_fires_after_upgrade(hu, monkeypatch):
    """升级成功后必须触发收尾（重启 Trade）—— 否则新 Hermes 永远不会被加载。"""
    monkeypatch.setattr(hu, "check_github_reachable", lambda: True)
    fired = []
    hu.set_success_hook(lambda: fired.append(True))
    # 收尾在独立线程里延迟 _RESTART_DELAY_SECONDS 再执行；测试里把延迟归零，
    # 否则用例要白等 2 秒（这是我们把延迟做成常量而非硬编码的理由之一）
    monkeypatch.setattr(hu, "_RESTART_DELAY_SECONDS", 0)

    hu.start_upgrade()
    _run(hu)
    # 等收尾线程跑完（延迟已归零，通常一轮即命中）
    for _ in range(100):
        if fired:
            break
        hu.threading.Event().wait(0.02)

    assert fired == [True]


# ── 端点：共存状态与升级 ────────────────────────────────────────────────────


def _system_endpoint(path: str, method: str):
    """从系统路由里取出端点函数（既有测试惯例：直接调函数，不经过 HTTP）。"""
    from trade.app import _create_system_router

    for route in _create_system_router().routes:
        if route.path == path and method in route.methods:
            return route.endpoint
    raise AssertionError(f"路由不存在: {method} {path}")


@pytest.fixture
def compat_ok(monkeypatch):
    """把共存状态钉成「可用」。"""
    from trade import bootstrap

    monkeypatch.setattr(bootstrap, "hermes_compat_state", lambda: {
        "verdict": "ok", "version": "0.22.0", "python": "3.14.7",
        "reason": "ok", "checkout": "/tmp/x",
    })


@pytest.fixture
def compat_too_old(monkeypatch):
    """把共存状态钉成「版本过旧」。"""
    from trade import bootstrap

    monkeypatch.setattr(bootstrap, "hermes_compat_state", lambda: {
        "verdict": "too_old", "version": "0.19.0", "python": "3.14.7",
        "reason": "Hermes 声明的 Python 区间 >=3.11,<3.14 不包含当前解释器 3.14.7",
        "checkout": "/tmp/x",
    })


def test_compat_endpoint_ok_hides_steps(compat_ok):
    """可用时不显示升级步骤（不要给用户看用不上的东西）。"""
    body = _system_endpoint("/system/hermes-compat", "GET")()

    assert body["usable"] is True
    assert body["steps"] == []


def test_compat_endpoint_too_old_returns_actionable_steps(compat_too_old):
    """过旧时必须带上可照做的步骤 —— 用户群是电脑小白，只报错等于没做。"""
    body = _system_endpoint("/system/hermes-compat", "GET")()

    assert body["usable"] is False
    assert body["version"] == "0.19.0"
    assert len(body["steps"]) == 3
    assert body["steps"][0]["command"] == "hermes update"


async def test_upgrade_stream_emits_state_and_ends(compat_too_old):
    """进度流必须推得出状态、且在终态立即收尾（不能挂住界面）。"""
    from trade.hermes_upgrade import DONE, reset_for_tests

    reset_for_tests()
    # 直接把状态设成终态，验证「不运行就立即结束」
    import trade.hermes_upgrade as hu

    hu._set(DONE, "升级完成")

    response = await _system_endpoint("/system/hermes-upgrade/stream", "GET")(offset=0)
    frames = [chunk async for chunk in response.body_iterator]

    states = [
        json.loads(f[len("data: "):])
        for f in frames if f.startswith("data: ")
    ]
    assert any(s.get("type") == "state" and s.get("status") == DONE for s in states)
