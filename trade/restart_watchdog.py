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


def _kill(pid: int, expected_create_time: float | None = None) -> None:
    """尽力终止进程；PID 已被复用（创建时间不符）时拒绝盲杀。"""
    if expected_create_time is not None:
        current = _proc_create_time(pid)
        if current is None or abs(current - expected_create_time) > 1.0:
            return
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


def _healthy(port: int, expected_nonce: str) -> bool:
    """服务是否健康，且**确实是本次重启新起的进程**。

    只认 app 名会把"旧进程没杀掉"误判成新进程健康，从而删掉 pending、
    丢掉回退点。新进程会带着 watchdog 传入的 nonce 启动并经 /api/status
    回传；nonce 不匹配（含空值）= 不是我们要等的那一个进程。
    """
    if not expected_nonce:
        return False  # 无 nonce 一律不判健康（fail-closed）
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/status", timeout=2,
        ) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
            return (
                data.get("app") == _APP_NAME
                and data.get("nonce") == expected_nonce
            )
    except Exception:
        return False


def _wait_healthy(
    port: int, timeout: float, nonce: str,
    proc: subprocess.Popen | None = None,
) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _healthy(port, nonce):
            return True
        # 新进程已退出（端口冲突/启动崩溃）→ 不必等到超时
        if proc is not None and proc.poll() is not None:
            return False
        time.sleep(2)
    return False


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
    p.add_argument("--nonce", required=True)
    p.add_argument("--log", required=True)
    p.add_argument("--timeout", type=float, default=90.0)
    p.add_argument("command", nargs=argparse.REMAINDER)
    args = p.parse_args(argv)

    cmd = args.command
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        return 1

    log_path = Path(args.log)
    _log(log_path, f"watchdog start (old pid={args.old_pid}, port={args.port})")

    old_create = _proc_create_time(args.old_pid)
    time.sleep(2)
    _kill(args.old_pid, old_create)
    time.sleep(0.5)
    try:
        proc = _spawn(cmd, args.workdir, args.nonce)
    except Exception as e:  # noqa: BLE001 — 旧进程已死，必须留日志/pending
        _log(log_path, f"spawn failed: {e!r}; pending kept for manual recovery")
        return 1
    _log(log_path, f"new process pid={proc.pid}")

    if _wait_healthy(args.port, args.timeout, args.nonce, proc):
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

    try:
        proc2 = _spawn(cmd, args.workdir, args.nonce)
    except Exception as e:  # noqa: BLE001 — 回退进程也起不来时保留 pending
        _log(log_path, f"rollback spawn failed: {e!r}; pending kept")
        return 1
    _log(log_path, f"rolled-back process pid={proc2.pid}")
    if _wait_healthy(args.port, args.timeout, args.nonce, proc2):
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
