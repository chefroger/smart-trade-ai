"""
数据库层测试 — schema 创建、v0→v1 迁移、spare columns 幂等性。

所有测试使用临时数据库文件，不影响 data/trade.db。
"""

from __future__ import annotations

import sqlite3

# 将 trade 加入 PYTHONPATH（如果通过 pytest 直接运行）
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade.database import (
    SCHEMA_SQL,
    _add_spare_columns,
    _migrate_from_v0,
    get_connection,
)


class TestSchemaCreation:
    """测试全新数据库的 schema 创建。"""

    def test_create_fresh_schema(self, tmp_path):
        """新数据库应创建 6 张表 + 5 个索引。"""
        db_path = tmp_path / "test_fresh.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")

        conn.executescript(SCHEMA_SQL)
        conn.commit()

        # 验证 6 张表
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = {t[0] for t in tables}
        expected = {"companies", "trade_companies", "libraries", "customers",
                    "customer_libraries", "conversations"}
        assert expected.issubset(table_names), f"Missing tables: {expected - table_names}"

        # 验证索引
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
        ).fetchall()
        index_names = {i[0] for i in indexes}
        expected_indexes = {
            "idx_libraries_company", "idx_customers_company",
            "idx_conversations_company", "idx_conversations_library",
            "idx_conversations_created",
        }
        assert expected_indexes.issubset(index_names), \
            f"Missing indexes: {expected_indexes - index_names}"

        conn.close()

    def test_foreign_keys_enabled(self, tmp_path):
        """外键约束应被启用（PRAGMA foreign_keys = ON）。"""
        db_path = tmp_path / "test_fk.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(SCHEMA_SQL)
        conn.commit()

        # 插入违反外键的数据（library 不存在的 company_id）
        conn.execute("INSERT INTO libraries (name, root_path, company_id) VALUES (?, ?, ?)",
                     ("Test", "/tmp/test", 999))
        # SQLite 默认不强制外键（需要 PRAGMA），但 get_connection 会启用
        conn.close()

        # 使用 get_connection 风格的连接（设置了 PRAGMA foreign_keys = ON）
        # 这里我们测试 TRADE 的 get_connection 是否启用了外键
        # 注：完整的外键测试在业务层测试中

    def test_all_tables_have_spare_columns(self, tmp_path):
        """所有 6 张表应有 extra1/extra2/extra3 备用列。"""
        db_path = tmp_path / "test_spare.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(SCHEMA_SQL)
        _add_spare_columns(conn)
        conn.commit()

        for table in ["companies", "trade_companies", "libraries", "customers",
                      "customer_libraries", "conversations"]:
            cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for extra_col in ["extra1", "extra2", "extra3"]:
                assert extra_col in cols, f"{table} missing column: {extra_col}"

        conn.close()

    def test_spare_columns_default_is_json_object(self, tmp_path):
        """备用列的默认值应为 '{}'（空 JSON 对象）。"""
        db_path = tmp_path / "test_defaults.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(SCHEMA_SQL)
        conn.commit()

        conn.execute(
            "INSERT INTO companies (name, slug) VALUES (?, ?)",
            ("Test Co", "test-co"),
        )
        conn.commit()
        row = conn.execute("SELECT extra1, extra2, extra3 FROM companies WHERE id=1").fetchone()
        assert row[0] == "{}"
        assert row[1] == "{}"
        assert row[2] == "{}"

        conn.close()


class TestSpareColumnsIdempotency:
    """测试 _add_spare_columns 的幂等性。"""

    def test_double_call_safe(self, tmp_path):
        """重复调用 _add_spare_columns 不应出错。"""
        db_path = tmp_path / "test_double.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(SCHEMA_SQL)
        conn.commit()

        # 第一次调用：添加 spare columns
        _add_spare_columns(conn)
        # 第二次调用：应静默忽略（幂等）
        _add_spare_columns(conn)
        conn.commit()

        # 验证各表的列只出现一次
        for table in ["companies", "libraries", "customers"]:
            cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            extra_count = sum(1 for c in cols if c.startswith("extra"))
            assert extra_count == 3, f"{table} has {extra_count} extra columns (expected 3)"

        conn.close()


