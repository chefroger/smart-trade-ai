"""
Trade AI Assistant — 系统数据备份与还原。

备份范围：
  - ~/.trade/data/trade.db（SQLite 数据库）
  - ~/.trade/companies/{slug}/（公司数据目录）
  - ~/.trade/prompts/（系统提示词文件）
  - ~/.hermes/memories/（Hermes 记忆文件）
  - ~/.hermes/skills/b2b-*/（B2B skill 定义）

输出格式：tar.gz 压缩包，文件名格式 trade-backup-YYYY-MM-DD-HHMM.tar.gz
"""

from __future__ import annotations

import shutil
import subprocess as _sp
import sys
import tarfile
import tempfile
from datetime import datetime as _real_datetime
from pathlib import Path

from trade.post_install.skills import _get_hermes_home, _get_trade_home

# ── 系统备份 ──────────────────────────────────────────────────────────────

def backup_trade(output_dir: str | None = None) -> str:
    """备份 Trade 系统数据为 tar.gz 压缩包。

    备份内容：
      - SQLite 数据库（仅有该文件即是最小可恢复备份）
      - 公司数据目录（companies/）
      - 系统提示词（prompts/）
      - Hermes 记忆文件（.md / .json / .txt）
      - B2B skill 定义（SKILL.md）

    Args:
        output_dir: 输出目录（默认桌面）

    Returns:
        生成的 tar.gz 文件绝对路径
    """
    import datetime

    if output_dir is None:
        # 未指定输出目录时默认使用桌面。
        # 用 workdir._get_desktop_path()（Windows 走 SHGetFolderPathW 拿真实桌面）——
        # 自己猜 ~/Desktop 在 OneDrive 重定向桌面的机器上会把备份落到
        # `C:\Users\x\`（一个用户根本不会去看的地方），而界面提示的是"已保存到桌面"。
        from trade.company.workdir import _get_desktop_path

        desktop = _get_desktop_path()
        output_dir = str(desktop if desktop.is_dir() else Path.home())

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    filename = f"trade-backup-{timestamp}.tar.gz"
    out_path = Path(output_dir) / filename

    trade_home = _get_trade_home()
    hermes_home = _get_hermes_home()

    # 收集需要打包的文件路径列表
    sources: list[tuple[Path, str]] = []  # (绝对路径, tar 内的 arcname)

    # 1) SQLite 数据库：最关键的备份目标
    db_path = trade_home / "data" / "trade.db"
    if db_path.is_file():
        sources.append((db_path, ".trade/data/trade.db"))

    # 2) 公司数据目录：递归收集所有文件
    companies_dir = trade_home / "companies"
    if companies_dir.is_dir():
        for company_dir in companies_dir.iterdir():
            if company_dir.is_dir():
                for f in company_dir.rglob("*"):
                    if f.is_file():
                        rel = str(f.relative_to(trade_home))
                        sources.append((f, f".trade/{rel}"))

    # 3) 系统提示词（prompts/system.md 等）
    prompts_dir = trade_home / "prompts"
    if prompts_dir.is_dir():
        for f in prompts_dir.rglob("*"):
            if f.is_file():
                sources.append((f, f".trade/{f.relative_to(trade_home)}"))

    # 4) Hermes 记忆文件（.md / .json / .txt）
    memories_dir = hermes_home / "memories"
    if memories_dir.is_dir():
        for f in memories_dir.rglob("*"):
            if f.is_file() and f.suffix in (".md", ".json", ".txt"):
                sources.append(
                    (f, f".hermes/memories/{f.relative_to(memories_dir)}")
                )

    # 5) B2B skill 定义（每个 b2b-* 目录下的 SKILL.md）
    skills_dir = hermes_home / "skills"
    if skills_dir.is_dir():
        for skill_dir in skills_dir.iterdir():
            if skill_dir.is_dir() and skill_dir.name.startswith("b2b-"):
                skill_md = skill_dir / "SKILL.md"
                if skill_md.is_file():
                    sources.append(
                        (skill_md, f".hermes/skills/{skill_dir.name}/SKILL.md")
                    )

    if not sources:
        print("[backup] WARNING: No data found to backup.")
        sys.exit(1)

    # 打包为 tar.gz
    print(f"[backup] Packaging {len(sources)} files ...")
    with tarfile.open(out_path, "w:gz") as tar:
        for abs_path, arcname in sources:
            tar.add(str(abs_path), arcname=arcname)

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"[backup] Done: {out_path} ({size_mb:.1f} MB)")
    return str(out_path)


