"""
Trade AI Assistant — FastAPI application factory.

不依赖 Hermes 初始化副作用，可被 pytest 安全导入。
"""

import os
import secrets
import subprocess as _sp
import sys
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
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

# ── GitHub latest-version 缓存（TTL 10 分钟）──────────────────────────────
# 避免 /api/status 每次请求都调 GitHub API，在 _waitForRestartAndReload
# 轮询期间（最多 90 次 × 2s = 3min）触发 API 限流（60 次/小时）。
_latest_version_cache: dict = {"value": None, "ts": 0.0}
_LATEST_VERSION_TTL = 600  # 10 分钟


def _ver_tuple(s: str) -> tuple:
    """把 '0.6.8' / 'v0.6.8' / '0.6.8-rc1' 解析为可比较的整数元组。"""
    parts = []
    for p in s.lstrip("vV").replace("-", ".").split("."):
        try:
            parts.append(int(p))
        except ValueError:
            break
    return tuple(parts)


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


def _is_gateway_running() -> bool:
    """检查是否有 Hermes Gateway 进程在运行（跨平台）。"""
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


def _ensure_gateway_running() -> None:
    """如果 Gateway 未运行，启动它。Gateway 独立于 Trade 生命周期。"""
    if _is_gateway_running():
        print("  Hermes Gateway → running (cron scheduler active)")
        return

    try:
        import shutil
        hermes_bin = shutil.which("hermes") or "hermes"

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

        _sp.Popen(
            [hermes_bin, "gateway", "run"],
            env={**os.environ},
            **kwargs,
        )
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
    """终止当前 Hermes Gateway 进程（升级/重启时调用，新进程会重启它）。

    跨平台：Unix 用 pgrep+SIGTERM，Windows 用 taskkill 按命令行匹配。
    失败静默——Gateway 是独立进程，杀不掉也不影响主服务重启。
    """
    try:
        if os.name == "nt":
            # Windows: taskkill 不直接支持命令行匹配，回退到通过端口找进程
            # （需 psutil；没有就跳过——下次启动时新 Trade 启动会判端口已占用而跳过启动新 Gateway）
            try:
                import psutil
                for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                    try:
                        cmdline = " ".join(proc.info.get("cmdline") or [])
                        if "hermes" in cmdline.lower() and "gateway" in cmdline.lower():
                            proc.terminate()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            except ImportError:
                pass
        else:
            _sp.run(
                ["pkill", "-TERM", "-f", "hermes.*gateway"],
                capture_output=True, timeout=5,
            )
    except Exception:
        # 杀 Gateway 失败不阻塞主流程
        pass


