"""Release 工作流：Hermes 是 .app 运行时的一部分，构建必须诚实失败。

2026-11-23 决定（Roger）：构建时内嵌最新 Hermes；装不上就红；构建后冒烟
导入；记录构建时的 Hermes 版本。不再产出「能双击但 AI 是坏的」安装包。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")


class TestReleaseHermesIsMandatory:
    def test_hermes_install_is_not_best_effort(self):
        assert "continue-on-error" not in RELEASE
        assert "pip install hermes-agent" in RELEASE

    def test_build_python_matches_hermes_support(self):
        assert 'python-version: "3.14"' in RELEASE, (
            "Hermes ≥0.21.6 只提供 3.14 的依赖集，release 构建也必须用 3.14"
        )

    def test_smoke_imports_run_agent(self):
        assert "import run_agent" in RELEASE, "构建后必须验证 run_agent 真能导入"

    def test_records_hermes_version(self):
        assert "GITHUB_STEP_SUMMARY" in RELEASE
        assert "hermes_cli" in RELEASE
