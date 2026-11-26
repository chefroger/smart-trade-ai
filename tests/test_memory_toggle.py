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
