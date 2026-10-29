"""重启 watchdog：拉起新进程、探活，失败自动回退到升级前的提交。

为什么必须独立进程：`/system/restart` 的旧进程会被杀掉，如果新代码起不来，
进程内没有任何代码还能执行回退。本模块由旧进程派生成独立会话，只依赖标准库，
即使 trade 包本身坏了也能跑。

失败回退只针对「刚更新过」的情形（存在 pending_update.json + pre_update_sha）；
普通重启没有可回退点，只做探活与日志。
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

_APP_NAME = "Foreign Trade Assistant"


def _log(path: Path, message: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass


def _proc_create_time(pid: int) -> float | None:
    """读取进程创建时间（防 PID 复用）；psutil 不可用时返回 None。"""
    try:
        import psutil

        return float(psutil.Process(pid).create_time())
    except Exception:
        return None


def _kill(
    pid: int, expected_create_time: float | None = None,
    log_path: Path | None = None,
) -> None:
    """尽力终止进程；PID 已被复用（创建时间不符）时拒绝盲杀。

    取不到创建时间（psutil 缺失）时无法证明身份，仍按原样终止（否则旧进程
    占着端口、新进程起不来），但必须在 watchdog 日志里留一行，事后可追溯。
    """
    if expected_create_time is not None:
        current = _proc_create_time(pid)
        if current is None or abs(current - expected_create_time) > 1.0:
            return
    elif log_path is not None:
        _log(
            log_path,
            f"pid {pid}: create_time unavailable (psutil missing) — "
            "identity unverified, killing anyway",
        )
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True, timeout=20,
            )
            return
        os.kill(pid, signal.SIGTERM)
        for _ in range(10):
            time.sleep(0.3)
            try:
                os.kill(pid, 0)
            except OSError:
                return
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return


def _spawn(
    command: list[str], workdir: str, nonce: str = "",
) -> subprocess.Popen:
    env = dict(os.environ)
    if nonce:
        env["TRADE_RESTART_NONCE"] = nonce
    kwargs: dict = {
        "cwd": workdir,
        "env": env,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000200  # CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, **kwargs)


def _healthy(port: int, expected_nonce: str, min_started_at: float = 0.0) -> bool:
    """服务是否健康，且**确实是本次重启新起的进程**。

    只认 app 名会把"旧进程没杀掉"误判成新进程健康，从而删掉 pending、
    丢掉回退点。两条判据，按可用性择一：

    - nonce（首选）：新进程带着 watchdog 传入的 nonce 启动并经 /api/status
      回传；nonce 不匹配 = 不是我们要等的那一个进程。
    - started_at（回退用）：**回退到升级前代码**时，那份代码可能还不认识
      nonce，只能要求它的启动时间晚于本次回退的拉起时刻。

    两者都缺失 → fail-closed（无 nonce 且无时间下界时不判健康）。
    """
    if not expected_nonce and min_started_at <= 0:
        return False
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/status", timeout=2,
        ) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return False
    if data.get("app") != _APP_NAME:
        return False
    if expected_nonce and data.get("nonce") == expected_nonce:
        return True
    if min_started_at > 0:
        try:
            started_at = float(data.get("started_at") or 0)
        except (TypeError, ValueError):
            return False
        return started_at > min_started_at
    return False


def _wait_healthy(
    port: int, timeout: float, nonce: str,
    proc: subprocess.Popen | None = None,
    min_started_at: float = 0.0,
) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _healthy(port, nonce, min_started_at):
            return True
        # 新进程已退出（端口冲突/启动崩溃）→ 不必等到超时
        if proc is not None and proc.poll() is not None:
            return False
        time.sleep(2)
    return False


def _kickstart(label: str, log_path: Path) -> bool:
    """通过 launchd 重启服务（-k = 先杀旧再起新），替代 kill + 自己 spawn。

    为什么必须走 launchd：安装脚本给 macOS 建的守护带 KeepAlive=true，
    我们一杀旧进程，launchd 立刻补起一个并抢到端口 → watchdog 自己 spawn
    的进程永远绑不上、被判不健康、进而回滚代码。交给 launchd 起就不会有
    两个实例抢同一个端口。
    """
    uid = os.getuid() if hasattr(os, "getuid") else ""
    target = f"gui/{uid}/{label}"
    try:
        r = subprocess.run(
            ["launchctl", "kickstart", "-k", target],
            capture_output=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as e:
        _log(log_path, f"launchctl kickstart failed: {e!r}")
        return False
    if r.returncode != 0:
        err = (r.stderr or b"").decode("utf-8", "replace").strip()[:300]
        _log(log_path, f"launchctl kickstart rc={r.returncode}: {err}")
        return False
    return True


def _clear_pending(pending_file: str) -> None:
    """探活成功后删掉「待重启」现场。"""
    if not pending_file:
        return
    try:
        Path(pending_file).unlink(missing_ok=True)
    except OSError:
        pass


def _run_launchd(args, log_path: Path) -> int:
    """launchd 托管时的重启路径：kickstart + 启动时间判定健康。

    不能用 nonce：launchd 按 plist 的环境变量启动，注入不了本轮 nonce。
    用「启动时间晚于本次 kickstart 时刻」证明是刚起的进程即可 —— 没被杀掉的
    旧进程启动时间必然更早。
    """
    label = args.launchd_label
    time.sleep(2)  # 先让 /system/restart 的 HTTP 响应发出去
    started = time.time()
    if not _kickstart(label, log_path):
        _log(log_path, "kickstart failed; leaving service as-is")
        return 1
    _log(log_path, f"kickstarted {label}")
    if _wait_healthy(args.port, args.timeout, "", None, min_started_at=started - 5):
        _log(log_path, "launchd-restarted process healthy")
        _clear_pending(args.pending_file)
        return 0

    _log(log_path, "launchd-restarted process did not become healthy")
    if not args.pre_sha or not args.repo:
        _log(log_path, "no pre-update commit; leaving service as-is")
        return 1
    if not _rollback(args.repo, args.pre_sha, log_path):
        _log(log_path, "rollback unsuccessful; leaving service as-is")
        return 1

    started2 = time.time()
    if not _kickstart(label, log_path):
        return 1
    if _wait_healthy(args.port, args.timeout, "", None, min_started_at=started2 - 5):
        _log(log_path, "rolled-back launchd process healthy")
        _clear_pending(args.pending_file)
        return 2
    _log(log_path, "rolled-back launchd process also unhealthy")
    return 1


def _rollback(repo: str, pre_sha: str, log_path: Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "-C", repo, "reset", "--keep", pre_sha],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as e:
        _log(log_path, f"rollback failed: {e}")
        return False
    if r.returncode == 0:
        _log(log_path, f"rolled back to {pre_sha[:8]}")
        return True
    _log(log_path, f"rollback failed: {(r.stderr or r.stdout).strip()[:300]}")
    return False


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Trade restart watchdog")
    p.add_argument("--old-pid", type=int, required=True)
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--pre-sha", default="")
    p.add_argument("--repo", default="")
    p.add_argument("--workdir", required=True)
    p.add_argument("--pending-file", default="")
    # --nonce 由新版调用方传入；**升级前的旧进程**只会传 --old-started-at，
    # 磁盘上的本模块却已是新版 —— 所以不能把任何一项设成 required，
    # 且必须容忍未知参数：否则旧进程一调 watchdog 就 argparse 报错退出，
    # 既不杀旧进程也不起新进程，用户点了「重启」服务静默不动。
    p.add_argument("--nonce", default="")
    p.add_argument("--old-started-at", type=float, default=0.0)
    # 由 launchd 托管时（macOS KeepAlive 守护）必须交给 launchctl 重启
    p.add_argument("--launchd-label", default="")
    p.add_argument("--log", required=True)
    p.add_argument("--timeout", type=float, default=90.0)
    p.add_argument("command", nargs=argparse.REMAINDER)
    args, _unknown = p.parse_known_args(argv)

    cmd = args.command
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        return 1

    log_path = Path(args.log)
    _log(log_path, f"watchdog start (old pid={args.old_pid}, port={args.port})")

    # launchd 托管：由 launchctl 负责杀旧+起新，我们只负责探活与回滚
    if args.launchd_label:
        _log(log_path, f"launchd-managed: {args.launchd_label}")
        return _run_launchd(args, log_path)

    # 旧版调用方没传 nonce：本进程自己生成一个注入给新进程。
    # 新进程是刚拉下来的新代码（认 TRADE_RESTART_NONCE），探活照样能精确判定。
    nonce = args.nonce or secrets.token_urlsafe(12)

    old_create = _proc_create_time(args.old_pid)
    time.sleep(2)
    _kill(args.old_pid, old_create, log_path)
    time.sleep(0.5)
    try:
        proc = _spawn(cmd, args.workdir, nonce)
    except Exception as e:  # noqa: BLE001 — 旧进程已死，必须留日志/pending
        _log(log_path, f"spawn failed: {e!r}; pending kept for manual recovery")
        return 1
    _log(log_path, f"new process pid={proc.pid}")

    if _wait_healthy(args.port, args.timeout, nonce, proc):
        _log(log_path, "new process healthy")
        if args.pending_file:
            try:
                Path(args.pending_file).unlink(missing_ok=True)
            except OSError:
                pass
        return 0

    _log(log_path, "new process did not become healthy")
    _kill(proc.pid)

    if not args.pre_sha or not args.repo:
        _log(log_path, "no pre-update commit; leaving service stopped")
        return 1

    if not _rollback(args.repo, args.pre_sha, log_path):
        _log(log_path, "rollback unsuccessful; leaving service stopped")
        return 1

    # 回退后跑的是 pre_sha 的代码，可能还不认识 nonce —— 探活须同时接受
    # 「nonce 匹配」或「启动时间晚于此刻」，否则会把已恢复的服务误判成失败。
    rollback_baseline = time.time()
    try:
        proc2 = _spawn(cmd, args.workdir, nonce)
    except Exception as e:  # noqa: BLE001 — 回退进程也起不来时保留 pending
        _log(log_path, f"rollback spawn failed: {e!r}; pending kept")
        return 1
    _log(log_path, f"rolled-back process pid={proc2.pid}")
    if _wait_healthy(
        args.port, args.timeout, nonce, proc2,
        min_started_at=rollback_baseline - 5,
    ):
        _log(log_path, "rolled-back process healthy")
        if args.pending_file:
            try:
                Path(args.pending_file).unlink(missing_ok=True)
            except OSError:
                pass
        return 2

    _log(log_path, "rolled-back process also unhealthy")
    return 1


if __name__ == "__main__":
    sys.exit(main())