# ── 系统还原 ──────────────────────────────────────────────────────────────

def restore_trade(backup_file: str = "") -> str:
    """从 tar.gz 备份文件还原系统数据。

    还原步骤：
      1. 解压 tar.gz 到临时目录
      2. SQLite 完整性检查（PRAGMA integrity_check）
      3. 备份当前数据（trade-before-restore-{timestamp}.db）
      4. 替换 data/ + companies/
      5. 重启 Trade 服务

    Args:
        backup_file: tar.gz 备份文件路径

    Returns:
        还原结果消息
    """
    src = Path(backup_file)
    if not src.is_file():
        return f"✗ 备份文件不存在: {backup_file}"

    trade_home = _get_trade_home()

    # 步骤 1: 解压到临时目录（使用内建 tarfile，跨平台兼容）
    print(f"[restore] 解压 {src.name} ...")
    tmp_dir = Path(tempfile.mkdtemp(prefix="trade-restore-"))
    try:
        with tarfile.open(src, "r:gz") as tar:
            # filter="data" 有两个作用：Python 3.14 起这是默认行为（不加会
            # DeprecationWarning 且将来行为改变），且它拒绝路径穿越条目 ——
            # 备份文件是可以从别处拿到的，解压不可信归档时必须有这层防护。
            # 3.11.4 之前的 Python 没有该参数，退回旧行为。
            try:
                tar.extractall(path=tmp_dir, filter="data")
            except TypeError:
                tar.extractall(path=tmp_dir)
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return f"✗ 解压失败: {e}"

    # 步骤 2: 定位备份内容的根目录
    #
    # 备份写入的 arcname 带 `.trade/` 前缀（见本文件 backup_trade 的
    # ".trade/data/trade.db"、".trade/{rel}"）。解压后内容在
    # `tmp_dir/.trade/...`，而历史上还原代码找的是 `tmp_dir/companies`、
    # `tmp_dir/data/trade.db` —— 永远不存在，于是 if exists() 静默跳过、
    # 不报错，最后照样说"已还原"。公司档案/提示词/记忆全丢，只有 DB 被
    # rglob 兜底碰巧救回，让整条路径看起来是对的。
    root = _resolve_backup_root(tmp_dir)

    # 步骤 3: SQLite 完整性检查
    # 用 Python 的 sqlite3 模块而不是命令行 —— Windows 不带 sqlite3.exe
    # （Python 只内置模块），精简 Linux 镜像同样没有。
    db_candidates = list(root.rglob("trade.db"))
    if not db_candidates:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return "✗ 备份中未找到 trade.db"

    db_file = db_candidates[0]
    try:
        import sqlite3

        conn = sqlite3.connect(str(db_file))
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            verdict = (row[0] if row else "").lower()
        finally:
            conn.close()
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return f"✗ 数据库完整性检查失败: {e}"

    if "ok" not in verdict:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return f"✗ 数据库完整性检查失败: {verdict}"

    print("[restore] 数据库完整性检查通过")

    # 步骤 4: 备份当前数据（还原前保护措施）
    # 当前库可能不存在（首次还原到全新安装）—— 此时没有东西可保护，跳过即可。
    backup_ts = _real_datetime.now().strftime("%Y%m%d-%H%M%S")
    current_db = trade_home / "data" / "trade.db"
    if current_db.is_file():
        current_db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            current_db,
            trade_home / "data" / f"trade-before-restore-{backup_ts}.db",
        )

    # 步骤 5: 替换数据库
    current_db.parent.mkdir(parents=True, exist_ok=True)
    restored_db = root / "data" / "trade.db"
    shutil.copy2(str(restored_db if restored_db.exists() else db_file), str(current_db))

    # 步骤 6: 还原其余数据目录
    # 逐个明确处理并**如实报告**：静默跳过是这条路径历史上最严重的问题
    # （用户以为全还原了，实际只回来了一个 DB）。
    restored: list[str] = ["database"]
    missing: list[str] = []

    # companies/ 与 prompts/ 在 ~/.trade 下；memories/ 与 skills/ 在 ~/.hermes 下
    for rel, dst_root, label in (
        ("companies", trade_home, "companies"),
        ("prompts", trade_home, "prompts"),
        ("memories", _get_hermes_home(), "memories"),
        ("skills", _get_hermes_home(), "skills"),
    ):
        src_dir = root / rel
        if not src_dir.is_dir():
            missing.append(label)
            continue
        dst_dir = dst_root / rel
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(src_dir), str(dst_dir), dirs_exist_ok=True)
        restored.append(label)

    shutil.rmtree(tmp_dir, ignore_errors=True)

    # 步骤 7: 重启服务
    print("[restore] 数据已还原，正在重启服务 ...")
    _restart_trade_service()

    msg = f"✓ 已从 {src.name} 还原（{'、'.join(restored)}），服务已重启"
    if missing:
        # 备份里本就没有这些内容（如只备份了 DB）—— 必须说出来，不能静默
        msg += f"\n  ⚠ 备份中未找到：{'、'.join(missing)}（这部分数据未还原）"
    return msg


