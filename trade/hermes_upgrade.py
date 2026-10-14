"""Hermes 升级编排：网络前置检查 → 后台执行上游官方更新命令 → 状态机 + 日志缓冲。

**为什么由 Trade 代跑**：Trade 的用户群基本是电脑小白，桌面端（tradewin）看不到终端，
让他们自己敲命令等于没做。所以由 Trade 在后台执行上游**官方**的更新子命令 ——
调它的命令不算「修改 Hermes」，符合 CLAUDE.md 的硬约束（不 monkeypatch、不碰 Hermes 源码）。

**为什么必须先查 GitHub 可达性**：`hermes update` 要从 GitHub 拉代码。用户多在国内，
不通时升级会半途失败 —— 而失败会**同时弄坏 Hermes 和 Trade**（Trade 依赖 Hermes 才能
跑 agent）。所以网络不通时绝不开始，改为引导用户先开代理。这条比「有没有按钮」重要得多。

状态机（供界面显示）::

    idle → checking_network → upgrading → done
                                        ↘ failed
                          ↘ offline（网络不通，压根没开始）
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

# ── 状态常量（前端按这些值渲染面板）────────────────────────────────────────
IDLE = "idle"
CHECKING = "checking_network"
UPGRADING = "upgrading"
DONE = "done"
FAILED = "failed"
OFFLINE = "offline"

# 日志环保留行数：界面只要看到滚动进度，不需要无限历史
_LOG_LIMIT = 400
# 单次 git 探测超时（秒）。冷启动 + 代理握手实测几秒内，20 秒足够且不会让用户干等太久
_PROBE_TIMEOUT = 20.0
# 上游仓库地址（与 scripts/install.sh 的 HERMES_REPO 一致）
_HERMES_REPO = "https://github.com/NousResearch/hermes-agent.git"
# 升级成功后延迟多久再重启：留一点时间让界面把「完成」渲染出来，否则用户只看到连接断开
_RESTART_DELAY_SECONDS = 2.0

# 升级成功后的收尾回调（由 app 层注入：重启 Trade 以加载新 Hermes）。
# 用回调而不是在这里 import app：hermes_upgrade 是底层模块，反向依赖 app 会成环。
_success_hook: Callable[[], None] | None = None


def set_success_hook(hook: Callable[[], None] | None) -> None:
    """注入升级成功后的收尾动作（app 层传 _perform_restart）。"""
    global _success_hook
    _success_hook = hook


_lock = threading.Lock()
_logs: deque[str] = deque(maxlen=_LOG_LIMIT)
# 累计写入行数（**单调递增**，不受 deque 淘汰影响）—— 前端用它作增量游标，
# 若改用 len(_logs)，一旦超过 _LOG_LIMIT 行、旧行被淘汰，游标就会错位丢日志
_log_total = 0
_thread: threading.Thread | None = None
_state: dict[str, Any] = {
    "status": IDLE,
    "message": "",
    "returncode": None,
    "started_at": None,
    "ended_at": None,
}


def _hermes_launcher() -> str | None:
    """定位用户自己的 `hermes` 启动器；找不到返回 None。

    优先上游安装器写出启动器的固定位置，再退回 PATH —— 顺序不能反：PATH 里可能存在
    Trade venv 自己的 `hermes`（旧架构会 `pip install -e` 装一份），那不是管理用户
    Hermes 安装的那一个，用它执行 update 会更新错对象。
    """
    names = ("hermes.exe", "hermes.cmd", "hermes") if os.name == "nt" else ("hermes",)

    from trade.post_install.skills import _get_hermes_home

    hermes_home = _get_hermes_home()
    candidates: list[Path] = []
    for name in names:
        # 上游安装器写的两个位置：数据目录下的启动器、以及用户级 bin
        candidates.append(hermes_home / "hermes-agent" / ".hermes" / "bin" / name)
        candidates.append(hermes_home / "bin" / name)
        candidates.append(Path.home() / ".local" / "bin" / name)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    # 兜底：PATH。找不到返回 None，由调用方给出「请先安装 Hermes」的指引
    return shutil.which("hermes")


def check_github_reachable() -> bool:
    """GitHub 是否可达 —— 用 git 自己探，而不是裸 TCP。

    为什么不用 TCP：用户可能配了代理（git config / http_proxy），此时裸 TCP 连
    github.com:443 会失败，但 git 能通 —— 那会把「能升级」误判成「不能升级」，
    白白拦住用户。`git ls-remote` 走的是 git 真实使用的链路，口径一致。
    """
    git = shutil.which("git")
    if not git:
        # 没装 git 时无从判断，交由升级命令自己报错（安装脚本本就要求 git）
        return True
    try:
        proc = subprocess.run(
            [git, "ls-remote", "--exit-code", _HERMES_REPO, "HEAD"],
            capture_output=True, text=True, timeout=_PROBE_TIMEOUT,
        )
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        # 超时/无法执行都按不可达处理：宁可让用户先开代理，也不要半途把 Hermes 弄坏
        return False


def _child_env() -> dict[str, str]:
    """构造升级子进程的环境变量。

    必须剔除 HERMES_DISABLE_LAZY_INSTALLS：那是 Trade 给自己设的「禁止 Hermes 重拉/
    装依赖」开关，而 `hermes update` **恰恰需要**安装依赖 —— 带着它会在升级中途失败。
    """
    env = dict(os.environ)
    env.pop("HERMES_DISABLE_LAZY_INSTALLS", None)
    return env


def _append_log(line: str) -> None:
    """追加一行升级输出（供界面增量读取）。"""
    global _log_total
    with _lock:
        _logs.append(line)
        _log_total += 1


def _set(status: str, message: str, *, returncode: int | None = None) -> None:
    """更新状态机（线程安全），并写一行日志便于事后排查。"""
    with _lock:
        _state["status"] = status
        _state["message"] = message
        if returncode is not None:
            _state["returncode"] = returncode
        if status in (DONE, FAILED, OFFLINE):
            _state["ended_at"] = _now()
    # 状态变更也写进日志流，界面按同一游标顺序显示，不会出现「状态跳了但日志没跟上」
    _append_log(f"[trade] {message}")


def _now() -> float:
    """当前时间戳（秒）。"""
    import time

    return time.time()


def status(log_offset: int = 0) -> dict[str, Any]:
    """返回升级状态快照 + 增量日志。

    Args:
        log_offset: 客户端已消费的日志行号；返回该位置之后的新行与新的游标，
                    供界面滚动显示进度（避免每轮重传全部日志）。
    """
    with _lock:
        lines = list(_logs)
        total = _log_total
        snapshot = dict(_state)
    # deque 只保留最近 _LOG_LIMIT 行，先按「已淘汰行数」把客户端游标对齐到现有下标
    dropped = total - len(lines)
    start = max(0, min(log_offset, total) - dropped)
    snapshot["logs"] = lines[start:]
    snapshot["log_cursor"] = total
    snapshot["running"] = snapshot["status"] in (CHECKING, UPGRADING)
    return snapshot


def start_upgrade() -> dict[str, Any]:
    """启动后台升级；已在升级中则直接返回当前状态（幂等）。

    Returns:
        status() 的快照（含 status 字符串，前端据此渲染）。
    """
    global _thread, _log_total

    # 幂等判断必须在**出锁之后**再调 status()：status() 自己也要拿同一把锁，
    # 而 threading.Lock 不可重入 —— 在锁内调用会把请求线程直接挂死（用户连点两次
    # 「重试」就会复现）。
    with _lock:
        already_running = _state["status"] in (CHECKING, UPGRADING)
    if already_running:
        return status()

    launcher = _hermes_launcher()
    if launcher is None:
        # 连启动器都找不到 → 不是「版本过旧」而是「没装」，给出安装指引而非升级
        _set(FAILED, "找不到 hermes 命令，请先安装 Hermes（见 README 安装步骤）")
        return status()

    with _lock:
        _logs.clear()
        # 清日志必须同步清零游标基数，否则前端按旧游标取增量会一片空白
        _log_total = 0
        _state.update({
            "status": CHECKING, "message": "正在检查网络…",
            "returncode": None, "started_at": _now(), "ended_at": None,
        })
        _thread = threading.Thread(target=_run_upgrade, args=(launcher,), daemon=True)
        _thread.start()
    return status()


def _run_upgrade(launcher: str) -> None:
    """后台线程主体：先探网络，再执行 `hermes update` 并实时收集输出。

    线程内绝不抛异常出去 —— 任何失败都必须落成 FAILED + 可读原因，否则界面会
    永远停在「正在升级」上，用户只能重启软件。
    """
    try:
        if not check_github_reachable():
            _set(
                OFFLINE,
                "无法访问 GitHub，升级未开始。请先开启代理（VPN）后重试。",
            )
            return

        _set(UPGRADING, "正在升级 Hermes，请勿关闭 Trade…（可能需要几分钟）")
        proc = subprocess.Popen(
            [launcher, "update"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=_child_env(),
        )
        # 逐行读取以实时喂给界面：升级要建数百 MB 的托管环境，静默几分钟用户会以为卡死
        if proc.stdout is not None:
            for line in proc.stdout:
                stripped = line.rstrip()
                if stripped:
                    _append_log(stripped)
        returncode = proc.wait()

        if returncode == 0:
            _set(DONE, "Hermes 升级完成，正在重启 Trade…", returncode=0)
            _trigger_success_hook()
        else:
            _set(
                FAILED,
                f"Hermes 升级失败（退出码 {returncode}）。"
                "可在下方日志里看原因；重试前请确认网络通畅。",
                returncode=returncode,
            )
    except Exception as exc:  # noqa: BLE001 — 线程内任何异常都要落成可见状态
        _set(FAILED, f"升级过程出错：{exc}")


def _trigger_success_hook() -> None:
    """升级成功后延迟触发重启，留一点时间让界面把「完成」渲染出来再断连接。

    重启是必须的：Trade 进程内嵌 Hermes，只有新进程才会加载升级后的 Hermes，
    兼容判定也才会从「过旧」翻成可用。
    """
    hook = _success_hook
    # 没注入回调（如单测环境）就什么都不做，不要因此让升级被判定为失败
    if hook is None:
        return

    def _later() -> None:
        import time

        time.sleep(_RESTART_DELAY_SECONDS)
        try:
            hook()
        except Exception as exc:  # noqa: BLE001 — 重启失败只提示，不能再改变升级结果
            _append_log(f"[trade] 自动重启失败，请手动重启 Trade：{exc}")

    threading.Thread(target=_later, daemon=True).start()


def reset_for_tests() -> None:
    """重置状态机（仅测试用）。"""
    global _thread, _log_total
    with _lock:
        _logs.clear()
        _log_total = 0
        _thread = None
        _state.update({
            "status": IDLE, "message": "", "returncode": None,
            "started_at": None, "ended_at": None,
        })
