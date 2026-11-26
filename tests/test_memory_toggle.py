"""Hindsight 用户开关 + 连通性探测（2026-11-20 审计 C6）。"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _db(monkeypatch, tmp_path):
    """临时库 + 每个用例后恢复默认开关与缓存，避免互相污染。"""
    from trade import database as db
    from trade import memory

    db_path = tmp_path / "mem.db"
    monkeypatch.setattr(db, "_get_db_path", lambda: db_path)
    db.init_db()
    memory.reset_cache()
    yield
    memory.set_enabled(True)
    memory.reset_cache()


class TestToggle:
    def test_default_enabled(self):
        from trade import memory

        assert memory.is_enabled() is True

    def test_disable_blocks_client(self):
        from trade import memory

        memory.set_enabled(False)
        assert memory.is_enabled() is False
        # 关闭时 _get_client 必须返回 None（即使之前缓存过实例）
        assert memory._get_client() is None
        assert memory.retain("hello") is False

    def test_reenable_restores(self):
        from trade import memory

        memory.set_enabled(False)
        memory.set_enabled(True)
        assert memory.is_enabled() is True


class TestHealthCheck:
    def test_false_when_not_available(self, monkeypatch):
        from trade import memory

        monkeypatch.setattr(memory, "is_available", lambda: False)
        assert memory.health_check() is False

    def test_true_when_connect_succeeds(self, monkeypatch):
        from trade import memory

        monkeypatch.setattr(memory, "is_available", lambda: True)

        class _Sock:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(socket, "create_connection", lambda *a, **k: _Sock())
        assert memory.health_check(timeout=0.1) is True

    def test_false_when_connect_fails(self, monkeypatch):
        from trade import memory

        monkeypatch.setattr(memory, "is_available", lambda: True)

        def _boom(*a, **k):
            raise OSError("refused")

        monkeypatch.setattr(socket, "create_connection", _boom)
        assert memory.health_check(timeout=0.1) is False

    def test_false_on_bad_url(self, monkeypatch):
        from trade import memory

        monkeypatch.setattr(memory, "is_available", lambda: True)
        monkeypatch.setenv("HINDSIGHT_API_URL", "not-a-url")
        assert memory.health_check(timeout=0.1) is False


class TestReplayGuard:
    def test_disabled_skips_replay(self, monkeypatch):
        from trade import memory
        from trade.company.transfer import replay

        memory.set_enabled(False)
        out = replay.replay_hindsight(1, [{"query": "q", "response": "r"}])
        assert out["status"] == "disabled"

    def test_unreachable_reported(self, monkeypatch):
        from trade import memory
        from trade.company.transfer import replay

        monkeypatch.setattr(memory, "is_enabled", lambda: True)
        monkeypatch.setattr(memory, "is_available", lambda: True)
        monkeypatch.setattr(memory, "health_check", lambda *a, **k: False)
        out = replay.replay_hindsight(1, [{"query": "q", "response": "r"}])
        assert out["status"] == "unreachable"
        assert out["replayed"] == 0


class TestHealthCheckUsesResolvedUrl:
    def test_probes_config_url_not_just_env(self, monkeypatch):
        """health_check 必须用与客户端相同的地址解析（config.json 优先）。

        否则只在 config.json 里配了自定义地址的用户会被误判不可达。
        """
        from trade import memory

        monkeypatch.setattr(memory, "is_available", lambda: True)
        # 模拟只有配置文件里写了自定义地址
        monkeypatch.setattr(
            memory, "_load_hindsight_config",
            lambda: {"api_url": "http://127.0.0.1:9/"},
        )
        monkeypatch.delenv("HINDSIGHT_API_URL", raising=False)

        seen = {}

        def _conn(addr, timeout=None):
            seen["addr"] = addr
            raise OSError("refused")

        monkeypatch.setattr(socket, "create_connection", _conn)
        assert memory.health_check(timeout=0.1) is False
        assert seen["addr"] == ("127.0.0.1", 9), f"探错了地址：{seen['addr']}"


class TestHermesMemoryCompanyIsolation:
    def test_retains_into_company_isolated_dir_not_global(self, monkeypatch, tmp_path):
        """多公司下 retain_to_hermes_memory 必须按 company_slug 隔离，不写共享 MEMORY.md。"""
        from trade import memory

        trade_home = tmp_path / "trade_home"
        hermes_home = tmp_path / "hermes_home"
        monkeypatch.setenv("TRADE_HOME", str(trade_home))
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))

        ok_a = memory.retain_to_hermes_memory(
            "Q-A", "R-A", company_name="Alpha", company_slug="alpha"
        )
        ok_b = memory.retain_to_hermes_memory(
            "Q-B", "R-B", company_name="Beta", company_slug="beta"
        )
        assert ok_a is True
        assert ok_b is True

        file_a = trade_home / "alpha" / "memories" / "MEMORY.md"
        file_b = trade_home / "beta" / "memories" / "MEMORY.md"
        assert file_a.is_file() and "Q-A" in file_a.read_text(encoding="utf-8")
        assert "Q-B" not in file_a.read_text(encoding="utf-8")
        assert file_b.is_file() and "Q-B" in file_b.read_text(encoding="utf-8")
        assert not (hermes_home / "memories" / "MEMORY.md").exists()

    def test_db_failure_without_slug_fails_closed(self, monkeypatch, tmp_path):
        """O-新33：未传 slug 且查库异常时必须 fail-closed，不回退写全局 MEMORY.md。"""
        from trade import database as db
        from trade import memory

        trade_home = tmp_path / "trade_home"
        hermes_home = tmp_path / "hermes_home"
        monkeypatch.setenv("TRADE_HOME", str(trade_home))
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))

        def _broken_conn():
            raise RuntimeError("db unavailable")

        with monkeypatch.context() as mp:
            mp.setattr(db, "get_connection", _broken_conn)
            assert memory.retain_to_hermes_memory("Q-err", "R-err") is False
        assert not (hermes_home / "memories" / "MEMORY.md").exists()

    def test_rolling_cap_prevents_unbounded_growth(self, monkeypatch, tmp_path):
        """公司专属 MEMORY.md 按最近条数滚动裁剪，不无限膨胀。"""
        from trade import memory

        trade_home = tmp_path / "trade_home"
        monkeypatch.setenv("TRADE_HOME", str(trade_home))
        for i in range(36):
            assert memory.retain_to_hermes_memory(
                f"Q-item-{i}", f"R-item-{i}", company_name="Alpha", company_slug="alpha"
            ) is True

        text = (trade_home / "alpha" / "memories" / "MEMORY.md").read_text(encoding="utf-8")
        assert "Q-item-35" in text
        assert "Q-item-6" in text
        assert "Q-item-0" not in text

    def test_build_query_consumes_company_isolated_memory_with_customer_filter(
        self, monkeypatch, tmp_path
    ):
        """P2-新1 闭环：build_query 读取当前公司专属 MEMORY.md，且按公司与客户严格隔离。"""
        import trade.company as co
        from trade import customer as cust_mod
        from trade import helpers, memory

        trade_home = tmp_path / "trade_home"
        hermes_home = tmp_path / "hermes_home"
        monkeypatch.setenv("TRADE_HOME", str(trade_home))
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))
        monkeypatch.setattr(co, "TRADE_HOME", trade_home)

        def _fake_setup(name, slug, suggested_name=""):
            wd = tmp_path / f"wd-{slug}"
            wd.mkdir(parents=True, exist_ok=True)
            return wd, True

        monkeypatch.setattr("trade.company.workdir._setup_work_directory", _fake_setup)
        alpha = co.create("Alpha Co", slug="alpha")
        beta = co.create("Beta Co", slug="beta")
        c1 = cust_mod.create("Northwind", "Tom", "", company_id=alpha["id"])
        c2 = cust_mod.create("Contoso", "Jane", "", company_id=alpha["id"])

        memory.retain_to_hermes_memory(
            "通用付款条件是什么", "默认 30% T/T 定金",
            company_name="Alpha Co", company_slug="alpha",
        )
        memory.retain_to_hermes_memory(
            "给 Northwind 报了什么价", "FOB Ningbo USD 12.50",
            company_name="Alpha Co", company_slug="alpha", customer_name="Northwind",
        )
        memory.retain_to_hermes_memory(
            "Beta 内部底价", "USD 99.00",
            company_name="Beta Co", company_slug="beta",
        )

        # Alpha 无特定客户：看到本公司记忆，看不到 Beta 记忆
        prompt_alpha, _ = helpers.build_query(alpha["id"], None, "整理今日跟进邮件")
        assert "默认 30% T/T 定金" in prompt_alpha
        assert "FOB Ningbo USD 12.50" in prompt_alpha
        assert "USD 99.00" not in prompt_alpha

        # Beta 只看到 Beta 专属记忆，看不到 Alpha 记忆
        prompt_beta, _ = helpers.build_query(beta["id"], None, "整理今日跟进邮件")
        assert "USD 99.00" in prompt_beta
        assert "默认 30% T/T 定金" not in prompt_beta

        # Alpha 选中客户 Contoso：能看通用记忆，但不得看到 Northwind 的专属报价记忆
        prompt_c2, _ = helpers.build_query(
            alpha["id"], None, "给客户写报价跟进", customer_id=c2["id"]
        )
        assert "默认 30% T/T 定金" in prompt_c2
        assert "FOB Ningbo USD 12.50" not in prompt_c2

        # Alpha 选中客户 Northwind：能看通用记忆 + Northwind 自己的记忆
        prompt_c1, _ = helpers.build_query(
            alpha["id"], None, "给客户写报价跟进", customer_id=c1["id"]
        )
        assert "FOB Ningbo USD 12.50" in prompt_c1

    def test_backup_and_transfer_include_isolated_company_memory(
        self, monkeypatch, tmp_path
    ):
        """P2-新1 闭环：备份还原与单公司导出导入均覆盖 TRADE_HOME/{slug}/memories/MEMORY.md。"""
        import shutil

        import trade.company as co
        from trade import memory
        from trade.company.transfer.exporter import export_company
        from trade.company.transfer.importer import import_company
        from trade.post_install import backup as bk

        trade_home = tmp_path / "trade_home"
        hermes_home = tmp_path / "hermes_home"
        (trade_home / "data").mkdir(parents=True)
        (trade_home / "prompts").mkdir(parents=True)
        hermes_home.mkdir(parents=True)
        monkeypatch.setenv("TRADE_HOME", str(trade_home))
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))
        monkeypatch.setattr(co, "TRADE_HOME", trade_home)
        monkeypatch.setattr(bk, "_restart_trade_service", lambda: None)

        from trade import database as db

        real_db = trade_home / "data" / "trade.db"
        with monkeypatch.context() as mp:
            mp.setattr(db, "_get_db_path", lambda: real_db)
            db.init_db()

            def _fake_setup(name, slug, suggested_name=""):
                wd = tmp_path / f"wd-{slug}"
                wd.mkdir(parents=True, exist_ok=True)
                return wd, True

            mp.setattr("trade.company.workdir._setup_work_directory", _fake_setup)
            mp.setattr("trade.company.workdir._get_desktop_path", lambda: tmp_path)

            src_co = co.create("Gamma Trade", slug="gamma")
            memory.retain_to_hermes_memory(
                "德国客户认证要求", "必须具备 CE 与 REACH 检测报告",
                company_name="Gamma Trade", company_slug="gamma",
            )
            mem_file = trade_home / "gamma" / "memories" / "MEMORY.md"
            assert mem_file.is_file()

            # 1) 验证单公司导出 → 导入新公司后记忆落在目标公司专属目录，不污染全局
            pkg = tmp_path / "gamma.zip"
            export_company(src_co["id"], pkg)
            rep = import_company(pkg, force_new=True)
            dst_slug = rep["target"]["slug"]
            dst_mem = trade_home / dst_slug / "memories" / "MEMORY.md"
            assert dst_mem.is_file()
            assert "CE 与 REACH" in dst_mem.read_text(encoding="utf-8")
            assert not (hermes_home / "memories" / "MEMORY.md").exists()

            # 2) 验证整机备份 → 删除公司记忆目录 → 还原后完整恢复
            archive = bk.backup_trade(output_dir=str(tmp_path))
            shutil.rmtree(trade_home / "gamma" / "memories")
            assert not mem_file.exists()
            bk.restore_trade(archive)
            assert mem_file.is_file()
            assert "CE 与 REACH" in mem_file.read_text(encoding="utf-8")