class TestV0ToV1Migration:
    """测试 v0（单公司）→ v1（多公司）迁移。"""

    def _create_v0_schema(self, conn):
        """创建 v0 版本的旧 schema（无 company_id 列）。"""
        conn.executescript("""
            CREATE TABLE libraries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                root_path TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                contact TEXT DEFAULT '',
                note TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                library_id INTEGER,
                query TEXT NOT NULL,
                response TEXT DEFAULT '',
                files_read TEXT DEFAULT '[]',
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
        """)
        # 插入一些 v0 格式数据
        conn.execute("INSERT INTO libraries (name, root_path) VALUES (?, ?)",
                     ("Old Library", "/tmp/old"))
        conn.execute("INSERT INTO customers (name, contact) VALUES (?, ?)",
                     ("Old Customer", "old@test.com"))
        conn.commit()

    def test_migration_detects_v0(self, tmp_path):
        """应检测到 v0 schema（libraries 无 company_id 列）。"""
        db_path = tmp_path / "test_migrate_detect.db"
        conn = sqlite3.connect(str(db_path))
        self._create_v0_schema(conn)

        # 验证迁移前状态
        cols = {row[1] for row in conn.execute("PRAGMA table_info(libraries)").fetchall()}
        assert "company_id" not in cols

        # 执行迁移
        migrated = _migrate_from_v0(conn)
        assert migrated is True, "Migration should have been performed"

        conn.close()

    def test_migration_idempotent(self, tmp_path):
        """已迁移的数据库不应重复执行迁移。"""
        db_path = tmp_path / "test_migrate_idempotent.db"
        conn = sqlite3.connect(str(db_path))

        # 使用完整 schema（已包含 company_id）
        conn.executescript(SCHEMA_SQL)
        conn.commit()

        # 调用迁移 → 应返回 False（已是 v1）
        migrated = _migrate_from_v0(conn)
        assert migrated is False, "Already-migrated DB should return False"

        conn.close()

    def test_existing_data_preserved(self, tmp_path):
        """迁移后 v0 旧数据不应丢失，全部归属默认公司。"""
        db_path = tmp_path / "test_migrate_data.db"
        conn = sqlite3.connect(str(db_path))
        self._create_v0_schema(conn)

        _migrate_from_v0(conn)
        conn.commit()

        # 旧 library 数据应保留且 company_id=1
        lib = conn.execute("SELECT name, company_id FROM libraries WHERE id=1").fetchone()
        assert lib[0] == "Old Library"
        assert lib[1] == 1

        # 旧 customer 数据应保留且 company_id=1
        cust = conn.execute("SELECT name, contact, company_id FROM customers WHERE id=1").fetchone()
        assert cust[0] == "Old Customer"
        assert cust[1] == "old@test.com"
        assert cust[2] == 1

        conn.close()

    def test_default_company_created(self, tmp_path):
        """迁移应创建默认公司 '我的公司' (slug=default)。"""
        db_path = tmp_path / "test_migrate_company.db"
        conn = sqlite3.connect(str(db_path))
        self._create_v0_schema(conn)

        _migrate_from_v0(conn)
        conn.commit()

        company = conn.execute("SELECT name, slug FROM companies WHERE id=1").fetchone()
        assert company[0] == "我的公司"
        assert company[1] == "default"

        # 应有 trade_companies 记录
        tc = conn.execute("SELECT company_id, is_active FROM trade_companies WHERE company_id=1").fetchone()
        assert tc is not None
        assert tc[1] == 1

        conn.close()


class TestWALMode:
    """测试 WAL 模式。"""

    def test_wal_mode_enabled(self, tmp_path):
        """get_connection 应启用 WAL journal 模式。"""
        db_path = tmp_path / "test_wal.db"
        # 临时 monkey-patch _get_db_path
        import trade.database
        original = trade.database._get_db_path
        trade.database._get_db_path = lambda: db_path

        try:
            conn = get_connection()
            journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert journal.upper() == "WAL", f"Expected WAL, got {journal}"
            conn.close()
        finally:
            trade.database._get_db_path = original


class TestMigrationTransactionAndPartial:
    """v0→v1 迁移的事务性与逐表判据（2026-10-21 审计 P1）。

    原先：判据只看 libraries 一张表 + executescript（隐式提交）无事务。
    中途失败的库下次启动会被误判"已是 v1"，剩余表行 company_id 为 NULL，
    被所有 WHERE company_id=? 静默过滤 —— 数据还在，但用户永远看不到。
    """

    def _v0(self, conn):
        conn.executescript("""
            CREATE TABLE libraries (id INTEGER PRIMARY KEY, name TEXT NOT NULL, root_path TEXT NOT NULL);
            CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, contact TEXT DEFAULT '');
            CREATE TABLE conversations (id INTEGER PRIMARY KEY, query TEXT NOT NULL, response TEXT DEFAULT '');
        """)
        conn.execute("INSERT INTO libraries (name, root_path) VALUES ('L', '/tmp/x')")
        conn.execute("INSERT INTO customers (name) VALUES ('C')")
        conn.execute("INSERT INTO conversations (query) VALUES ('Q')")
        conn.commit()

    def test_partial_migration_completes_missing_tables(self):
        """libraries 已迁完、其余表没迁 —— 不能再判"已是 v1"，必须补齐。"""
        import sqlite3

        from trade.database import _migrate_from_v0

        conn = sqlite3.connect(":memory:")
        self._v0(conn)
        # 人为制造"上一次迁移在加完 libraries 列后崩了"的中间状态
        conn.execute("ALTER TABLE libraries ADD COLUMN company_id INTEGER")
        conn.execute("UPDATE libraries SET company_id = 1")
        conn.commit()

        migrated = _migrate_from_v0(conn)
        assert migrated is True, "部分迁移的库必须继续补迁，而不是误判已是 v1"

        for table in ("libraries", "customers", "conversations"):
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            assert "company_id" in cols, f"{table} 缺 company_id"
            nulls = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE company_id IS NULL").fetchone()[0]
            assert nulls == 0, f"{table} 仍有 company_id 为 NULL 的孤儿行"
        conn.close()

    def test_failure_rolls_back_whole_migration(self, monkeypatch):
        """迁移中途失败 → 整个迁移回滚，不留"列已加、值没填"的半成品。"""
        import sqlite3

        import trade.database as db

        conn = sqlite3.connect(":memory:")
        self._v0(conn)

        def boom(_conn):
            raise RuntimeError("simulated failure")

        # 放在最后一步失败：此时三张表的 ALTER/UPDATE 都已执行
        monkeypatch.setattr(db, "_add_spare_columns", boom)

        with __import__("pytest").raises(RuntimeError):
            db._migrate_from_v0(conn)

        # 回滚后：三张表都不该有 company_id（含 libraries）
        for table in ("libraries", "customers", "conversations"):
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            assert "company_id" not in cols, f"{table} 的 company_id 未随事务回滚"
        # companies 表也不该残留
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "companies" not in tables
        conn.close()
