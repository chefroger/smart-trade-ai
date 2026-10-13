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


class TestHermesVersionPin:
    """安装脚本必须把 Hermes 固定在**已核对兼容**的版本上，而不是 main 尖端。

    为什么：main 每天前进约 200 个提交，一旦版本号越出 Trade 声明的兼容窗口
    （0.13.0 ≤ v < 0.22.0，`trade/bootstrap.py` / `pre_install_check.py`），
    新装机器会「装得上、起不来」—— 最坏的一类安装问题。固定到 release tag
    同时也让装机结果可复现。

    **另一条硬约束（2026-10-13 实测）**：上游从 v0.21.6 起把 45/46 条核心依赖
    都标成 `; python_version >= '3.14'`（requires-python 却仍写 >=3.11）。
    在 Python 3.11–3.13 上 `pip install -e hermes-agent` 会**一条依赖都不装**
    （实测 3.13：装完只有 2 个包），Hermes 直接起不来。所以安装 pin 必须落在
    marker 之前的 tag（当前为 v2026.9.24），并实测过「装完依赖齐全」。
    """

    @staticmethod
    def _pinned_ref(name: str, text: str) -> str:
        """从 TRADE_HERMES_REF 赋值行取出固定的 **ref（tag 名）**，如 v2026.9.24。

        保留完整 ref（不是拆出的语义化版本号）：pin 可能是日期式 tag
        （v2026.9.24），也可能对回语义化 tag（v0.21.6）—— 两者都要能核对。

        **必须跳过注释行**：注释里举了「临时装别的版本」的例子（含另一个版本号），
        按行扫描会把例子当成固定值 —— 第一版就是这么写的，mutation 检验时
        才发现「把 pin 改成不存在的版本」测不出来（解析到了注释里的旧版本）。
        """
        import re

        for line in text.splitlines():
            if line.strip().startswith("#"):
                continue  # 注释里的示例不算
            if "TRADE_HERMES_REF" in line:
                m = re.search(r"(v[0-9][0-9A-Za-z.\-]*)", line)
                if m:
                    return m.group(1).rstrip(".")
        raise AssertionError(f"{name} 未见固定的 Hermes ref（TRADE_HERMES_REF 行）")

    def test_both_scripts_pin_a_version(self):
        for name, text in (("install.sh", SH), ("install.ps1", PS1)):
            self._pinned_ref(name, text)  # 取不到会抛错
            assert "TRADE_HERMES_REF" in text, f"{name} 未提供 TRADE_HERMES_REF 覆盖入口"

    def test_clone_uses_the_ref_variable_not_hardcoded_main(self):
        """克隆必须走 ref 变量 —— 写死 main 会让固定版本静默失效。"""
        assert '--branch "$ref"' in SH, "install.sh 的克隆未使用 ref 变量"
        assert "--branch $Ref" in PS1, "install.ps1 的克隆未使用 Ref 变量"

    def test_hermes_step_passes_the_pinned_ref(self):
        """Step 2 调用克隆辅助函数时必须把固定版本传进去（漏传 = 退回 main）。"""
        assert (
            '_clone_or_update "hermes-agent" "$HERMES_REPO" "$HERMES_DIR" "$HERMES_REF"'
            in SH
        ), "install.sh 的 Hermes 步骤未传固定版本"
        assert (
            'Invoke-CloneOrUpdate "hermes-agent" $HermesRepo $HermesDir $HermesRef'
            in PS1
        ), "install.ps1 的 Hermes 步骤未传固定版本"

    def test_pinned_version_is_declared_compatible(self):
        """脚本固定的版本必须在 COMPATIBILITY.md 里标为兼容 —— 两边不许漂移。

        这条防的是「升了脚本的 pin、忘了核对/记录」：那会装出一个没验证过的版本。
        """
        compat = (ROOT / "COMPATIBILITY.md").read_text(encoding="utf-8")
        for name, text in (("install.sh", SH), ("install.ps1", PS1)):
            ref = self._pinned_ref(name, text)
            # 兼容矩阵的行既有语义化版本号（0.21.5），也有的备注里写 tag 名；
            # 只要**某条 ✅ 行提到这个 ref** 就算核对过（v2026.9.24 这种日期式
            # tag 没有同名版本行，靠 0.21.5 那行的备注关联）。
            assert any(
                "✅" in line and ref in line for line in compat.splitlines()
            ), f"{name} 固定的 {ref} 未在任何 ✅ 兼容行中出现（未核对/未记录）"

    def test_pinned_version_matches_between_scripts(self):
        """两个脚本固定同一 ref（跨平台一致性）。"""
        assert self._pinned_ref("install.sh", SH) == self._pinned_ref("install.ps1", PS1)

    def test_readme_manual_install_uses_the_same_pin(self):
        """README 的手动安装命令必须与脚本同一固定版本（三处不许漂移）。

        手动安装是「方式 3」，走 README 的用户不经过安装脚本 —— 这里不钉住的话，
        脚本固定了、文档还在装 main，问题原样复现。
        """
        pin = self._pinned_ref("install.sh", SH)
        for name in ("README.md", "README.en.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            lines = [ln for ln in text.splitlines() if "NousResearch/hermes-agent.git" in ln]
            assert lines, f"{name} 未见 Hermes 克隆命令"
            for ln in lines:
                assert pin in ln, f"{name} 的 Hermes 克隆未用固定版本 {pin}：{ln.strip()}"


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

    def _run_helper(self, repo: str, dest: pathlib.Path, ref: str | None = None) -> tuple[str, int]:
        import subprocess

        extra = f' "{ref}"' if ref else ""
        script = (
            "log_info(){ :; }; log_ok(){ :; }; log_warn(){ :; }; log_err(){ :; }\n"
            + self._extract_helper()
            + f'\n_clone_or_update "test" "{repo}" "{dest}"{extra} && echo RESULT_OK || echo RESULT_FAIL\n'
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

    def test_pinned_ref_clones_that_tag_and_never_moves_to_main(self, tmp_path):
        """固定版本模式：克隆指定 tag，且**再次运行时不得被拖到 main 尖端**。

        背景：main 每天前进约 200 个提交，一旦越出 Trade 的兼容窗口
        （0.13.0 ≤ v < 0.22.0），新装机器会「装得上、起不来」。所以安装脚本把
        Hermes 固定在已核对兼容的 release tag 上 —— 而固定只有在**不会**被
        后续 pull main 悄悄带走时才有意义（在 tag 检出上 `git pull origin main`
        会直接快进到 main 尖端）。
        """
        import subprocess

        src = self._make_local_repo(tmp_path / "src_pin")
        git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
        subprocess.run(["git", "tag", "v0.21.7"], cwd=src, check=True)
        tag_sha = subprocess.run(
            ["git", "rev-parse", "v0.21.7"], cwd=src, capture_output=True, text=True, check=True
        ).stdout.strip()

        dest = tmp_path / "dest_pin"
        out, _ = self._run_helper(str(src), dest, ref="v0.21.7")
        assert "RESULT_OK" in out, out
        head1 = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=dest, capture_output=True, text=True, check=True
        ).stdout.strip()
        assert head1 == tag_sha, f"克隆未落在固定 tag 上：{out}"

        # 源仓库 main 前进（模拟上游发新版），再次运行安装脚本
        (src / "new.txt").write_text("新提交", encoding="utf-8")
        subprocess.run([*git, "add", "-A"], cwd=src, check=True)
        subprocess.run([*git, "commit", "-qm", "advance main"], cwd=src, check=True)

        out2, _ = self._run_helper(str(src), dest, ref="v0.21.7")
        assert "RESULT_OK" in out2, out2
        head2 = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=dest, capture_output=True, text=True, check=True
        ).stdout.strip()
        assert head2 == tag_sha, f"固定 tag 被拖到了 main 尖端（固定失效）：{out2}"


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
