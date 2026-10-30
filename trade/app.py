"""
Trade AI Assistant — FastAPI application factory.

不依赖 Hermes 初始化副作用，可被 pytest 安全导入。
"""

import json
import os
import secrets
import shlex
import shutil
import subprocess as _sp
import sys
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ── Database initialization ──────────────────────────────────────────────────


def _init_db():
    """初始化/迁移数据库，返回数据库路径。"""
    from trade.database import init_db as _do_init
    return _do_init()


def _check_license():
    """检查许可证，返回 (ok, message)。"""
    from trade.license import check_license
    return check_license()


# ── Session token ────────────────────────────────────────────────────────────

_SESSION_TOKEN = secrets.token_urlsafe(32)
_STARTED_AT = time.time()  # 进程启动时间戳，供前端重启检测
# 重启 nonce：watchdog 用环境变量传给新进程，新进程经 /api/status 回传。
# 只认匹配的 nonce，与墙钟、旧进程是否存活都无关（比 started_at 可靠）。
_STARTUP_NONCE = os.environ.get("TRADE_RESTART_NONCE", "") or secrets.token_urlsafe(12)
# 本进程实际监听的端口（重启 watchdog 探活用）。由 main()/tradewin 在启动时写入。
_BOUND_PORT = 9119

# Hermes 后台升级成功后置 True：前端据此提示「重启 Trade 生效」。
_RESTART_REQUIRED = {"hermes": False}


def _mark_hermes_restart_required() -> None:
    _RESTART_REQUIRED["hermes"] = True

# 版本显示只认「正在运行的代码」—— 不再拿 GitHub release tag 做基准。
# 2026-10-26 用户决定：升级就是拉取 GitHub main 最新内容，release 版本号
# 会落后于 main（修完不立刻发版），拿它比较只会误导用户「已是最新」。


def _install_cors(app: FastAPI, port: int) -> None:
    """根据实际监听端口注册 CORS 中间件（仅本机）。"""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
        ],
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["X-Hermes-Session-Token", "X-Company-ID", "Content-Type"],
    )


# ── Hermes Gateway ────────────────────────────────────────────────────────────


def _gateway_running_via_hermes() -> bool | None:
    """用 Hermes 自己的严格探测判断 gateway 是否在跑（与 `hermes gateway status` 同源）。

    为什么不再用端口/进程名猜：
      - **端口 8642 不可靠**：0.22 起 api_server 未启用时该端口不监听 → 把已在跑的
        gateway 判成没跑（每次启动多余 spawn 一次，2026-10-21 实测）；
      - **`pgrep -f hermes.*gateway` 会假阳性**：`hermes gateway status` / dashboard
        这类兄弟命令的命令行也含 "hermes … gateway"，会被误判成 gateway 在跑，
        而真没跑时就会漏启动 → 定时任务静默不跑（更危险的方向）。
    上游 `hermes gateway status` 内部调用 `find_gateway_pids()`：PID 文件 + 服务管理器
    （launchd/systemd/SCM）+ 严格 argv 扫描，且排除当前调用链。Trade 直接复用同一
    判断（0.21.6 与 0.22.x 均提供该函数）。

    Returns:
        True/False 为权威结论；None 表示 Hermes 不可导入/探测异常 —— 调用方回退旧探测。
    """
    try:
        from hermes_cli.gateway import find_gateway_pids
    except Exception:
        return None
    try:
        return bool(find_gateway_pids())
    except Exception:
        return None


def _gateway_running_fallback() -> bool:
    """旧探测（仅在 Hermes 严格探测不可用时使用）。

    POSIX：`pgrep -f`（可能假阳性，见 `_gateway_running_via_hermes` 的说明）；
    Windows：TCP 8642（≤0.21.x 的 api_server 会监听该端口）。两者都只在导入失败时兜底。
    """
    try:
        if os.name == "nt":
            import socket as _sock
            s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
            try:
                s.settimeout(1)
                s.connect(("127.0.0.1", 8642))
                s.close()
                return True
            except OSError:
                return False
            finally:
                s.close()
        else:
            result = _sp.run(
                ["pgrep", "-f", "hermes.*gateway"],
                capture_output=True, text=True, timeout=3,
            )
            return result.returncode == 0 and bool(result.stdout.strip())
    except Exception:
        return False


def _is_gateway_running() -> bool:
    """检查 Hermes Gateway 是否在运行（跨平台）。

    首选 Hermes 的严格探测器（与 `hermes gateway status` 同源）；它不可用时回退旧探测。
    """
    hermes_result = _gateway_running_via_hermes()
    if hermes_result is not None:
        return hermes_result
    return _gateway_running_fallback()


def _find_hermes_binary(*, executable: str | None = None) -> str:
    """定位 hermes 可执行文件，**优先当前解释器所在目录（即 Trade 的 venv）**。

    为什么不能只查 PATH：Hermes 装在 Trade 自己的 venv 里，而
      - Windows 的计划任务、Linux 的 systemd user unit 都不带 venv 的 bin/Scripts
      - macOS 的 launchd plist 恰好显式设了 PATH（含 venv/bin），所以开发机正常

    于是只查 PATH 时 Windows/Linux 上 Gateway 永远起不来 → 定时任务静默失效，
    而 cron 界面照常列出任务、全部标"missed"，用户以为在跑。

    Args:
        executable: 解释器路径，默认 `sys.executable`。可注入以便测试 ——
                    直接改全局 `sys.executable` 会波及同进程的其它调用。
    """
    exe_dir = Path(executable or sys.executable).parent
    names = ("hermes.exe", "hermes.cmd", "hermes") if os.name == "nt" else ("hermes",)
    for name in names:
        candidate = exe_dir / name
        if candidate.is_file():
            return str(candidate)

    found = shutil.which("hermes")
    if found:
        return found

    # 兜底返回字面量而非 None：让 Popen 抛 FileNotFoundError 并在日志里可见，
    # 比返回 None 导致更难懂的 TypeError 好。
    return "hermes"


