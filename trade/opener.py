"""`trade open` —— 打开 Trade 界面（桌面快捷方式的目标）。

## 为什么要单独一个子命令

桌面快捷方式双击后应该"直接能用"：服务没跑就先起，起了就打开界面。
把这段逻辑放进 Python（而不是写死在 .bat / .vbs 里）有三个好处：

1. **可测**：探测/启动/开浏览器都是可注入的，能在没有 Windows 的机器上跑单测，
   而 .bat 里的端口探测没法测。
2. **错误可见**：失败时能打印人能看懂的原因（端口被占、启动超时），
   而不是让浏览器显示一个"无法连接"。
3. **一套逻辑多处复用**：快捷方式、将来的托盘/菜单项都调它。

与开机自启的区别：自启用 `--no-browser`（登录时不该弹浏览器），
`trade open` 才负责打开界面。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# 与 trade/app.py 的默认端口一致
DEFAULT_BASE_URL = "http://127.0.0.1:9119"
# 等待服务就绪的上限（秒）。首次启动要做 skills 同步等，实测约 60s 才绑端口；
# 给 90s 留余量，超时后如实报错而不是无限等。
STARTUP_TIMEOUT_SECONDS = 90.0
_POLL_INTERVAL = 0.5


def is_server_up(base_url: str = DEFAULT_BASE_URL, timeout: float = 1.5) -> bool:
    """探测 Trade 服务是否已在运行。"""
    try:
        with urllib.request.urlopen(f"{base_url}/api/status", timeout=timeout) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        # 能拿到 HTTP 响应就说明端口有人在听（哪怕返回非 200）
        return e.code < 500
    except Exception:
        return False


def _server_script_path() -> Path | None:
    """定位 server.py（仓库根，与 trade/ 同级）。"""
    candidate = Path(__file__).resolve().parent.parent / "server.py"
    return candidate if candidate.is_file() else None


def _spawn_detached(cmd: list[str]) -> None:
    """后台启动，且**不显示窗口**（Windows）/ 脱离会话（POSIX）。"""
    kwargs: dict = {}
    if os.name == "nt":
        # CREATE_NO_WINDOW：无控制台窗口；CREATE_NEW_PROCESS_GROUP + DETACHED_PROCESS：
        # 与父进程解耦，父进程退出（快捷方式那次调用）不会带走服务。
        kwargs["creationflags"] = 0x08000000 | 0x00000200 | 0x00000008
    else:
        kwargs["start_new_session"] = True
    kwargs["stdout"] = subprocess.DEVNULL
    kwargs["stderr"] = subprocess.DEVNULL
    subprocess.Popen(cmd, **kwargs)


def open_trade(
    *,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = STARTUP_TIMEOUT_SECONDS,
    probe=is_server_up,
    spawn=_spawn_detached,
    opener=None,
) -> str:
    """确保服务在运行，然后打开界面。返回一句给用户看的结果说明。

    Args:
        probe: 探测函数 ``(base_url) -> bool``（可注入以便测试）
        spawn: 启动函数 ``(cmd) -> None``（可注入以便测试）
        opener: 打开界面的函数 ``(url) -> bool``；默认用 webbrowser
    """
    url = f"{base_url}/trade"

    if probe(base_url):
        _open(url, opener)
        return f"✓ Trade 已在运行，已打开界面：{url}"

    server_py = _server_script_path()
    if server_py is None:
        return (
            "✗ 找不到 server.py，无法启动服务。请重新安装 Trade，"
            f"或手动运行 trade 后访问 {url}"
        )

    print("[open] Trade 未运行，正在后台启动 ...")
    try:
        # --no-browser：浏览器由本命令负责打开，避免服务自己也开一次（两个标签页）
        spawn([sys.executable, str(server_py), "--no-browser"])
    except Exception as e:
        return f"✗ 启动 Trade 失败：{e}"

    deadline = time.time() + timeout
    while time.time() < deadline:
        if probe(base_url):
            _open(url, opener)
            return f"✓ Trade 已启动，已打开界面：{url}"
        time.sleep(_POLL_INTERVAL)

    # 超时不要假装成功 —— 让用户知道去哪看日志
    return (
        f"✗ Trade 启动超时（{int(timeout)}s 内未就绪）。请查看日志：\n"
        "    ~/.trade/logs/   （Windows: %LOCALAPPDATA%\\trade\\logs\\）"
    )


def _open(url: str, opener) -> None:
    """打开浏览器；失败不抛（打不开界面不该让整个命令失败）。"""
    if opener is None:
        import webbrowser

        opener = webbrowser.open
    try:
        opener(url)
    except Exception:
        print(f"[open] 无法自动打开浏览器，请手动访问：{url}")
