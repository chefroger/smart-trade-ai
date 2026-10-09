"""安装脚本的健壮性测试（install.sh / install.ps1）。

这些缺陷都是实测发现的：
- Step 4 用 `python -m trade.post_install install`，而该包**没有 __main__.py**
  → 这一步永远失败（stderr 被 2>/dev/null 吞掉），新装后 skills 数为 0。
- 克隆被中断会留下**空目录**，脚本用 `[ -d ]` 判定「已安装」→ 之后 git pull
  静默失败、pip 在残缺树里报出误导性错误，且**重试永远不好**。
- 全历史克隆是弱网下最慢的路径，且克隆/pip 的报错被 `2>/dev/null`、`| tail -1` 吞掉。
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SH = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
PS1 = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")



def _code_lines(text: str) -> str:
    """去掉注释行后的脚本内容。

    注释里会引用旧的错误写法（说明历史缺陷），断言只应针对真正的代码行。
    """
    return "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )


class TestSkillsInstallStep:
    """Step 4 必须调用真实存在的入口。"""

    def test_no_nonexistent_module_entry(self):
        """不得再用 `-m trade.post_install install`（该包没有 __main__.py）。"""
        for name, text in (("install.sh", SH), ("install.ps1", PS1)):
            assert "-m trade.post_install install" not in _code_lines(text), \
                f"{name} 仍在调用不存在的模块入口"

    def test_uses_working_entry(self):
        """必须出现可用的入口：console script 或 install_skills 调用。"""
        for name, text in (("install.sh", SH), ("install.ps1", PS1)):
            assert ("install-trade-skills" in text) or ("install_skills" in text), \
                f"{name} 找不到可用的 skills 安装入口"


class TestSkillsEntryActuallyWorks:
    """「脚本里用的入口」必须真的能把 skills 装进去（行为验证）。"""

    def test_install_skills_writes_into_hermes_home(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

        from trade.post_install import install_skills

        install_skills()

        installed = list((tmp_path / "hermes" / "skills").glob("*/SKILL.md"))
        assert len(installed) > 0, "install_skills() 应当把 skills 复制进 HERMES_HOME/skills"


class TestCloneRobustness:
    """克隆要能自愈、要浅、要不吞错。"""

    def test_shallow_clone(self):
        for name, text in (("install.sh", SH), ("install.ps1", PS1)):
            assert "--depth" in text, f"{name} 未使用浅克隆（弱网下全历史克隆最慢且最易失败）"

    def test_detects_invalid_leftover_checkout(self):
        """必须能识别「目录存在但不是有效 git 仓库」的残缺状态。"""
        for name, text in (("install.sh", SH), ("install.ps1", PS1)):
            assert "rev-parse --verify HEAD" in text, \
                f"{name} 未校验仓库有效性（残缺目录会被误判为已安装，导致重试永远失败）"

    def test_clone_errors_are_visible(self):
        """克隆命令不得把 stderr 丢掉。"""
        for name, text in (("install.sh", SH), ("install.ps1", PS1)):
            for line in _code_lines(text).splitlines():
                if "git clone" in line:
                    assert "2>/dev/null" not in line, f"{name} 克隆丢了 stderr: {line.strip()}"
                    assert "2>$null" not in line, f"{name} 克隆丢了 stderr: {line.strip()}"

    def test_pip_errors_are_visible(self):
        """pip 安装不得只留最后一行（会掩盖真实报错）。"""
        for name, text in (("install.sh", SH), ("install.ps1", PS1)):
            assert "install -e \".\" --quiet 2>&1 | tail -1" not in _code_lines(text), \
                f"{name} 仍在截断 pip 报错"


@pytest.mark.skipif(
    os.name == "nt",
    reason="需要真正的 POSIX bash：Windows runner 上的 bash 只是 WSL 存根（无发行版）。"
           "install.sh 的 shell 辅助函数只服务 macOS/Linux，Windows 侧由 install.ps1 承担"
           "（其行为已由本文件的静态断言覆盖）",
)
class TestCloneHelperBehaviour:
    """行为验证（不只是静态断言）：残缺目录必须能被重克隆。"""

    @staticmethod
    def _extract_helper() -> str:
        """从 install.sh 抽出 _clone_or_update 函数体（按花括号配对）。"""
        start = SH.index("_clone_or_update() {")
        depth = 0
        for i in range(start, len(SH)):
            if SH[i] == "{":
                depth += 1
            elif SH[i] == "}":
                depth -= 1
                if depth == 0:
                    return SH[start:i + 1]
        raise AssertionError("install.sh 里未找到 _clone_or_update 的结尾")

    @staticmethod
    def _make_local_repo(path: pathlib.Path) -> pathlib.Path:
        """造一个本地 git 仓库当克隆源（不需要网络）。"""
        import subprocess

        path.mkdir(parents=True, exist_ok=True)
        (path / "pyproject.toml").write_text('version = "1.0.0"\n', encoding="utf-8")
        git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
        subprocess.run([*git, "add", "-A"], cwd=path, check=True)
        subprocess.run([*git, "commit", "-qm", "init"], cwd=path, check=True)
        return path

    def _run_helper(self, repo: str, dest: pathlib.Path) -> tuple[str, int]:
        import subprocess

        script = (
            "log_info(){ :; }; log_ok(){ :; }; log_warn(){ :; }; log_err(){ :; }\n"
            + self._extract_helper()
            + f'\n_clone_or_update "test" "{repo}" "{dest}" && echo RESULT_OK || echo RESULT_FAIL\n'
        )
        proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        return proc.stdout + proc.stderr, proc.returncode

    def test_recovers_from_broken_leftover_directory(self, tmp_path):
        """目录存在但不是 git 仓库（克隆中断的残留）→ 必须重新克隆。

        旧逻辑用 `[ -d ]` 判定「已安装」，于是只跑 git pull（静默失败）+
        在残缺树里 pip install，重试永远无法恢复。
        """
        src = self._make_local_repo(tmp_path / "src")
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "leftover.txt").write_text("残留", encoding="utf-8")  # 非仓库内容

        out, _ = self._run_helper(str(src), dest)

        assert "RESULT_OK" in out, out
        assert (dest / ".git").is_dir(), f"残留目录未被重新克隆：{out}"
        assert (dest / "pyproject.toml").is_file(), "克隆后应含源仓库内容"

    def test_reuses_valid_checkout(self, tmp_path):
        """已是有效仓库时走更新分支，不重新克隆。"""
        src = self._make_local_repo(tmp_path / "src2")
        dest = tmp_path / "dest2"

        out, _ = self._run_helper(str(src), dest)   # 首次：克隆
        assert "RESULT_OK" in out, out
        marker = dest / "local-marker.txt"
        marker.write_text("本地标记", encoding="utf-8")

        out2, _ = self._run_helper(str(src), dest)  # 再次：应为 pull 分支
        assert "RESULT_OK" in out2, out2
        assert marker.is_file(), "走了重新克隆（本地文件被删）—— 应走更新分支"

    def test_reports_failure_when_repo_unavailable(self, tmp_path):
        """克隆源不可用时必须返回失败，让调用方中止（而不是继续用残缺树）。"""
        out, rc = self._run_helper(str(tmp_path / "no-such-repo"), tmp_path / "dest3")

        assert "RESULT_FAIL" in out, out
        assert rc == 0  # 脚本自身正常结束，失败通过返回值表达


class TestLauncherDisablesHermesLazyInstalls:
    """生成的启动器必须禁用 Hermes 懒加载重启。

    客户机实测（2026-10-08）：「网站诊断」时前端只显示「Agent 未返回有效回复」。
    成因是 `from run_agent import AIAgent` 连带执行 Hermes 的 `hermes_bootstrap.py`，
    它把 server.py 重新 exec 到 Hermes 自带的 store python（那里没有 trade 包），
    子进程 ModuleNotFoundError 退出，父进程 raise RelaunchExit(1)——继承 SystemExit，
    Trade 的 except Exception 抓不到，agent 线程静默死亡。

    `trade/bootstrap.py` 已在代码层设了这个开关；启动器里再设一次是双保险，而且
    **必须写进生成器**：`trade.cmd` 是 install.ps1 生成的产物，手改会被重装抹掉。
    """

    FLAG = "HERMES_DISABLE_LAZY_INSTALLS"

    def test_bash_launcher_sets_flag(self):
        assert self.FLAG in _code_lines(SH), (
            "install.sh 生成的 ~/.local/bin/trade 未禁用 Hermes 懒加载重启"
        )

    def test_powershell_launcher_sets_flag(self):
        assert self.FLAG in _code_lines(PS1), (
            "install.ps1 生成的 trade.cmd 未禁用 Hermes 懒加载重启"
        )

    def test_flag_value_is_one(self):
        """两个脚本都必须设成 1（上游判的是 == "1"，别的值等于没设）。"""
        import re

        for name, text in (("install.sh", SH), ("install.ps1", PS1)):
            body = _code_lines(text)
            # bash: export FLAG="1"  /  cmd: set FLAG=1
            assert re.search(rf'{self.FLAG}=(?:"1"|1)(\s|$)', body), (
                f"{name} 里 {self.FLAG} 的值不是 1"
            )


class TestPowerShellChecksPipExitCodes:
    """install.ps1 的每个 pip 调用后都必须检查 $LASTEXITCODE。

    历史 bug：Step 2（装 Hermes）显式查了退出码，Step 3（装 Trade 依赖）没查 ——
    而脚本自己在 105 行注释过「PowerShell 里原生命令非零退出不会抛异常」，
    同一个坑只堵了一半。后果：弱网下 requirements.txt 装失败，脚本照样打印
    「✓ Foreign Trade Assistant 安装完成」→「══ 安装完成 ══」，用户运行 trade
    只得到一句 ModuleNotFoundError，且开机自启任务每次登录都静默失败。

    macOS 走 install.sh（`set -e`，pip 失败即中止）所以开发机看不出来；
    CI 的 windows-latest 不跑安装脚本。
    """

    def test_each_pip_install_is_followed_by_exit_code_check(self):
        body = _code_lines(PS1)
        lines = body.splitlines()
        checked = 0

        for idx, line in enumerate(lines):
            if "& $PipCmd install" not in line:
                continue
            # 其后 3 行内必须出现 $LASTEXITCODE 判定
            window = "\n".join(lines[idx + 1: idx + 4])
            assert "$LASTEXITCODE" in window, (
                f"第 {idx + 1} 行的 `{line.strip()}` 之后没有检查 $LASTEXITCODE —— "
                "pip 失败会被当成安装成功"
            )
            checked += 1

        # 脚本里共 3 处 pip 调用：Hermes 装 1 处 + Trade 依赖/自身 2 处
        assert checked >= 3, f"应覆盖全部 3 处 pip 调用（Hermes 1 + Trade 2），实际 {checked}"

    def test_failure_exits_nonzero(self):
        """失败分支必须真的中止脚本，而不是只打印一行。"""
        body = _code_lines(PS1)

        assert "exit 1" in body, "安装失败没有 exit 1"


class TestPowerShellLauncherEncoding:
    """trade.cmd 用 ASCII 落盘会把中文用户名路径写成 '?'。

    `-Encoding ASCII` 把每个非 ASCII 字符替换为 `?` 且**不报错**。中文 Windows
    用户名（C:\\Users\\张伟\\...）是本产品的主力用户群，写坏后 `trade` 命令报
    「系统找不到指定的路径」，而自启任务用的是 API 传参（不受影响）——
    于是表现为「后台能跑、命令坏了」，更难排查。
    """

    def test_launcher_not_written_as_ascii(self):
        body = _code_lines(PS1)

        assert "-Encoding ASCII" not in body, (
            "trade.cmd 仍用 ASCII 编码 —— 中文用户名路径会被写成 '?'"
        )

    def test_launcher_uses_unicode_capable_encoding(self):
        import re

        body = _code_lines(PS1)

        assert re.search(r"-Encoding\s+(OEM|Default|UTF8|utf8)", body), (
            "应改用能承载非 ASCII 的编码（OEM/Default/UTF8）"
        )
