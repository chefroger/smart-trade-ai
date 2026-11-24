"""
测试环境隔离护栏 —— 测试绝不能写到真实用户数据目录。

背景：tests/conftest.py 最初只隔离了 TRADE_HOME，`~/.hermes` 没有重定向。
后果是真实发生过的：某次测试里 install_skills() 被真实执行，把真实的
~/.hermes/skills 覆盖了一遍；trade/memory.py 也会写 ~/.hermes/memories/MEMORY.md。

这些用例锁住隔离本身：如果将来有人删掉 conftest 里的 HERMES_HOME 设置，
它们会立刻失败，而不是等下一次污染真实数据才发现。
"""

from __future__ import annotations

import os
from pathlib import Path


class TestHermesHomeIsolation:
    """HERMES_HOME 必须被重定向到临时目录。"""

    def test_trade_home_is_temp_and_not_real_home(self):
        """TRADE_HOME 同样必须隔离。"""
        trade_home = os.environ.get("TRADE_HOME", "")
        assert trade_home, "conftest 必须设置 TRADE_HOME"
        real_trade = (Path.home() / ".trade").resolve()
        assert Path(trade_home).resolve() != real_trade
        assert real_trade not in Path(trade_home).resolve().parents

    def test_conftest_registers_temp_dir_cleanup(self):
        """W11：会话结束必须删除两个 mkdtemp 目录，不能每次运行漏 /tmp。"""
        src = (Path(__file__).parent / "conftest.py").read_text(encoding="utf-8")
        assert "pytest_sessionfinish" in src
        assert "shutil.rmtree" in src
        assert "trade-test-hermes-" in src

    def test_hermes_home_env_is_set_and_not_real_home(self):
        """HERMES_HOME 必须已设置，且不指向真实的 ~/.hermes。"""
        hermes_home = os.environ.get("HERMES_HOME", "")
        assert hermes_home, (
            "conftest 必须设置 HERMES_HOME —— 否则 install_skills / 记忆写入会落到真实 ~/.hermes"
        )

        real_hermes = (Path.home() / ".hermes").resolve()
        assert Path(hermes_home).resolve() != real_hermes
        # 不能是真实 ~/.hermes 的子目录（否则仍会写进用户数据）
        assert real_hermes not in Path(hermes_home).resolve().parents

    def test_cron_module_uses_isolated_home(self):
        """cron 端点在 import 期算出的目录必须是隔离目录。"""
        from trade.api import cron

        assert str(cron._HERMES_HOME) == os.environ["HERMES_HOME"]

    def test_skill_router_uses_isolated_home(self):
        """skill_router 解析的 skills 目录必须在隔离目录下。"""
        from trade import skill_router

        assert skill_router._get_hermes_skills_dir() == Path(os.environ["HERMES_HOME"]) / "skills"

    def test_license_uses_isolated_home(self):
        """license 的 Hermes 根目录解析也必须在隔离目录下。"""
        from trade.license import _resolve_hermes_home

        assert _resolve_hermes_home() == Path(os.environ["HERMES_HOME"])
