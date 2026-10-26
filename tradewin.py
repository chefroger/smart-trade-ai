"""
TradeWin — 独立桌面应用入口 (Windows/macOS)。

双击 tradewin.exe 或 python tradewin.py 启动：
  FastAPI 后端在后台线程运行 → WebView 窗口加载 trade_chat.html。
不依赖外部浏览器。

单实例（审计 P2-21）：用 OS 文件锁保证只跑一个后端；第二个实例只打开已有
窗口，不再因端口冲突报"服务起不来"。首选端口被别的程序占用时自动顺延。
"""

import json
import multiprocessing
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

PREFERRED_PORT = 9119
_PORT_TRIES = 10

# 持有文件锁的句柄：必须活到进程退出，不能是局部变量
_LOCK_HANDLE = None


def _acquire_single_instance(lock_path: Path) -> bool:
    """尝试独占锁文件；成功返回 True（锁句柄常驻进程）。"""
    global _LOCK_HANDLE
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False
    _LOCK_HANDLE = handle
    return True


def _port_file(lock_path: Path) -> Path:
    """端口信息单独存一个文件。

    不能写进锁文件：Windows 的 msvcrt.locking 锁住的是字节区间，向被锁区域
    写入会失败（实测导致端口永远读不到）。
    """
    return lock_path.with_name(lock_path.stem + ".port")


def _write_lock_port(lock_path: Path, port: int) -> None:
    if _LOCK_HANDLE is None:
        return
    try:
        _port_file(lock_path).write_text(
            f"{os.getpid()} {port}\n", encoding="utf-8",
        )
    except OSError:
        pass


def _read_lock_port(lock_path: Path) -> int | None:
    try:
        parts = _port_file(lock_path).read_text(encoding="utf-8").split()
        return int(parts[1]) if len(parts) >= 2 else None
    except (OSError, ValueError, IndexError):
        return None


def _pick_free_port(host: str = "127.0.0.1", preferred: int = PREFERRED_PORT,
                    tries: int = _PORT_TRIES) -> int | None:
    """从 preferred 起找一个可绑定的端口；都不行返回 None。"""
    for port in range(preferred, preferred + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                continue
        return port
    return None


def _existing_trade_running(host: str, port: int, timeout: float = 1.0) -> bool:
    """该端口是否已经在跑一个 Trade 后端（例如 launchd 常驻服务）。"""
    try:
        with urllib.request.urlopen(
            f"http://{host}:{port}/api/status", timeout=timeout
        ) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
            return data.get("app") == "Foreign Trade Assistant"
    except Exception:
        return False


def _open_existing(host: str, port: int) -> None:
    try:
        webbrowser.open(f"http://{host}:{port}/trade")
    except Exception:
        pass


def main():
    # 1. Bootstrap（路径、版本检查、env 加载、skills 同步）
    from trade.bootstrap import setup
    setup()

    # 2. 创建 FastAPI app
    from trade.app import create_app, serve_trade_chat

    host = "127.0.0.1"

    from trade.app import _get_trade_data_dir

    lock_path = _get_trade_data_dir() / "tradewin.lock"
    if not _acquire_single_instance(lock_path):
        # 已有 TradeWin 在跑：读它记录的端口，直接把界面打开
        print("TradeWin 已在运行，正在打开已有界面。")
        _open_existing(host, _read_lock_port(lock_path) or PREFERRED_PORT)
        return 0

    # launchd/systemd 可能已经在跑 Trade 后端 —— 不重复启动，只开窗口
    if _existing_trade_running(host, PREFERRED_PORT):
        _open_existing(host, PREFERRED_PORT)
        return 0

    port = _pick_free_port(host, PREFERRED_PORT)
    if port is None:
        print(f"Error: {PREFERRED_PORT}-{PREFERRED_PORT + _PORT_TRIES - 1} 端口都被占用")
        return 1
    _write_lock_port(lock_path, port)

    app = create_app()
    serve_trade_chat(app)

    # 3. 启动 uvicorn 在后台线程
    server_thread = threading.Thread(
        target=uvicorn.run,
        kwargs={"app": app, "host": host, "port": port, "log_level": "warning"},
        daemon=True,
    )
    server_thread.start()

    # 4. 等待后端就绪
    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://{host}:{port}/api/status", timeout=1)
            break
        except Exception:
            time.sleep(0.3)
    else:
        print("Error: 后端启动超时")
        sys.exit(1)

    # 5. 打开 WebView 窗口
    import webview

    url = f"http://{host}:{port}/trade"
    webview.create_window(
        "Smart Trade AI",
        url,
        width=1280,
        height=900,
        min_size=(900, 600),
        text_select=True,
    )
    webview.start()
    sys.exit(0)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