def _ensure_gateway_running() -> None:
    """如果 Gateway 未运行，启动它。Gateway 独立于 Trade 生命周期。"""
    if _is_gateway_running():
        print("  Hermes Gateway → running (cron scheduler active)")
        return

    try:
        hermes_bin = _find_hermes_binary()

        # 架构检测：Rosetta 下尝试使用原生 arm64 hermes 二进制
        import platform as _platform
        if _platform.system() == "Darwin" and _platform.machine() == "x86_64":
            import subprocess as _sp_arch
            try:
                _hw = _sp_arch.run(
                    ["uname", "-m"], capture_output=True, text=True, timeout=5
                ).stdout.strip()
                if _hw == "arm64":
                    for _candidate in (
                        "/opt/homebrew/bin/hermes",
                        "/opt/homebrew/opt/hermes-agent/bin/hermes",
                    ):
                        if os.path.isfile(_candidate):
                            hermes_bin = _candidate
                            print(f"  ✓ 检测到 Rosetta，使用原生 arm64 hermes: {_candidate}")
                            break
            except Exception:
                pass  # 架构检测失败不阻断 gateway 启动

        kwargs = {
            "stdout": _sp.DEVNULL,
            "stderr": _sp.DEVNULL,
        }
        if os.name == "nt":
            kwargs["creationflags"] = 0x00000200  # CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        _gateway_proc = _sp.Popen(
            [hermes_bin, "gateway", "run"],
            env={**os.environ},
            **kwargs,
        )
        # 记下 PID：重启时只杀我们启动的这个 gateway，不做命令行模式匹配
        try:
            _pid_file = _get_trade_data_dir() / "gateway.pid"
            _pid_file.parent.mkdir(parents=True, exist_ok=True)
            _pid_file.write_text(str(_gateway_proc.pid), encoding="utf-8")
        except OSError:
            pass
        print("  Hermes Gateway → started (cron scheduler active)")
    except Exception as e:
        print(f"  ⚠️  Hermes Gateway 启动失败: {e}")


def _get_trade_data_dir() -> Path:
    """返回 Trade 数据目录（跨平台），与 database._get_db_path 逻辑一致。"""
    trade_home = os.environ.get("TRADE_HOME", "").strip()
    if not trade_home:
        if os.name == "nt":
            _local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
            trade_home = str(Path(_local) / "trade")
        else:
            trade_home = str(Path.home() / ".trade")
    return Path(trade_home) / "data"


def _get_trade_home_path() -> Path:
    """返回 Trade 根目录（不带 /data 后缀），与 _get_trade_data_dir 逻辑一致。"""
    trade_home = os.environ.get("TRADE_HOME", "").strip()
    if not trade_home:
        if os.name == "nt":
            _local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
            trade_home = str(Path(_local) / "trade")
        else:
            trade_home = str(Path.home() / ".trade")
    return Path(trade_home)


def _client_is_loopback(request) -> bool:
    """判断请求是否来自本机回环地址。"""
    host = str(getattr(getattr(request, "client", None), "host", "") or "")
    return host in ("127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost")


def _remote_ui_allowed() -> bool:
    """是否显式允许向非本机客户端下发 token（局域网使用场景，默认关闭）。"""
    return os.environ.get("TRADE_ALLOW_REMOTE_UI", "").strip().lower() in ("1", "true", "yes")


def _client_may_receive_token(request) -> bool:
    """是否允许向该客户端下发 session token。

    session token 是唯一凭据，而 /trade 页面无需鉴权即可获取 ——
    若绑定 --host 0.0.0.0 时照常下发，局域网内任意主机 fetch 该页即可拿到
    token 并接管全部 API（包括 /system/update 这类系统端点）。
    默认只给本机回环客户端；确需局域网访问时用 TRADE_ALLOW_REMOTE_UI=1 显式开启。
    """
    return _remote_ui_allowed() or _client_is_loopback(request)


def _pyproject_path() -> Path | None:
    """定位与「当前运行代码」配套的 pyproject.toml。

    PyInstaller 打包后 pyproject.toml 在 _MEIPASS 下；开发/源码运行时在包的上一级目录。
    找不到时返回 None（打包场景可能没带此文件）。
    """
    _meipass = getattr(sys, "_MEIPASS", None)
    # 优先用打包目录里的副本，它与被冻结的代码版本一致
    if _meipass:
        _bundled = Path(_meipass) / "pyproject.toml"
        if _bundled.is_file():
            return _bundled
    _source = Path(__file__).resolve().parent.parent / "pyproject.toml"
    return _source if _source.is_file() else None


def _running_code_version() -> str:
    """返回当前进程正在运行的代码版本（读与运行代码配套的 pyproject.toml）。"""
    pyproject = _pyproject_path()
    if not pyproject:
        return ""
    try:
        try:
            import tomllib as _toml
        except ImportError:
            import tomli as _toml
        # 必须显式 utf-8：Windows 上默认用 cp1252 打开，而 pyproject.toml 含中文注释，
        # 不指定编码会抛 UnicodeDecodeError（被下面 except 吞掉，标记文件永远写不出来）
        return _toml.loads(pyproject.read_text(encoding="utf-8")).get("project", {}).get("version", "")
    except Exception:
        # 解析失败不应影响启动，降级为空串由调用方兜底
        return ""


def _write_version_marker() -> str:
    """把「当前进程运行的版本」写入 version.txt（进程启动时调用一次）。

    version.txt 的语义是「正在运行的代码版本」，所以只由启动流程写。
    /api/status 不再反写 —— 否则磁盘上刚 pull 下来的新版本会在没重启的情况下
    伪装成「已升级」，用户以为升级成功、实际仍跑旧代码。
    """
    version = _running_code_version()
    if not version:
        return ""
    try:
        data_dir = _get_trade_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "version.txt").write_text(version, encoding="utf-8")
    except Exception:
        pass  # 写标记失败不影响服务启动
    return version


def _resolve_reported_version() -> str:
    """/api/status 上报的版本号。

    以 version.txt（= 运行版本）为准；缺失时只读回退到 pyproject.toml，绝不写盘。
    """
    try:
        _vf = _get_trade_data_dir() / "version.txt"
        if _vf.is_file():
            _v = _vf.read_text(encoding="utf-8").strip()
            if _v:
                return _v
    except Exception:
        pass
    return _running_code_version() or "0.0.0"


