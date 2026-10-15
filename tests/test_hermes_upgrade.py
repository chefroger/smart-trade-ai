"""Hermes 升级编排（trade.hermes_upgrade）与共存端点测试。

这里钉住三件最容易出错、且出错代价最高的事：
  1. **网络不通绝不起升级进程** —— 半途失败会同时弄坏 Hermes 和 Trade；
  2. 升级子进程的环境必须剔除 Trade 自己的懒加载开关，否则 `hermes update` 装不了依赖；
  3. 接口在不能升级时必须给出**可照做**的步骤（用户群是电脑小白）。
"""

from __future__ import annotations

import json
import threading

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
    # ⓔ 的守卫要求「补救方向必须是 upgrade_hermes 才允许启动」。这一组用例测的是
    # 升级本身的机制，所以把守卫放行；守卫自身的逻辑与接线由 TestUpgradeApplicability
    # 单独测（那组只打桩 hermes_compat_state，不绕过守卫）。
    monkeypatch.setattr(hermes_upgrade, "_not_applicable_reason", lambda: None)
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

    response = await _system_endpoint("/system/hermes-upgrade/stream", "GET")(
        request=_fake_request(), offset=0
    )
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


# ── ⓔ：补救方向不对时，start_upgrade 自己必须拒绝 ─────────────────────────


class TestUpgradeApplicability:
    """`start_upgrade()` 自己校验「该不该升」，不依赖调用方判断。

    为什么钉在被调方：调用方有三处（bootstrap 降级分支、/system/hermes-upgrade 端点、
    前端重试按钮），只要一处漏判，就会在「Trade 运行环境过旧」的场景跑一场毫无用处的
    hermes update —— 而它的 UPGRADING 状态会经 SSE 覆盖界面上的「重建运行环境」提示。
    """

    @staticmethod
    def _stub_fix(monkeypatch, value):
        """只打桩判定来源，不绕过守卫本身。"""
        from trade import bootstrap

        monkeypatch.setattr(
            bootstrap, "hermes_compat_state",
            lambda: {"verdict": "ok" if value == "none" else "python_too_old",
                     "fix": value, "reason": "r", "version": "0.22.0", "python": "3.13.5"},
        )

    @pytest.mark.parametrize("fix,expect", [
        ("upgrade_hermes", None),
        ("rebuild_trade_venv", "重建 Trade 的运行环境"),
        ("none", "无需升级"),
    ])
    def test_reason_by_fix_direction(self, monkeypatch, fix, expect):
        from trade import hermes_upgrade as hu

        self._stub_fix(monkeypatch, fix)

        reason = hu._not_applicable_reason()

        if expect is None:
            assert reason is None
        else:
            assert reason and expect in reason

    def test_start_upgrade_refuses_when_rebuild_is_needed(self, monkeypatch):
        """方向是「重建」时必须拒绝，且**不得改动状态机**。"""
        from trade import hermes_upgrade as hu

        hu.reset_for_tests()
        self._stub_fix(monkeypatch, "rebuild_trade_venv")
        # 一旦真的启动就会起子进程：用会炸的替身确保它没被启动
        monkeypatch.setattr(hu, "_hermes_launcher", lambda: pytest.fail("不该启动升级"))

        snap = hu.start_upgrade()

        assert snap.get("rejected"), "必须给出拒绝原因"
        assert snap["status"] == hu.IDLE, "拒绝时不得改动状态机（否则界面会显示假进度）"
        assert snap["running"] is False

    def test_start_upgrade_proceeds_when_hermes_is_old(self, hu, monkeypatch):
        """方向是升级 Hermes（该升的那一档）时照常放行 —— 别把守卫做过头。

        这里**不绕过守卫**：只打桩判定来源，让真实的 `_not_applicable_reason()` 跑一遍。
        """
        from trade import bootstrap

        # 撤掉夹具的放行桩，让真实守卫参与（undo 会撤掉全部桩，所以之后要重装）
        monkeypatch.undo()
        monkeypatch.setattr(hu, "_hermes_launcher", lambda: "/usr/local/bin/hermes")
        monkeypatch.setattr(hu.subprocess, "Popen", FakePopen)
        monkeypatch.setattr(hu, "check_github_reachable", lambda: True)
        monkeypatch.setattr(
            bootstrap, "hermes_compat_state",
            lambda: {"verdict": "too_old", "fix": "upgrade_hermes",
                     "reason": "r", "version": "0.19.0", "python": "3.14.7"},
        )

        hu.start_upgrade()
        _run(hu)

        assert hu.status()["status"] == hu.DONE
        assert hu.status().get("rejected") is None


