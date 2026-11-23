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