def _kill_gateway() -> None:
    """终止 **Trade 自己启动的** Hermes Gateway（重启/升级时调用）。

    只认启动时记录的 PID（`~/.trade/data/gateway.pid`），不再用
    `pkill -f hermes.*gateway` —— 后者会误杀用户为其它用途独立跑的 gateway
    （审计 P2-31）。没有 PID 文件（gateway 不是我们启动的）就跳过，
    交给用户/新进程自行管理。失败静默：gateway 是独立进程，杀不掉不影响重启。
    """
    pid_file = _get_trade_data_dir() / "gateway.pid"
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return
    try:
        import psutil

        proc = psutil.Process(pid)
        cmdline = " ".join(proc.cmdline()).lower()
        if "hermes" not in cmdline or "gateway" not in cmdline:
            return  # PID 已被别的进程复用：绝不按 PID 盲杀
        proc.terminate()
    except Exception:
        pass
    finally:
        try:
            pid_file.unlink(missing_ok=True)
        except OSError:
            pass


_LAUNCHD_LABEL = "com.trade.assistant"


def _launchd_label_if_managed() -> str:
    """当前进程由 macOS launchd 的 KeepAlive 守护托管时返回 label，否则空串。

    为什么必须区分：KeepAlive 会在进程死掉时**立刻**补起一个并抢到端口，
    watchdog 再自己 spawn 就会绑不上端口、被判不健康，进而把代码回滚。
    托管场景下重启只能交给 `launchctl kickstart`。
    """
    if sys.platform != "darwin":
        return ""
    plist = Path.home() / "Library" / "LaunchAgents" / f"{_LAUNCHD_LABEL}.plist"
    if not plist.is_file():
        return ""
    try:
        # 用无参 `launchctl list`（制表符分列的 PID/状态/Label 表格）。
        # `launchctl list <label>` 在较新 macOS 上输出的是 plist 字典，解析不出 pid。
        r = _sp.run(
            ["launchctl", "list"], capture_output=True, text=True, timeout=10,
        )
    except (OSError, _sp.SubprocessError):
        return ""
    if r.returncode != 0:
        return ""
    for line in (r.stdout or "").splitlines():
        cols = line.split("\t")
        if len(cols) >= 3 and cols[-1].strip() == _LAUNCHD_LABEL:
            # 必须是我们自己这个 pid —— 否则是别处手动起的实例，走普通重启路径
            return _LAUNCHD_LABEL if cols[0].strip() == str(os.getpid()) else ""
    return ""


def _fix_restart_argv(argv: list[str], *, windows: bool | None = None) -> list[str]:
    """Windows：进程若是**用 trade.exe（console script）**起的，把 argv[0] 换成 server.py。

    为什么（客户机 2026-10-30 实测）：console script 启动时 sys.argv[0] 就是那个
    .exe 路径，于是重启命令被拼成「python.exe trade.exe --no-browser」——
    把可执行文件当脚本喂给 python，**必然起不来**，「重启」按钮因此也是坏的。

    POSIX 不受影响（覆盖运行中的脚本文件是允许的），所以只在 Windows 上改。
    纯函数，不碰进程状态，便于测试。

    windows 参数可注入：直接改 os.name 会连累 pathlib（Windows 上 Path() 抛
    NotImplementedError，把整个 pytest 进程搞崩）——这个坑在 win_setup.py 里
    已经踩过一次，所以这里用参数而不是 monkeypatch。
    """
    is_win = (os.name == "nt") if windows is None else windows
    if not is_win or not argv:
        return argv
    argv0 = Path(argv[0])
    if argv0.suffix.lower() not in (".exe", ".cmd", ".bat"):
        return argv
    server_py = Path(__file__).resolve().parent.parent / "server.py"
    if not server_py.is_file():
        return argv
    fixed = list(argv)
    fixed[0] = str(server_py)
    return fixed


