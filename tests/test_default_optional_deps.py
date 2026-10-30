"""默认安装策略：只装 sqlite-vec 与 holehe，hindsight / sentence-transformers 默认不装。

2026-10-30 12:24 Lau 拍板（取代当日上午的「默认安装」结论）：

- **hindsight-client 默认不装**：Lau 没有 API key，装了也用不上。
- **sentence-transformers 默认不装**：占空间（依赖 torch，300MB~1GB），
  安装弊大于利。

两条都不是「删掉能力」——代码层的降级守卫原样保留：没装时
`trade/memory.py` 走会话内记忆、`trade/embeddings.py` 走内置 TF-IDF，
用户想用时手动 `pip install` 即可。本文件钉住的是**默认安装策略**，
不是功能可用性。
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent

REQUIREMENTS = (ROOT / "requirements.txt").read_text(encoding="utf-8")
PYPROJECT = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
INSTALL_SH = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
INSTALL_PS1 = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
UPDATE_PY = (ROOT / "trade" / "post_install" / "update.py").read_text(encoding="utf-8")
DOCTOR_PY = (ROOT / "trade" / "doctor.py").read_text(encoding="utf-8")
MEMORY_PY = (ROOT / "trade" / "memory.py").read_text(encoding="utf-8")
EMBEDDINGS_PY = (ROOT / "trade" / "embeddings.py").read_text(encoding="utf-8")


def _code_lines(text: str) -> str:
    """去掉注释行后的脚本内容（注释里会引用旧写法，断言只针对真代码）。"""
    return "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )


def _requirement_lines(text: str) -> str:
    """requirements 的真依赖行（去掉注释与空行）。"""
    return "\n".join(
        line for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    )


class TestHindsightNotInstalledByDefault:
    """hindsight-client 默认不装（Lau 没有 API key，装了没用）。"""

    def test_not_in_requirements(self):
        assert "hindsight-client" not in _requirement_lines(REQUIREMENTS), (
            "requirements.txt 仍在默认安装 hindsight-client"
        )

    def test_not_in_pyproject_dependencies(self):
        deps = PYPROJECT.split("[project.optional-dependencies]")[0]
        assert "hindsight-client" not in deps, (
            "pyproject.toml 的 dependencies 仍在默认安装 hindsight-client"
        )


class TestSentenceTransformersNotInstalledByDefault:
    """sentence-transformers 默认不装（占空间、要拉 torch）。"""

    def test_not_in_requirements(self):
        assert "sentence-transformers" not in _requirement_lines(REQUIREMENTS)

    def test_not_in_semantic_extra(self):
        """semantic extra 只剩 sqlite-vec。"""
        extra = PYPROJECT.split("semantic = [")[1].split("]")[0]
        assert "sentence-transformers" not in extra, (
            "semantic extra 仍在安装 sentence-transformers"
        )
        assert "sqlite-vec" in extra, "semantic extra 不应连 sqlite-vec 一起删掉"

    def test_not_in_install_sh(self):
        assert "sentence-transformers" not in _code_lines(INSTALL_SH)

    def test_not_in_install_ps1(self):
        assert "sentence-transformers" not in _code_lines(INSTALL_PS1)

    def test_not_in_update_optional_deps(self):
        assert "sentence-transformers" not in UPDATE_PY, (
            "升级链路仍在默认安装 sentence-transformers"
        )

    def test_sqlite_vec_still_installed(self):
        """只删 ST，sqlite-vec 的默认安装保持现状。"""
        assert "sqlite-vec" in _code_lines(INSTALL_SH)
        assert "sqlite-vec" in _code_lines(INSTALL_PS1)
        assert "sqlite_vec" in UPDATE_PY


class TestDoctorTreatsMissingAsNormal:
    """「未安装」是预期状态，不能报成警告去吓唬用户。"""

    def test_hindsight_section_uses_ok_status(self):
        section = DOCTOR_PY.split("Hindsight（长期记忆）")[0][-1200:]
        assert "STATUS_OK" in section, "Hindsight 未安装档仍是警告级别"

    def test_hindsight_wording_says_default_off(self):
        assert "默认不装" in DOCTOR_PY, "Hindsight 文案未说明默认不装"

    def test_sentence_transformers_branch_uses_ok_for_missing(self):
        section = DOCTOR_PY.split("sentence-transformers")[-1]
        assert "STATUS_WARN" not in section.split("return out")[0], (
            "sentence-transformers 未安装档仍是警告级别"
        )

    def test_sentence_transformers_wording_says_default_off(self):
        assert "内置 TF-IDF 后端工作中" in DOCTOR_PY


class TestDegradationGuardsStillIntact:
    """只改安装策略，不改运行时降级逻辑 —— 守卫必须原样存在。"""

    def test_memory_guard_exists(self):
        assert "except ImportError" in MEMORY_PY
        assert "hindsight_client" in MEMORY_PY

    def test_embeddings_guard_exists(self):
        assert "except ImportError" in EMBEDDINGS_PY
        assert "sentence_transformers" in EMBEDDINGS_PY

    def test_version_is_077(self):
        assert re.search(r'^version = "0\.7\.7"$', PYPROJECT, re.M), (
            "版本号应为 0.7.7"
        )
