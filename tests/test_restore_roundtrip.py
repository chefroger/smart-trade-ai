"""备份 → 还原必须真的把数据还回来。

## 历史 bug（三处，全部只在真还原时暴露）

1. **路径前缀错配**：备份时 arcname 带 `.trade/` 前缀
   （`backup.py:68` 写 `.trade/data/trade.db`、`:78` 写 `.trade/{rel}`），
   解压到 tmp_dir 后文件落在 `tmp_dir/.trade/...`，可还原代码找的是
   `tmp_dir/"data"/"trade.db"` 与 `tmp_dir/"companies"` —— **永远不存在**，
   于是 `if exists()` 静默跳过，**不报错、不警告**，最后打印「✓ 已还原」。
   公司档案 / 提示词 / 记忆 / skills 全都没回来，只有 DB 因为
   `rglob("trade.db")` 兜底被碰巧救回 —— 这让整条路径"看起来是对的"。

2. **重启回退是死代码**：`_build_restart_command()` 返回
   `[sys.executable, "-m", "trade"]`，但**仓库里没有 `trade/__main__.py`**
   → 子进程 `No module named trade.__main__` 秒退；而 Popen 本身成功，
   所以照样打印「↻ Trade 服务已重新启动」。用户被告知服务已起，实际已下线。

3. **依赖 sqlite3 CLI**：完整性检查用 `["sqlite3", ...]`，而 Windows 不带
   `sqlite3.exe`（Python 只有 sqlite3 模块）→ 必崩。
"""

from __future__ import annotations

import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _no_real_restart(monkeypatch):
    """必须屏蔽真实重启 —— restore_trade 末尾会 Popen 一个新的 Trade 进程。

    不屏蔽的话测试会在 CI 机器上真的拉起一个服务（占端口、留进程），
    既慢又不可控。
    """
    from trade.post_install import backup as bk

    monkeypatch.setattr(bk, "_restart_trade_service", lambda: None)


@pytest.fixture
def trade_env(monkeypatch, tmp_path):
    """临时 TRADE_HOME / HERMES_HOME，带一份可辨别的数据。"""
    trade_home = tmp_path / "trade"
    hermes_home = tmp_path / "hermes"
    (trade_home / "data").mkdir(parents=True)
    (trade_home / "companies" / "acme").mkdir(parents=True)
    (trade_home / "prompts").mkdir(parents=True)
    hermes_home.mkdir(parents=True)

    # 造一个真实可用的最小 sqlite 库
    import sqlite3

    conn = sqlite3.connect(trade_home / "data" / "trade.db")
    conn.execute("CREATE TABLE marker (v TEXT)")
    conn.execute("INSERT INTO marker VALUES ('orig')")
    conn.commit()
    conn.close()

    (trade_home / "companies" / "acme" / "profile.md").write_text(
        "ACME 档案内容", encoding="utf-8"
    )
    (trade_home / "prompts" / "system.md").write_text("自定义提示词", encoding="utf-8")

    monkeypatch.setenv("TRADE_HOME", str(trade_home))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    return {"trade_home": trade_home, "hermes_home": hermes_home, "tmp": tmp_path}


class TestRoundtripRestoresData:
    def test_companies_and_prompts_come_back(self, trade_env):
        """核心：还原后公司档案与提示词必须真的回来了。"""
        from trade.post_install.backup import backup_trade, restore_trade

        archive = backup_trade(output_dir=str(trade_env["tmp"]))

        # 抹掉数据（模拟换机/重装后还原）
        th = trade_env["trade_home"]
        import shutil

        shutil.rmtree(th / "companies")
        shutil.rmtree(th / "prompts")
        (th / "data" / "trade.db").unlink()

        msg = restore_trade(archive)

        assert (th / "companies" / "acme" / "profile.md").is_file(), (
            f"公司档案没有还原（restore 返回：{msg!r}）—— "
            "备份的 arcname 带 .trade/ 前缀，还原却在不带前缀的路径找"
        )
        assert (th / "prompts" / "system.md").is_file(), "提示词没有还原"
        assert (th / "prompts" / "system.md").read_text(encoding="utf-8") == "自定义提示词"

    def test_database_restored(self, trade_env):
        from trade.post_install.backup import backup_trade, restore_trade

        archive = backup_trade(output_dir=str(trade_env["tmp"]))
        th = trade_env["trade_home"]
        (th / "data" / "trade.db").unlink()

        restore_trade(archive)

        import sqlite3

        conn = sqlite3.connect(th / "data" / "trade.db")
        try:
            assert conn.execute("SELECT v FROM marker").fetchone()[0] == "orig"
        finally:
            conn.close()

    def test_missing_payload_is_reported_not_silent(self, trade_env):
        """备份里缺内容时要报出来，不能静默跳过还宣称成功。"""
        from trade.post_install import backup as bk

        # 造一个只有 DB 的备份（没有 companies/prompts）
        thin = trade_env["tmp"] / "thin.tar.gz"
        with tarfile.open(thin, "w:gz") as tar:
            tar.add(
                trade_env["trade_home"] / "data" / "trade.db",
                arcname=".trade/data/trade.db",
            )

        msg = bk.restore_trade(str(thin))

        assert "companies" in msg or "未找到" in msg or "部分" in msg, (
            f"备份里没有公司数据却报告成功：{msg!r}"
        )


class TestIntegrityCheckHasNoCliDependency:
    def test_does_not_shell_out_to_sqlite3(self, trade_env, monkeypatch):
        """完整性检查必须用 Python 的 sqlite3 模块 —— Windows 没有 sqlite3.exe。"""
        from trade.post_install import backup as bk

        archive = bk.backup_trade(output_dir=str(trade_env["tmp"]))

        calls: list[list[str]] = []
        real_run = bk._sp.run

        def _spy(cmd, *a, **kw):
            if isinstance(cmd, (list, tuple)):
                calls.append([str(c) for c in cmd])
            return real_run(cmd, *a, **kw)

        monkeypatch.setattr(bk._sp, "run", _spy)

        bk.restore_trade(archive)

        flat = [c[0] for c in calls if c]
        assert "sqlite3" not in flat, (
            "仍在调用 sqlite3 命令行 —— Windows/精简 Linux 上没有这个可执行文件"
        )


class TestRestartCommandIsRunnable:
    def test_no_nonexistent_module_entrypoint(self):
        """`-m trade` 依赖 trade/__main__.py，而仓库里没有这个文件。"""
        from trade.post_install.backup import _build_restart_command

        cmd = _build_restart_command()

        if "-m" in cmd:
            mod = cmd[cmd.index("-m") + 1]
            assert mod != "trade", (
                "`-m trade` 需要 trade/__main__.py，而它不存在 —— 重启必然秒退，"
                "但 Popen 成功所以仍会打印「已重新启动」"
            )