def _perform_restart() -> None:
    """终止当前 Trade 进程并以独立子进程启动新实例。

    核心策略：不杀自己（不可靠——uvicorn graceful shutdown 可能卡住）。
    而是通过独立子进程去等待、杀旧、启新。

    只由 /system/restart 调用；/system/update 与 Hermes 升级成功都不再自动
    重启（用户手动确认）。

    刚更新过（存在 pending_update.json）时改走 `trade.restart_watchdog`：
    新进程探活失败会自动回退到 pre_update_sha 再拉起；普通重启走原脚本。
    """
    import sys as _sys

    # 架构检测：重启前尝试修正 Python 路径
    _restart_python = _sys.executable
    import platform as _platform
    if _platform.system() == "Darwin" and _platform.machine() == "x86_64":
        import subprocess as _sp_check
        try:
            _hw = _sp_check.run(
                ["uname", "-m"], capture_output=True, text=True, timeout=5
            ).stdout.strip()
            if _hw == "arm64":
                # 运行在 Rosetta 下，搜索原生 arm64 Python（与 install.sh 逻辑一致）
                for _candidate in (
                    "/opt/homebrew/bin/python3.13",
                    "/opt/homebrew/bin/python3.12",
                    "/opt/homebrew/bin/python3.11",
                    "/opt/homebrew/bin/python3",
                ):
                    if not os.path.isfile(_candidate):
                        continue
                    try:
                        _native_arch = _sp_check.run(
                            [_candidate, "-c", "import platform; print(platform.machine())"],
                            capture_output=True, text=True, timeout=5,
                        ).stdout.strip()
                    except Exception:
                        continue
                    if _native_arch == "arm64":
                        _restart_python = _candidate
                        print(f"  ✓ 检测到原生 arm64 Python: {_candidate}，重启将使用原生架构")
                        break
        except Exception:
            pass

    trade_data = _get_trade_data_dir()
    pid_file = trade_data / "trade.pid"
    old_pid = os.getpid()  # 直接用自己的 PID，不从文件读（更可靠）

    # 记录启动命令，交给 shell 子进程执行
    _restart_cmd = [_restart_python] + _fix_restart_argv(list(_sys.argv))
    # POSIX 走 sh：用 shlex.quote（repr 对含单引号的参数会生成 sh 无法解析的引法）
    _cmd_str = " ".join(shlex.quote(a) for a in _restart_cmd)
    # Windows 走 cmd，cmd 不认单引号：必须用 list2cmdline 生成双引号命令，
    # 否则旧进程已被 taskkill、新进程却起不来，服务彻底下线
    _cmd_str_win = _sp.list2cmdline(_restart_cmd)

    # 杀 Gateway
    _kill_gateway()

    # 刚更新过：交给 watchdog 探活，失败回退到升级前提交（P1-10 补偿）。
    pending_file = trade_data / "pending_update.json"
    pre_sha = ""
    try:
        _pending = json.loads(pending_file.read_text(encoding="utf-8"))
        pre_sha = str(_pending.get("pre_update_sha") or "").strip()
    except (OSError, ValueError):
        pre_sha = ""

    # 「刚更新过」或「launchd 托管」都交给 watchdog：
    # - 有 pre_sha：探活失败可回滚到升级前提交；
    # - 仅 launchd 托管：由 watchdog 校验 kickstart 退出码并事后探活 —— 本进程
    #   会被 launchd 杀掉，没法在进程内做检查。普通「杀旧 → exec 新」脚本在
    #   KeepAlive 下会与 launchd 抢端口，不能用于托管场景。
    _launchd_label = _launchd_label_if_managed()
    if pre_sha or _launchd_label:
        # 新进程用这个 nonce 回传身份；旧进程不会持有它 → 探活不会误判
        restart_nonce = secrets.token_urlsafe(12)
        try:
            _watchdog_cmd = [
                _restart_python, "-m", "trade.restart_watchdog",
                "--old-pid", str(old_pid),
                "--port", str(_BOUND_PORT),
                "--nonce", restart_nonce,
                "--repo", str(_trade_runtime_dir()),
                "--workdir", str(Path.cwd()),
                "--pending-file", str(pending_file),
                "--log", str(trade_data / "restart-watchdog.log"),
            ]
            if pre_sha:
                _watchdog_cmd += ["--pre-sha", pre_sha]
            # KeepAlive 托管时不能再自己 spawn（launchd 会抢先占端口）→ 交给 launchctl
            if _launchd_label:
                _watchdog_cmd += ["--launchd-label", _launchd_label]
            _watchdog_cmd += ["--", *_restart_cmd]
            _watchdog_kwargs = {
                "stdout": _sp.DEVNULL, "stderr": _sp.DEVNULL,
                "stdin": _sp.DEVNULL,
            }
            if os.name == "nt":
                _watchdog_kwargs["creationflags"] = 0x00000200
            else:
                _watchdog_kwargs["start_new_session"] = True
            _sp.Popen(_watchdog_cmd, **_watchdog_kwargs)
            _how = f"launchd={_launchd_label}" if _launchd_label else f"rollback={pre_sha[:8]}"
            print(f"  🔄 重启 watchdog 已调度 (old PID={old_pid}, {_how})")
            try:
                pid_file.unlink(missing_ok=True)
            except Exception:
                pass
            return
        except Exception as e:
            # watchdog 起不来不能挡住重启：退回原脚本，只是少了自动回退
            print(f"  ⚠ watchdog 启动失败（{e}），使用普通重启脚本")

    # 构建独立 shell 脚本：sleep 等响应发完 → kill 旧进程 → 启动新进程
    if os.name == "nt":
        _script = f'@echo off\r\ntimeout /t 3 /nobreak >nul\r\ntaskkill /PID {old_pid} /F\r\n{_cmd_str_win}'
        _sp.Popen(
            ["cmd", "/c", _script],
            stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
            creationflags=0x00000200,
        )
    else:
        _script = (
            f"sleep 2; "
            # gateway 已在 _kill_gateway() 里按记录的 PID 处理，这里不再做命令行模式匹配
            f"kill -TERM {old_pid} 2>/dev/null; "
            f"sleep 1; "
            f"kill -KILL {old_pid} 2>/dev/null; "
            f"sleep 0.5; "
            f"cd {repr(str(Path.cwd()))}; "
            f"exec {_cmd_str}"
        )
        _sp.Popen(
            ["/bin/sh", "-c", _script],
            stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
            start_new_session=True,
        )

    print(f"  🔄 重启子进程已调度 (old PID={old_pid})")

    # 主动删除 PID 文件，避免新进程读到旧 PID
    try:
        pid_file.unlink(missing_ok=True)
    except Exception:
        pass


# ── 运行环境重建（venv 的 Python 版本不对时）──────────────────────────────────
#
# 什么时候会用到：2026-10-14 之前装的机器，trade 的 venv 跑的是 Python 3.11~3.13，
# 而 Hermes 从 v0.21.6 起只发 3.14 的依赖集（见 COMPATIBILITY.md）。这类机器升级
# trade 之后必然进降级模式（agent 起不来），必须重建 venv 才能恢复。
#
# **为什么不放在 update_trade() 里顺带做**：重建要停机 5~10 分钟。用户点「系统更新」
# 时被顺带停掉一次服务，体验上等于「点了个按钮软件就没了」——必须让他先看到说明、
# 主动确认（界面上的「开始重建」按钮），这也是当初把「系统更新」按钮藏起来的同一个理由。
#
# **为什么必须交给独立子进程**：重建要替换 venv 目录，而当前进程的 sys.executable
# 就在那个 venv 里 —— 在原地重建等于把自己脚下的地板换掉。所以本进程只负责
# 「派一个不受自己存亡影响的子进程，然后退出」，重建与新服务的启动都归子进程。


def _trade_runtime_dir() -> Path:
    """运行时仓库目录（`~/.trade/foreign-trade-assistant`）。"""
    return _get_trade_home_path() / "foreign-trade-assistant"


