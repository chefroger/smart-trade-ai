"""副驾需要排除的自身进程（Trade 主进程 + 副驾进程）。

按下热键时如果前台是 Trade 自己的窗口，读进来的只会是 Trade 的界面文字。
平台模块在截图前用本模块判定，命中就返回 `host_frontmost` 错误，而不是
退回去读它后面那个窗口（2026-11-06 口径：提示用户先切到聊天窗口）。

PID 来源（按可靠性排序）：

1. `TRADE_HOST_PID` —— 设置页拉起副驾时由 Trade 主进程注入，最准确；
2. `$TRADE_HOME/data/trade.pid` —— Trade 启动时写的自有 PID 文件，
   手动 `trade copilot` 时靠它；
3. `os.getpid()` —— 副驾进程自己（悬浮窗、pywebview 辅助进程）。

读不到一律忽略：宁可少排除，也不要因为权限/格式问题让读取失败。
"""

from __future__ import annotations

import os

from trade.copilot.settings import default_settings_path


def _read_pid_file(path) -> int:
    """读 PID 文件；不存在/损坏/非正数返回 0。"""
    try:
        value = int(path.read_text(encoding="utf-8").strip())
    except Exception:
        return 0
    return value if value > 0 else 0


def own_window_pids() -> set[int]:
    """返回需要排除的进程 PID 集合（永远包含副驾自身）。"""
    pids = {os.getpid()}

    raw_env = os.environ.get("TRADE_HOST_PID", "").strip()
    try:
        env_pid = int(raw_env)
    except (TypeError, ValueError):
        env_pid = 0
    if env_pid > 0:
        pids.add(env_pid)

    pid_file = default_settings_path().parent / "data" / "trade.pid"
    file_pid = _read_pid_file(pid_file)
    if file_pid > 0:
        pids.add(file_pid)

    return pids
