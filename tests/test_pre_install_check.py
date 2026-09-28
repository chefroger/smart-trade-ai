"""安装前检查的版本判定测试。

与运行时门禁（trade/bootstrap.check_hermes_version）同一原则：
**识别不到版本 ≠ 版本过旧**，不能因此卡死安装流程。

背景：上游 main 把 hermes_cli.__version__ 改成惰性读安装印章，读不到返回 "0.0.0"；
而 get_installed_hermes_version() 也会返回带 git 后缀的派生版本（如 0.21.4+5045）。
旧逻辑用 _parse_version 把这类字符串解析成 (0,0,0)，于是判成「过旧」并退出码 2。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pre_install_check as pic


class TestInstalledVersionJudgement:
    """_judge_installed_version 的三态判定。"""

    @pytest.mark.parametrize("reported", ["0.0.0", "0.0.0.0", "unknown", "none", "", "  ", "dev"])
    def test_placeholder_is_unknown_not_too_old(self, reported):
        """占位值/空值 → unknown（跳过下限检查），不能判成过旧。"""
        assert pic._judge_installed_version(reported, "0.13.0") == "unknown"

    @pytest.mark.parametrize("reported", ["git.abc1234", "not-a-version", "0.21.x", "main"])
    def test_unparseable_is_unknown(self, reported):
        """无法解析成版本号的字符串 → unknown（不是「过旧」）。"""
        assert pic._judge_installed_version(reported, "0.13.0") == "unknown"

    @pytest.mark.parametrize("reported", ["0.21.4+5045", "v0.21.5-490-gabc1234"])
    def test_derived_versions_use_their_base(self, reported):
        """带本地/git 后缀的派生版本按基础版本号判定，而不是被算成 0.0.0 判过旧。"""
        assert pic._judge_installed_version(reported, "0.13.0") == "ok"

    def test_derived_version_below_floor_is_still_too_old(self):
        """派生版本的基础号低于下限时仍然判过旧。"""
        assert pic._judge_installed_version("0.12.5+99", "0.13.0") == "too_old"

    @pytest.mark.parametrize("reported", ["0.12.0", "0.9.0", "v0.12.9"])
    def test_genuinely_old_is_too_old(self, reported):
        """真实且低于下限的版本仍必须判过旧。"""
        assert pic._judge_installed_version(reported, "0.13.0") == "too_old"

    @pytest.mark.parametrize("reported", ["0.13.0", "0.21.4", "0.21.5", "v0.21.5", "0.13"])
    def test_new_enough_is_ok(self, reported):
        """满足下限的版本判通过。"""
        assert pic._judge_installed_version(reported, "0.13.0") == "ok"


class TestInstalledVersionDetection:
    """探测已安装 Hermes：包名必须是 hermes_cli，CLI 超时不能过紧。

    历史缺陷：回退探测去 import `hermes_agent`，而实际包名是 `hermes_cli` → 必然失败；
    且 CLI 探测用 5 秒硬超时，冷启动一旦超过就落到坏的回退上 → 报「未安装」。
    实测本机出现过：Hermes 装得好好的，检查却让人重装。
    """

    def test_cli_probe_timeout_is_relaxed(self, monkeypatch):
        """CLI 冷启动可能明显超过 5 秒，超时必须放宽。"""
        import shutil
        import subprocess
        from types import SimpleNamespace

        captured: dict = {}

        def _fake_run(cmd, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(stdout="Hermes Agent v0.21.4 (2026.9.21) · upstream d275e422\n", stderr="")

        monkeypatch.setattr(shutil, "which", lambda name: "/fake/hermes")
        monkeypatch.setattr(subprocess, "run", _fake_run)

        assert pic.get_installed_hermes_version() == "0.21.4"
        assert captured.get("timeout", 0) >= 15, f"CLI 探测超时过紧: {captured.get('timeout')}"

    def test_falls_back_to_hermes_cli_module(self, monkeypatch):
        """CLI 不可用时回退 import `hermes_cli`（不是 hermes_agent）。"""
        import shutil
        import types

        monkeypatch.setattr(shutil, "which", lambda name: None)
        fake = types.ModuleType("hermes_cli")
        fake.__version__ = "0.21.4"
        monkeypatch.setitem(sys.modules, "hermes_cli", fake)

        assert pic.get_installed_hermes_version() == "0.21.4"

    def test_scans_sys_path_for_hermes_cli_dir(self, monkeypatch, tmp_path):
        """CLI 与 import 都不可用时，扫描 sys.path 里的 hermes_cli 包目录。"""
        import shutil

        pkg = tmp_path / "hermes_cli"
        pkg.mkdir()
        (pkg / "__init__.py").write_text('__version__ = "0.21.4"\n', encoding="utf-8")

        monkeypatch.setattr(shutil, "which", lambda name: None)
        monkeypatch.setitem(sys.modules, "hermes_cli", None)  # 强制 import 失败
        monkeypatch.setattr(sys, "path", [str(tmp_path), *sys.path])

        assert pic.get_installed_hermes_version() == "0.21.4"

    def test_returns_none_when_really_absent(self, monkeypatch, tmp_path):
        """确实没装时仍返回 None（不能因为放宽回退就假报版本）。"""
        import shutil

        monkeypatch.setattr(shutil, "which", lambda name: None)
        monkeypatch.setitem(sys.modules, "hermes_cli", None)
        monkeypatch.setattr(sys, "path", [str(tmp_path)])

        assert pic.get_installed_hermes_version() is None
