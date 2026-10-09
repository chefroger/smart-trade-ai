"""Windows 开机自启 + 桌面快捷方式生成（纯逻辑部分，跨平台可测）。

## 背景

客户的部署流程是「装 Hermes → 让 Hermes 装 Trade」，**不经过 install.ps1**，
所以脚本里配好的自启拿不到。这里要保证：这份代码在任何安装路径下都能把
自启和桌面快捷方式配好，且**不弹终端窗口**。

历史实现有两套且都不满足要求：
  - install.ps1：`Register-ScheduledTask -Execute python.exe ...`
  - update.py：`schtasks /tr '"py" "server.py"'`
两者都是控制台程序 → 登录必然弹黑框。文档里给客户的手动教程（VBS 隐藏窗口）
反而是对的，本模块统一到后者。

## 编码这条最容易被忽略

`.bat` 会被 cmd.exe 按系统 OEM 代码页读取。中文用户名
（`C:\\Users\\张伟\\AppData\\Local\\`）直接写进去会乱码；文档那段用
`-Encoding ASCII` 写则是把非 ASCII 静默替换成 `?`。正确做法是**让生成的脚本
保持纯 ASCII** —— 路径里的用户目录前缀换成 `%LOCALAPPDATA%` 运行时展开。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade.post_install import win_setup as ws


class TestBatchPathRewriting:
    """生成的脚本必须保持纯 ASCII。"""

    def test_localappdata_prefix_replaced(self, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\张伟\AppData\Local")
        monkeypatch.delenv("USERPROFILE", raising=False)

        out = ws.to_batch_path(r"C:\Users\张伟\AppData\Local\trade\venv\Scripts\trade.exe")

        assert out == r"%LOCALAPPDATA%\trade\venv\Scripts\trade.exe"
        assert out.isascii(), "仍然含非 ASCII —— cmd 读取时会乱码"

    def test_userprofile_prefix_replaced(self, monkeypatch):
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        monkeypatch.setenv("USERPROFILE", r"C:\Users\张伟")

        assert ws.to_batch_path(r"C:\Users\张伟\Desktop\Trade") == r"%USERPROFILE%\Desktop\Trade"

    def test_unrelated_path_untouched(self, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\a\AppData\Local")
        assert ws.to_batch_path(r"D:\opt\trade") == r"D:\opt\trade"

    def test_case_insensitive_match(self, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\A\AppData\Local")
        out = ws.to_batch_path(r"c:\users\a\appdata\local\trade")
        assert out.startswith("%LOCALAPPDATA%")


class TestGeneratedScripts:
    def test_autostart_has_no_browser_and_logs(self):
        bat = ws.build_autostart_bat('"%LOCALAPPDATA%\\trade\\venv\\Scripts\\trade.exe"', "%LOCALAPPDATA%\\trade\\a.log")

        assert "--no-browser" in bat, "开机自启不该打开浏览器"
        assert "> " in bat and "2>&1" in bat, "必须重定向日志 —— 隐藏窗口后就没别的排查手段了"

    def test_open_has_open_subcommand(self):
        bat = ws.build_open_bat('"%LOCALAPPDATA%\\trade\\venv\\Scripts\\trade.exe"', "%LOCALAPPDATA%\\trade\\o.log")

        assert " open " in bat, "快捷方式应调用 `trade open`（起服务 + 开浏览器）"
        assert "--no-browser" not in bat, "open 子命令自己负责开浏览器"

    def test_vbs_hides_window(self):
        vbs = ws.build_hidden_vbs(Path(r"C:\x\a.bat"))

        assert "WScript.Shell" in vbs
        # Run(cmd, 0, False)：0 = 隐藏窗口，False = 不等待
        assert ", 0, False" in vbs, "窗口样式不是 0 → 会弹出终端窗口"

    def test_resolve_command_prefers_venv_exe(self, tmp_path, monkeypatch):
        exe_dir = tmp_path / "Scripts"
        exe_dir.mkdir()
        (exe_dir / "trade.exe").write_text("", encoding="utf-8")
        monkeypatch.setattr(ws.sys, "executable", str(exe_dir / "python.exe"))
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

        cmd = ws.resolve_trade_command(tmp_path)

        assert "trade.exe" in cmd

    def test_resolve_command_falls_back_to_python(self, tmp_path, monkeypatch):
        exe_dir = tmp_path / "Scripts"
        exe_dir.mkdir()
        monkeypatch.setattr(ws.sys, "executable", str(exe_dir / "python.exe"))
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        (tmp_path / "server.py").write_text("", encoding="utf-8")

        cmd = ws.resolve_trade_command(tmp_path)

        assert "python.exe" in cmd and "server.py" in cmd


class TestTaskXmlDetection:
    def test_detects_new_style_vbs_task(self):
        xml = '<Command>wscript.exe</Command><Arguments>"C:\\x\\trade-autostart.vbs"</Arguments>'
        assert ws.is_vbs_launcher_task(xml) is True

    def test_old_style_python_task_is_not_vbs(self):
        """旧实现跑 python.exe → 会弹窗 → 必须被识别为"需要替换"。"""
        xml = '<Command>C:\\Python\\python.exe</Command><Arguments>server.py --no-browser</Arguments>'
        assert ws.is_vbs_launcher_task(xml) is False

    def test_empty_xml_is_not_treated_as_ok(self):
        assert ws.is_vbs_launcher_task("") is False


class TestScheduledTaskReplacement:
    """客户机上残留的旧任务要能自动修好（弹窗问题不靠人工干预自愈）。"""

    def _patch_run(self, monkeypatch, xml: str, created: list):
        def fake_run(cmd, timeout=30):
            created.append(list(cmd))

            class R:
                returncode = 0
                stdout = xml
                stderr = ""

            if cmd[:2] == ["schtasks", "/query"]:
                R.stdout, R.returncode = (xml, 0) if xml else ("", 1)
            return R()

        monkeypatch.setattr(ws, "_run", fake_run)

    def test_replaces_old_python_task(self, monkeypatch):
        calls: list[list[str]] = []
        old_xml = '<Command>python.exe</Command><Arguments>server.py</Arguments>'
        self._patch_run(monkeypatch, old_xml, calls)

        msg = ws.ensure_scheduled_task(Path(r"C:\x\trade-autostart.vbs"))

        kinds = [c[1].lstrip("/") for c in calls if c[0] == "schtasks"]
        assert "delete" in kinds, "旧任务（python.exe，会弹窗）没有被注销替换"
        assert "create" in kinds
        assert "替换" in msg

    def test_skips_when_already_vbs(self, monkeypatch):
        calls: list[list[str]] = []
        new_xml = '<Command>wscript.exe</Command><Arguments>"C:\\x\\a.vbs"</Arguments>'
        self._patch_run(monkeypatch, new_xml, calls)

        msg = ws.ensure_scheduled_task(Path(r"C:\x\trade-autostart.vbs"))

        kinds = [c[1].lstrip("/") for c in calls if c[0] == "schtasks"]
        assert "delete" not in kinds and "create" not in kinds
        assert "跳过" in msg

    def test_creates_when_absent(self, monkeypatch):
        calls: list[list[str]] = []
        self._patch_run(monkeypatch, "", calls)

        msg = ws.ensure_scheduled_task(Path(r"C:\x\trade-autostart.vbs"))

        kinds = [c[1].lstrip("/") for c in calls if c[0] == "schtasks"]
        assert "create" in kinds
        assert "已设置" in msg

    def test_task_runs_wscript_not_python(self, monkeypatch):
        """注册的必须是 wscript.exe —— 直接跑 python.exe 就是会弹窗的旧做法。"""
        calls: list[list[str]] = []
        self._patch_run(monkeypatch, "", calls)

        ws.ensure_scheduled_task(Path(r"C:\x\trade-autostart.vbs"))

        create = next(c for c in calls if c[0] == "schtasks" and c[1] == "/create")
        tr = create[create.index("/tr") + 1]
        assert "wscript" in tr.lower(), f"计划任务的执行体不是 wscript：{tr}"


class TestNonWindowsIsNoop:
    def test_returns_empty_off_windows(self, monkeypatch):
        monkeypatch.setattr(ws.os, "name", "posix")
        assert ws.ensure_windows_setup(Path("/tmp")) == []
