"""Gateway 的可执行文件查找必须优先看**当前解释器所在的 venv**。

## 为什么（客户机上定时任务静默失效）

Hermes 是装在 Trade 自己的 venv 里的（`~/.trade/venv`），而启动 Gateway 用的是
`shutil.which("hermes") or "hermes"` —— 只查 PATH。

三个平台的 PATH 里有没有 venv 的 bin 目录：
  - macOS：install.sh 写的 launchd plist **显式设了** PATH，含 `$VENV_DIR/bin` ✓
  - Windows：install.ps1 只把 `%LOCALAPPDATA%\\local\\bin` 加进 PATH（里面只有
    trade.cmd），venv 的 Scripts 不在其中 ✗
  - Linux：systemd user unit 的 `ExecStart` 没有 Environment，不继承 venv ✗

后果：Windows/Linux 上 Gateway 永远起不来 → **所有定时任务静默失效**，而
cron 界面还会照常列出 8 条内置任务且全部标成「missed」，用户以为在跑。
macOS 开发机因为 plist 设了 PATH，复现不出来。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _clear_path(monkeypatch):
    """模拟客户机：PATH 里没有任何 hermes。"""
    monkeypatch.setenv("PATH", "/nonexistent-bin-dir")


class TestVenvFirst:
    def test_prefers_interpreters_own_directory(self, monkeypatch, tmp_path):
        """与解释器同目录的 hermes 优先 —— 那就是 Trade venv 里的那份。"""
        import trade.app as app

        monkeypatch.setattr(sys, "executable", str(tmp_path / "bin" / "python"))
        (tmp_path / "bin").mkdir(parents=True)
        exe = "hermes.exe" if os.name == "nt" else "hermes"
        (tmp_path / "bin" / exe).write_text("", encoding="utf-8")
        _clear_path(monkeypatch)

        assert app._find_hermes_binary() == str(tmp_path / "bin" / exe)

    def test_falls_back_to_path(self, monkeypatch):
        """venv 里没有时退回 PATH 查找（开发者机器上常见）。"""
        import trade.app as app

        monkeypatch.setattr(sys, "executable", "/nonexistent/python")
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setattr(app.shutil, "which", lambda _n: "/usr/bin/hermes")

        assert app._find_hermes_binary() == "/usr/bin/hermes"

    def test_last_resort_is_name_not_none(self, monkeypatch):
        """都找不到时返回 'hermes' 字面量，让 Popen 抛错并在日志里可见。

        返回 None 会让 Popen 报更难懂的 TypeError。
        """
        import trade.app as app

        monkeypatch.setattr(sys, "executable", "/nonexistent/python")
        _clear_path(monkeypatch)
        monkeypatch.setattr(app.shutil, "which", lambda _n: None)

        assert app._find_hermes_binary() == "hermes"
