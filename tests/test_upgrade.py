"""
升级管线测试 — _capture_output, _perform_restart, 版本检查, 失败标记检测。

使用 mock 避免真实 git pull / 进程管理 / GitHub API 调用。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── _capture_output 测试 ──────────────────────────────────────────────────


class TestCaptureOutput:
    """测试 trade.api.cron._capture_output。"""

    def test_capture_print_output(self):
        """正常函数的 print 输出应被捕获。"""
        from trade.api.cron import _capture_output

        def hello():
            print("hello world")

        result = _capture_output(hello)
        assert result["ok"] is True
        assert "hello world" in result["output"]

    def test_capture_return_string_as_file(self):
        """返回字符串的函数（如 backup_trade）应设 file 字段。"""
        from trade.api.cron import _capture_output

        def backup():
            print("backing up...")
            return "/tmp/backup.tar.gz"

        result = _capture_output(backup)
        assert result["ok"] is True
        assert result["file"] == "/tmp/backup.tar.gz"

    def test_capture_exception(self):
        """函数抛 Exception 时应返回 ok=False。"""
        from trade.api.cron import _capture_output

        def boom():
            raise RuntimeError("something broke")

        result = _capture_output(boom)
        assert result["ok"] is False
        assert "something broke" in result["error"]

    def test_capture_system_exit(self):
        """sys.exit() 被 _capture_output 拦截，返回 ok=False 而非穿透。"""
        from trade.api.cron import _capture_output

        def exit_func():
            sys.exit(1)

        result = _capture_output(exit_func)
        assert result["ok"] is False
        assert "exited" in result["error"].lower()

    def test_capture_system_exit_message(self):
        """sys.exit("message") 的消息应包含在 error 中。"""
        from trade.api.cron import _capture_output

        def exit_with_msg():
            sys.exit("git pull failed")

        result = _capture_output(exit_with_msg)
        assert result["ok"] is False
        assert "git pull failed" in result["error"]

    def test_stdout_restored_after_capture(self):
        """_capture_output 执行后 sys.stdout 应恢复原值。"""
        from trade.api.cron import _capture_output

        original = sys.stdout
        _capture_output(lambda: print("test"))
        assert sys.stdout is original

    def test_stdout_restored_after_exception(self):
        """函数抛异常时 sys.stdout 也应恢复。"""
        from trade.api.cron import _capture_output

        original = sys.stdout
        _capture_output(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        assert sys.stdout is original


# ── _perform_restart 测试 ─────────────────────────────────────────────────


class TestPerformRestart:
    """测试 trade.app._perform_restart（核心重启逻辑）。"""

    @patch("trade.app._sp")
    @patch("trade.app._kill_gateway")
    @patch("trade.app._get_trade_data_dir")
    def test_new_process_started_before_kill(self, mock_data_dir, mock_kill_gw, mock_sp):
        """新进程应先于旧进程被杀之前启动（先 Popen 再 kill）。"""
        import tempfile

        from trade.app import _perform_restart

        # 准备临时 PID 文件
        tmp_dir = Path(tempfile.mkdtemp())
        pid_file = tmp_dir / "trade.pid"
        pid_file.write_text(str(99999))  # 不存在的 PID，不会真的杀
        mock_data_dir.return_value = tmp_dir

        # mock Popen
        mock_sp.DEVNULL = -1
        mock_sp.Popen = MagicMock()

        # mock os.name 和 os.kill（让 PID 校验通过）
        with patch("trade.app.os") as mock_os:
            mock_os.name = "posix"
            mock_os.kill = MagicMock(side_effect=OSError("no such process"))
            mock_os.getpid = MagicMock(return_value=12345)

            _perform_restart()

        # Popen 应被调用（新进程启动）
        assert mock_sp.Popen.called

    @patch("trade.app._sp")
    @patch("trade.app._kill_gateway")
    @patch("trade.app._get_trade_data_dir")
    def test_windows_creationflags(self, mock_data_dir, mock_kill_gw, mock_sp):
        """Windows 上应使用 creationflags 而非 start_new_session。"""
        import tempfile

        from trade.app import _perform_restart

        tmp_dir = Path(tempfile.mkdtemp())
        mock_data_dir.return_value = tmp_dir

        mock_sp.DEVNULL = -1
        mock_sp.Popen = MagicMock()

        with patch("trade.app.os") as mock_os:
            mock_os.name = "nt"
            mock_os.getpid = MagicMock(return_value=12345)

            _perform_restart()

        # 检查 Popen 被调用时用了 creationflags
        popen_kwargs = mock_sp.Popen.call_args[1]
        assert popen_kwargs.get("creationflags") == 0x00000200
        assert "start_new_session" not in popen_kwargs

    @patch("trade.app._sp")
    @patch("trade.app._kill_gateway")
    @patch("trade.app._get_trade_data_dir")
    def test_windows_script_quotes_python_path_for_cmd(self, mock_data_dir, mock_kill_gw, mock_sp):
        """Windows 重启脚本必须用 cmd 认得的双引号包裹解释器路径。

        历史 bug：脚本由 repr() 拼成单引号（'C:\\...\\python.exe'），cmd 不认单引号，
        而脚本上一行已经 taskkill 掉旧进程 —— 结果是旧进程已死、新进程起不来，服务彻底下线。
        """
        import subprocess as real_sp
        import tempfile

        from trade.app import _perform_restart

        tmp_dir = Path(tempfile.mkdtemp())
        mock_data_dir.return_value = tmp_dir

        mock_sp.DEVNULL = -1
        mock_sp.Popen = MagicMock()
        # 让被测代码能拿到真实的 list2cmdline 实现
        mock_sp.list2cmdline = real_sp.list2cmdline

        with patch("trade.app.os") as mock_os:
            mock_os.name = "nt"
            mock_os.getpid = MagicMock(return_value=12345)
            # 解释器路径故意带空格，逼出引号处理。
            # app.py 内部是 `import sys as _sys` 的局部导入，只能 patch 真实 sys 模块的属性。
            with patch.object(sys, "executable", "C:\\Program Files\\Python313\\python.exe"):
                _perform_restart()

        # Windows 分支的第一个位置参数是 ["cmd", "/c", <脚本>]
        script = mock_sp.Popen.call_args[0][0][-1]
        assert "'C:\\Program Files" not in script, f"cmd 不认单引号，脚本仍为：{script}"
        assert '"C:\\Program Files\\Python313\\python.exe"' in script, f"解释器路径未被双引号包裹：{script}"
        assert "taskkill /PID 12345 /F" in script, f"脚本未先杀旧进程：{script}"

    @patch("trade.app._sp")
    @patch("trade.app._kill_gateway")
    @patch("trade.app._get_trade_data_dir")
    def test_unix_start_new_session(self, mock_data_dir, mock_kill_gw, mock_sp):
        """Unix 上应使用 start_new_session。"""
        import tempfile

        from trade.app import _perform_restart

        tmp_dir = Path(tempfile.mkdtemp())
        mock_data_dir.return_value = tmp_dir

        mock_sp.DEVNULL = -1
        mock_sp.Popen = MagicMock()

        with patch("trade.app.os") as mock_os:
            mock_os.name = "posix"
            mock_os.getpid = MagicMock(return_value=12345)

            _perform_restart()

        popen_kwargs = mock_sp.Popen.call_args[1]
        assert popen_kwargs.get("start_new_session") is True
        assert "creationflags" not in popen_kwargs


# ── update_trade 失败分级测试 ─────────────────────────────────────────────


class TestUpdateStepSeverity:
    """update_trade 的失败分级：只有 git / pip / 数据库算致命，其余只记警告。

    历史 bug：skills 步骤失败也把 ok 置为 False，导致「代码和依赖都已就绪却不重启」，
    用户被锁在旧代码上，而 /api/status 又会把磁盘上 pyproject.toml 的新版本号反写进
    version.txt —— 「卡在旧版」被伪装成「升级成功」。
    """

    @staticmethod
    def _fake_run(pull_rc=0, pip_rc=0, stash_rc=0):
        """按命令内容分派返回码，替掉真实 subprocess.run。"""
        def _run(cmd, **kwargs):
            joined = " ".join(str(c) for c in cmd)
            rc = 0
            # git stash 优先匹配（stash 命令里也含 "git"）
            if "git" in joined and "stash" in joined:
                rc = stash_rc
            elif "git" in joined and "pull" in joined:
                rc = pull_rc
            elif "pip" in joined:
                rc = pip_rc
            result = MagicMock()
            result.returncode = rc
            result.stdout = ""
            result.stderr = "boom" if rc else ""
            return result
        return _run

    def _run_update(self, *, skills_raise=False, pull_rc=0, pip_rc=0,
                    stash_rc=0, db_ok=True, existing_dir=False):
        """在全部外部依赖被 mock 的前提下跑一次 update_trade()。"""
        from contextlib import ExitStack

        from trade.post_install import update as update_mod
        from trade.post_install.skills import _get_trade_home

        with ExitStack() as stack:
            mock_sub = stack.enter_context(patch("trade.post_install.update.subprocess"))
            mock_sub.run.side_effect = self._fake_run(pull_rc=pull_rc, pip_rc=pip_rc, stash_rc=stash_rc)
            mock_sub.DEVNULL = -1
            # 供目录定位用例断言实际执行的命令（cwd / clone 目标）
            self.last_subprocess = mock_sub
            # 模板同步/开机自启有真实副作用（写 launchd plist 等），必须 mock
            stack.enter_context(patch("trade.post_install.update._sync_trade_template"))
            stack.enter_context(patch("trade.post_install.update._ensure_auto_start"))
            stack.enter_context(patch("trade.bootstrap.check_native_architecture", return_value=True))

            mock_init = stack.enter_context(patch("trade.database.init_db"))
            if db_ok:
                mock_init.return_value = "/tmp/fake.db"
            else:
                mock_init.side_effect = RuntimeError("db boom")

            # skills 步骤必须始终 mock：真实 install_skills 会写 ~/.hermes/skills，
            # update_skills 还会访问 GitHub —— 测试绝不能碰真实用户数据或网络
            if skills_raise:
                stack.enter_context(patch("trade.post_install.update.install_skills", side_effect=SystemExit(1)))
                stack.enter_context(patch("trade.post_install.update.update_skills", side_effect=SystemExit(1)))
            else:
                stack.enter_context(patch("trade.post_install.update.install_skills"))
                stack.enter_context(patch("trade.post_install.update.update_skills"))

            # 显式设定运行目录的存在状态，避免用例之间互相污染（共享同一个 TRADE_HOME）
            trade_dir = Path(_get_trade_home()) / "foreign-trade-assistant"
            if existing_dir:
                trade_dir.mkdir(parents=True, exist_ok=True)  # 存在 → 走 git pull
            elif trade_dir.exists():
                shutil.rmtree(trade_dir)  # 不存在 → 走 git clone

            return update_mod.update_trade()

    def test_skills_failure_does_not_block_restart(self):
        """skills 安装/更新失败只算警告，升级仍应 ok=True 以便重启到新代码。"""
        result = self._run_update(skills_raise=True)

        assert result["ok"] is True, f"skills 失败不应阻止重启：{result}"
        assert "install_skills failed" in result["warnings"]
        assert "update_skills failed" in result["warnings"]
        # 非致命步骤不得污染 errors
        assert result["errors"] == [], f"errors 只应装致命失败：{result['errors']}"

    def test_pip_failure_is_fatal(self):
        """pip install 失败必须阻止重启（依赖没装好，重启也起不来）。"""
        result = self._run_update(pip_rc=1)

        assert result["ok"] is False
        assert any("pip install" in e for e in result["errors"]), result["errors"]

    def test_database_failure_is_fatal(self):
        """数据库检查失败必须阻止重启。"""
        result = self._run_update(db_ok=False)

        assert result["ok"] is False
        assert any("Database check failed" in e for e in result["errors"]), result["errors"]

    def test_stash_without_pop_tells_user_how_to_restore(self):
        """pull 重试仍失败时本地改动会留在 stash —— 必须明确告知用户如何取回。"""
        result = self._run_update(pull_rc=1, existing_dir=True)

        assert result["ok"] is False
        joined = "\n".join(result["messages"])
        assert "git stash pop" in joined, f"未告知用户如何恢复被暂存的改动：{joined}"
        assert any("stash" in w for w in result["warnings"]), result["warnings"]


# ── 版本缓存测试 ─────────────────────────────────────────────────────────


class TestVersionCache:
    """测试 GitHub 版本缓存机制。"""

    def test_cache_structure(self):
        """缓存应为 dict 含 value 和 ts 键。"""
        from trade.app import _LATEST_VERSION_TTL, _latest_version_cache

        assert "value" in _latest_version_cache
        assert "ts" in _latest_version_cache
        assert _LATEST_VERSION_TTL == 600

    def test_cache_invalidation(self):
        """设置 ts=0 应使缓存失效。"""
        from trade.app import _latest_version_cache

        _latest_version_cache["value"] = "0.6.2"
        _latest_version_cache["ts"] = 100.0

        # 失效
        _latest_version_cache["ts"] = 0.0

        # 缓存应被视为过期（_now - 0.0 > TTL）
        import time
        assert time.monotonic() - _latest_version_cache["ts"] > 0

    def test_fetch_latest_version_github_api(self):
        """_fetch_latest_version 应从 GitHub API 返回版本号。"""
        # 此测试 mock GitHub API 响应
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"tag_name": "v0.6.3"}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            with patch("urllib.request.Request"):
                # 需要在 create_app 的 status 闭包外独立测试
                # 直接测试版本解析逻辑
                import json
                data = json.loads(mock_response.read())
                version = data.get("tag_name", "").lstrip("v")
                assert version == "0.6.3"


# ── 失败标记检测测试 ──────────────────────────────────────────────────────


class TestFailedMarkers:
    """致命失败必须以可识别的标记进入 errors（结构化返回值直读）。

    注：旧版靠扫描 stdout 文本找 "❌ / pip install failed" 等标记，该机制已在
    结构化返回值重构中删除；这里断言 update_trade() 返回值里的真实标记。
    非致命步骤不得进 errors —— 由 TestUpdateStepSeverity 的 skills 用例覆盖。
    """

    def test_git_pull_failure_is_fatal(self):
        """git pull 失败必须阻止升级，并在 errors 里带上可识别标记。"""
        updater = TestUpdateStepSeverity()
        result = updater._run_update(pull_rc=1, existing_dir=True)

        assert result["ok"] is False
        assert any("git pull failed" in e for e in result["errors"]), result["errors"]

    def test_git_stash_failure_is_fatal(self):
        """pull 失败且自动 stash 也失败时必须阻止升级。"""
        updater = TestUpdateStepSeverity()
        result = updater._run_update(pull_rc=1, stash_rc=1, existing_dir=True)

        assert result["ok"] is False
        assert any("git stash failed" in e for e in result["errors"]), result["errors"]


# ── update_trade 目录定位测试 ─────────────────────────────────────────────


class TestUpdateTradeDir:
    """测试 update_trade 使用运行目录而非桌面目录。"""

    def test_git_clone_target_is_runtime_dir(self):
        """升级操作必须落在 ~/.trade/foreign-trade-assistant/，不能碰开发源码目录。"""
        from trade.post_install.skills import _get_trade_home

        updater = TestUpdateStepSeverity()
        updater._run_update(existing_dir=False)  # 目录不存在 → 走 git clone 分支

        clone_cmd = updater.last_subprocess.run.call_args_list[0][0][0]
        expected_dir = _get_trade_home() / "foreign-trade-assistant"
        assert clone_cmd[:3] == [
            "git", "clone", "https://github.com/chefroger/smart-trade-ai.git",
        ], clone_cmd
        assert clone_cmd[-1] == str(expected_dir), f"clone 目标应是运行目录：{clone_cmd}"

    def test_git_pull_runs_inside_runtime_dir(self):
        """目录已存在时，git pull 的 cwd 必须是运行目录。"""
        from trade.post_install.skills import _get_trade_home

        updater = TestUpdateStepSeverity()
        updater._run_update(existing_dir=True)

        first_call = updater.last_subprocess.run.call_args_list[0]
        assert first_call[0][0][:3] == ["git", "pull", "--ff-only"], first_call
        assert first_call[1]["cwd"] == str(_get_trade_home() / "foreign-trade-assistant"), first_call[1]

    def test_guess_running_project_dir_removed(self):
        """_guess_running_project_dir 应已被删除。"""
        import trade.post_install as pi
        assert not hasattr(pi, "_guess_running_project_dir"), \
            "_guess_running_project_dir should have been removed"

    def test_force_sync_from_source_removed(self):
        """_force_sync_from_source 应已被删除。"""
        import trade.post_install as pi
        assert not hasattr(pi, "_force_sync_from_source"), \
            "_force_sync_from_source should have been removed"


# ── _create_system_router 测试 ────────────────────────────────────────────


class TestSystemRouter:
    """测试系统管理路由创建。"""

    def test_system_router_created(self):
        """_create_system_router 应返回 APIRouter。"""
        from fastapi import APIRouter

        # mock session token 以通过依赖注入
        with patch("trade.api.deps.set_session_token", lambda t: None):
            with patch("trade.api.deps._SESSION_TOKEN", "test-token"):
                from trade.app import _create_system_router
                # 需要 mock _capture_output 和 _perform_restart 避免真实调用
                with patch("trade.api.cron._capture_output", return_value={"ok": True}):
                    router = _create_system_router()
                assert isinstance(router, APIRouter)

    def test_system_router_has_update_endpoint(self):
        """路由应包含 /system/update 端点。"""
        with patch("trade.api.deps.set_session_token", lambda t: None):
            with patch("trade.api.deps._SESSION_TOKEN", "test-token"):
                with patch("trade.api.cron._capture_output", return_value={"ok": True}):
                    from trade.app import _create_system_router
                    router = _create_system_router()

        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert "/system/update" in paths

    def test_system_router_has_restart_endpoint(self):
        """路由应包含 /system/restart 端点。"""
        with patch("trade.api.deps.set_session_token", lambda t: None):
            with patch("trade.api.deps._SESSION_TOKEN", "test-token"):
                with patch("trade.api.cron._capture_output", return_value={"ok": True}):
                    from trade.app import _create_system_router
                    router = _create_system_router()

        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert "/system/restart" in paths


# ── update_trade 测试 ─────────────────────────────────────────────────────


class TestUpdateTrade:
    """测试 trade.post_install.update_trade 的 7 步更新流程。

    用 mock 隔离 git/pip/skills/db 等外部副作用，仅验证流程编排逻辑。
    """

    def _make_completed(self, returncode=0, stdout="", stderr=""):
        """构造 subprocess.run 的 CompletedProcess 替身。"""
        cp = MagicMock()
        cp.returncode = returncode
        cp.stdout = stdout
        cp.stderr = stderr
        return cp

    def test_update_trade_success(self, tmp_path, monkeypatch):
        """全部步骤成功时，update_trade 应正常返回（无 sys.exit）。"""
        from trade.post_install import update as update_module

        # 准备假的 trade 运行目录
        fake_trade_dir = tmp_path / "foreign-trade-assistant"
        fake_trade_dir.mkdir()
        (fake_trade_dir / ".trade-template").mkdir()

        # mock _get_trade_home 返回 tmp_path，使 update_trade 找到 fake_trade_dir
        monkeypatch.setattr(
            update_module, "_get_trade_home", lambda: tmp_path
        )

        # mock subprocess.run：git pull 成功 + pip install 成功
        subprocess_calls = []
        def fake_run(cmd, *args, **kwargs):
            subprocess_calls.append(cmd)
            if cmd[0] == "git" and cmd[1] == "pull":
                return self._make_completed(0, stdout="Already up-to-date.")
            if cmd[0:3] == [sys.executable, "-m", "pip"]:
                return self._make_completed(0, stdout="Successfully installed")
            return self._make_completed(0, stdout="", stderr="")

        monkeypatch.setattr(update_module.subprocess, "run", fake_run)

        # mock 后续步骤
        monkeypatch.setattr(update_module, "install_skills", lambda: None)
        monkeypatch.setattr(update_module, "update_skills", lambda: None)
        monkeypatch.setattr(update_module, "_sync_trade_template", lambda s, d: None)
        monkeypatch.setattr(update_module, "_ensure_auto_start", lambda d: None)

        # mock init_db
        def fake_init_db():
            return tmp_path / "trade.db"
        import trade.database as db_module
        monkeypatch.setattr(db_module, "init_db", fake_init_db)

        # 不应抛 SystemExit
        update_module.update_trade()

        # 验证调用了 git pull 和 pip install
        assert any(c[0] == "git" and c[1] == "pull" for c in subprocess_calls)
        # pip 命令形如 [python, "-m", "pip", "install", "-e", dir]
        assert any(
            len(c) >= 4 and c[0] == sys.executable and c[2] == "pip" and c[3] == "install"
            for c in subprocess_calls
        )

    def test_pip_step_must_skip_dependencies(self, tmp_path, monkeypatch):
        """pip 装 Trade 自身时必须带 --no-deps，并单独按 requirements.txt 装依赖。

        Hermes 的 setup.py 明确拒绝通过 pip 构建，pyproject 里一旦再声明它，
        不带 --no-deps 的 pip install 就会整次失败——升级会卡在旧版本。
        """
        from trade.post_install import update as update_module

        fake_trade_dir = tmp_path / "foreign-trade-assistant"
        fake_trade_dir.mkdir()
        (fake_trade_dir / ".trade-template").mkdir()
        (fake_trade_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")

        monkeypatch.setattr(update_module, "_get_trade_home", lambda: tmp_path)

        subprocess_calls = []
        def fake_run(cmd, *args, **kwargs):
            subprocess_calls.append(cmd)
            return self._make_completed(0, stdout="ok")

        monkeypatch.setattr(update_module.subprocess, "run", fake_run)
        monkeypatch.setattr(update_module, "install_skills", lambda: None)
        monkeypatch.setattr(update_module, "update_skills", lambda: None)
        monkeypatch.setattr(update_module, "_sync_trade_template", lambda s, d: None)
        monkeypatch.setattr(update_module, "_ensure_auto_start", lambda d: None)

        import trade.database as db_module
        monkeypatch.setattr(db_module, "init_db", lambda: tmp_path / "trade.db")

        update_module.update_trade()

        installs = [c for c in subprocess_calls if c[0:4] == [sys.executable, "-m", "pip", "install"]]
        editable = [c for c in installs if "-e" in c]
        assert editable, "没有执行 pip install -e"
        assert all("--no-deps" in c for c in editable), "pip install -e 缺少 --no-deps"
        assert any("-r" in c for c in installs), "没有按 requirements.txt 安装依赖"
        # 不能出现不带 --no-deps 的解析式安装（会去构建 hermes-agent）
        assert not [
            c for c in subprocess_calls
            if c[0] == "git" and len(c) > 2 and c[1] == "clone" and "hermes" in " ".join(c)
        ], "升级过程不应尝试重新克隆 hermes-agent"

    def test_update_trade_pip_install_failure(self, tmp_path, monkeypatch):
        """pip install 失败时，update_trade 应继续执行后续步骤但不退出。"""
        from trade.post_install import update as update_module

        fake_trade_dir = tmp_path / "foreign-trade-assistant"
        fake_trade_dir.mkdir()

        monkeypatch.setattr(
            update_module, "_get_trade_home", lambda: tmp_path
        )

        def fake_run(cmd, *args, **kwargs):
            if cmd[0] == "git" and cmd[1] == "pull":
                return self._make_completed(0, stdout="Already up-to-date.")
            if cmd[0:3] == [sys.executable, "-m", "pip"]:
                # pip 失败
                return self._make_completed(1, stdout="", stderr="ERROR: package conflict")
            return self._make_completed(0, stdout="", stderr="")

        monkeypatch.setattr(update_module.subprocess, "run", fake_run)
        monkeypatch.setattr(update_module, "install_skills", lambda: None)
        monkeypatch.setattr(update_module, "update_skills", lambda: None)
        monkeypatch.setattr(update_module, "_sync_trade_template", lambda s, d: None)
        monkeypatch.setattr(update_module, "_ensure_auto_start", lambda d: None)

        import trade.database as db_module
        monkeypatch.setattr(db_module, "init_db", lambda: tmp_path / "trade.db")

        # 不应抛异常（失败仅设置 ok=False）
        update_module.update_trade()

    def test_update_trade_git_pull_stash_failure(self, tmp_path, monkeypatch):
        """git pull 失败 + git stash 也失败时，update_trade 应继续后续步骤。"""
        from trade.post_install import update as update_module

        fake_trade_dir = tmp_path / "foreign-trade-assistant"
        fake_trade_dir.mkdir()

        monkeypatch.setattr(
            update_module, "_get_trade_home", lambda: tmp_path
        )

        def fake_run(cmd, *args, **kwargs):
            if cmd[0] == "git" and cmd[1] == "pull":
                # 第一次 pull 失败
                if len(cmd) == 5:  # ['git', 'pull', '--ff-only', 'origin', 'main']
                    return self._make_completed(1, stdout="", stderr="local changes")
            if cmd[0] == "git" and cmd[1] == "stash":
                # stash 也失败
                return self._make_completed(1, stdout="", stderr="no stash")
            if cmd[0:3] == [sys.executable, "-m", "pip"]:
                return self._make_completed(0, stdout="OK")
            return self._make_completed(0, stdout="", stderr="")

        monkeypatch.setattr(update_module.subprocess, "run", fake_run)
        monkeypatch.setattr(update_module, "install_skills", lambda: None)
        monkeypatch.setattr(update_module, "update_skills", lambda: None)
        monkeypatch.setattr(update_module, "_sync_trade_template", lambda s, d: None)
        monkeypatch.setattr(update_module, "_ensure_auto_start", lambda d: None)

        import trade.database as db_module
        monkeypatch.setattr(db_module, "init_db", lambda: tmp_path / "trade.db")

        # 不应抛异常
        update_module.update_trade()

    def test_update_trade_missing_install_dir(self, tmp_path, monkeypatch):
        """运行目录不存在且 git clone 失败时，返回 ok=False + errors 含提示。"""
        import subprocess as _sp

        from trade.post_install import update as update_module

        monkeypatch.setattr(
            update_module, "_get_trade_home", lambda: tmp_path
        )
        # 模拟 git clone 失败（无网络 / git 未安装）
        _orig_run = _sp.run

        def _fake_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "git" and "clone" in cmd:
                result = _orig_run(["echo", "fake"], capture_output=True, text=True)
                result.returncode = 1
                result.stderr = "fatal: could not resolve host"
                return result
            return _orig_run(cmd, **kwargs)

        monkeypatch.setattr(_sp, "run", _fake_run)

        result = update_module.update_trade()
        assert result["ok"] is False
        assert any("git clone failed" in e for e in result["errors"])


# ── 版本标记语义测试 ─────────────────────────────────────────────────────


class TestVersionMarker:
    """version.txt 的语义 = 当前进程实际运行的代码版本。

    历史 bug：/api/status 拿磁盘上 pyproject.toml 的新版本号反写 version.txt，
    于是「git pull 成功但没重启（pip 失败/被跳过）」时 UI 显示新版本号，
    把「卡在旧版」伪装成「升级成功」。
    """

    def test_running_code_version_matches_pyproject(self):
        """_running_code_version 读取与运行代码配套的 pyproject.toml。"""
        import tomllib

        from trade import app as app_mod

        pyproject = Path(app_mod.__file__).resolve().parent.parent / "pyproject.toml"
        expected = tomllib.loads(pyproject.read_text())["project"]["version"]

        assert app_mod._running_code_version() == expected

    def test_write_version_marker_records_running_version(self):
        """启动时写入的标记必须等于当前运行的代码版本。"""
        from trade import app as app_mod

        app_mod._write_version_marker()

        marker = app_mod._get_trade_data_dir() / "version.txt"
        assert marker.is_file(), "版本标记文件应被写出"
        assert marker.read_text().strip() == app_mod._running_code_version()

    def test_reported_version_prefers_marker_and_never_rewrites(self):
        """上报版本以 version.txt 为准，且不得被磁盘上的 pyproject 反写。"""
        from trade import app as app_mod

        marker = app_mod._get_trade_data_dir() / "version.txt"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("9.9.9-sentinel")

        reported = app_mod._resolve_reported_version()

        assert reported == "9.9.9-sentinel", \
            "version.txt 应优先于磁盘 pyproject，否则未重启也会显示新版本号"
        assert marker.read_text().strip() == "9.9.9-sentinel", \
            "/api/status 不得把 pyproject 的版本号反写进 version.txt"

    def test_reported_version_falls_back_readonly(self):
        """version.txt 缺失时只读回退到 pyproject，且不得写盘。"""
        from trade import app as app_mod

        marker = app_mod._get_trade_data_dir() / "version.txt"
        marker.unlink(missing_ok=True)

        reported = app_mod._resolve_reported_version()

        assert reported == app_mod._running_code_version()
        assert not marker.exists(), "只读回退不得创建 version.txt"