def _perform_restart() -> None:
    """终止当前 Trade 进程并以独立子进程启动新实例。

    核心策略：不杀自己（不可靠——uvicorn graceful shutdown 可能卡住）。
    而是通过独立 shell 子进程去等待、杀旧、启新。

    供 /system/restart 和 /system/update (via BackgroundTasks) 调用。
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
    _restart_cmd = [_restart_python] + _sys.argv
    # POSIX 走 sh，repr() 产生的单引号是合法引法
    _cmd_str = " ".join(repr(a) for a in _restart_cmd)
    # Windows 走 cmd，cmd 不认单引号：必须用 list2cmdline 生成双引号命令，
    # 否则旧进程已被 taskkill、新进程却起不来，服务彻底下线
    _cmd_str_win = _sp.list2cmdline(_restart_cmd)

    # 杀 Gateway
    _kill_gateway()

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
            f"pkill -TERM -f 'hermes.*gateway' 2>/dev/null; "
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


# ── System endpoints (无需 session token) ────────────────────────────────────


# ── 系统端点限流（5 req/min per token） ──────────────────────────────────
# 防止脚本循环触发 git pull + pip install 耗尽 GitHub API / pip 配额

_system_rate_lock = threading.Lock()
_system_rate_map: dict[str, list[float]] = {}
_SYS_WINDOW = 60  # 1 分钟窗口
_SYS_MAX = 5      # 最多 5 次


def _check_system_rate_limit(key: str) -> bool:
    """系统端点限流：同一 key 每分钟最多 _SYS_MAX 次。返回 True 表示放行。"""
    now = time.time()
    with _system_rate_lock:
        stamps = _system_rate_map.get(key, [])
        stamps = [t for t in stamps if now - t < _SYS_WINDOW]
        if len(stamps) >= _SYS_MAX:
            _system_rate_map[key] = stamps
            return False
        stamps.append(now)
        _system_rate_map[key] = stamps
        return True


def _create_system_router() -> APIRouter:
    """创建系统管理路由（更新/备份/重启），需要 session token 认证。"""
    from fastapi import BackgroundTasks, Request

    from trade.api.deps import require_session

    router = APIRouter(tags=["system"], dependencies=[Depends(require_session)])

    @router.post("/system/update")
    def api_update_trade(background_tasks: BackgroundTasks, request: Request):
        """一键更新 Trade 系统。

        升级成功后通过 BackgroundTasks 调度全量重启。
        返回 {"ok": bool, "version": str, "errors": list, "restart_scheduled": bool}
        """
        _tk = request.headers.get("X-Hermes-Session-Token", "")
        if _tk and not _check_system_rate_limit(_tk[:16]):
            from fastapi import HTTPException
            raise HTTPException(status_code=429, detail="系统端点请求过于频繁，请稍后重试。")

        from trade.post_install import update_trade as _do_update
        result = _do_update()  # 现在返回结构化 dict，不再依赖 _capture_output

        if result["ok"]:
            _latest_version_cache["ts"] = 0.0  # 强制重新拉取 GitHub latest
            background_tasks.add_task(_perform_restart)
            result["restart_scheduled"] = True
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

        委托给 _perform_restart()——含三层 PID 安全校验和 Gateway 协同重启。
        """
        _tk = request.headers.get("X-Hermes-Session-Token", "")
        if _tk and not _check_system_rate_limit(_tk[:16]):
            from fastapi import HTTPException
            raise HTTPException(status_code=429, detail="系统端点请求过于频繁，请稍后重试。")

        # 清缓存：用户可能手动 git pull 后只 restart，避免重启后 latest_version 显示旧值
        _latest_version_cache["ts"] = 0.0
        _perform_restart()
        return {"ok": True, "message": "重启指令已发送"}

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

    # 挂载 license 路由（无需 session token）
    from trade.api.license import router as license_router
    app.include_router(license_router, prefix="/api/trade")

    # 挂载 system 路由（需要 session token）
    app.include_router(_create_system_router(), prefix="/api/trade")

    # 挂载 Trade API 路由
    from trade.api import router as trade_router
    app.include_router(trade_router, prefix="/api/trade")

    # Health check
    @app.get("/api/status", include_in_schema=False)
    async def status():
        # 读取当前版本号：以 version.txt（= 启动时写入的运行版本）为准，只读不写。
        # 曾在此处把磁盘 pyproject.toml 的新版本号反写进 version.txt，导致
        # 「pull 成功但没重启」时 UI 显示新版本，把卡在旧版伪装成升级成功。
        version = _resolve_reported_version()

        # 用缓存降低 GitHub API 调用频率，防止限流导致版本检测失效
        _now = time.monotonic()
        if (_latest_version_cache["value"] is not None
                and _now - _latest_version_cache["ts"] < _LATEST_VERSION_TTL):
            latest = _latest_version_cache["value"]
        else:
            import asyncio as _asyncio

            def _fetch_latest_version() -> str:
                import urllib.request as _ur
                try:
                    _req = _ur.Request(
                        "https://api.github.com/repos/chefroger/smart-trade-ai/releases/latest",
                        headers={"Accept": "application/vnd.github+json", "User-Agent": "Trade-Status/1.0"},
                    )
                    with _ur.urlopen(_req, timeout=5) as _resp:
                        import json as _json
                        _data = _json.loads(_resp.read().decode())
                        return _data.get("tag_name", "").lstrip("v")
                except Exception:
                    return ""

            latest = await _asyncio.get_event_loop().run_in_executor(None, _fetch_latest_version)
            # 仅在 GitHub API 调用成功时更新缓存（失败时 keep 旧值，宁可短暂不一致）
            if latest:
                _latest_version_cache["value"] = latest
                _latest_version_cache["ts"] = time.monotonic()

            # 本地版本已领先于 GitHub release 时不显示"有新版"
            if latest and _ver_tuple(latest) <= _ver_tuple(version):
                latest = None

        return {
            "status": "ok",
            "app": "Foreign Trade Assistant",
            "version": version,
            "latest_version": latest or None,
            "started_at": _STARTED_AT,
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

    if not args.no_gateway:
        _ensure_gateway_running()

    # 后台静默从 GitHub 同步 skills，不阻塞服务启动
    from trade.bootstrap import background_github_skills_sync
    background_github_skills_sync()

    url = f"http://{args.host}:{args.port}/trade"
    print(f"\n  Foreign Trade Assistant → {url}")
    print(f"  Session token: {_SESSION_TOKEN[:8]}...（完整 token 已注入 API 页面）")
    print()

    if not args.no_browser:
        import threading
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

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