def test_child_env_forces_unbuffered_output(monkeypatch):
    """升级子进程必须无缓冲输出。

    不加 PYTHONUNBUFFERED 时子进程 stdout 是块缓冲，界面上会**整段时间一行都看不到**
    （升级要几分钟），用户以为卡死 —— 而「让用户看到有在动」正是这个面板存在的理由。
    """
    from trade import hermes_upgrade as hu

    env = hu._child_env()

    assert env.get("PYTHONUNBUFFERED") == "1"


class HangingPopen:
    """stdout 既不产出也不结束，直到被 kill —— 模拟撞上弹窗/交互询问而卡死。"""

    instances: list[dict] = []

    def __init__(self, args, **kwargs):
        HangingPopen.instances.append({"args": args, "kwargs": kwargs})
        self.killed = False
        self._release = threading.Event()

    @property
    def stdout(self):
        def _gen():
            # 阻塞在这里，直到看门狗 kill 掉我们
            self._release.wait(30)
            return
            yield  # pragma: no cover — 让它成为生成器

        return _gen()

    def kill(self) -> None:
        self.killed = True
        self._release.set()

    def wait(self, timeout=None) -> int:
        return -9


def test_watchdog_kills_a_silent_upgrade(hu, monkeypatch):
    """超过 N 分钟没有任何输出 → 杀掉子进程并落成 FAILED，不能永远停在 UPGRADING。

    为什么必须有这条：`for line in proc.stdout` 会阻塞到子进程关掉 stdout。若
    `hermes update` 撞上**非凭证类**卡死（管理员权限弹窗、系统服务询问），
    `_NO_PROMPT_ENV` 挡不住，而用户点「重试」又会被幂等判断顶回 —— 彻底没有出路。
    复用探测那套硬截止思路即可，不需要架构大改。
    """
    monkeypatch.setattr(hu, "check_github_reachable", lambda: True)
    monkeypatch.setattr(hu.subprocess, "Popen", HangingPopen)
    # 把窗口压到亚秒级，让用例快
    monkeypatch.setattr(hu, "_NO_OUTPUT_LIMIT_SECONDS", 0.2)
    monkeypatch.setattr(hu, "_WATCHDOG_TICK_SECONDS", 0.05)
    HangingPopen.instances = []

    hu.start_upgrade()
    _run(hu)

    snap = hu.status()
    assert snap["status"] == hu.FAILED
    assert "卡住" in snap["message"], f"失败原因应指明是卡住：{snap['message']}"
    assert HangingPopen.instances, "应该真的起了子进程"


def test_watchdog_leaves_normal_failure_alone(hu, monkeypatch):
    """子进程正常退出（非零）时，失败原因不能误报成「卡住」。"""
    monkeypatch.setattr(hu, "check_github_reachable", lambda: True)
    FakePopen.returncode = 7

    hu.start_upgrade()
    _run(hu)

    snap = hu.status()
    assert snap["status"] == hu.FAILED
    assert "卡住" not in snap["message"], "非零退出不是超时"
    assert snap["returncode"] == 7


class _FakeRequest:
    """只有 `.headers.get()` 的最小替身 —— 端点只需要读 session token。"""

    def __init__(self, token: str = "") -> None:
        self.headers = {"X-Hermes-Session-Token": token} if token else {}


def _fake_request(token: str = "") -> _FakeRequest:
    return _FakeRequest(token)


async def test_stream_does_not_end_on_idle(compat_too_old):
    """`IDLE`（还没启动）**不是**终态 —— 流不能一上来就收尾。

    原来的判断是 `if not snap["running"]: break`，而 IDLE 的 running 也是 False，
    于是「前端先连上来、再点升级」的顺序会拿到一个空流就断开，之后再也收不到进度。
    现在只有 DONE / FAILED / OFFLINE 才收尾。
    """
    import asyncio

    import trade.hermes_upgrade as hu

    hu.reset_for_tests()
    assert hu.status()["status"] == hu.IDLE, "前置：状态应是 idle"

    response = await _system_endpoint("/system/hermes-upgrade/stream", "GET")(
        request=_fake_request(), offset=0
    )

    async def _drain() -> None:
        async for _chunk in response.body_iterator:
            pass

    # 流应当**继续挂着**（等升级开始），所以在此窗口内超时才算通过
    try:
        await asyncio.wait_for(_drain(), timeout=0.3)
        raise AssertionError("IDLE 时流不应结束")
    except TimeoutError:
        pass
    finally:
        await response.body_iterator.aclose()
