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
        "reason": "ok", "checkout": "/tmp/x", "fix": "none",
    })


@pytest.fixture
def compat_too_old(monkeypatch):
    """把共存状态钉成「Hermes 版本过旧」。"""
    from trade import bootstrap

    monkeypatch.setattr(bootstrap, "hermes_compat_state", lambda: {
        "verdict": "too_old", "version": "0.19.0", "python": "3.14.7",
        "reason": "Hermes 声明的 Python 区间 >=3.11,<3.14 不包含当前解释器 3.14.7",
        "checkout": "/tmp/x", "fix": "upgrade_hermes",
    })


@pytest.fixture
def compat_python_too_old(monkeypatch):
    """把共存状态钉成「Trade 运行环境过旧」（Hermes 够新、解释器太老）。"""
    from trade import bootstrap

    monkeypatch.setattr(bootstrap, "hermes_compat_state", lambda: {
        "verdict": "python_too_old", "version": "0.22.0", "python": "3.13.5",
        "reason": "Hermes 0.22.0 需要 Python 3.14 运行时，而 Trade 当前的解释器是 3.13.5",
        "checkout": "/tmp/x", "fix": "rebuild_trade_venv",
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
    assert body["fix"] == "upgrade_hermes"
    assert len(body["steps"]) == 3
    assert body["steps"][0]["command"] == "hermes update"


def test_compat_endpoint_rebuild_case_gives_reinstall_steps(compat_python_too_old):
    """「Trade 运行环境过旧」给的是**重装**指引，不是升级 Hermes。

    2026-10-15 客户机实测：这一档当时被判成 ok，界面只显示「AI Agent 模块未加载」；
    而即便判出来，若沿用「升级 Hermes」的步骤，用户跑完 hermes update 也毫无用处 ——
    问题在 Trade 这一侧。
    """
    body = _system_endpoint("/system/hermes-compat", "GET")()

    assert body["usable"] is False
    assert body["fix"] == "rebuild_trade_venv"
    assert body["steps"], "必须给步骤，否则用户无从下手"
    # 步骤里要出现重装脚本，且**不能**是 hermes update
    assert "scripts/install" in body["steps"][0]["command"]
    assert "hermes update" not in body["steps"][0]["command"]


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


# ── 探测：绝不能永久挂住（2026-10-15 客户机实测）────────────────────────────


def test_probe_uses_no_pipes_and_disables_prompts(monkeypatch):
    """探测子进程必须：不给任何管道 + 禁掉一切交互提示 + 关掉凭证助手。

    2026-10-15 客户机实测：Windows 上 `git ls-remote` 撞到凭证提示会**永久挂住**，
    面板就停在「正在检查网络」不动。根源有两个，都要堵：
      1. 有管道 → 孙进程（凭证助手）持着句柄时 `communicate()` 会越过 timeout 继续等；
      2. 凭证助手会弹提示 → 必须从环境上禁掉。
    """
    from trade import hermes_upgrade as hu

    captured: dict = {}

    class FakeProc:
        def __init__(self, args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(hu.shutil, "which", lambda _n: "/usr/bin/git")
    monkeypatch.setattr(hu.subprocess, "Popen", FakeProc)

    assert hu.check_github_reachable() is True

    kwargs = captured["kwargs"]
    assert kwargs["stdin"] == hu.subprocess.DEVNULL
    assert kwargs["stdout"] == hu.subprocess.DEVNULL, "有管道就可能在超时后继续等"
    assert kwargs["stderr"] == hu.subprocess.DEVNULL
    assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert kwargs["env"]["GCM_INTERACTIVE"] == "never"
    # 关掉凭证助手，且 -c 必须排在子命令之前（否则 git 把它当成 ls-remote 的参数）
    assert "credential.helper=" in captured["args"]
    assert captured["args"].index("credential.helper=") < captured["args"].index("ls-remote")


def test_probe_hard_deadline_beats_a_stuck_thread(monkeypatch):
    """即便探测线程本身卡死（内层超时收不回来），外层硬截止也必须让它返回「不可达」。

    这条钉的是**界面不会永远停住**：状态机只要拿到 False 就会翻到 offline 并显示可重试，
    而卡在 checking_network 时用户面对的是一个不会动的界面（客户机的实际遭遇）。
    """
    import time

    from trade import hermes_upgrade as hu

    monkeypatch.setattr(hu, "_PROBE_DEADLINE", 0.3)
    monkeypatch.setattr(hu, "_probe_github", lambda: time.sleep(30) or True)

    start = time.time()
    reached = hu.check_github_reachable()
    elapsed = time.time() - start

    assert reached is False, "卡住的探测必须按「不可达」处理"
    assert elapsed < 5, f"外层硬截止没生效（耗时 {elapsed:.1f}s）"


def test_probe_disables_prompts_for_the_update_child_too(monkeypatch):
    """`hermes update` 子进程同样要禁掉提示。

    它内部要跑 git fetch，撞上凭证提示会挂住；而升级子进程**不能像探测那样被超时杀掉**
    （杀掉一个做到一半的 Hermes 升级很危险），所以只能从源头保证它不会去等输入。
    """
    from trade import hermes_upgrade as hu

    monkeypatch.setenv("HERMES_DISABLE_LAZY_INSTALLS", "1")

    env = hu._child_env()

    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GCM_INTERACTIVE"] == "never"
    # 必须剔除 Trade 自己的懒加载开关：带着它 `hermes update` 装不了依赖
    assert "HERMES_DISABLE_LAZY_INSTALLS" not in env


def test_update_child_stdin_is_closed(hu, monkeypatch):
    """`hermes update` 的 stdin 必须断开：宁可就地失败并显示重试，也不要挂在看不见的提示上。"""
    monkeypatch.setattr(hu, "check_github_reachable", lambda: True)

    hu.start_upgrade()
    _run(hu)

    assert FakePopen.instances[0]["kwargs"]["stdin"] == hu.subprocess.DEVNULL
