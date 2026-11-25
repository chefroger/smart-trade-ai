"""Release 工作流：Mac 独立包不内嵌 Hermes，运行时用用户自己那份。

2026-11-23 实跑结论：PyPI 的 `hermes-agent` 只有 0.15.2（低于最低要求
0.21.6），官方最新版装不进构建环境。因此构建不再尝试 pip 安装 Hermes；
`tradewin-mac.spec` 也不收集 hermes 模块，改由 bootstrap 的 frozen 分支
在运行时加载 `~/.hermes/hermes-agent`。构建解释器仍须是 3.14，才能加载
用户托管环境的 cp314 依赖。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
MAC_SPEC = (ROOT / "tradewin-mac.spec").read_text(encoding="utf-8")


class TestReleaseDoesNotBundleHermes:
    def test_release_does_not_pip_install_hermes(self):
        assert "pip install hermes-agent" not in RELEASE
        assert "continue-on-error" not in RELEASE

    def test_spec_does_not_collect_hermes_modules(self):
        for name in ("'hermes_cli'", "'run_agent'", "'hermes_constants'"):
            assert name not in MAC_SPEC, f"spec 仍在打包 {name}"

    def test_build_python_matches_hermes_support(self):
        assert 'python-version: "3.14"' in RELEASE, (
            "用户 Hermes 托管环境是 cp314；打包解释器必须是 3.14 才能加载其依赖"
        )


class TestReleaseBuildsBothMacArchitectures:
    def test_intel_and_arm64_runners_are_both_present(self):
        # 用户机器可能是 Intel：只出 arm64 包等于没验证
        assert "macos-15-intel" in RELEASE
        assert "-macOS-x64.zip" in RELEASE
        assert "-macOS-arm64.zip" in RELEASE

    def test_arm64_runner_is_pinned_not_latest(self):
        """W9：arm64 固定到 macos-15，不依赖 macos-latest 的指向。"""
        assert "- os: macos-15\n" in RELEASE
        assert "- os: macos-latest" not in RELEASE


class TestPostBuildArchCheck:
    """W9：构建产物架构必须与 matrix 一致，否则失败。"""

    def test_post_build_checks_lipo_arch(self):
        assert "lipo -archs" in RELEASE
        assert "产物架构不符" in RELEASE
        assert "exit 1" in RELEASE

    def test_expected_arch_mapping(self):
        # matrix 的 x64 → x86_64；其余 arm64
        assert "matrix.arch == 'x64' && 'x86_64' || 'arm64'" in RELEASE

    def test_checks_named_binary_not_first_file(self):
        """O-新11：按主程序名取二进制，不能靠 head -n1 猜。"""
        assert 'BIN="TradeWin.app/Contents/MacOS/TradeWin"' in RELEASE
        assert "head -n1" not in RELEASE


class TestManualDispatchPublishesFormalRelease:
    """W8（2026-11-25）：手动触发直接产出正式 Release，发布作业串行且只 Attach 一次。"""

    @staticmethod
    def _workflow() -> dict:
        import yaml

        return yaml.safe_load(RELEASE)

    def test_only_manual_dispatch_trigger(self):
        """不恢复 tag 触发：任何标签推送都不能绕过人工确认自动发布。"""
        wf = self._workflow()
        # PyYAML 会把裸 on 解析成 True，两种键名都接受
        triggers = wf.get("on", wf.get(True))
        assert triggers == "workflow_dispatch" or set(triggers or {}) == {"workflow_dispatch"}
        assert "push:" not in RELEASE and "refs/tags" not in RELEASE

    def test_publish_job_runs_after_build(self):
        wf = self._workflow()
        assert wf["jobs"]["publish"]["needs"] == "build"

    def test_only_one_release_attach(self):
        """矩阵分支不再各自 Attach（消灭同标签重复建 Release 的竞态）。"""
        assert RELEASE.count("softprops/action-gh-release@v2") == 1
        attach = [
            step for step in self._workflow()["jobs"]["publish"]["steps"]
            if step.get("uses", "").startswith("softprops/action-gh-release")
        ]
        assert len(attach) == 1

    def test_release_is_formal_not_draft(self):
        wf = self._workflow()
        attach = [
            step for step in wf["jobs"]["publish"]["steps"]
            if step.get("uses", "").startswith("softprops/action-gh-release")
        ][0]
        assert attach["with"]["draft"] is False
        assert "draft: ${{ github.event_name == 'workflow_dispatch' }}" not in RELEASE

    def test_publish_collects_all_artifacts(self):
        wf = self._workflow()
        uses = [s.get("uses", "") for s in wf["jobs"]["publish"]["steps"]]
        assert "actions/download-artifact@v5" in uses
        dl = next(
            s for s in wf["jobs"]["publish"]["steps"]
            if s.get("uses", "").startswith("actions/download-artifact")
        )
        assert dl["with"]["merge-multiple"] is True
        assert "files: dist/*.zip" in RELEASE

    def test_version_step_emits_release_tag(self):
        # 手动触发时 ref_name 是分支名，Release 必须用 v<版本号>
        assert 'REL_TAG="v$VER"' in RELEASE
        assert 'echo "tag=$REL_TAG" >> "$GITHUB_OUTPUT"' in RELEASE
