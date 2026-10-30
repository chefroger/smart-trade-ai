"""Windows「升级按钮必然失败」的三个根因与修复（2026-10-30 客户机实测）。

铁证（客户机原文）：
    Step 4/7 pip install ...
    ERROR: Could not install packages due to an OSError: [WinError 32]
    另一个程序正在使用此文件，进程无法访问。:
    '...\\venv\\Scripts\\trade.exe' -> '...\\venv\\Scripts\\trade.exe.deleteme'

因果链：
    启动器用 venv\\Scripts\\trade.exe 起服务
      → 升级第 4 步 `pip install -e .` 要重写同一个 trade.exe
      → Windows 不允许替换正在运行的 exe（WinError 32）
      → updater 判致命 → 回滚代码 → 界面只显示「升级失败」（点一下必然失败）

三处修复：
    1. win_setup.resolve_trade_command  改用 python.exe + server.py（根治）
    2. app._fix_restart_argv             console script 起的进程也能正确重启
    3. update._looks_like_exe_lock       失败时给出**可照做**的提示，而不是「升级失败」
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from trade.post_install import update as upd  # noqa: E402

WINERROR_32 = (
    "ERROR: Could not install packages due to an OSError: [WinError 32] "
    "另一个程序正在使用此文件，进程无法访问。: "
    "'C:\\Users\\张伟\\AppData\\Local\\trade\\venv\\Scripts\\trade.exe' -> "
    "'C:\\Users\\张伟\\AppData\\Local\\trade\\venv\\Scripts\\trade.exe.deleteme'"
)


class TestExeLockDetection:
    """必须能认出「正在运行的 exe 被占用」，且不误报普通 pip 失败。"""

    def test_detects_winerror_32(self):
        assert upd._looks_like_exe_lock(WINERROR_32) is True

    def test_detects_english_variant(self):
        err = (
            "Permission denied: 'venv\\Scripts\\trade.exe' is being used "
            "by another process"
        )
        assert upd._looks_like_exe_lock(err) is True

    def test_ignores_ordinary_pip_failure(self):
        """普通依赖装不上（如网络断）不能被当成 exe 占用 —— 提示会误导用户。"""
        assert upd._looks_like_exe_lock(
            "ERROR: Could not find a version that satisfies the requirement foo"
        ) is False

    def test_ignores_permission_error_without_exe(self):
        """权限问题但与 exe 无关 → 不误报。"""
        assert upd._looks_like_exe_lock(
            "ERROR: Could not install packages due to an OSError: [WinError 5] "
            "拒绝访问: 'C:\\some\\dir'"
        ) is False


class TestExeLockHint:
    """提示必须给出能照做的命令（项目硬规则：告警要有行动价值）。"""

    def test_hint_names_python_and_server_py(self):
        hint = upd._exe_lock_hint(pathlib.Path("/tmp/code"))

        assert "server.py" in hint
        assert "python" in hint.lower()

    def test_hint_asks_for_one_restart(self):
        """根治办法是重启一次（自启链会在本次升级里被改成 python.exe 启动）。"""
        hint = upd._exe_lock_hint(pathlib.Path("/tmp/code"))

        assert "重启" in hint


class TestExeLockIsNotFatal:
    """exe 被占用时**升级必须照样成功** —— 这是「点一下必然失败」的根治。"""

    def test_update_continues_when_exe_is_locked(self, monkeypatch, tmp_path):
        """pip -e 因 WinError 32 失败 → 记警告、不判致命。"""
        import sys as _sys

        def _fake_pip_args(*args):
            return [_sys.executable, "-c",
                    "import sys; sys.stderr.write("
                    "'ERROR: [WinError 32] 另一个程序正在使用此文件: "
                    "'venv\\\\Scripts\\\\trade.exe''); sys.exit(1)"]

        monkeypatch.setattr(upd, "_pip_install_args", _fake_pip_args)

        warnings: list[str] = []
        err = upd._install_trade_package(tmp_path, lambda _m: None, warnings)

        assert err is None, "exe 被占用被判成致命错误 → 升级按钮必然失败"
        assert warnings and "重启" in warnings[0]

    def test_other_pip_failures_stay_fatal(self, monkeypatch, tmp_path):
        """普通 pip 失败仍必须致命（不能把真问题当警告吞掉）。"""
        import sys as _sys

        def _fake_pip_args(*args):
            return [_sys.executable, "-c",
                    "import sys; sys.stderr.write('ERROR: network unreachable'); sys.exit(1)"]

        monkeypatch.setattr(upd, "_pip_install_args", _fake_pip_args)

        warnings: list[str] = []
        err = upd._install_trade_package(tmp_path, lambda _m: None, warnings)

        assert err is not None, "普通 pip 失败必须判致命"
        assert not warnings


class TestOldLaunchersMigrate:
    """老用户的启动器必须能自动迁到 python.exe 启动，不需要人工干预。

    否则这次修复只对**新装**机器有效 —— 而踩到 WinError 32 的正是老机器。
    迁移路径：每次启动 `ensure_windows_setup` → `ensure_launcher_scripts`
    无条件重写 bat/vbs（没有「已存在就跳过」）。
    """

    def test_launcher_scripts_are_rewritten_not_skipped(self, monkeypatch, tmp_path):
        from trade.post_install import win_setup as ws

        d = tmp_path / "trade"
        d.mkdir()
        monkeypatch.setattr(ws, "launcher_dir", lambda: d)

        # 老版本留下的 trade.exe 启动器
        (d / "trade-autostart.bat").write_text(
            '"%LOCALAPPDATA%\\trade\\venv\\Scripts\\trade.exe" --no-browser\r\n',
            encoding="utf-8",
        )
        (tmp_path / "server.py").write_text("", encoding="utf-8")

        scripts = ws.ensure_launcher_scripts(tmp_path)

        content = scripts["autostart_bat"].read_text(encoding="utf-8")
        assert "trade.exe" not in content, "老启动器未被迁移（仍指向 trade.exe）"
        assert "server.py" in content


class TestRestartArgvFix:
    """console script 起的进程，重启命令不能是「python.exe trade.exe」。"""

    def test_replaces_console_script_argv0(self):
        from trade import app

        server_py = pathlib.Path(app.__file__).resolve().parent.parent / "server.py"
        if not server_py.is_file():  # 打包环境下没有 server.py → 保持原样
            return
        fixed = app._fix_restart_argv(
            [r"C:\venv\Scripts\trade.exe", "--no-browser"], windows=True
        )

        assert fixed[0] == str(server_py)
        assert fixed[1] == "--no-browser"

    def test_keeps_normal_argv(self):
        from trade import app

        argv = ["server.py"]
        assert app._fix_restart_argv(list(argv), windows=True) == argv

    def test_posix_untouched(self):
        """POSIX 上覆盖运行中的脚本是允许的，不需要改。"""
        from trade import app

        argv = ["/usr/local/bin/trade"]
        assert app._fix_restart_argv(list(argv), windows=False) == argv
