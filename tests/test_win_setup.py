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
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

        cmd = ws.resolve_trade_command(tmp_path, executable=str(exe_dir / "python.exe"))

        assert "trade.exe" in cmd

    def test_resolve_command_falls_back_to_python(self, tmp_path, monkeypatch):
        exe_dir = tmp_path / "Scripts"
        exe_dir.mkdir()
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        (tmp_path / "server.py").write_text("", encoding="utf-8")

        cmd = ws.resolve_trade_command(tmp_path, executable=str(exe_dir / "python.exe"))

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
        # 必须指向**我们期望的那个** vbs —— 判据已收紧：指向别的脚本算需要替换
        new_xml = (
            "<Command>wscript.exe</Command>"
            '<Arguments>"C:\\x\\trade-autostart.vbs"</Arguments>'
        )
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
    """非 Windows 上必须完全不动系统。

    **不要 monkeypatch 全局 `os.name`**：`ws.os` 就是 `os` 模块本身，改它会让
    pathlib 以为当前是 POSIX —— Windows 上 `Path()` 随即抛 NotImplementedError，
    连 pytest 自己的报告机制都崩（CI 上真实发生过）。这里注入模块内的
    `_is_windows` 判断函数，只影响被测代码。
    """

    def test_returns_empty_off_windows(self, monkeypatch):
        monkeypatch.setattr(ws, "_is_windows", lambda: False)
        assert ws.ensure_windows_setup(Path("/tmp")) == []

    def test_no_side_effects_off_windows(self, monkeypatch):
        """非 Windows 上连脚本都不该生成。"""
        monkeypatch.setattr(ws, "_is_windows", lambda: False)
        called = []
        monkeypatch.setattr(ws, "ensure_launcher_scripts", lambda _d: called.append(1))

        ws.ensure_windows_setup(Path("/tmp"))

        assert called == []


class TestTaskDetectionIsStrict:
    """判据必须严格到能识别「注册坏了」的任务。

    历史判据只要 XML 里同时出现 wscript 与 .vbs 就算通过 —— 于是一个被引号
    截断、或指向残留旧脚本的任务会被当成好的，**永远不修**，
    而症状恰是"开机弹终端窗口"或"开机什么都不发生"。
    """

    def test_missing_arguments_is_not_ok(self):
        xml = "<Command>wscript.exe</Command>"
        assert ws.is_vbs_launcher_task(xml) is False

    def test_pointing_at_another_vbs_is_not_ok(self):
        """任务指向残留的旧 vbs —— 必须判为需要替换。"""
        xml = (
            "<Command>wscript.exe</Command>"
            '<Arguments>"C:\\old\\leftover-launcher.vbs"</Arguments>'
        )

        assert ws.is_vbs_launcher_task(
            xml, expected_vbs=Path(r"C:\Users\x\AppData\Local\trade\trade-autostart.vbs")
        ) is False

    def test_pointing_at_expected_vbs_is_ok(self):
        xml = (
            "<Command>C:\\Windows\\System32\\wscript.exe</Command>"
            '<Arguments>"C:\\Users\\x\\AppData\\Local\\trade\\trade-autostart.vbs"</Arguments>'
        )

        assert ws.is_vbs_launcher_task(
            xml, expected_vbs=Path(r"C:\Users\x\AppData\Local\trade\trade-autostart.vbs")
        ) is True

    def test_bare_wscript_command_is_ok(self):
        """schtasks 存的是裸文件名 wscript.exe 时也算对。"""
        xml = (
            "<Command>wscript.exe</Command>"
            '<Arguments>"C:\\x\\trade-autostart.vbs"</Arguments>'
        )
        assert ws.is_vbs_launcher_task(xml) is True

    def test_cmd_wrapping_wscript_is_not_ok(self):
        """`cmd /c wscript ...` 这种包一层的写法会真的闪一下窗口，判为需要替换。"""
        xml = (
            "<Command>cmd.exe</Command>"
            '<Arguments>/c wscript "C:\\x\\trade-autostart.vbs"</Arguments>'
        )
        assert ws.is_vbs_launcher_task(xml) is False


class TestVbsIsAsciiSafe:
    """VBS 里的 bat 路径也要走环境变量展开，保持纯 ASCII。

    wscript 按系统 ANSI 代码页读 .vbs，中文用户名路径原样写进去依赖编码兜底；
    换成 `%LOCALAPPDATA%` 由 cmd 运行时展开就没有这个问题。
    """

    def test_vbs_uses_env_var_not_literal_path(self, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\张伟\AppData\Local")
        bat = Path(r"C:\Users\张伟\AppData\Local\trade\trade-autostart.bat")

        vbs = ws.build_hidden_vbs(bat)

        assert "%LOCALAPPDATA%" in vbs
        assert "张伟" not in vbs
        assert vbs.isascii(), "VBS 里仍有非 ASCII，wscript 读取可能乱码"

    def test_vbs_still_hides_window(self, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\a\AppData\Local")

        vbs = ws.build_hidden_vbs(Path(r"C:\Users\a\AppData\Local\trade\t.bat"))

        assert ", 0, False" in vbs


class TestNoStrayLaunchersOnDesktop:
    """桌面只该有 Trade.lnk —— 启动器脚本一律在 launcher_dir()。

    为什么专门测这条：让 AI「在桌面放个快捷方式」时，很容易变成把 .vbs 复制到桌面。
    那等于桌面上多一个可执行文件：容易被误删、也可能被杀软拦截。
    """

    def test_detects_stray_vbs(self, tmp_path):
        (tmp_path / "trade-autostart.vbs").write_text("x", encoding="utf-8")

        found = ws.find_stray_desktop_launchers(tmp_path)

        assert [p.name for p in found] == ["trade-autostart.vbs"]

    def test_detects_all_four_launcher_names(self, tmp_path):
        for name in ("trade-autostart.vbs", "trade-open.vbs",
                     "trade-autostart.bat", "trade-open.bat"):
            (tmp_path / name).write_text("x", encoding="utf-8")

        assert len(ws.find_stray_desktop_launchers(tmp_path)) == 4

    def test_clean_desktop_returns_empty(self, tmp_path):
        (tmp_path / "Trade.lnk").write_text("x", encoding="utf-8")
        (tmp_path / "我的文档.docx").write_text("x", encoding="utf-8")

        assert ws.find_stray_desktop_launchers(tmp_path) == []

    def test_does_not_delete_anything(self, tmp_path):
        """只报告不删除 —— 删桌面上的文件必须由人决定。"""
        stray = tmp_path / "trade-autostart.vbs"
        stray.write_text("x", encoding="utf-8")

        ws.find_stray_desktop_launchers(tmp_path)

        assert stray.is_file(), "检测过程把文件删了"

    def test_launcher_dir_is_never_the_desktop(self, tmp_path, monkeypatch):
        """启动器目录落在 TRADE_HOME / %LOCALAPPDATA%\\trade，绝不是桌面。"""
        monkeypatch.setenv("TRADE_HOME", str(tmp_path / "th"))
        assert ws.launcher_dir() == tmp_path / "th"

        monkeypatch.delenv("TRADE_HOME", raising=False)
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "la"))
        assert "trade" in str(ws.launcher_dir())