def _venv_rebuild_script() -> tuple[list[str], str] | None:
    """构造重建用的独立子进程命令。返回 (argv, 说明) 或 None（平台未支持）。

    子进程做的事，顺序不能变：
      1. 等 2 秒 —— 让本次 HTTP 响应先发回浏览器（否则前端只看到连接被掐断）
      2. 杀掉当前 Trade 进程（腾出 venv 与端口）
      3. 跑安装脚本重建运行环境（脚本本身是原子的，失败会保留旧 venv）
      4. 无论成败都启动 Trade —— 失败了也要用旧环境把服务拉回来，
         否则用户面对的是一台彻底打不开的机器，比升级前还糟
    """
    trade_dir = _trade_runtime_dir()
    trade_home = _get_trade_home_path()
    log_dir = trade_home / "logs"
    log_file = log_dir / "rebuild-venv.log"

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None

    old_pid = os.getpid()

    if os.name == "nt":
        # Windows：安装脚本是 PowerShell，启动器是 install.ps1 生成的 trade.cmd。
        #
        # ⚠️ 这个路径必须与 install.ps1 的 `$LocalBin = "$env:LOCALAPPDATA\local\bin"`
        # 严格一致。2026-10-16 评审抓到过一次写错的后果：原来少了 `local\bin` 一层，
        # 于是重建**全部成功**、最后一步 `start` 却找不到文件 → 服务起不来、界面卡在
        # 「正在重建」直到 15 分钟超时 —— 比不重建还糟，因为用户以为在正常推进。
        # 回归测试：tests/test_venv_rebuild.py::TestWindowsLauncherPath。
        _local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        ps1 = trade_dir / "scripts" / "install.ps1"
        launcher = Path(_local) / "local" / "bin" / "trade.cmd"
        if not ps1.is_file():
            return None
        # 用 -ExecutionPolicy Bypass 是因为脚本来自用户自己的机器、且此前就是这么装的
        script = (
            f"@echo off\r\n"
            f"timeout /t 2 /nobreak >nul\r\n"
            f"taskkill /PID {old_pid} /F >nul 2>&1\r\n"
            f"echo [rebuild] start %DATE% %TIME%\r\n"
            f"powershell -NoProfile -ExecutionPolicy Bypass -File \"{ps1}\"\r\n"
            f"echo [rebuild] install exit=%ERRORLEVEL%\r\n"
            f"start \"\" \"{launcher}\" --no-browser\r\n"
        )
        return (["cmd", "/c", script], str(log_file))

    # POSIX：安装脚本是 install.sh，启动器是 ~/.local/bin/trade
    sh = trade_dir / "scripts" / "install.sh"
    launcher = Path.home() / ".local" / "bin" / "trade"
    if not sh.is_file():
        return None

    script = (
        f"sleep 2; "
        f"kill -TERM {old_pid} 2>/dev/null; sleep 1; kill -KILL {old_pid} 2>/dev/null; "
        f"echo \"[rebuild] 开始重建运行环境\"; "
        # 重建失败不阻止启动 —— 安装脚本是原子的，失败时旧 venv 原样可用
        f"if /bin/bash {sh!r}; then echo \"[rebuild] 重建成功\"; "
        f"else echo \"[rebuild] 重建失败（退出码 $?），将用原环境启动\"; fi; "
        f"echo \"[rebuild] 启动 Trade\"; "
        f"exec {launcher!r} --no-browser"
    )
    return (["/bin/sh", "-c", script], str(log_file))


def _schedule_venv_rebuild() -> bool:
    """派独立子进程执行重建。返回是否成功派发（不代表重建本身成功）。"""
    built = _venv_rebuild_script()
    if built is None:
        return False
    argv, log_file = built

    try:
        # 日志重定向到文件：服务停掉之后前端读不到任何东西，这份日志是事后唯一的线索
        with open(log_file, "ab") as fh:
            if os.name == "nt":
                _sp.Popen(
                    argv, stdout=fh, stderr=fh, stdin=_sp.DEVNULL,
                    creationflags=0x00000200,
                )
            else:
                _sp.Popen(
                    argv, stdout=fh, stderr=fh, stdin=_sp.DEVNULL,
                    start_new_session=True,   # 脱离本进程的会话，不受其退出影响
                )
    except Exception as exc:  # noqa: BLE001 — 派发失败要让调用方知道，不能静默
        print(f"  ✗ 重建子进程派发失败：{exc}")
        return False
    print(f"  🔧 运行环境重建已调度 (old PID={os.getpid()}, log={log_file})")
    return True


# ── System endpoints (无需 session token) ────────────────────────────────────


# ── 系统端点限流（5 req/min per token） ──────────────────────────────────
# 防止脚本循环触发 git pull + pip install 耗尽 GitHub API / pip 配额

_system_rate_lock = threading.Lock()
_system_rate_map: dict[str, list[float]] = {}
_SYS_WINDOW = 60  # 1 分钟窗口
_SYS_MAX = 5      # 最多 5 次
# SSE 进度流用更宽松的额度：它是长连接、且界面在重试/重连时会重新连。
# 真正消耗资源的是**触发升级的那个 POST**（会起探测线程 + git 子进程），
# 流本身只读进程内状态 —— 所以两边不该用同一个阈值。
_SYS_STREAM_MAX = 30

# 升级串行锁：界面上连点两下（或两个标签页）会并发跑 git pull / pip install，
# 撞 .git/index.lock、把依赖装坏。第二次点击直接告知「正在进行」，不再起第二份。
_update_lock = threading.Lock()


def _log_update_failure(message: str) -> None:
    """把升级失败的异常文本追加到 ~/.trade/logs/update.log（best-effort）。

    用户只会转述「更新失败」；没有这份日志，事后无法定位真实原因。
    """
    try:
        from trade.post_install.skills import _get_trade_home

        log_dir = _get_trade_home() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        with (log_dir / "update.log").open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {message}\n")
    except OSError:
        pass


def _check_system_rate_limit(
    key: str, *, max_hits: int = _SYS_MAX, window: float = _SYS_WINDOW
) -> bool:
    """系统端点限流：同一 key 在窗口内最多 max_hits 次。返回 True 表示放行。"""
    now = time.time()
    with _system_rate_lock:
        stamps = _system_rate_map.get(key, [])
        stamps = [t for t in stamps if now - t < window]
        if len(stamps) >= max_hits:
            _system_rate_map[key] = stamps
            return False
        stamps.append(now)
        _system_rate_map[key] = stamps
        return True


