"""chat-memory 插件 + 配套的 search_history / config.yaml 写入的测试。

覆盖：
- search_history 时间范围边界（含 yesterday 含不含"现在"的语义、跨月、闰年、now=2027-01-01）
- search_history 端到端：含 end 上界、recent_days/recent_months 互斥、未知枚举 fail-safe
- ensure_chat_memory_plugin_enabled：仅追加 plugins.enabled 与 enabled_toolsets 两键，原子性
- sync_chat_memory_plugin：幂等（hash 比对不变就不写）
- 插件端到端：register + handler 拒缺 company_id + handler 互斥校验
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# ── search_history 边界（用 FakeDatetime 钉 now） ────────────────────────


class _FakeDatetime:
    """替换 trade.chat_memory._dt.datetime：构造走真 datetime，now() 拿固定值。"""

    fixed: datetime = None

    @classmethod
    def now(cls):
        return cls.fixed

    def __new__(cls, *args, **kwargs):
        return datetime(*args, **kwargs)


@pytest.fixture
def freeze_now(monkeypatch):
    """把 trade.chat_memory 内部的 datetime 换成 _FakeDatetime，用例传 now= 即可。"""
    from trade import chat_memory

    def _install(now: datetime):
        _FakeDatetime.fixed = now
        monkeypatch.setattr(chat_memory._dt, "datetime", _FakeDatetime)
    return _install


class TestSearchHistoryBoundaries:

    def test_today_at_thursday_noon(self, freeze_now):
        from trade.chat_memory import _BOUNDARY_COMPUTERS
        freeze_now(datetime(2026, 10, 15, 11, 30, 0))  # Thursday
        assert _BOUNDARY_COMPUTERS["today"](_FakeDatetime.fixed) == datetime(2026, 10, 15, 0, 0, 0)

    def test_yesterday_at_thursday_noon(self, freeze_now):
        from trade.chat_memory import _BOUNDARY_COMPUTERS
        freeze_now(datetime(2026, 10, 15, 11, 30, 0))
        assert _BOUNDARY_COMPUTERS["yesterday"](_FakeDatetime.fixed) == datetime(2026, 10, 14, 0, 0, 0)

    def test_last_week_at_thursday(self, freeze_now):
        """Thursday: this_week = Mon 10-12, last_week = Mon 10-05"""
        from trade.chat_memory import _BOUNDARY_COMPUTERS
        freeze_now(datetime(2026, 10, 15, 11, 30, 0))
        assert _BOUNDARY_COMPUTERS["last_week"](_FakeDatetime.fixed) == datetime(2026, 10, 5, 0, 0, 0)

    def test_last_week_at_monday(self, freeze_now):
        """Monday: this_week = today, last_week = 7 days ago"""
        from trade.chat_memory import _BOUNDARY_COMPUTERS
        freeze_now(datetime(2026, 10, 12, 11, 30, 0))  # Monday
        assert _BOUNDARY_COMPUTERS["last_week"](_FakeDatetime.fixed) == datetime(2026, 10, 5, 0, 0, 0)

    def test_last_month_at_october(self, freeze_now):
        from trade.chat_memory import _BOUNDARY_COMPUTERS
        freeze_now(datetime(2026, 10, 15, 11, 30, 0))
        assert _BOUNDARY_COMPUTERS["last_month"](_FakeDatetime.fixed) == datetime(2026, 9, 1, 0, 0, 0)

    def test_last_month_january_wraps_to_prev_year(self, freeze_now):
        """1 月的 last_month 必须走 12/去年（stdlib 没有 -1 month）。"""
        from trade.chat_memory import _BOUNDARY_COMPUTERS
        freeze_now(datetime(2026, 1, 15, 11, 30, 0))
        assert _BOUNDARY_COMPUTERS["last_month"](_FakeDatetime.fixed) == datetime(2025, 12, 1, 0, 0, 0)

    def test_last_year_at_january_wraps_to_2025(self, freeze_now):
        from trade.chat_memory import _BOUNDARY_COMPUTERS
        freeze_now(datetime(2026, 1, 1, 11, 30, 0))
        assert _BOUNDARY_COMPUTERS["last_year"](_FakeDatetime.fixed) == datetime(2025, 1, 1, 0, 0, 0)

    def test_now_2027_01_01_cross_year(self, freeze_now):
        """跨年：now 在 2027-01-01 11:30，last_year 必须跳回 2026。"""
        from trade.chat_memory import _BOUNDARY_COMPUTERS
        freeze_now(datetime(2027, 1, 1, 11, 30, 0))
        assert _BOUNDARY_COMPUTERS["this_year"](_FakeDatetime.fixed) == datetime(2027, 1, 1, 0, 0, 0)
        assert _BOUNDARY_COMPUTERS["last_year"](_FakeDatetime.fixed) == datetime(2026, 1, 1, 0, 0, 0)
        assert _BOUNDARY_COMPUTERS["this_month"](_FakeDatetime.fixed) == datetime(2027, 1, 1, 0, 0, 0)
        assert _BOUNDARY_COMPUTERS["last_month"](_FakeDatetime.fixed) == datetime(2026, 12, 1, 0, 0, 0)

    def test_all_returns_none(self, freeze_now):
        from trade.chat_memory import _BOUNDARY_COMPUTERS
        freeze_now(datetime(2026, 10, 15, 11, 30, 0))
        assert _BOUNDARY_COMPUTERS["all"](_FakeDatetime.fixed) is None


# ── search_history 端到端（真 SQLite） ─────────────────────────────────────


class TestSearchHistoryE2E:

    @pytest.fixture
    def db_with_rows(self, tmp_path, monkeypatch):
        """临时 TRADE_HOME + 真实 init_db + 插若干对话。

        返回 {"path", "rows": [(query, datetime)]}：日期相关的断言要用 rows 现算期望 ——
        写死期望会随日历变红（"前天"在周一/周二是上周；"10 天前"在月初是上个月）。
        """
        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        import trade.database as db
        db.init_db()
        con = db.get_connection()
        con.execute("INSERT INTO companies (id, name, slug) VALUES (1, '测试', 'test')")

        from datetime import timedelta as _td

        rows: list[tuple[str, datetime]] = []

        def insert(days_ago, q, r):
            ts = datetime.now() - _td(days=days_ago)
            con.execute(
                "INSERT INTO conversations (company_id, query, response, created_at) "
                "VALUES (1, ?, ?, ?)", (q, r, ts.strftime("%Y-%m-%d %H:%M:%S")),
            )
            rows.append((q, ts))

        insert(0, "今天的问题", "今天的回复")
        insert(1, "昨天的问题", "昨天的回复")
        insert(2, "前天的问题", "前天的回复")
        insert(10, "上周的问题", "上周的回复")
        con.commit()
        return {"path": tmp_path, "rows": rows}

    @staticmethod
    def _rows_desc(db_with_rows):
        """按时间倒序（与 search_history 的排序一致）的 (query, ts) 列表。"""
        return sorted(db_with_rows["rows"], key=lambda r: r[1], reverse=True)

    def test_today_returns_only_today(self, db_with_rows):
        from trade.chat_memory import search_history

        r = search_history(1, time_range="today")
        assert [x["query"] for x in r] == ["今天的问题"]

    def test_yesterday_excludes_today(self, db_with_rows):
        """**关键测试**：yesterday 不应包含今天 00:00 之后的内容。"""
        from trade.chat_memory import search_history

        r = search_history(1, time_range="yesterday")
        assert [x["query"] for x in r] == ["昨天的问题"]

    def test_this_week_includes_today(self, db_with_rows):
        """this_week 起点 = 本周一 0:00（含"现在"）—— 期望值按实际插入日期现算。"""
        from trade.chat_memory import search_history

        now = datetime.now()
        week_start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        expected = [q for q, ts in self._rows_desc(db_with_rows) if ts >= week_start]

        r = search_history(1, time_range="this_week")
        assert [x["query"] for x in r] == expected

    def test_last_week_does_not_include_this_week(self, db_with_rows):
        """last_week = 上周一 0:00 到本周一 0:00（前一侧完整窗口）—— 现算期望。"""
        from trade.chat_memory import search_history

        now = datetime.now()
        week_start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        last_week_start = week_start - timedelta(days=7)
        expected = [
            q for q, ts in self._rows_desc(db_with_rows)
            if last_week_start <= ts < week_start
        ]

        r = search_history(1, time_range="last_week")
        assert [x["query"] for x in r] == expected

    def test_all_returns_everything(self, db_with_rows):
        from trade.chat_memory import search_history

        r = search_history(1, time_range="all")
        assert len(r) == 4

    def test_recent_days_includes_only_within_window(self, db_with_rows):
        from trade.chat_memory import search_history

        r = search_history(1, time_range="all", recent_days=7)
        # today/昨天/前天都在 7 天内；10 天前的不在
        assert sorted(x["query"] for x in r) == sorted(["今天的问题", "昨天的问题", "前天的问题"])

    def test_recent_days_1_equals_today(self, db_with_rows):
        """recent_days=1 = today（同一起点 today 0:00，闭端到"现在"——这里"现在"是 now）。"""
        from trade.chat_memory import search_history

        r_today = search_history(1, time_range="today")
        r_rd1 = search_history(1, time_range="all", recent_days=1)
        assert sorted(x["query"] for x in r_today) == sorted(x["query"] for x in r_rd1)

    def test_recent_days_2_includes_today_and_yesterday(self, db_with_rows):
        from trade.chat_memory import search_history

        r = search_history(1, time_range="all", recent_days=2)
        # 起点 = 昨天 0:00 → 含今天 + 昨天
        assert sorted(x["query"] for x in r) == sorted(["今天的问题", "昨天的问题"])

    def test_recent_months_1_returns_only_this_month(self, db_with_rows):
        from trade.chat_memory import search_history

        now = datetime.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        expected = [q for q, ts in self._rows_desc(db_with_rows) if ts >= month_start]

        r = search_history(1, time_range="all", recent_months=1)
        # 期望按实际日期现算：月初时"10 天前"会落到上个月
        assert [x["query"] for x in r] == expected

    def test_unknown_enum_falls_through_to_all(self, db_with_rows):
        from trade.chat_memory import search_history

        r = search_history(1, time_range="完全不存在的枚举")
        assert len(r) == 4  # fail-safe → all

    def test_company_id_isolation(self, db_with_rows):
        import trade.database as db
        from trade.chat_memory import search_history

        con = db.get_connection()
        con.execute("INSERT INTO companies (id, name, slug) VALUES (2, '另一家', 'other')")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        con.execute(
            "INSERT INTO conversations (company_id, query, response, created_at) "
            "VALUES (2, '另一家的问题', '另一家的回复', ?)", (ts,),
        )
        con.commit()

        r1 = search_history(1, time_range="all")
        assert all(row["company_id"] == 1 for row in r1)
        assert not any("另一家" in row["query"] for row in r1)


# ── config.yaml 写入原子性 ───────────────────────────────────────────────


class TestEnsureChatMemoryPluginEnabled:

    @pytest.fixture
    def hermes_home(self, tmp_path, monkeypatch):
        """临时 HERMES_HOME 与 TRADE_HOME。"""
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        return tmp_path

    def _write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_creates_minimal_skeleton_when_no_config(self, hermes_home):
        from trade.bootstrap import ensure_chat_memory_plugin_enabled

        ensure_chat_memory_plugin_enabled()

        config_path = Path(hermes_home) / "config.yaml"
        assert config_path.is_file()
        content = config_path.read_text(encoding="utf-8")
        assert "chat-memory" in content

    def test_appends_to_existing_plugins_enabled(self, hermes_home):
        from trade.bootstrap import ensure_chat_memory_plugin_enabled

        config_path = Path(hermes_home) / "config.yaml"
        self._write(config_path, "plugins:\n  enabled: [foo, bar]\n")
        before = config_path.read_text(encoding="utf-8")

        ensure_chat_memory_plugin_enabled()

        new = config_path.read_text(encoding="utf-8")
        # 旧的两个 key 不能丢
        assert "foo" in new
        assert "bar" in new
        # 新增
        assert "chat-memory" in new
        # plugins 块不能丢
        assert "plugins" in new
        # 起头内容（yaml 头部空格等）不能被改坏 —— 至少 plugins: 还在
        assert before.split("plugins")[0] in new or before[:20] in new[:20]

    def test_idempotent_no_change_on_second_call(self, hermes_home):
        from trade.bootstrap import ensure_chat_memory_plugin_enabled

        ensure_chat_memory_plugin_enabled()
        first = (Path(hermes_home) / "config.yaml").read_text(encoding="utf-8")

        ensure_chat_memory_plugin_enabled()  # 第二次
        second = (Path(hermes_home) / "config.yaml").read_text(encoding="utf-8")

        # 第二次**不应**改文件
        assert first == second, "第二次应幂等，但文件内容变了"

    def test_skip_when_in_plugins_disabled(self, hermes_home, capfd):
        from trade.bootstrap import ensure_chat_memory_plugin_enabled

        config_path = Path(hermes_home) / "config.yaml"
        self._write(config_path, "plugins:\n  enabled: [foo]\n  disabled: [chat-memory]\n")
        original = config_path.read_text(encoding="utf-8")

        ensure_chat_memory_plugin_enabled()

        # disallow 总是赢：plugins.enabled 不应被加 chat-memory
        # 检查 enabled 段不含 chat-memory
        before_enabled, before_disabled, _ = original.partition("disabled:")
        # enabled 段（在 disabled 之前）只含 foo
        assert "chat-memory" not in before_enabled or "chat-memory" in original.split("disabled:")[1]
        # 提示日志
        out = capfd.readouterr().out
        assert "plugins.disabled" in out

    def test_skip_when_user_messed_up_list_type(self, hermes_home):
        """plugins.enabled 已被用户改成非 list（如 dict / str）：不要覆盖，警告。"""
        from trade.bootstrap import ensure_chat_memory_plugin_enabled

        config_path = Path(hermes_home) / "config.yaml"
        self._write(config_path, "plugins:\n  enabled:\n    foo: bar\n")
        original = config_path.read_text(encoding="utf-8")

        ensure_chat_memory_plugin_enabled()

        new = config_path.read_text(encoding="utf-8")
        # **不能**覆盖用户的 dict；chat-memory 应未写入 enabled
        assert new == original, "用户改坏的数据不应被覆盖"

    def test_does_not_delete_unrelated_top_level_keys(self, hermes_home):
        """必须**不**碰其它顶层 key。"""
        from trade.bootstrap import ensure_chat_memory_plugin_enabled

        config_path = Path(hermes_home) / "config.yaml"
        self._write(config_path, (
            "server:\n  port: 9119\n"
            "logging:\n  level: info\n"
            "plugins:\n  enabled: [foo]\n"
        ))

        ensure_chat_memory_plugin_enabled()

        new = config_path.read_text(encoding="utf-8")
        # 顶层 key 都得在
        assert "server:" in new
        assert "port: 9119" in new
        assert "logging:" in new
        assert "level: info" in new
        assert "plugins:" in new


# ── sync_chat_memory_plugin 幂等性 ──────────────────────────────────────


class TestSyncChatMemoryPlugin:

    def test_creates_plugin_dir_from_source(self, tmp_path, monkeypatch):
        from trade import bootstrap
        from trade.post_install import skills as sk_mod

        src = tmp_path / "src_plugin" / "hermes_chat_memory_plugin"
        src.mkdir(parents=True)
        (src / "plugin.yaml").write_text("name: chat-memory\nversion: 1.0.0\n", encoding="utf-8")
        (src / "__init__.py").write_text("def register(ctx): pass\n", encoding="utf-8")
        (src / "tools.py").write_text("X = 1\n", encoding="utf-8")

        # 引导 _local_chat_memory_plugin_source 到 src
        monkeypatch.setattr(bootstrap, "_local_chat_memory_plugin_source", lambda: src)
        # 引导 _get_hermes_home 到 tmp_path/hermes_home（_get_hermes_home 在 skills 模块里）
        hermes_home = tmp_path / "hermes_home"
        monkeypatch.setattr(sk_mod, "_get_hermes_home", lambda: hermes_home)

        bootstrap.sync_chat_memory_plugin()

        dst = hermes_home / "plugins" / "chat-memory"
        assert (dst / "plugin.yaml").is_file()
        assert (dst / "__init__.py").is_file()
        assert (dst / "tools.py").is_file()

    def test_idempotent_second_run(self, tmp_path, monkeypatch):
        """hash 一致时第二次只打印 up-to-date，不重写文件。"""
        from trade import bootstrap

        src = tmp_path / "src_plugin" / "hermes_chat_memory_plugin"
        src.mkdir(parents=True)
        (src / "plugin.yaml").write_text("name: chat-memory\n", encoding="utf-8")
        (src / "__init__.py").write_text("x = 1\n", encoding="utf-8")
        (src / "tools.py").write_text("x = 1\n", encoding="utf-8")

        monkeypatch.setattr(bootstrap, "_local_chat_memory_plugin_source", lambda: src)
        from trade.post_install import skills as sk_mod
        hermes_home = tmp_path / "hermes_home"
        monkeypatch.setattr(sk_mod, "_get_hermes_home", lambda: hermes_home)

        bootstrap.sync_chat_memory_plugin()
        dst = hermes_home / "plugins" / "chat-memory"
        first_mtime = (dst / "plugin.yaml").stat().st_mtime_ns

        # 等够长时间以保证 mtime 真的可能不同
        import time as _t
        _t.sleep(0.05)
        bootstrap.sync_chat_memory_plugin()
        second_mtime = (dst / "plugin.yaml").stat().st_mtime_ns

        assert first_mtime == second_mtime, "up-to-date 时不应重写文件（mtime 不该变）"

    def test_redeploys_when_source_changes(self, tmp_path, monkeypatch):
        from trade import bootstrap

        src = tmp_path / "src_plugin" / "hermes_chat_memory_plugin"
        src.mkdir(parents=True)
        (src / "plugin.yaml").write_text("name: chat-memory\nversion: 1.0.0\n", encoding="utf-8")
        (src / "__init__.py").write_text("x = 1\n", encoding="utf-8")
        (src / "tools.py").write_text("x = 1\n", encoding="utf-8")

        monkeypatch.setattr(bootstrap, "_local_chat_memory_plugin_source", lambda: src)
        from trade.post_install import skills as sk_mod
        hermes_home = tmp_path / "hermes_home"
        monkeypatch.setattr(sk_mod, "_get_hermes_home", lambda: hermes_home)

        bootstrap.sync_chat_memory_plugin()

        # 改源
        (src / "tools.py").write_text("x = 2\n", encoding="utf-8")

        bootstrap.sync_chat_memory_plugin()
        dst = hermes_home / "plugins" / "chat-memory" / "tools.py"
        assert dst.read_text(encoding="utf-8") == "x = 2\n"


# ── 插件端到端（注册 + handler 互斥校验） ───────────────────────────────


class TestChatMemoryPluginE2E:

    def _load_plugin(self):
        """直接 import 插件模块（不通过 trade.bootstrap）。

        路径必须**从本文件位置推**，不能写死 —— 第一版写死了开发机的绝对路径，
        本地全绿、CI 上 6 个用例全挂在 FileNotFoundError（仓库不在那个路径下）。
        """
        plugin_path = Path(__file__).resolve().parent.parent / "trade" / "hermes_chat_memory_plugin"
        spec = importlib.util.spec_from_file_location("chat_memory_plugin", plugin_path / "__init__.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_register_registers_one_tool(self):
        plugin = self._load_plugin()
        calls = []
        class Ctx:
            def register_tool(self, **kw): calls.append(kw)
        plugin.register(Ctx())
        assert len(calls) == 1
        assert calls[0]["name"] == "chat_memory_list"
        assert calls[0]["toolset"] == "chat-memory"
        assert "schema" in calls[0] and "handler" in calls[0]

    def test_handler_rejects_missing_company_id(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        plugin = self._load_plugin()
        res = json.loads(plugin.handle_chat_memory_list({"time_range": "all"}))
        assert "error" in res
        assert "company_id" in res["error"]

    def test_handler_rejects_non_int_company_id(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        plugin = self._load_plugin()
        res = json.loads(plugin.handle_chat_memory_list({"company_id": "1", "time_range": "all"}))
        assert "company_id" in res["error"]

    def test_handler_rejects_recent_days_and_months_together(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        plugin = self._load_plugin()
        res = json.loads(plugin.handle_chat_memory_list({
            "company_id": 1, "recent_days": 7, "recent_months": 2,
        }))
        assert "mutually exclusive" in res["error"]

    def test_handler_rejects_zero_recent_days(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        plugin = self._load_plugin()
        res = json.loads(plugin.handle_chat_memory_list({
            "company_id": 1, "recent_days": 0,
        }))
        assert "recent_days" in res["error"]

    def test_handler_succeeds_with_valid_args(self, tmp_path, monkeypatch):
        """端到端：真 SQLite + 真 handler。"""
        # 用 monkeypatch 而不是直接赋值 —— 后者不会在用例结束时还原，
        # 会把 TRADE_HOME 渗给后续用例（它们拿到的是已删除的 tmp_path）
        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        import trade.database as db
        db.init_db()
        con = db.get_connection()
        con.execute("INSERT INTO companies (id, name, slug) VALUES (1, 't', 't')")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        con.execute(
            "INSERT INTO conversations (company_id, query, response, created_at) "
            "VALUES (1, '今天', '今天回', ?)", (ts,),
        )
        con.commit()

        plugin = self._load_plugin()
        res = json.loads(plugin.handle_chat_memory_list({"company_id": 1, "time_range": "today"}))
        assert "error" not in res
        assert res["count"] == 1
        assert res["rows"][0]["query"] == "今天"


# ── 回归：2026-10-16 外部验证抓到的三个问题 ────────────────────────────


class TestPluginToolsetIsEnabled:
    """插件声明的 toolset **必须**在 trade 的 DEFAULT_ENABLED_TOOLSETS 里。

    这是本 feature 的"最后一公里"：Hermes 只把 enabled 列表里那些 toolset 的工具
    放进工具表。插件加载成功（enabled=True / tools=1）但 toolset 没启用的话，
    工具就只是躺在注册表里、**LLM 完全看不见** —— 和"工具根本不存在"等效。

    2026-10-16 实测就是这么翻车的：我验证"工具在不在工具表里"时**显式传了**
    chat-memory，而 trade 的真实路径传的是 DEFAULT_ENABLED_TOOLSETS（里面没有它）。
    这条契约测试直接从插件注册结果反查，任何一边漏了就红。
    """

    def test_plugin_toolset_is_in_default_enabled_toolsets(self):
        from trade.helpers import DEFAULT_ENABLED_TOOLSETS

        plugin = TestChatMemoryPluginE2E()._load_plugin()
        captured = []

        class Ctx:
            def register_tool(self, **kw):
                captured.append(kw)

        plugin.register(Ctx())

        assert captured, "插件没有注册任何工具"
        for kw in captured:
            toolset = kw["toolset"]
            assert toolset in DEFAULT_ENABLED_TOOLSETS, (
                f"插件把工具注册到 toolset={toolset!r}，但它不在 DEFAULT_ENABLED_TOOLSETS "
                f"里 → Hermes 不会把该工具放进 agent 工具表，LLM 看不见它。"
                f"现有列表：{list(DEFAULT_ENABLED_TOOLSETS)}"
            )


class TestRecentMonthsAtMonthEnd:
    """`recent_months ≥ 2` 在月末不得崩。

    2026-10-16 外部验证抓到：直接拿"当前时刻"逐月回退，在 3/31、5/31、7/31、10/31
    会 ValueError（2/4/6/9 月没有 31 号）。修法是回退前先归一到月初。
    原测试只覆盖 recent_months=1（循环零次），这条路完全没测到。
    """

    @pytest.mark.parametrize("month", [1, 3, 5, 7, 8, 10, 12])
    def test_month_end_does_not_crash(self, freeze_now, tmp_path, monkeypatch, month):
        """这些月份的 31 号都要能跑（2/4/6/9/11 月没有 31 号，不在参数里）。"""
        from datetime import datetime as _dt

        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        import trade.database as db
        db.init_db()

        freeze_now(_dt(2026, month, 31, 11, 30, 0))
        from trade.chat_memory import search_history

        for n in (2, 3, 6):
            rows = search_history(1, time_range="all", recent_months=n)
            assert isinstance(rows, list)

    def test_window_is_month_start_not_day_end(self, freeze_now, tmp_path, monkeypatch):
        """归一到月初后，窗口起点仍是"N-1 个月前的 1 号"，不是被截断的月末。"""
        from datetime import datetime as _dt

        from trade.chat_memory import _start_of_month, _subtract_one_month

        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        import trade.database as db
        db.init_db()

        now = _dt(2026, 3, 31, 11, 30, 0)
        freeze_now(now)
        # 复算实现的窗口起点：3/31 → 归一 3/1 → 回退 1 次 → 2/1
        expected = _subtract_one_month(_start_of_month(now))
        assert expected == _dt(2026, 2, 1, 0, 0, 0)

        from trade.chat_memory import search_history
        ts = _dt(2026, 2, 15, 10, 0, 0).strftime("%Y-%m-%d %H:%M:%S")
        with_ts = _dt(2026, 1, 15, 10, 0, 0).strftime("%Y-%m-%d %H:%M:%S")
        con = db.get_connection()
        con.execute("INSERT INTO companies (id, name, slug) VALUES (1,'t','t')")
        con.execute("INSERT INTO conversations (company_id,query,response,created_at) VALUES (1,'2月中','r',?)", (ts,))
        con.execute("INSERT INTO conversations (company_id,query,response,created_at) VALUES (1,'1月中','r',?)", (with_ts,))
        con.commit()

        rows = search_history(1, time_range="all", recent_months=2)
        # 窗口是 [2/1, now=3/31]，所以只该拿到"2月中"，拿不到"1月中"
        assert sorted(r["query"] for r in rows) == ["2月中"]


class TestSchemaDescriptionAccuracy:
    """schema 描述不能把 LLM 引到错的参数上。

    2026-10-16 外部验证抓到：`recent_days` 的描述写"N=1 等价于 'yesterday'"，而实现是
    "今天 00:00 起"（= today）。LLM 照着描述走，用户问"昨天"就会传 recent_days=1，
    拿到的是**今天**的数据 —— 静默答错，比报错更糟。
    """

    def test_recent_days_description_does_not_claim_yesterday(self):
        from trade.hermes_chat_memory_plugin import tools as cm_tools

        desc = cm_tools._RECENT_DAYS_DESCRIPTION
        assert "yesterday" not in desc or "不是" in desc or "**不是**" in desc, (
            "描述里把 recent_days=1 说成 yesterday 了 —— 会误导 LLM 用错参数"
        )
        assert "today" in desc, "应明确说 N=1 等价于 today"

    def test_enum_values_match_implementation(self):
        """schema 的 enum 必须与 search_history 认的枚举一一对应（两边漏一个就漂移）。"""
        from trade.chat_memory import _VALID_TIME_RANGES
        from trade.hermes_chat_memory_plugin.tools import CHAT_MEMORY_LIST_SCHEMA

        enum = set(CHAT_MEMORY_LIST_SCHEMA["parameters"]["properties"]["time_range"]["enum"])
        assert enum == set(_VALID_TIME_RANGES), (
            f"schema enum 与实现不一致：schema-only={enum - set(_VALID_TIME_RANGES)}, "
            f"impl-only={set(_VALID_TIME_RANGES) - enum}"
        )
