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
        # DETACHED_PROCESS(0x8)：子进程**没有控制台** → 不可能出现终端窗口，
        #   且与父进程解耦（快捷方式那次调用退出后服务仍在）。
        # CREATE_NEW_PROCESS_GROUP(0x200)：Ctrl+C 等信号不串到子进程。
        #
        # 注意**不要**再加 CREATE_NO_WINDOW(0x08000000)：微软文档明确写着它与
        # DETACHED_PROCESS 或 CREATE_NEW_CONSOLE 同时使用时会被忽略
        # （「This flag is ignored if ... used with either CREATE_NEW_CONSOLE or
        # DETACHED_PROCESS」）。加它只会让代码看起来在防窗口、实际没生效。
        kwargs["creationflags"] = 0x00000008 | 0x00000200
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
    focuser=None,
) -> str:
    """确保服务在运行，然后**切到已打开的 Trade 页面；没有才打开**。

    顺序很关键：先确保服务在跑，再决定聚焦还是新开。反过来的话，服务没起时
    会把用户切到一个浏览器的错误页上。

    Args:
        probe: 探测函数 ``(base_url) -> bool``（可注入以便测试）
        spawn: 启动函数 ``(cmd) -> None``（可注入以便测试）
        opener: 打开界面的函数 ``(url) -> bool``；默认用 webbrowser
        focuser: 聚焦已有窗口的函数 ``(marker) -> bool``（可注入以便测试）
    """
    url = f"{base_url}/trade"

    # 区分「本来就在跑」与「这次被我们启动」—— 文案不同，别把刚启动的说成已在运行
    was_running = probe(base_url)
    started = was_running
    if not started:
        server_py = _server_script_path()
        if server_py is None:
            return (
                "✗ 找不到 server.py，无法启动服务。请重新安装 Trade，"
                f"或手动运行 trade 后访问 {url}"
            )

        print("[open] Trade 未运行，正在后台启动 ...")
        try:
            # --no-browser：浏览器由本命令负责，避免服务自己也开一次
            spawn([sys.executable, str(server_py), "--no-browser"])
        except Exception as e:
            return f"✗ 启动 Trade 失败：{e}"

        deadline = time.time() + timeout
        while time.time() < deadline:
            if probe(base_url):
                started = True
                break
            time.sleep(_POLL_INTERVAL)

        if not started:
            # 超时不要假装成功 —— 让用户知道去哪看日志
            return (
                f"✗ Trade 启动超时（{int(timeout)}s 内未就绪）。请查看日志：\n"
                "    ~/.trade/logs/   （Windows: %LOCALAPPDATA%\\trade\\logs\\）"
            )

    # 服务就绪。已打开的 Trade 页面就直接切过去，避免每点一次多一个标签页。
    # 浏览器不向外部程序暴露「聚焦已有标签页」的接口，只能按窗口标题找回。
    # 默认聚焦器在运行时解析（定义在下方；默认参数是定义时求值，不能写在那里）。
    if focuser is None:
        focuser = _focus_window_by_title
    try:
        if focuser(WINDOW_TITLE_MARKER):
            return "✓ 已切到已打开的 Trade 页面"
    except Exception:
        pass  # 聚焦失败不是错误，照常打开新页面即可

    _open(url, opener)
    suffix = "已在运行" if was_running else "已启动"
    return f"✓ Trade {suffix}，已打开界面：{url}"


# 页面标题里这段是稳定的（见 static/trade_chat.html 的 <title>）。
# 浏览器会在后面追加 " - Google Chrome" / " - Microsoft Edge" 之类，
# 所以用「包含」而不是相等来匹配。
WINDOW_TITLE_MARKER = "Trade AI Assistant"


def match_trade_window(titles: list[str]) -> str | None:
    """从窗口标题里挑出 Trade 页面那个；没有则返回 None。

    纯函数，便于测试 —— 真正的窗口枚举在 Windows 上用 Win32 API。
    """
    for t in titles:
        if t and WINDOW_TITLE_MARKER in t:
            return t
    return None


def _iter_window_titles() -> list[str]:
    """枚举当前所有可见顶层窗口的标题（仅 Windows；其它平台返回空表）。"""
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        titles: list[str] = []
        EnumWindowsProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )

        def _cb(hwnd, _lparam):
            # 只看可见窗口 —— 隐藏窗口聚焦了也没意义
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if buf.value:
                    titles.append(buf.value)
            return True

        user32.EnumWindows(EnumWindowsProc(_cb), 0)
        return titles
    except Exception:
        return []


def _focus_window_by_title(marker: str) -> bool:
    """把标题含 marker 的窗口切到前台。成功返回 True。

    用 `SwitchToThisWindow` 而不是 `SetForegroundWindow`：后者会被 Windows 的
    前台锁拒绝（调用进程当前不在前台时直接失败，且不报错），而本命令恰恰是在
    用户双击快捷方式的瞬间运行的 —— 典型的前台切换被拒场景。
    SwitchToThisWindow 是未公开 API，但它正是任务栏/alt-tab 内部用的那个，
    被广泛用于这个用途。
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        target = {"hwnd": None}
        EnumWindowsProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )

        def _cb(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if marker in buf.value:
                    target["hwnd"] = hwnd
                    return False  # 找到即停
            return True

        user32.EnumWindows(EnumWindowsProc(_cb), 0)
        hwnd = target["hwnd"]
        if not hwnd:
            return False
        if user32.IsIconic(hwnd):  # 最小化的先还原
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SwitchToThisWindow(hwnd, True)
        return True
    except Exception:
        return False


def _open(url: str, opener) -> None:
    """打开浏览器；失败不抛（打不开界面不该让整个命令失败）。"""
    if opener is None:
        import webbrowser

        opener = webbrowser.open
    try:
        opener(url)
    except Exception:
        print(f"[open] 无法自动打开浏览器，请手动访问：{url}")
