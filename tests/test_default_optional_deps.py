"""默认安装的两个依赖：hindsight-client（硬依赖）与 sentence-transformers（软依赖）。

为什么一个硬一个软 —— 这是 2026-10-30 的实测结论，不是偏好：

- **hindsight-client**：纯 Python（aiohttp 系，无 C 扩展），Python 3.14 + 三平台
  都能解析安装（`pip install --dry-run` 实测通过），版本下限对齐 Hermes 侧
  catalog 插件的 `hindsight-client>=0.10.1`。所以可以进 `requirements.txt` /
  `pyproject.toml` 的硬依赖。
- **sentence-transformers**：依赖 `torch>=2.2`，而 **torch 自 2.9 起不再发布
  macOS x86_64 wheel**（只剩 arm64）。Trade 强制 Python 3.14，于是 **Intel Mac
  上根本装不上**（实测 pip 报 "no matching distributions available for your
  environment: torch"）。若写进硬依赖清单，Intel Mac 的整次安装会直接失败
  —— 违反「可用性高于一切」。

  所以它走「默认尝试安装、失败只警告」的路径：安装脚本 + 升级链路都会试装，
  装不上就继续用内置 TF-IDF 后端（Apple Silicon / Windows / Linux 正常）。
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


def _code_lines(text: str) -> str:
    """去掉注释行后的脚本内容（注释里会引用旧写法，断言只针对真代码）。"""
    return "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )


class TestHindsightIsHardDependency:
    """hindsight-client 默认安装 —— 纯 Python，可以进硬依赖清单。"""

    def test_in_requirements(self):
        assert re.search(r"^hindsight-client", REQUIREMENTS, re.M), (
            "requirements.txt 未包含 hindsight-client"
        )

    def test_in_pyproject_dependencies(self):
        assert re.search(r'"hindsight-client', PYPROJECT), (
            "pyproject.toml 的 dependencies 未包含 hindsight-client"
        )

    def test_version_floor_matches_hermes_catalog_plugin(self):
        """下限与 Hermes catalog 插件声明的 >=0.10.1 对齐，避免装出版本太老。"""
        assert ">=0.10.1" in REQUIREMENTS, "hindsight-client 的版本下限与 Hermes 侧不一致"


class TestSentenceTransformersIsBestEffort:
    """sentence-transformers 默认尝试安装，但**不得**进硬依赖清单。"""

    def test_not_in_requirements(self):
        """进了 requirements.txt 就是硬失败路径 —— Intel Mac 会装不上。"""
        body = "\n".join(
            line for line in REQUIREMENTS.splitlines()
            if not line.strip().startswith("#")
        )
        assert "sentence-transformers" not in body, (
            "sentence-transformers 不能进 requirements.txt 的硬依赖 —— "
            "torch 在 Intel Mac 上无 wheel，会让整次安装失败"
        )

    def test_in_semantic_extra(self):
        """手动强制安装的路：pip install -e \".[semantic]\"。"""
        assert '"sentence-transformers' in PYPROJECT, (
            "pyproject.toml 的 semantic extra 未包含 sentence-transformers"
        )

    def test_install_sh_attempts_it(self):
        assert "sentence-transformers" in _code_lines(INSTALL_SH), (
            "install.sh 未尝试安装 sentence-transformers"
        )

    def test_install_ps1_attempts_it(self):
        assert "sentence-transformers" in _code_lines(INSTALL_PS1), (
            "install.ps1 未尝试安装 sentence-transformers"
        )

    def test_installers_do_not_abort_on_failure(self):
        """装不上只能警告，不能 exit —— 可用性高于一切。"""
        for name, text in (("install.sh", INSTALL_SH), ("install.ps1", INSTALL_PS1)):
            body = _code_lines(text)
            idx = body.index("sentence-transformers")
            window = body[idx: idx + 400]
            assert "exit 1" not in window, (
                f"{name} 在 sentence-transformers 安装失败时会阻断整次安装"
            )

    def test_update_chain_attempts_it(self):
        """升级链路同样要尝试装（否则老用户永远补不上）。"""
        assert "sentence-transformers" in UPDATE_PY, (
            "trade/post_install/update.py 未尝试安装 sentence-transformers"
        )


class TestDoctorReportsBothHonestly:
    """自检要给三档信息，不给虚假绿灯。"""

    def test_hindsight_distinguishes_installed_but_unconfigured(self):
        assert "已安装但未配置 API key" in DOCTOR_PY, (
            "doctor 未区分「Hindsight 已装但没配 key」"
        )

    def test_sentence_transformers_reports_default_backend(self):
        assert "TRADE_EMBEDDING_BACKEND" in DOCTOR_PY, (
            "doctor 未说明 sentence-transformers 装了但默认后端仍是 TF-IDF"
        )