def _create_system_router() -> APIRouter:
    """创建系统管理路由（更新/备份/重启），需要 session token 认证。"""
    from fastapi import Request

    from trade.api.deps import require_session

    router = APIRouter(tags=["system"], dependencies=[Depends(require_session)])

    from pydantic import BaseModel

    class _UpdatePayload(BaseModel):
        # 前端预览接口返回、用户确认过的目标提交；缺省时后端临场取 main 头
        target_sha: str | None = None

    @router.get("/system/update-preview")
    def api_update_preview(request: Request):
        """返回本次更新将要钉选的远端 main 短 SHA（供确认框展示）。"""
        _tk = request.headers.get("X-Hermes-Session-Token", "")
        if _tk and not _check_system_rate_limit(_tk[:16]):
            from fastapi import HTTPException
            raise HTTPException(status_code=429, detail="系统端点请求过于频繁，请稍后重试。")

        from trade.post_install.update import preview_update_target
        return preview_update_target()

    @router.post("/system/update")
    def api_update_trade(request: Request, payload: _UpdatePayload | None = None):
        """一键更新 Trade 系统（只拉取 + 装依赖，不自动重启）。

        **不自动重启**：audit P1-10 的安全替代方案 —— 拉取完成即返回，由用户
        看到结果后自己点「重启」。这样新代码起不来时旧服务还在，不会把整台
        机器留在「升级后服务直接下线」的状态。
        返回 {"ok": bool, "version": str, "errors": list, "restart_scheduled": false}
        """
        _tk = request.headers.get("X-Hermes-Session-Token", "")
        if _tk and not _check_system_rate_limit(_tk[:16]):
            from fastapi import HTTPException
            raise HTTPException(status_code=429, detail="系统端点请求过于频繁，请稍后重试。")

        # 更新 = 拉代码 + 装依赖 + 重启，前端 confirm() 只是浏览器层，任何持 token
        # 的脚本都能直接 POST。要求一个显式确认头，与删除公司同一套防误触语义
        # （审计 P1-10）。
        if request.headers.get("X-Confirm-Update", "").lower() != "yes":
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail="更新需要确认：缺少 X-Confirm-Update: yes 请求头。",
            )

        from trade.post_install import update_trade as _do_update

        # 串行化：并发升级会互撞 git 锁 / 把依赖装坏。第二次点击直接返回提示，
        # 不排队、不重复跑（界面连点是常态，尤其是网络慢的时候）。
        if not _update_lock.acquire(blocking=False):
            return {
                "ok": False,
                "version": "",
                "target_sha": "",
                "error": "更新正在进行中，请等待完成后再试。",
                "errors": ["update already running"],
                "warnings": [],
                "messages": [],
                "restart_scheduled": False,
            }
        try:
            # 钉到用户在确认框里看到的那个提交（预览接口返回）；缺省时后端临场取 main
            result = _do_update(payload.target_sha if payload else None)
        except Exception as e:  # noqa: BLE001 — 绝不能把升级按钮变成 500
            # 未捕获异常会让前端只看到「请求失败 (500)」，用户只会说「更新失败」。
            # 转成结构化结果，把真实原因带到界面上。
            import traceback

            traceback.print_exc()
            _log_update_failure(str(e))
            result = {
                "ok": False, "version": "", "target_sha": "",
                "error": f"更新过程中出现异常：{e}",
                "errors": [str(e)], "warnings": [], "messages": [],
            }
        finally:
            _update_lock.release()

        # 只更新不重启：让用户在确认结果后自己点「重启」，避免新代码起不来
        # 时连旧服务也没了（audit P1-10 允许的替代方案）。
        result["restart_scheduled"] = False
        return result

    @router.post("/system/backup")
    def api_backup_trade(request: Request):
        """备份 Trade 数据为 tar.gz。"""
        _tk = request.headers.get("X-Hermes-Session-Token", "")
        if _tk and not _check_system_rate_limit(_tk[:16]):
            from fastapi import HTTPException
            raise HTTPException(status_code=429, detail="系统端点请求过于频繁，请稍后重试。")

        from trade.api.cron import _capture_output
        from trade.post_install import backup_trade as _do_backup
        return _capture_output(_do_backup)

    @router.post("/system/restart")
    def api_restart_trade(request: Request):
        """重启 Trade 服务（跨平台）。

        委托给 _perform_restart()：只签发重启脚本、不直接杀进程；脚本等旧进程
        释放端口后再起新进程，并与 Gateway 协同重启。
        """
        _tk = request.headers.get("X-Hermes-Session-Token", "")
        if _tk and not _check_system_rate_limit(_tk[:16]):
            from fastapi import HTTPException
            raise HTTPException(status_code=429, detail="系统端点请求过于频繁，请稍后重试。")

        _perform_restart()
        return {"ok": True, "message": "重启指令已发送"}

    # ── Hermes 共存 / 升级端点 ──────────────────────────────────────────────
    # 为什么放在系统路由：这些是「修好软件本身」的动作，不属于任何公司的业务数据，
    # 因此不需要 X-Company-ID，只需要 session token（与 update/restart 同级）。

    @router.get("/system/hermes-compat")
    def api_hermes_compat():
        """返回 Hermes 共存状态 + 升级进度（界面据此渲染面板）。"""
        from trade.bootstrap import hermes_compat_state, hermes_is_usable
        from trade.hermes_compat import compat_steps
        from trade.hermes_upgrade import status as upgrade_status

        state = hermes_compat_state()
        usable = hermes_is_usable()
        return {
            "usable": usable,
            "verdict": state.get("verdict"),
            "version": state.get("version"),
            "python": state.get("python"),
            "reason": state.get("reason"),
            # 补救方向：界面据此决定是显示「升级 Hermes」还是「重建 Trade 运行环境」。
            # 两种动作完全不同，给错会让用户白折腾。
            "fix": state.get("fix"),
            # 不可用时附带可照做的步骤（与终端提示共用同一份文案）
            "steps": [] if usable else compat_steps(state),
            "upgrade": upgrade_status(),
            # Hermes 升级成功但 Trade 还没重启：前端提示手动重启，不再自动重启
            "restart_required": _RESTART_REQUIRED["hermes"],
        }

    @router.post("/system/hermes-upgrade")
    def api_hermes_upgrade(request: Request):
        """触发（或重试）后台升级 Hermes；升级进行中重复调用为幂等。"""
        from trade.hermes_upgrade import start_upgrade

        _tk = request.headers.get("X-Hermes-Session-Token", "")
        if _tk and not _check_system_rate_limit(_tk[:16]):
            from fastapi import HTTPException
            raise HTTPException(status_code=429, detail="系统端点请求过于频繁，请稍后重试。")

        return start_upgrade()

    @router.post("/system/rebuild-venv")
    def api_rebuild_venv(request: Request):
        """一键重建 Trade 的运行环境（venv 的解释器不是 3.14 时）。

        为什么要有这个端点：这类机器（2026-10-14 前装的）升级 trade 后必然进降级
        模式，而旧界面给用户的是一行 `curl … | bash` 让他自己去终端粘 —— 客群是
        电脑小白，这一行就等于「软件坏了」。改成按钮后，用户只需点一次。

        返回 {"ok": bool, "message"/"error": str}。派发成功**不等于**重建成功：
        本进程马上就会退出，前端靠轮询 /api/status 判断是否恢复。
        """
        _tk = request.headers.get("X-Hermes-Session-Token", "")
        if _tk and not _check_system_rate_limit(_tk[:16]):
            from fastapi import HTTPException
            raise HTTPException(status_code=429, detail="系统端点请求过于频繁，请稍后重试。")

        # 只在确实需要重建时才动手。缺了这道闸，界面上的按钮一旦被误触（或前端状态
        # 过期），就会在健康的机器上白停 5~10 分钟服务。
        from trade.bootstrap import hermes_compat_state

        state = hermes_compat_state()
        if state.get("fix") != "rebuild_trade_venv":
            return {
                "ok": False,
                "error": "当前运行环境不需要重建。",
                "fix": state.get("fix"),
            }

        if not _schedule_venv_rebuild():
            return {
                "ok": False,
                "error": "重建子进程派发失败，请查看日志或联系技术支持。",
            }
        return {
            "ok": True,
            "message": "重建已开始，Trade 会在完成后自动恢复（约 5~10 分钟）。",
        }

    @router.get("/system/hermes-upgrade/stream")
    async def api_hermes_upgrade_stream(request: Request, offset: int = 0):
        """SSE：把升级状态与新增日志实时推给界面。

        为什么必须走 SSE：升级要建数百 MB 的托管环境、耗时以分钟计，而前端 `api()`
        有 120s 硬超时，普通请求必然超时；且用户需要看到「有在动」而不是一个转圈。
        """
        import asyncio
        import json

        # 流也要限流（额度比 POST 宽松）：长连接 + 界面重试时会重连，
        # 用 POST 那档 5/分钟会把正常重连也挡掉
        _tk = request.headers.get("X-Hermes-Session-Token", "")
        if _tk and not _check_system_rate_limit(_tk[:16], max_hits=_SYS_STREAM_MAX):
            from fastapi import HTTPException
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后重试。")

        from fastapi.responses import StreamingResponse

        from trade.hermes_upgrade import DONE, FAILED, OFFLINE
        from trade.hermes_upgrade import status as upgrade_status

        async def _events():
            cursor = max(0, offset)
            # 轮询式推流：升级状态是进程内变量，1 秒粒度足够，且天然处理断线重连
            while True:
                snap = upgrade_status(cursor)
                cursor = snap["log_cursor"]
                for line in snap["logs"]:
                    yield "data: " + json.dumps(
                        {"type": "log", "line": line}, ensure_ascii=False
                    ) + "\n\n"
                yield "data: " + json.dumps(
                    {
                        "type": "state",
                        "status": snap["status"],
                        "message": snap["message"],
                        "running": snap["running"],
                        "cursor": cursor,
                    },
                    ensure_ascii=False,
                ) + "\n\n"
                # 只有**终态**才收尾。不能写成 `if not running` —— IDLE（还没启动）
                # 的 running 也是 False，那样前端若在 start_upgrade() 之前连上来，
                # 会拿到一个空流就断开，之后再也收不到进度。
                if snap["status"] in (DONE, FAILED, OFFLINE):
                    break
                await asyncio.sleep(1.0)

        return StreamingResponse(_events(), media_type="text/event-stream")

    return router


