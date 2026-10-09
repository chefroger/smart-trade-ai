"""init_db 只在**真会改 schema** 时才备份，且备份不会无限累积。

## 实测出来的问题

`init_db()` 每次启动都调用，而它在 `_backup_db` 上是**无条件**的。
一台开发机上累积到 **72,626 个备份文件 / 38 GB**（每个 573KB），
而没有一次是必要的 —— 那台机器的迁移列表是空的、schema 已是最新。

这类问题的可怕之处在于它完全静默：没有人会去看 `~/.trade/backups/`，
直到磁盘满。客户机上同样在发生。
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fresh_db(tmp_path: Path) -> Path:
    """建一个已是最新 schema 的库（spare 列/context 列齐全）。"""
    db = tmp_path / "trade.db"
    conn = sqlite3.connect(db)
    for table in ("companies", "trade_companies", "libraries", "customers",
                  "customer_libraries", "conversations", "orders"):
        conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, extra1 TEXT, extra2 TEXT, extra3 TEXT)")
    conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)")
    conn.execute("ALTER TABLE conversations ADD COLUMN context TEXT DEFAULT ''")
    conn.commit()
    conn.close()
    return db


class TestNeedsSchemaWork:
    def test_up_to_date_db_needs_nothing(self, tmp_path):
        from trade.database import _needs_schema_work

        conn = sqlite3.connect(_fresh_db(tmp_path))
        try:
            assert _needs_schema_work(conn) is False, (
                "schema 已最新却判为需要处理 —— 于是每次启动都多一个备份"
            )
        finally:
            conn.close()

    def test_missing_table_needs_work(self, tmp_path):
        from trade.database import _needs_schema_work

        db = _fresh_db(tmp_path)
        conn = sqlite3.connect(db)
        conn.execute("DROP TABLE orders")
        conn.commit()
        try:
            assert _needs_schema_work(conn) is True
        finally:
            conn.close()

    def test_missing_spare_column_needs_work(self, tmp_path):
        from trade.database import _needs_schema_work

        db = tmp_path / "old.db"
        conn = sqlite3.connect(db)
        for table in ("companies", "trade_companies", "libraries", "customers",
                      "customer_libraries", "conversations", "orders"):
            # 老 schema：没有 spare 列
            conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)")
        conn.commit()
        try:
            assert _needs_schema_work(conn) is True
        finally:
            conn.close()

    def test_missing_context_column_needs_work(self, tmp_path):
        from trade.database import _needs_schema_work

        db = _fresh_db(tmp_path)
        # 用重建方式去掉 context 列（sqlite 不支持 DROP COLUMN 的旧版本）
        conn = sqlite3.connect(db)
        conn.executescript("""
            CREATE TABLE conversations_new (id INTEGER PRIMARY KEY, extra1 TEXT, extra2 TEXT, extra3 TEXT);
            DROP TABLE conversations;
            ALTER TABLE conversations_new RENAME TO conversations;
        """)
        conn.commit()
        try:
            assert _needs_schema_work(conn) is True
        finally:
            conn.close()

    def test_corrupt_db_is_conservative(self, tmp_path):
        """读不出来（损坏）→ 保守判为需要处理，照旧备份。"""
        from trade.database import _needs_schema_work

        bad = tmp_path / "bad.db"
        bad.write_text("这不是 sqlite 文件", encoding="utf-8")
        conn = sqlite3.connect(bad)
        try:
            assert _needs_schema_work(conn) is True
        finally:
            conn.close()


class TestInitDbDoesNotBackUpUnnecessarily:
    """用**真实 schema**建库（手写建表会漏列，跑不出真场景）。"""

    def _init_once(self, tmp_path, monkeypatch):
        """把库建好（首次 init_db 不备份 —— 库文件还不存在）。返回路径三元组。"""
        import trade.database as dbmod

        trade_home = tmp_path / ".trade"
        (trade_home / "data").mkdir(parents=True)
        db_path = trade_home / "data" / "trade.db"
        monkeypatch.setattr(dbmod, "_get_db_path", lambda: db_path)

        dbmod.init_db()  # 首次：建出真实 schema
        return dbmod, trade_home, db_path

    def test_no_backup_when_schema_current(self, tmp_path, monkeypatch):
        """核心断言：schema 已最新时 init_db 不产生备份文件。"""
        dbmod, trade_home, _ = self._init_once(tmp_path, monkeypatch)
        backup_dir = trade_home / "backups"
        before = list(backup_dir.glob("trade-*.db")) if backup_dir.is_dir() else []

        dbmod.init_db()  # 第二次：什么都不需要改

        after = list(backup_dir.glob("trade-*.db")) if backup_dir.is_dir() else []
        assert after == before, f"schema 没变却新增了备份：{set(after) - set(before)}"

    def test_repeated_init_does_not_accumulate(self, tmp_path, monkeypatch):
        """连续多次 init_db 不该累积备份 —— 这正是 7 万文件事故的形态。"""
        dbmod, trade_home, _ = self._init_once(tmp_path, monkeypatch)

        for _ in range(5):
            dbmod.init_db()

        backup_dir = trade_home / "backups"
        count = len(list(backup_dir.glob("trade-*.db"))) if backup_dir.is_dir() else 0
        assert count == 0, f"5 次重复启动产生了 {count} 个备份（每次 573KB，永不清理）"


class TestPruneOldBackups:
    def test_keeps_only_newest(self, tmp_path):
        from trade.database import prune_old_backups

        d = tmp_path / "backups"
        d.mkdir()
        for i in range(10):
            (d / f"trade-2026010{i}-120000.db").write_text("x", encoding="utf-8")

        removed = prune_old_backups(d, keep=3)

        assert len(removed) == 7
        remaining = sorted(p.name for p in d.iterdir())
        assert remaining == [
            "trade-20260107-120000.db",
            "trade-20260108-120000.db",
            "trade-20260109-120000.db",
        ]

    def test_never_deletes_manual_backups(self, tmp_path):
        """手工备份（trade-before-restore-*）是用户特意留的，绝不能删。"""
        from trade.database import prune_old_backups

        d = tmp_path / "backups"
        d.mkdir()
        manual = d / "trade-before-restore-20260101-000000.db"
        manual.write_text("x", encoding="utf-8")
        for i in range(5):
            (d / f"trade-2026010{i}-120000.db").write_text("x", encoding="utf-8")

        prune_old_backups(d, keep=1)

        assert manual.is_file(), "手工备份被误删了"

    def test_noop_when_under_limit(self, tmp_path):
        from trade.database import prune_old_backups

        d = tmp_path / "backups"
        d.mkdir()
        (d / "trade-20260101-120000.db").write_text("x", encoding="utf-8")

        assert prune_old_backups(d, keep=5) == []

    def test_missing_dir_is_safe(self, tmp_path):
        from trade.database import prune_old_backups

        assert prune_old_backups(tmp_path / "nope", keep=5) == []