def _resolve_backup_root(tmp_dir: Path) -> Path:
    """定位解压后的备份内容根目录。

    新版备份把内容放在 `.trade/` 前缀下（`tmp_dir/.trade/...`）；也容忍
    没有前缀的备份（早期版本或手工打包），此时根目录就是 tmp_dir 本身。

    判据：目录下是否存在 `data/` 或 `companies/`。
    """
    nested = tmp_dir / ".trade"
    if nested.is_dir() and any(
        (nested / sub).exists() for sub in ("data", "companies", "prompts")
    ):
        return nested
    return tmp_dir


# ── 服务重启（跨平台） ────────────────────────────────────────────────────

def _restart_trade_service() -> None:
    """重启 Trade 服务进程（跨平台实现）。

    重启策略（按优先级）：
      1. 通过 PID 文件查找旧进程 → kill + 重新启动（推荐）
      2. launchd (macOS) → unload + load plist
      3. systemd (Linux) → systemctl --user restart
      4. 打印手动操作指引（所有自动方式都失败时）

    注意：此函数用于 restore 场景。正常升级/重启走 app.py 的
    _perform_restart()（独立 shell 子进程方式）。
    """
    import platform
    import signal as _signal
    import time as _time_module

    sys_name = platform.system()

    # ── 策略 1：通过 PID 文件终止旧进程，然后启动新进程 ──
    trade_home = _get_trade_home()
    pid_file = trade_home / "data" / "trade.pid"
    old_pid = None
    if pid_file.is_file():
        try:
            _pid_text = pid_file.read_text().strip()
            if _pid_text:
                old_pid = int(_pid_text)
        except (ValueError, OSError):
            pass  # PID 文件损坏或无内容，跳过 kill 步骤

    if old_pid is not None:
        try:
            if sys_name == "Windows":
                # Windows: taskkill 终止进程树
                _sp.run(
                    ["taskkill", "/PID", str(old_pid), "/T", "/F"],
                    capture_output=True, timeout=10,
                )
            else:
                # Unix: SIGTERM 优雅终止 → 等 2 秒 → SIGKILL 强制终止
                _os_module = __import__("os")
                _os_module.kill(old_pid, _signal.SIGTERM)
                _waited = 0
                for _ in range(20):  # 最多等 2 秒（20 × 0.1s）
                    _time_module.sleep(0.1)
                    _waited += 0.1
                    try:
                        _os_module.kill(old_pid, 0)  # 信号 0 = 检查进程是否存活
                    except OSError:
                        break  # 进程已退出
                else:
                    # 进程仍在运行，SIGKILL 强制终止
                    try:
                        _os_module.kill(old_pid, _signal.SIGKILL)
                    except OSError:
                        pass  # 进程可能已经不存在
        except Exception:
            pass  # 进程可能已经不存在，不阻塞后续重启
        finally:
            # 清理旧 PID 文件（无论 kill 成功与否）
            try:
                pid_file.unlink()
            except OSError:
                pass

    # ── 策略 2：重新启动 Trade（继承原始启动参数） ──
    cmd = _build_restart_command()
    try:
        kwargs = {
            "stdout": _sp.DEVNULL,
            "stderr": _sp.DEVNULL,
        }
        if sys_name == "Windows":
            kwargs["creationflags"] = 0x00000200  # CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True  # 独立进程会话，脱离父进程生命周期
        _sp.Popen(cmd, **kwargs)
        print("  ↻ Trade 服务已重新启动")
        return
    except Exception as e:
        print(f"  ⚠ 自动重启失败: {e}")

    # ── 策略 3：launchd (macOS) / systemd (Linux) ──
    label = "com.trade.assistant"

    if sys_name == "Darwin":
        _try_launchd_restart(label)
        return

    if sys_name == "Linux":
        _try_systemd_restart(label)
        return

    # ── 策略 4：无法自动重启，打印手动指引 ──
    _print_manual_restart_instructions(sys_name, label)