# ── App factory ──────────────────────────────────────────────────────────────


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用。

    可在测试中导入以创建独立 app 实例。
    """
    app = FastAPI(title="Foreign Trade Assistant")

    # 数据库初始化
    _db_path = _init_db()
    print(f"  Database: {_db_path}")

    # 版本标记：记录「本进程实际运行的代码版本」，供 /api/status 上报。
    # 只在启动时写，升级流程不写 —— 这样没重启就一定显示旧版本（真话）。
    _running_version = _write_version_marker()
    if _running_version:
        print(f"  Version:  v{_running_version}")

    # 许可证检查：到期不影响服务启动（chat 端点在每次请求时校验），
    # 但打印醒目提示引导用户激活
    lic_ok, lic_msg = _check_license()
    if not lic_ok:
        print(f"\n  ⚠️  {lic_msg}")
        print("  Chat 接口已限制，请通过前端获取激活码。\n")

    # 注入 session token
    from trade.api.deps import set_session_token
    set_session_token(_SESSION_TOKEN)

    # 挂载 license 路由（路由自带 session 依赖：状态里含 expires_at/request_code）
    from trade.api.license import router as license_router
    app.include_router(license_router, prefix="/api/trade")

    # 挂载 system 路由（需要 session token）
    app.include_router(_create_system_router(), prefix="/api/trade")

    # 挂载 Trade API 路由
    from trade.api import router as trade_router
    app.include_router(trade_router, prefix="/api/trade")

    # ── 到期软着陆：只读浏览保留，业务写入被挡 ─────────────────────────────
    # 允许的写入：激活/许可证状态、系统维护（更新/重启/备份/skills）、切公司。
    # GET 一律放行 —— 历史、产品库、已生成草稿仍然可看。
    _READ_ONLY_EXEMPT_PREFIXES = (
        "/api/trade/license/",
        "/api/trade/system/",
    )

    def _write_allowed_when_read_only(path: str) -> bool:
        if path.startswith(_READ_ONLY_EXEMPT_PREFIXES):
            return True
        if path.endswith("/switch"):  # 切公司是 POST，但只影响浏览
            return True
        if path == "/api/trade/skills/update":  # 维护动作，不产生业务价值
            return True
        return False

    @app.middleware("http")
    async def _license_read_only_guard(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            path = request.url.path
            if path.startswith("/api/trade/") and not _write_allowed_when_read_only(path):
                from trade.license import license_state

                state, message = license_state()
                if state in ("expired", "tampered"):
                    return JSONResponse(
                        status_code=402,
                        content={"detail": message},
                    )
        return await call_next(request)

    # Health check
    @app.get("/api/status", include_in_schema=False)
    async def status():
        # 读取当前版本号：以 version.txt（= 启动时写入的运行版本）为准，只读不写。
        # 曾在此处把磁盘 pyproject.toml 的新版本号反写进 version.txt，导致
        # 「pull 成功但没重启」时 UI 显示新版本，把卡在旧版伪装成升级成功。
        version = _resolve_reported_version()

        # 不再请求 GitHub release：升级走 main 最新内容，release tag 只代表
        # 最近一次发版，拿它当"最新版本"会让用户错过 main 上的修复。
        # 上次自检结果（首次启动后台跑，结果落盘）。只读，不影响状态码 ——
        # 自检失败时 Trade 仍在运行，界面据此提示用户去修而不是把服务判死。
        try:
            from trade.doctor import load_doctor_result

            doctor_result = load_doctor_result()
        except Exception:
            doctor_result = None

        # 工具安全守卫是否真的会加载（插件未部署/未启用 = 整套守卫缺席）。
        # 只读检查，不打印；前端据此给用户可见告警。
        try:
            from trade.bootstrap import verify_tool_guard_ready

            tool_guard = verify_tool_guard_ready()
        except Exception:
            tool_guard = {"ok": False, "deployed": False, "enabled": False}

        return {
            "status": "ok",
            "app": "Foreign Trade Assistant",
            "version": version,
            "started_at": _STARTED_AT,
            "nonce": _STARTUP_NONCE,
            "doctor": doctor_result,
            "tool_guard": tool_guard,
        }

    return app


def serve_trade_chat(app: FastAPI) -> None:
    """注册 /trade SPA 路由（需要 app 实例和 _SESSION_TOKEN）。"""
    # 静态文件查找优先级：PyInstaller _MEIPASS > 运行时目录 > 开发目录
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        _STATIC_DIR = Path(sys._MEIPASS) / "static"
    else:
        # 运行时目录（~/.trade/foreign-trade-assistant/static/）
        _runtime_static = _get_trade_home_path() / "foreign-trade-assistant" / "static"
        if _runtime_static.is_dir():
            _STATIC_DIR = _runtime_static
        else:
            _STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
    _TRADE_CHAT_HTML = _STATIC_DIR / "trade_chat.html"

    # 托管 static/ 目录下的 CSS/JS 等静态资源
    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/trade", response_class=HTMLResponse, include_in_schema=False)
    async def trade_chat_ui(request: Request):
        """Serve the B2B chat interface with session token injected.

        非本机来源不下发 token（见 _client_may_receive_token）：token 是唯一凭据，
        而本页面无需鉴权即可获取它，绑定 0.0.0.0 时照常下发等于把 API 交给整个局域网。
        远程客户端会拿到一页说明，引导其改用本机地址访问。
        """
        if not _TRADE_CHAT_HTML.exists():
            return HTMLResponse(
                content='<html><body style="font-family:sans-serif;padding:2rem;"><h1>Trade chat UI not found</h1><p>The frontend file <code>static/trade_chat.html</code> is missing.</p></body></html>',
                status_code=404,
            )
        if not _client_may_receive_token(request):
            return HTMLResponse(
                content=(
                    '<html><body style="font-family:sans-serif;padding:2rem;max-width:40rem;">'
                    '<h1>请在本机浏览器中打开</h1>'
                    '<p>本服务只向本机（回环地址）浏览器下发会话凭据，'
                    '以免局域网内其它主机取得凭据后接管全部接口。</p>'
                    '<p>请在这台机器上访问 <code>http://127.0.0.1:{port}/trade</code>。</p>'
                    '<p style="color:#666;font-size:0.9rem;">确需局域网访问时，'
                    '可在启动前设置环境变量 <code>TRADE_ALLOW_REMOTE_UI=1</code>（会降低安全性）。</p>'
                    '</body></html>'
                ).replace("{port}", str(getattr(request.url, "port", "") or "")),
                status_code=403,
            )
        html = _TRADE_CHAT_HTML.read_text(encoding="utf-8")
        html = html.replace("__TRADE_SESSION_TOKEN__", _SESSION_TOKEN)
        return HTMLResponse(content=html)


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    """`trade` console script 入口 + `python server.py` 入口。"""
    import argparse

    parser = argparse.ArgumentParser(description="Foreign Trade Assistant")
    parser.add_argument("--port", type=int, default=9119)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-gateway", action="store_true", help="不检查/启动 Hermes Gateway")
    args = parser.parse_args()

    # 写入 PID 文件（0600 权限防止被其他用户篡改）
    import atexit
    pid_dir = _get_trade_data_dir()
    pid_dir.mkdir(parents=True, exist_ok=True)
    pid_file = pid_dir / "trade.pid"
    pid_file.write_text(str(os.getpid()))
    if os.name != "nt":
        pid_file.chmod(0o600)
    atexit.register(lambda: pid_file.unlink(missing_ok=True))

    app = create_app()
    serve_trade_chat(app)
    _install_cors(app, args.port)

    # 降级模式（Hermes 不可用）不拉 Gateway：旧 Hermes 在当前 Python 上根本起不来，
    # 拉起来也是立刻死，还会在日志里刷错误让用户以为 Trade 坏了
    from trade.bootstrap import hermes_is_usable
    if not args.no_gateway and hermes_is_usable():
        _ensure_gateway_running()

    # Hermes 升级成功不再自动重启（与 Trade 自身更新统一为手动重启）。
    # 回调只置标记，前端从 /system/hermes-compat 读 restart_required 后提示用户。
    from trade.hermes_upgrade import set_success_hook
    set_success_hook(_mark_hermes_restart_required)

    # 后台静默从 GitHub 同步 skills，不阻塞服务启动
    from trade.bootstrap import background_github_skills_sync
    background_github_skills_sync()

    url = f"http://{args.host}:{args.port}/trade"
    print(f"\n  Foreign Trade Assistant → {url}")
    # 只说明"已生成"，不打印任何片段：日志会被转发/截图，凭据片段不该出现在里面
    print("  Session token 已生成（已注入 API 页面）")
    print()

    if not args.no_browser:
        import threading
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    # 记录实际端口：重启 watchdog 需要知道自己该探哪个端口
    global _BOUND_PORT
    _BOUND_PORT = args.port

    # 重启场景：旧进程可能仍在占用端口，uvicorn 内部将端口冲突转成 sys.exit(1)
    # 而非抛出 OSError，因此还需捕获 SystemExit。最多等 10 秒。
    import time as _time
    for _attempt in range(20):
        try:
            uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
            break
        except (OSError, SystemExit) as _e:
            # 端口冲突：OSError errno 48 或 SystemExit（uvicorn 内部 sys.exit(1)）
            _is_port_conflict = (
                (isinstance(_e, OSError) and ("Address already in use" in str(_e) or getattr(_e, 'errno', None) == 48))
                or isinstance(_e, SystemExit)
            )
            if _is_port_conflict:
                if _attempt == 0:
                    print("  ⏳ 等待旧进程释放端口...")
                elif _attempt % 4 == 0:
                    print(f"     (已等待 {_attempt * 0.5:.0f}s)")
                _time.sleep(0.5)
                continue
            raise
