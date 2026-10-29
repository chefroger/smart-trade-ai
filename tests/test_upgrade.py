"""
升级管线测试 — _capture_output, _perform_restart, 版本检查, 失败标记检测。

使用 mock 避免真实 git pull / 进程管理 / GitHub API 调用。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


import pytest


@pytest.fixture(autouse=True)
def _bypass_interpreter_guard(monkeypatch):
    """绕过「解释器必须在 Trade venv 内」的守卫。

    这一组用例测的是升级的各**步骤**，而它们跑在开发/CI 解释器里（不是 Trade 的 venv），
    真实守卫会把整个流程拦掉 —— 那是守卫在正常工作，不是被测代码有问题。
    守卫自身的逻辑与接线由 tests/test_doctor.py::TestUpdateInterpreterGuard 覆盖。
    """
    from trade.post_install import update as upd

    monkeypatch.setattr(upd, "_refuse_reason_for_interpreter", lambda: None)


# 钉选测试用的稳定提交：默认让「远端 main」与「本地 HEAD」一致，
# 需要模拟漂移的用例自行覆盖 `_remote_main_sha` / `_git_head`。
PIN_SHA = "a" * 40

# 在 autouse fixture 替换之前留住真实实现，供解析函数自身的行为测试使用
from trade.post_install import update as _update_mod  # noqa: E402

_REAL_REMOTE_MAIN_SHA = _update_mod._remote_main_sha
_REAL_REMOTE_MAIN_SHA_FROM = _update_mod._remote_main_sha_from


@pytest.fixture(autouse=True)
def _pin_git_commit(monkeypatch):
    """默认固定钉选提交，避免每个用例都要为 ls-remote / rev-parse 造返回。

    钉选本身的解析与不一致处理由 TestUpdatePinning 覆盖；这里只是让其余
    「测某一步」的用例不必关心 git 交互。
    """
    from trade.post_install import update as upd

    monkeypatch.setattr(upd, "_remote_main_sha", lambda *a, **k: PIN_SHA)
    monkeypatch.setattr(upd, "_remote_main_sha_from", lambda *a, **k: PIN_SHA)
    monkeypatch.setattr(upd, "_git_head", lambda *a, **k: PIN_SHA)


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

def _classify_subprocess_cmd(cmd) -> str:
    """把被 mock 的命令分类成 git-stash / git-pull / git-other / pip / other。

    **只看程序名与参数，不看路径**。历史事故（2026-10-13 CI 随机失败）：
    旧实现用 `" ".join(cmd)` 做子串匹配，而 mkdtemp 的随机后缀恰好是
    `ypipz09g` → `git clone ... /tmp/trade-test-ypipz09g/...` 被判成 pip 命令
    → 假 subprocess 给 clone 返回失败码 → `test_pip_failure_is_fatal` 随机红。
    概率约万分之一，CI 上撞到了。
    """
    argv = [str(c) for c in cmd]
    if not argv:
        return "other"
    # 取程序名（去目录、去 .exe 后缀），大小写不敏感
    prog = argv[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    if prog.startswith("git"):
        if "stash" in argv:
            return "git-stash"
        if "pull" in argv:
            return "git-pull"
        return "git-other"  # clone / fetch 等
    # pip 可能是裸命令，也可能是 `python -m pip ...`（前 4 个参数足够覆盖）
    if "pip" in argv[:4]:
        return "pip"
    return "other"


class TestUpdateStepSeverity:
    """update_trade 的失败分级：只有 git / pip / 数据库算致命，其余只记警告。

    历史 bug：skills 步骤失败也把 ok 置为 False，导致「代码和依赖都已就绪却不重启」，
    用户被锁在旧代码上，而 /api/status 又会把磁盘上 pyproject.toml 的新版本号反写进
    version.txt —— 「卡在旧版」被伪装成「升级成功」。
    """

    @staticmethod
    def _fake_run(pull_rc=0, pip_rc=0, stash_rc=0):
        """按命令的**实际动作**分派返回码，替掉真实 subprocess.run。

        分类走 `_classify_subprocess_cmd`（看程序名+参数），**不要**对整条命令行
        做子串匹配 —— 见那个函数的说明（路径含 "pip" 导致 CI 随机红的事故）。
        """
        def _run(cmd, **kwargs):
            kind = _classify_subprocess_cmd(cmd)
            rc = 0
            if kind == "git-stash":
                rc = stash_rc
            elif kind == "git-pull":
                rc = pull_rc
            elif kind == "pip":
                rc = pip_rc
            result = MagicMock()
            result.returncode = rc
            result.stdout = ""
            result.stderr = "boom" if rc else ""
            return result
        return _run

    def _run_update(self, *, skills_raise=False, pull_rc=0, pip_rc=0,
                    stash_rc=0, db_ok=True, existing_dir=False,
                    skills_exc=None):
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

            # 调用方可用 skills_exc 指定具体异常类型；skills_raise=True 是
            # SystemExit 的简写（保持既有用例不变）
            skills_exc = skills_exc or (SystemExit(1) if skills_raise else None)

            # skills 步骤必须始终 mock：真实 install_skills 会写 ~/.hermes/skills，
            # update_skills 还会访问 GitHub —— 测试绝不能碰真实用户数据或网络
            if skills_exc is not None:
                stack.enter_context(patch("trade.post_install.update.install_skills", side_effect=skills_exc))
                stack.enter_context(patch("trade.post_install.update.update_skills", side_effect=skills_exc))
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
        # 警告文案带上了异常详情（便于定位），所以按前缀匹配而非精确相等
        assert any(w.startswith("install_skills failed") for w in result["warnings"]), result["warnings"]
        assert any(w.startswith("update_skills failed") for w in result["warnings"]), result["warnings"]
        # 非致命步骤不得污染 errors
        assert result["errors"] == [], f"errors 只应装致命失败：{result['errors']}"

    def test_pip_failure_is_fatal(self):
        """pip install 失败必须阻止重启（依赖没装好，重启也起不来）。"""
        result = self._run_update(pip_rc=1)

        assert result["ok"] is False
        assert any("pip install" in e for e in result["errors"]), result["errors"]

    def test_non_systemexit_skill_error_is_also_non_fatal(self):
        """skills 抛**非 SystemExit**（如目录只读的 PermissionError）同样非致命。

        历史 bug：这两步只捕 `except SystemExit`，而 install_skills 内部做文件
        复制（shutil.copy2/copytree），只读目录、磁盘满、杀软占用都会抛
        OSError/PermissionError。这类异常会穿透出去 —— 后果是半升级状态：
        代码已 git pull 到新版、依赖没装、服务不重启、UI 只有一个 500。
        """
        result = self._run_update(skills_exc=PermissionError("skills 目录只读"))

        assert result["ok"] is True, f"非 SystemExit 的 skills 失败不应致命：{result}"
        assert result["errors"] == []
        assert any("install_skills failed" in w for w in result["warnings"]), result["warnings"]

    def test_command_classifier_ignores_paths_containing_pip(self):
        """回归：命令的**路径**里含 "pip"/"git" 不得改变分类（CI 随机红的根因）。

        用事故现场的真实路径（/tmp/trade-test-ypipz09g）钉住。
        """
        clone = ["git", "clone", "https://github.com/x/y.git",
                 "/tmp/trade-test-ypipz09g/foreign-trade-assistant"]
        assert _classify_subprocess_cmd(clone) == "git-other"
        assert _classify_subprocess_cmd(["git", "-C", "/tmp/gitlab-proj", "pull", "--ff-only"]) == "git-pull"
        assert _classify_subprocess_cmd(["git", "-C", "/p", "stash"]) == "git-stash"
        assert _classify_subprocess_cmd(["/usr/bin/python3", "-m", "pip", "install", "-r", "req.txt"]) == "pip"
        assert _classify_subprocess_cmd(["pip", "install", "x"]) == "pip"
        # 路径含 "pip" 的 python 调用（不是 pip 安装）不得误判
        assert _classify_subprocess_cmd(["/opt/pipeline/python", "-c", "print(1)"]) == "other"

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


class TestNoReleaseVersionBaseline:
    """升级不再以 GitHub release tag 为基准（2026-10-26 用户决定）。

    release 版本号会落后于 main（修完不立刻发版），拿它比较会让用户错过
    main 上的修复；升级只认「拉取 main 最新内容」。
    """

    def test_status_does_not_query_github_releases(self):
        root = Path(__file__).resolve().parent.parent
        src = (root / "trade" / "app.py").read_text(encoding="utf-8")

        assert "releases/latest" not in src
        assert "latest_version" not in src
        assert "_latest_version_cache" not in src

    def test_confirm_dialog_does_not_show_release_target(self):
        root = Path(__file__).resolve().parent.parent
        src = (root / "static" / "trade_chat.js").read_text(encoding="utf-8")

        assert "sys.update_confirm_version" not in src
        assert "d.latest_version" not in src
        assert "/api/trade/system/update" in src


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

        # 首个调用现在是 `git rev-parse HEAD`（升级前记录回滚点，见 TestUpdateRollback），
        # 所以这里按命令找 pull，而不是假设它是第一次调用。
        calls = updater.last_subprocess.run.call_args_list
        pull = next(c for c in calls if c[0][0][:3] == ["git", "pull", "--ff-only"])
        assert pull[1]["cwd"] == str(_get_trade_home() / "foreign-trade-assistant"), pull[1]

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

    def test_pip_install_forces_no_user(self, tmp_path, monkeypatch):
        """W 修复：用户 pip.conf 的 no-user=1 不能把升级拖垮。

        pip 26 会把 `no-user = 1` 解析成 use_user_site 真值；venv 里做 --user
        安装必失败。升级必须显式带 --no-user + PIP_USER=0。
        """
        from trade.post_install import update as update_module

        monkeypatch.setenv("PIP_USER", "1")  # 模拟环境里已有的坏值
        assert update_module._pip_env()["PIP_USER"] == "0"

        fake_trade_dir = tmp_path / "foreign-trade-assistant"
        fake_trade_dir.mkdir()
        (fake_trade_dir / ".trade-template").mkdir()
        (fake_trade_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
        monkeypatch.setattr(update_module, "_get_trade_home", lambda: tmp_path)

        calls: list[tuple[list[str], dict]] = []

        def fake_run(cmd, *args, **kwargs):
            calls.append((list(cmd), kwargs))
            cp = MagicMock()
            cp.returncode, cp.stdout, cp.stderr = 0, "ok", ""
            return cp

        monkeypatch.setattr(update_module.subprocess, "run", fake_run)
        monkeypatch.setattr(update_module, "install_skills", lambda: None)
        monkeypatch.setattr(update_module, "update_skills", lambda: None)
        monkeypatch.setattr(update_module, "_sync_trade_template", lambda s, d: None)
        monkeypatch.setattr(update_module, "_ensure_auto_start", lambda d: None)
        import trade.database as db_module
        monkeypatch.setattr(db_module, "init_db", lambda: tmp_path / "trade.db")

        update_module.update_trade()

        pip_calls = [
            (cmd, kw) for cmd, kw in calls
            if cmd[:4] == [sys.executable, "-m", "pip", "install"]
        ]
        assert pip_calls, "没有执行 pip install"
        assert all("--no-user" in cmd for cmd, _ in pip_calls)
        assert all((kw.get("env") or {}).get("PIP_USER") == "0" for _, kw in pip_calls)

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
        # 显式 utf-8：pyproject.toml 含中文注释，Windows 默认 cp1252 会读失败
        expected = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]

        assert app_mod._running_code_version() == expected

    def test_write_version_marker_records_running_version(self):
        """启动时写入的标记必须等于当前运行的代码版本。"""
        from trade import app as app_mod

        app_mod._write_version_marker()

        marker = app_mod._get_trade_data_dir() / "version.txt"
        assert marker.is_file(), "版本标记文件应被写出"
        assert marker.read_text(encoding="utf-8").strip() == app_mod._running_code_version()

    def test_reported_version_prefers_marker_and_never_rewrites(self):
        """上报版本以 version.txt 为准，且不得被磁盘上的 pyproject 反写。"""
        from trade import app as app_mod

        marker = app_mod._get_trade_data_dir() / "version.txt"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("9.9.9-sentinel", encoding="utf-8")

        reported = app_mod._resolve_reported_version()

        assert reported == "9.9.9-sentinel", \
            "version.txt 应优先于磁盘 pyproject，否则未重启也会显示新版本号"
        assert marker.read_text(encoding="utf-8").strip() == "9.9.9-sentinel", \
            "/api/status 不得把 pyproject 的版本号反写进 version.txt"

    def test_reported_version_falls_back_readonly(self):
        """version.txt 缺失时只读回退到 pyproject，且不得写盘。"""
        from trade import app as app_mod

        marker = app_mod._get_trade_data_dir() / "version.txt"
        marker.unlink(missing_ok=True)

        reported = app_mod._resolve_reported_version()

        assert reported == app_mod._running_code_version()
        assert not marker.exists(), "只读回退不得创建 version.txt"


# ── 文本读写必须显式指定编码 ────────────────────────────────────────────────
# CI 的 windows-latest 任务抓到过：pyproject.toml 含中文注释，而未指定编码的
# read_text() 在 Windows 上按 cp1252 解码 → UnicodeDecodeError → 被 except 吞掉，
# version.txt 永远写不出来（产品行为，不只是测试问题）。
# macOS 上 Python 对 C locale 会强制 UTF-8，本地无法复现该条件，
# 所以这里锁住「显式指定编码」这一属性；端到端保障仍由 CI 的 windows 任务承担。


class TestTextEncodingIsExplicit:
    """版本相关的文件读写必须显式用 UTF-8，不依赖平台默认编码。"""

    def test_version_marker_io_is_explicitly_utf8(self, tmp_path, monkeypatch):
        """pyproject.toml 的读 + version.txt 的读写都必须显式 utf-8。"""
        import pathlib

        from trade import app as app_mod

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "x"  # 中文注释\nversion = "1.2.3"\n', encoding="utf-8"
        )
        monkeypatch.setattr(app_mod, "_pyproject_path", lambda: pyproject)

        seen: list[tuple[str, str | None]] = []
        _orig_read, _orig_write = pathlib.Path.read_text, pathlib.Path.write_text

        def _read(self, encoding=None, errors=None):
            seen.append(("read", encoding))
            return _orig_read(self, encoding=encoding, errors=errors)

        def _write(self, data, encoding=None, errors=None):
            seen.append(("write", encoding))
            return _orig_write(self, data, encoding=encoding, errors=errors)

        monkeypatch.setattr(pathlib.Path, "read_text", _read)
        monkeypatch.setattr(pathlib.Path, "write_text", _write)

        assert app_mod._running_code_version() == "1.2.3"
        assert app_mod._write_version_marker() == "1.2.3"
        assert app_mod._resolve_reported_version() == "1.2.3"

        # 每一次读写都必须带显式编码；缺失就会退回平台默认（Windows=cp1252）
        missing = [kind for kind, enc in seen if not enc]
        assert not missing, f"存在未指定编码的读写：{missing}"
        assert all(str(enc).lower().replace("-", "") == "utf8" for _, enc in seen), seen


class TestUpdateRollback:
    """致命失败必须回退源码，不能留下「新源码 + 旧依赖」的半升级状态。

    2026-10-21 审计 P0：git pull 成功后 pip 失败时，原实现直接 return —— 源码
    已经是新版、依赖还是旧版、服务也没重启。下次重启就会用新代码配旧依赖启动，
    直接起不来，且用户没有任何办法回到能跑的状态。
    """

    SHA = "a" * 40

    def _run(
        self, tmp_path, monkeypatch, *, pip_fail: str | None = None,
        db_fail: bool = False, reset_rc: int = 0,
        db_mutate: Path | None = None,
    ):
        """跑一次 update_trade，按需让某一步失败；返回 (结果, 调用记录)。"""
        from trade.post_install import update as update_module

        fake_trade_dir = tmp_path / "foreign-trade-assistant"
        fake_trade_dir.mkdir()
        (fake_trade_dir / ".trade-template").mkdir()
        (fake_trade_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
        monkeypatch.setattr(update_module, "_get_trade_home", lambda: tmp_path)

        calls: list[list[str]] = []

        def fake_run(cmd, *args, **kwargs):
            calls.append(list(cmd))
            cp = MagicMock()
            cp.stdout = cp.stderr = ""
            cp.returncode = 0
            if cmd[:3] == ["git", "rev-parse", "HEAD"]:
                cp.stdout = self.SHA + "\n"
            elif cmd[:2] == ["git", "pull"]:
                cp.stdout = "Fast-forward"
            elif cmd[:2] == ["git", "reset"]:
                cp.returncode = reset_rc
                cp.stderr = "error: could not reset" if reset_rc else ""
            elif cmd[:3] == ["git", "stash"]:
                cp.stdout = "No local changes"
            elif cmd[0:4] == [sys.executable, "-m", "pip", "install"]:
                # requirements.txt 与自身安装都是 pip install；用参数区分
                if pip_fail == "requirements" and "-r" in cmd:
                    cp.returncode = 1
                    cp.stderr = "ERROR: Could not install requirement"
                elif pip_fail == "self" and "--no-deps" in cmd:
                    cp.returncode = 1
                    cp.stderr = "ERROR: package build failed"
            return cp

        monkeypatch.setattr(update_module.subprocess, "run", fake_run)
        monkeypatch.setattr(update_module, "install_skills", lambda: None)
        monkeypatch.setattr(update_module, "update_skills", lambda: None)
        monkeypatch.setattr(update_module, "_sync_trade_template", lambda s, d: None)
        monkeypatch.setattr(update_module, "_ensure_auto_start", lambda d: None)

        import trade.database as db_module
        if db_fail:
            def boom():
                # 模拟"迁移改了一半才失败"：先真的写入一个表，再抛错
                if db_mutate is not None:
                    import sqlite3

                    conn = sqlite3.connect(str(db_mutate))
                    try:
                        conn.execute("CREATE TABLE failed_migration(x)")
                        conn.commit()
                    finally:
                        conn.close()
                raise sqlite3_error_ref()
            monkeypatch.setattr(db_module, "init_db", boom)
        else:
            monkeypatch.setattr(db_module, "init_db", lambda: tmp_path / "trade.db")

        return update_module.update_trade(), calls

    @pytest.mark.parametrize("which", ["requirements", "self"])
    def test_pip_failure_rolls_back_to_pre_update_commit(self, tmp_path, monkeypatch, which):
        result, calls = self._run(tmp_path, monkeypatch, pip_fail=which)

        assert result["ok"] is False
        resets = [c for c in calls if c[:2] == ["git", "reset"]]
        assert resets, "pip 失败后必须回退源码"
        assert "--keep" in resets[0], "必须用 --keep（--hard 会静默删掉用户的未提交改动）"
        assert self.SHA in resets[0]
        assert any("rolled back" in w for w in result["warnings"])

    def test_database_failure_also_rolls_back(self, tmp_path, monkeypatch):
        result, calls = self._run(tmp_path, monkeypatch, db_fail=True)

        assert result["ok"] is False
        assert [c for c in calls if c[:2] == ["git", "reset"]], (
            "数据库迁移失败也必须回退源码（新代码 + 半迁移的库重启只会更糟）"
        )

    def test_rollback_failure_is_reported_not_swallowed(self, tmp_path, monkeypatch):
        result, _calls = self._run(tmp_path, monkeypatch, pip_fail="self", reset_rc=1)

        assert result["ok"] is False
        # 原始错误仍在
        assert any("pip install" in e for e in result["errors"])
        # 回退失败必须让用户看见（含手动恢复命令）
        assert any("rollback" in w for w in result["warnings"])

    def test_success_does_not_roll_back(self, tmp_path, monkeypatch):
        result, calls = self._run(tmp_path, monkeypatch)

        assert result["ok"] is True
        assert not [c for c in calls if c[:2] == ["git", "reset"]], (
            "升级成功时不该回退"
        )

    def test_database_failure_restores_pre_upgrade_snapshot(self, tmp_path, monkeypatch):
        """迁移失败时不仅回滚代码，还要把库恢复到升级前的备份。

        审计 P1-10：ALTER TABLE 不可逆 —— 只回滚代码，旧版本面对的仍是
        半迁移的库，重启照样起不来。升级前那份备份就是为这一刻留的。
        """
        import sqlite3

        db_path = tmp_path / "data" / "trade.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("CREATE TABLE keep(x)")
            conn.execute("INSERT INTO keep VALUES (1)")
            conn.commit()
        finally:
            conn.close()

        result, _calls = self._run(
            tmp_path, monkeypatch, db_fail=True, db_mutate=db_path,
        )

        assert result["ok"] is False
        conn = sqlite3.connect(str(db_path))
        try:
            tables = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            assert "failed_migration" not in tables, (
                "迁移失败写入的表必须被备份覆盖掉"
            )
            assert conn.execute("SELECT COUNT(*) FROM keep").fetchone()[0] == 1
        finally:
            conn.close()
        assert any("恢复到升级前备份" in m for m in result["messages"]), result["messages"]


class TestUpdatePinning:
    """P1-10：更新钉选远端 main 的提交；拉取后 HEAD 不一致就中止并回退。"""

    def test_remote_main_sha_parses_ls_remote_output(self, monkeypatch):
        from trade.post_install import update as upd

        class _R:
            returncode = 0
            stdout = PIN_SHA + "\trefs/heads/main\n"
            stderr = ""

        monkeypatch.setattr(upd.subprocess, "run", lambda *a, **k: _R())
        monkeypatch.setattr(upd, "_remote_main_sha_from", _REAL_REMOTE_MAIN_SHA_FROM)
        assert _REAL_REMOTE_MAIN_SHA(Path("/tmp")) == PIN_SHA

    def test_remote_main_sha_rejects_unparseable_output(self, monkeypatch):
        from trade.post_install import update as upd

        class _R:
            returncode = 0
            stdout = "fatal: not a git repository\n"
            stderr = ""

        monkeypatch.setattr(upd.subprocess, "run", lambda *a, **k: _R())
        monkeypatch.setattr(upd, "_remote_main_sha_from", _REAL_REMOTE_MAIN_SHA_FROM)
        assert _REAL_REMOTE_MAIN_SHA(Path("/tmp")) is None

    def test_unresolvable_remote_aborts_before_touching_worktree(self, tmp_path, monkeypatch):
        from trade.post_install import update as upd

        trade_dir = tmp_path / "foreign-trade-assistant"
        trade_dir.mkdir()
        monkeypatch.setattr(upd, "_get_trade_home", lambda: tmp_path)
        calls: list[list[str]] = []

        def fake_run(cmd, *a, **k):
            calls.append(list(cmd))
            cp = MagicMock()
            cp.returncode = 0
            cp.stdout = cp.stderr = ""
            return cp

        monkeypatch.setattr(upd.subprocess, "run", fake_run)
        monkeypatch.setattr(upd, "_remote_main_sha", lambda *a, **k: None)

        result = upd.update_trade()

        assert result["ok"] is False
        assert any("cannot resolve remote main" in e for e in result["errors"])
        assert not [c for c in calls if c[:2] == ["git", "pull"]], (
            "解析不到钉选提交时不能拉取（否则装进来的是未经确认的版本）"
        )

    def test_fresh_clone_is_pinned_to_remote_sha(self, tmp_path, monkeypatch):
        """首次安装也必须 checkout 到钉选提交，不能直接吃 clone 那一刻的分支头。"""
        from trade.post_install import update as upd

        monkeypatch.setattr(upd, "_get_trade_home", lambda: tmp_path)
        calls: list[list[str]] = []

        def fake_run(cmd, *a, **k):
            calls.append(list(cmd))
            cp = MagicMock()
            cp.returncode = 0
            cp.stdout = cp.stderr = ""
            return cp

        monkeypatch.setattr(upd.subprocess, "run", fake_run)
        monkeypatch.setattr(upd, "install_skills", lambda: None)
        monkeypatch.setattr(upd, "update_skills", lambda: None)
        monkeypatch.setattr(upd, "_sync_trade_template", lambda *a, **k: None)
        monkeypatch.setattr(upd, "_ensure_auto_start", lambda *a, **k: None)

        import trade.database as db_module
        monkeypatch.setattr(db_module, "init_db", lambda: tmp_path / "trade.db")

        result = upd.update_trade()

        assert result["ok"] is True, result
        clone = next(c for c in calls if c[:2] == ["git", "clone"])
        assert clone[2].endswith("smart-trade-ai.git")
        assert any(
            c[:3] == ["git", "checkout", "-B"] and c[3] == "main" and PIN_SHA in c
            for c in calls
        ), calls

    def test_clone_checkout_failure_cleans_up_half_install(self, tmp_path, monkeypatch):
        from trade.post_install import update as upd

        monkeypatch.setattr(upd, "_get_trade_home", lambda: tmp_path)

        def fake_run(cmd, *a, **k):
            cp = MagicMock()
            cp.stdout = cp.stderr = ""
            cp.returncode = 1 if cmd[:2] == ["git", "checkout"] else 0
            return cp

        monkeypatch.setattr(upd.subprocess, "run", fake_run)
        monkeypatch.setattr(upd, "install_skills", lambda: None)
        monkeypatch.setattr(upd, "update_skills", lambda: None)

        result = upd.update_trade()

        assert result["ok"] is False
        assert not (tmp_path / "foreign-trade-assistant").exists(), (
            "检出钉选提交失败时必须删掉不完整目录"
        )

    def test_update_does_not_reenable_disabled_autostart(self, tmp_path, monkeypatch):
        """用户手动关掉自启后，更新不能又打开它（审计 P2-20）。"""
        from trade.post_install import update as upd

        trade_dir = tmp_path / "foreign-trade-assistant"
        trade_dir.mkdir()
        (trade_dir / ".trade-template").mkdir()
        monkeypatch.setattr(upd, "_get_trade_home", lambda: tmp_path)
        monkeypatch.setattr(upd, "_auto_start_present", lambda: False)
        ensure = MagicMock()
        monkeypatch.setattr(upd, "_ensure_auto_start", ensure)

        class _CP:
            returncode = 0
            stdout = stderr = ""

        monkeypatch.setattr(upd.subprocess, "run", lambda *a, **k: _CP())
        monkeypatch.setattr(upd, "install_skills", lambda: None)
        monkeypatch.setattr(upd, "update_skills", lambda: None)
        monkeypatch.setattr(upd, "_sync_trade_template", lambda *a, **k: None)

        import trade.database as db_module
        monkeypatch.setattr(db_module, "init_db", lambda: tmp_path / "trade.db")

        result = upd.update_trade()

        assert result["ok"] is True, result
        ensure.assert_not_called()
        assert any("不会重新打开" in m for m in result["messages"]), result["messages"]

    def test_fresh_install_still_registers_autostart(self, tmp_path, monkeypatch):
        from trade.post_install import update as upd

        monkeypatch.setattr(upd, "_get_trade_home", lambda: tmp_path)
        monkeypatch.setattr(upd, "_auto_start_present", lambda: False)
        ensure = MagicMock()
        monkeypatch.setattr(upd, "_ensure_auto_start", ensure)

        class _CP:
            returncode = 0
            stdout = stderr = ""

        monkeypatch.setattr(upd.subprocess, "run", lambda *a, **k: _CP())
        monkeypatch.setattr(upd, "install_skills", lambda: None)
        monkeypatch.setattr(upd, "update_skills", lambda: None)
        monkeypatch.setattr(upd, "_sync_trade_template", lambda *a, **k: None)

        import trade.database as db_module
        monkeypatch.setattr(db_module, "init_db", lambda: tmp_path / "trade.db")

        result = upd.update_trade()

        assert result["ok"] is True, result
        ensure.assert_called_once()

    def test_head_drift_aborts_and_rolls_back(self, tmp_path, monkeypatch):
        from trade.post_install import update as upd

        trade_dir = tmp_path / "foreign-trade-assistant"
        trade_dir.mkdir()
        (trade_dir / ".trade-template").mkdir()
        monkeypatch.setattr(upd, "_get_trade_home", lambda: tmp_path)
        calls: list[list[str]] = []

        def fake_run(cmd, *a, **k):
            calls.append(list(cmd))
            cp = MagicMock()
            cp.returncode = 0
            cp.stdout = ""
            cp.stderr = ""
            return cp

        monkeypatch.setattr(upd.subprocess, "run", fake_run)
        monkeypatch.setattr(upd, "install_skills", lambda: None)
        monkeypatch.setattr(upd, "update_skills", lambda: None)
        monkeypatch.setattr(upd, "_remote_main_sha", lambda *a, **k: "b" * 40)
        monkeypatch.setattr(upd, "_git_head", lambda *a, **k: "c" * 40)

        result = upd.update_trade()

        assert result["ok"] is False
        assert any("pinned head mismatch" in e for e in result["errors"]), result["errors"]
        assert [c for c in calls if c[:2] == ["git", "reset"]], (
            "HEAD 与钉选提交不一致时必须回退到升级前的提交"
        )


class TestPruneFailedMigrationCopies:
    def test_keeps_latest_three(self, tmp_path):
        from trade.post_install import update as upd

        for i in range(5):
            (tmp_path / f"trade-2026010{i}-120000-failed-migration.db").write_text(
                "x", encoding="utf-8",
            )
        (tmp_path / "trade-20260101-120000-before-upgrade.db").write_text(
            "x", encoding="utf-8",
        )

        upd._prune_failed_migration_copies(tmp_path)

        left = sorted(p.name for p in tmp_path.glob("*-failed-migration.db"))
        assert len(left) == 3
        assert left == [
            "trade-20260102-120000-failed-migration.db",
            "trade-20260103-120000-failed-migration.db",
            "trade-20260104-120000-failed-migration.db",
        ]
        # 升级前备份不属于现场副本，不能误删
        assert (tmp_path / "trade-20260101-120000-before-upgrade.db").is_file()


def sqlite3_error_ref():
    """构造一个不是 ImportError 的通用异常（模拟迁移失败）。"""
    return RuntimeError("migration failed")


class TestPreUpgradeBackup:
    """升级前必须有可回退的数据库快照，且快照要包含 WAL 里的已提交事务。

    2026-10-21 审计 P1：备份链路从不被升级调用；且原实现直接 copy2 主库，
    WAL 模式下会漏掉还在 -wal 里的已提交事务。
    """

    def test_snapshot_includes_wal_transactions(self, tmp_path):
        import sqlite3

        from trade.post_install.backup import snapshot_db

        db = tmp_path / "trade.db"
        writer = sqlite3.connect(db)
        try:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("CREATE TABLE t (x INTEGER)")
            writer.commit()
            writer.execute("INSERT INTO t VALUES (42)")
            writer.commit()
            # 写入者保持连接打开：这条已提交事务可能还在 -wal 里
            snap = tmp_path / "snap.db"
            snapshot_db(db, snap)
        finally:
            writer.close()

        reader = sqlite3.connect(snap)
        try:
            assert reader.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1, (
                "快照必须包含 WAL 中已提交的事务"
            )
        finally:
            reader.close()

    def test_backup_prunes_old_files(self, tmp_path):
        import sqlite3

        from trade.post_install.backup import backup_db_before_upgrade

        db = tmp_path / "trade.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.commit()
        conn.close()

        backups = tmp_path / "backups"
        backups.mkdir()
        for i in range(8):
            (backups / f"trade-2026010{i}-000000-before-upgrade.db").write_bytes(b"old")

        out = backup_db_before_upgrade(db, backups, keep=5)
        assert out is not None and out.is_file()
        remaining = list(backups.glob("trade-*-before-upgrade.db"))
        assert len(remaining) == 5, f"应只保留最近 5 份，实际 {len(remaining)}"

    def test_update_backs_up_before_git_pull(self, tmp_path, monkeypatch):
        """update_trade 必须在 git pull 之前落一份备份。"""
        import sqlite3

        from trade.post_install import update as update_module

        fake_trade_dir = tmp_path / "foreign-trade-assistant"
        fake_trade_dir.mkdir()
        (fake_trade_dir / ".trade-template").mkdir()
        (fake_trade_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
        (tmp_path / "data").mkdir()
        db = tmp_path / "data" / "trade.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.commit()
        conn.close()

        monkeypatch.setattr(update_module, "_get_trade_home", lambda: tmp_path)
        calls: list[list[str]] = []

        def fake_run(cmd, *args, **kwargs):
            calls.append(list(cmd))
            cp = MagicMock()
            cp.stdout = cp.stderr = ""
            cp.returncode = 0
            if cmd[:3] == ["git", "rev-parse", "HEAD"]:
                cp.stdout = "b" * 40
            return cp

        monkeypatch.setattr(update_module.subprocess, "run", fake_run)
        monkeypatch.setattr(update_module, "install_skills", lambda: None)
        monkeypatch.setattr(update_module, "update_skills", lambda: None)
        monkeypatch.setattr(update_module, "_sync_trade_template", lambda s, d: None)
        monkeypatch.setattr(update_module, "_ensure_auto_start", lambda d: None)

        import trade.database as db_module
        monkeypatch.setattr(db_module, "init_db", lambda: db)

        # 给备份打一个调用顺序标记（架构检查会先跑 uname/sysctl，不能用 calls[0] 判序）
        from trade.post_install import backup as backup_module

        real_backup = backup_module.backup_db_before_upgrade

        def recording_backup(*a, **k):
            calls.append(["backup"])
            return real_backup(*a, **k)

        monkeypatch.setattr(backup_module, "backup_db_before_upgrade", recording_backup)

        result = update_module.update_trade()
        assert result["ok"] is True

        backups = list((tmp_path / "backups").glob("*-before-upgrade.db"))
        assert len(backups) == 1, "升级必须留下数据库快照"
        assert any("升级前数据库备份" in m for m in result["messages"])

        backup_at = calls.index(["backup"])
        first_git = next(i for i, c in enumerate(calls) if c[:1] == ["git"])
        assert backup_at < first_git, "备份必须发生在任何 git 命令之前"

    def test_backup_failure_aborts_upgrade(self, tmp_path, monkeypatch):
        """备份失败必须中止升级 —— 没有回退点就不换代码、不迁 schema。"""
        from trade.post_install import backup as backup_module
        from trade.post_install import update as update_module

        fake_trade_dir = tmp_path / "foreign-trade-assistant"
        fake_trade_dir.mkdir()
        monkeypatch.setattr(update_module, "_get_trade_home", lambda: tmp_path)

        def boom(*a, **k):
            raise OSError("disk full")

        monkeypatch.setattr(backup_module, "backup_db_before_upgrade", boom)

        calls: list[list[str]] = []
        monkeypatch.setattr(
            update_module.subprocess, "run",
            lambda cmd, *a, **k: calls.append(list(cmd)),
        )

        result = update_module.update_trade()
        assert result["ok"] is False
        assert any("backup" in e for e in result["errors"])
        assert not [c for c in calls if c[:1] in (["git"], [sys.executable])], (
            "备份失败后不应再执行任何 git/pip 命令"
        )


class TestRollbackVerifiedByHead:
    """回退必须用**回读 HEAD** 验证，不能只信退出码。

    2026-10-21 真机实测：`git reset --keep` 遇到冲突的未提交改动时**静默放弃** ——
    既不改工作树也不报错，退出码仍是 0。只信退出码会把"没回退"误报成"已回退"，
    用户以为回到旧版本，实际代码还停在新版。
    """

    def test_keep_conflict_is_reported_as_failed(self, tmp_path, monkeypatch):
        from trade.post_install import update as update_module

        # 模拟：git reset --keep 返回 0，但 HEAD 没变（冲突静默放弃）
        monkeypatch.setattr(update_module, "_git_head", lambda d: "f" * 40)
        monkeypatch.setattr(
            update_module.subprocess, "run",
            lambda cmd, *a, **k: MagicMock(returncode=0, stdout="", stderr=""),
        )

        out: list[str] = []
        warnings: list[str] = []
        ok = update_module._rollback_checkout(
            tmp_path, "a" * 40, out.append, warnings,
        )

        assert ok is False, "HEAD 未变 → 必须报回退失败"
        assert any("回退未生效" in m for m in out)
        assert any("rollback" in w for w in warnings)

    def test_successful_rollback_is_confirmed(self, tmp_path, monkeypatch):
        from trade.post_install import update as update_module

        # 先返回旧 sha（记录回滚点），回退后 HEAD 应等于目标
        seq = iter(["a" * 40, "a" * 40])
        monkeypatch.setattr(update_module, "_git_head", lambda d: next(seq))
        monkeypatch.setattr(
            update_module.subprocess, "run",
            lambda cmd, *a, **k: MagicMock(returncode=0, stdout="", stderr=""),
        )
        monkeypatch.setattr(update_module, "install_skills", lambda: None)

        out: list[str] = []
        warnings: list[str] = []
        ok = update_module._rollback_checkout(
            tmp_path, "a" * 40, out.append, warnings,
        )

        assert ok is True
        assert any("已回退代码" in m for m in out)


class TestUpdateTargetPin:
    """W1：确认框的目标 SHA 必须原样钉进更新（显示即所用）。"""

    def test_normalize_sha(self):
        from trade.post_install import update as upd

        assert upd._normalize_sha("A" * 40) == "a" * 40
        assert upd._normalize_sha("a" * 39) is None
        assert upd._normalize_sha("z" * 40) is None
        assert upd._normalize_sha(None) is None
        # 防参数注入：不允许把 git 选项塞进来
        assert upd._normalize_sha("--upload-pack=x") is None

    def test_invalid_target_rejected_before_any_git(self, monkeypatch):
        from trade.post_install import update as upd

        called = []
        monkeypatch.setattr(upd, "_git_head", lambda d: called.append(d) or None)

        result = upd.update_trade("not-a-sha")

        assert result["ok"] is False
        assert "格式非法" in result["error"]
        assert called == [], "非法目标不得进入任何 git/备份步骤"

    def test_pending_update_record(self, monkeypatch, tmp_path):
        from trade.post_install import update as upd

        monkeypatch.setattr(upd, "_get_trade_home", lambda: tmp_path)
        upd._record_pending_update("b" * 40, "c" * 40, "0.7.0")

        import json

        data = json.loads(
            (tmp_path / "data" / "pending_update.json").read_text(encoding="utf-8")
        )
        assert data["pre_update_sha"] == "b" * 40
        assert data["target_sha"] == "c" * 40
        assert data["version"] == "0.7.0"

    def test_no_pending_record_for_fresh_install(self, monkeypatch, tmp_path):
        from trade.post_install import update as upd

        monkeypatch.setattr(upd, "_get_trade_home", lambda: tmp_path)
        upd._record_pending_update(None, "c" * 40, "0.7.0")

        assert not (tmp_path / "data" / "pending_update.json").exists()


class TestRestartWatchdog:
    def test_health_check_false_on_closed_port(self):
        from trade.restart_watchdog import _healthy, _wait_healthy

        # 1 端口不会是我们的服务
        assert _healthy(1, "nonce") is False
        assert _wait_healthy(1, 0.1, "nonce") is False

    def test_healthy_requires_matching_nonce(self, monkeypatch):
        """探活只认本次重启的 nonce：旧进程（别的 nonce）不能算健康。"""
        import json as _json

        from trade import restart_watchdog as w

        class _Resp:
            def __init__(self, data):
                self._body = _json.dumps(data).encode()

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        payload = {"app": "Foreign Trade Assistant", "nonce": "new-nonce"}
        monkeypatch.setattr(
            w.urllib.request, "urlopen", lambda *a, **k: _Resp(payload),
        )

        assert w._healthy(9119, "new-nonce") is True
        assert w._healthy(9119, "old-nonce") is False
        assert w._healthy(9119, "") is False  # 空 nonce fail-closed

    def test_wait_healthy_stops_when_new_process_exits(self):
        from trade import restart_watchdog as w

        class _Proc:
            def poll(self):
                return 1

        assert w._wait_healthy(1, 10, "nonce", _Proc()) is False

    def test_started_at_fallback_when_no_nonce(self, monkeypatch):
        """回退到旧代码时它不认识 nonce：只能按启动时间判定。"""
        import json as _json

        from trade import restart_watchdog as w

        class _Resp:
            def __init__(self, data):
                self._body = _json.dumps(data).encode()

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def _patch(started_at):
            payload = {"app": "Foreign Trade Assistant", "started_at": started_at}
            monkeypatch.setattr(
                w.urllib.request, "urlopen", lambda *a, **k: _Resp(payload),
            )

        _patch(1000.0)
        # 早于回退拉起时刻 → 是没被杀掉的旧进程，不算健康
        assert w._healthy(9119, "", 2000.0) is False
        # 晚于回退拉起时刻 → 是本次回退拉起的进程
        assert w._healthy(9119, "", 500.0) is True
        # 无 nonce 也无时间下界 → fail-closed
        assert w._healthy(9119, "") is False

    def test_legacy_cli_args_are_accepted(self, tmp_path, monkeypatch):
        """升级前的旧进程只会传 --old-started-at：不能让 argparse 报错退出。"""
        from trade import restart_watchdog as w

        spawned = {}

        class _Proc:
            pid = 4242

            def poll(self):
                return None

        def fake_spawn(cmd, workdir, nonce=""):
            spawned["nonce"] = nonce
            return _Proc()

        monkeypatch.setattr(w, "_spawn", fake_spawn)
        monkeypatch.setattr(w, "_kill", lambda *a, **k: None)
        monkeypatch.setattr(w, "_proc_create_time", lambda pid: None)
        monkeypatch.setattr(w.time, "sleep", lambda *_a: None)
        monkeypatch.setattr(w, "_wait_healthy", lambda *a, **k: True)

        code = w.main([
            "--old-pid", "1", "--port", "9119", "--old-started-at", "123.0",
            "--pre-sha", "a" * 40, "--repo", str(tmp_path),
            "--workdir", str(tmp_path), "--log", str(tmp_path / "wd.log"),
            "--", "python", "server.py",
        ])

        assert code == 0, "旧命令行必须能跑通，否则用户点重启服务静默不动"
        assert spawned["nonce"], "旧调用方没传 nonce 时，watchdog 必须自己生成一个"

    def test_launchd_path_uses_kickstart_and_never_spawns(self, tmp_path, monkeypatch):
        """KeepAlive 托管：重启必须交给 launchctl，不能再自己 spawn 抢端口。"""
        from trade import restart_watchdog as w

        calls = {"kickstart": 0, "spawn": 0, "kill": 0}

        def _boom(*a, **k):
            calls["spawn"] += 1
            raise AssertionError("launchd 托管时不得自己 spawn")

        def _kill(*a, **k):
            calls["kill"] += 1

        monkeypatch.setattr(w, "_spawn", _boom)
        monkeypatch.setattr(w, "_kill", _kill)
        monkeypatch.setattr(w.time, "sleep", lambda *_a: None)
        monkeypatch.setattr(
            w, "_kickstart",
            lambda label, log: calls.__setitem__("kickstart", calls["kickstart"] + 1) or True,
        )
        monkeypatch.setattr(w, "_wait_healthy", lambda *a, **k: True)

        pending = tmp_path / "pending_update.json"
        pending.write_text("{}", encoding="utf-8")

        code = w.main([
            "--old-pid", "1", "--port", "9119",
            "--launchd-label", "com.trade.assistant",
            "--pre-sha", "a" * 40, "--repo", str(tmp_path),
            "--workdir", str(tmp_path), "--pending-file", str(pending),
            "--log", str(tmp_path / "wd.log"),
            "--", "python", "server.py",
        ])

        assert code == 0
        assert calls == {"kickstart": 1, "spawn": 0, "kill": 0}
        assert not pending.exists(), "健康后必须清掉 pending 现场"

    def test_launchd_unhealthy_rolls_back_then_kickstarts_again(self, tmp_path, monkeypatch):
        from trade import restart_watchdog as w

        kicks = []

        monkeypatch.setattr(w.time, "sleep", lambda *_a: None)
        monkeypatch.setattr(
            w, "_kickstart",
            lambda label, log: kicks.append(label) or True,
        )
        # 第一次不健康，回退后第二次健康
        health = iter([False, True])
        monkeypatch.setattr(w, "_wait_healthy", lambda *a, **k: next(health))
        rolled = []
        monkeypatch.setattr(
            w, "_rollback",
            lambda repo, sha, log: rolled.append(sha) or True,
        )

        pending = tmp_path / "pending_update.json"
        pending.write_text("{}", encoding="utf-8")

        code = w.main([
            "--old-pid", "1", "--port", "9119",
            "--launchd-label", "com.trade.assistant",
            "--pre-sha", "a" * 40, "--repo", str(tmp_path),
            "--workdir", str(tmp_path), "--pending-file", str(pending),
            "--log", str(tmp_path / "wd.log"),
            "--", "python", "server.py",
        ])

        assert code == 2
        assert rolled == ["a" * 40]
        assert len(kicks) == 2, "回退后必须再 kickstart 一次"
        assert not pending.exists()

    def test_launchd_kickstart_command_and_rc(self, tmp_path, monkeypatch):
        from trade import restart_watchdog as w

        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            cp = MagicMock()
            cp.returncode = 0
            cp.stderr = b""
            return cp

        monkeypatch.setattr(w.subprocess, "run", fake_run)
        assert w._kickstart("com.trade.assistant", tmp_path / "x.log") is True
        assert seen["cmd"][:3] == ["launchctl", "kickstart", "-k"]
        assert seen["cmd"][3].endswith("/com.trade.assistant")

    def test_main_uses_parse_known_args(self):
        """新版调用方多传参数时不能直接崩：必须 parse_known_args。"""
        import inspect

        from trade import restart_watchdog as w

        src = inspect.getsource(w.main)
        assert "parse_known_args(" in src
        assert "p.parse_args(" not in src


class TestLaunchdDetection:
    """KeepAlive 托管识别：认错会导致 restart 与 launchd 抢端口、回滚代码。"""

    def _patch(self, monkeypatch, tmp_path, platform="darwin", plist=True,
               stdout=None, rc=0):
        from trade import app as app_mod

        monkeypatch.setattr(sys, "platform", platform)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
        if plist:
            d = tmp_path / "Library" / "LaunchAgents"
            d.mkdir(parents=True)
            (d / "com.trade.assistant.plist").write_text("x", encoding="utf-8")

        class _R:
            returncode = rc

            def __init__(self):
                self.stdout = stdout if stdout is not None else ""

        monkeypatch.setattr(app_mod._sp, "run", lambda *a, **k: _R())
        return app_mod

    def test_non_macos_is_never_managed(self, monkeypatch, tmp_path):
        mod = self._patch(monkeypatch, tmp_path, platform="linux")
        assert mod._launchd_label_if_managed() == ""

    def test_missing_plist_is_not_managed(self, monkeypatch, tmp_path):
        mod = self._patch(monkeypatch, tmp_path, plist=False)
        assert mod._launchd_label_if_managed() == ""

    def test_our_pid_running_is_managed(self, monkeypatch, tmp_path):
        mod = self._patch(
            monkeypatch, tmp_path,
            stdout=(
                "PID\tStatus\tLabel\n"
                "123\t0\tcom.apple.something\n"
                f"{os.getpid()}\t-15\tcom.trade.assistant\n"
            ),
        )
        assert mod._launchd_label_if_managed() == "com.trade.assistant"

    def test_other_pid_is_not_managed(self, monkeypatch, tmp_path):
        """其它实例在跑（手动起了第二份）→ 本进程不该交给 launchctl。"""
        mod = self._patch(
            monkeypatch, tmp_path, stdout="99999\t-15\tcom.trade.assistant\n",
        )
        assert mod._launchd_label_if_managed() == ""

    def test_job_loaded_but_not_running(self, monkeypatch, tmp_path):
        mod = self._patch(
            monkeypatch, tmp_path, stdout="-\t0\tcom.trade.assistant\n",
        )
        assert mod._launchd_label_if_managed() == ""

    def test_label_absent_from_table(self, monkeypatch, tmp_path):
        mod = self._patch(
            monkeypatch, tmp_path, stdout="123\t0\tcom.apple.other\n",
        )
        assert mod._launchd_label_if_managed() == ""

    def test_launchctl_missing_degrades(self, monkeypatch, tmp_path):
        mod = self._patch(monkeypatch, tmp_path)

        def _raise(*a, **k):
            raise FileNotFoundError("launchctl")

        monkeypatch.setattr(mod._sp, "run", _raise)
        assert mod._launchd_label_if_managed() == ""

    def test_stash_pop_conflict_aborts_and_restores(self, tmp_path, monkeypatch):
        """stash pop 冲突：升级立即中止，代码恢复到 pre_update_sha，改动留在 stash。"""
        from trade.post_install import update as upd

        fake_trade_dir = tmp_path / "foreign-trade-assistant"
        fake_trade_dir.mkdir()
        monkeypatch.setattr(upd, "_get_trade_home", lambda: tmp_path)
        pre_sha = "a" * 40
        monkeypatch.setattr(upd, "_git_head", lambda d: pre_sha)
        monkeypatch.setattr(upd, "_remote_main_sha", lambda d: "b" * 40)

        pulled = {"first": False}
        calls = []

        def fake_run(cmd, *a, **k):
            calls.append(list(cmd))
            cp = MagicMock()
            cp.returncode, cp.stdout, cp.stderr = 0, "", ""
            if cmd[:3] == ["git", "pull", "--ff-only"] and not pulled["first"]:
                cp.returncode, cp.stderr = 1, "diverged"
                pulled["first"] = True
            elif cmd[:3] == ["git", "stash", "pop"]:
                cp.returncode, cp.stderr = 1, "CONFLICT"
            return cp

        monkeypatch.setattr(upd.subprocess, "run", fake_run)
        monkeypatch.setattr(upd, "install_skills", lambda: None)
        monkeypatch.setattr(upd, "update_skills", lambda: None)

        result = upd.update_trade()

        assert result["ok"] is False
        assert "stash" in result["error"]
        assert any(
            c[:3] == ["git", "reset", "--hard"] and pre_sha in c for c in calls
        ), "必须恢复到升级前代码，不能停在冲突态"

    def test_rollback_resets_repo(self, tmp_path):
        """探活失败后的回退是真的 git reset，不是只打日志。"""
        import subprocess as sp

        from trade.restart_watchdog import _rollback

        repo = tmp_path / "repo"
        repo.mkdir()
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

        def run(*args):
            return sp.run(
                ["git", "-C", str(repo), *args],
                capture_output=True, text=True,
                env={**os.environ, **env}, check=True,
            )

        run("init", "-q")
        (repo / "f.txt").write_text("v1", encoding="utf-8")
        run("add", ".")
        run("commit", "-qm", "v1")
        first = sp.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        (repo / "f.txt").write_text("v2", encoding="utf-8")
        run("commit", "-qam", "v2")

        log = tmp_path / "watchdog.log"
        assert _rollback(str(repo), first, log) is True
        head = sp.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        assert head == first
        assert "rolled back" in log.read_text(encoding="utf-8")


class TestRequestedShaPins:
    def test_requested_sha_is_pinned_without_refetching_main(self, tmp_path, monkeypatch):
        from trade.post_install import update as upd

        fake_trade_dir = tmp_path / "foreign-trade-assistant"
        fake_trade_dir.mkdir()
        (fake_trade_dir / ".trade-template").mkdir()
        monkeypatch.setattr(upd, "_get_trade_home", lambda: tmp_path)
        target = "c" * 40
        monkeypatch.setattr(upd, "_git_head", lambda d: target)
        monkeypatch.setattr(
            upd, "_remote_main_sha",
            lambda d: (_ for _ in ()).throw(AssertionError("不得再取 main 头")),
        )
        calls = []

        def fake_run(cmd, *a, **k):
            calls.append(cmd)
            cp = MagicMock()
            cp.returncode, cp.stdout, cp.stderr = 0, "Already up-to-date.", ""
            return cp

        monkeypatch.setattr(upd.subprocess, "run", fake_run)
        monkeypatch.setattr(upd, "install_skills", lambda: None)
        monkeypatch.setattr(upd, "update_skills", lambda: None)
        monkeypatch.setattr(upd, "_sync_trade_template", lambda s, d: None)
        monkeypatch.setattr(upd, "_ensure_auto_start", lambda d: None)
        import trade.database as db_module
        monkeypatch.setattr(db_module, "init_db", lambda: tmp_path / "trade.db")

        result = upd.update_trade(target)

        assert result["ok"] is True
        assert result["target_sha"] == target
        assert any(c[:2] == ["git", "merge-base"] for c in calls)
        assert any(c[:2] == ["git", "reset"] and target in c for c in calls)


class TestSystemRouterUpdatePreview:
    def test_router_has_update_preview_and_target_body(self):
        from trade.app import _create_system_router

        router = _create_system_router()
        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert "/system/update-preview" in paths

    def test_hermes_success_hook_is_manual_restart(self):
        """Hermes 升级成功不再自动重启（W1）。"""
        src = (Path(__file__).resolve().parent.parent / "trade" / "app.py").read_text(
            encoding="utf-8"
        )
        assert "set_success_hook(_mark_hermes_restart_required)" in src
        assert "set_success_hook(_perform_restart)" not in src
        assert '"restart_required": _RESTART_REQUIRED["hermes"]' in src