def _build_restart_command() -> list[str]:
    """根据当前进程的启动方式，推断并构建重启命令。

    支持两种启动方式：
      - python server.py（直接运行脚本）→ 复用同路径
      - 其它（console_scripts 入口等）→ 走包内入口

    **不要用 `-m trade`**：那需要 `trade/__main__.py`，而本仓库没有这个文件
    （console script 是指向 `trade.cli:run_server` 的）。历史上这里返回
    `-m trade`，子进程以 `No module named trade.__main__` 秒退，但 Popen 本身
    成功 → 照样打印「↻ Trade 服务已重新启动」，用户被告知服务已起、实际已下线。
    """
    # 通过 sys.argv 推断启动方式
    if len(sys.argv) > 0 and "server.py" in sys.argv[0]:
        # python server.py 方式 → 复用同路径
        server_py = Path(sys.argv[0]).resolve()
        if server_py.is_file():
            return [sys.executable, str(server_py)]

    # 默认：调用包内的真实入口（等价于 console script `trade`）
    return [sys.executable, "-c", "from trade.cli import run_server; run_server()"]


def _try_launchd_restart(label: str) -> None:
    """尝试通过 macOS launchd 重启服务。"""
    plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    if not plist.exists():
        return

    _launchctl = shutil.which("launchctl") or "/bin/launchctl"
    try:
        _sp.run(
            [_launchctl, "unload", str(plist)],
            capture_output=True, timeout=10,
        )
        _sp.run(
            [_launchctl, "load", str(plist)],
            capture_output=True, timeout=10,
        )
        print("  ↻ Trade 后台服务已重新加载（launchd）")
    except Exception:
        pass  # launchd 失败时静默 fallthrough


def _try_systemd_restart(label: str) -> None:
    """尝试通过 Linux systemd user unit 重启服务。"""
    for cmd in (
        ["systemctl", "--user", "restart", label],
        ["sudo", "systemctl", "restart", label],
    ):
        r = _sp.run(cmd, capture_output=True, timeout=10)
        if r.returncode == 0:
            print("  ↻ Trade 后台服务已重新启动（systemd）")
            return


def _print_manual_restart_instructions(sys_name: str, label: str) -> None:
    """当所有自动重启方式都失败时，打印明确的手动操作指引。"""
    print("  💡 Trade 代码已更新。请重启 Trade 以应用更改：")
    if sys_name == "Windows":
        print("     关闭当前 Trade 窗口后重新运行 trade 命令")
    elif sys_name == "Darwin":
        print(f"     launchctl unload ~/Library/LaunchAgents/{label}.plist")
        print(f"     launchctl load ~/Library/LaunchAgents/{label}.plist")
        print("     或手动运行: trade")
    else:
        print(f"     systemctl --user restart {label}")
        print("     或手动运行: trade")
