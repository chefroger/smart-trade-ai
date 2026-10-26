"""
Trade AI Assistant — 一键系统更新。

update_trade() 按序执行 7 个步骤：
  1. git pull（在运行目录拉取最新代码；拉取前钉选远端 main 的 SHA，
     拉取后回读 HEAD 必须与之一致，否则中止并回退）
  2. install_skills()（安装新增的 b2b-* skill 目录 + 模板）
  3. update_skills()（从 GitHub 同步每个 SKILL.md 内容）
  4. pip install -e .（更新包及依赖）
  5. _sync_trade_template()（同步新增的模板文件）
  6. _ensure_auto_start()（开机自启设置幂等检查）
  7. 数据库迁移检查

用法：trade-update（或 trade update）
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from trade.post_install.skills import (
    _get_trade_home,
    install_skills,
    update_skills,
)

# ── 目录同步 ──────────────────────────────────────────────────────────────

def _sync_dir_rsync(src: Path, dst: Path) -> None:
    """递归同步目录 src → dst（覆盖旧文件，删除目标中多余文件）。

    不跟踪软链接，不保留权限（统一 0o644/0o755）。
    跳过 __pycache__、.DS_Store、.pyc 文件。
    """
    if not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)

    _keep = set()  # 记录源目录的所有目标路径，用于后续清理
    for item in src.rglob("*"):
        # 跳过构建产物和系统文件
        if item.name in ("__pycache__", ".DS_Store") or item.name.endswith(".pyc"):
            continue
        rel = item.relative_to(src)
        target = dst / rel
        _keep.add(str(target))
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            # 只复制修改过的文件（mtime 比对，减少不必要的写盘）
            if not target.is_file() or item.stat().st_mtime != target.stat().st_mtime:
                shutil.copy2(item, target)

    # 删除目标中多余的文件（源目录已移除的文件在目标中也应删除）
    for item in sorted(dst.rglob("*"), reverse=True):
        if item.name in ("__pycache__", ".DS_Store"):
            continue
        if str(item) not in _keep:
            if item.is_dir() and not any(
                str(c).startswith(str(item)) for c in _keep
            ):
                shutil.rmtree(item)
            elif item.is_file():
                item.unlink()


def _sync_trade_template(template_src: Path, trade_home: Path) -> None:
    """将 .trade-template/ 中新增的模板文件同步到 Trade 运行时目录。

    仅复制新增的文件，不覆盖用户已有数据。
    同时处理 prompts/system.md 的植入逻辑（与 install_skills 行为一致）。
    """
    if not template_src.is_dir():
        return

    _dest = trade_home / ".trade-template"
    if not _dest.exists():
        # 模板目录不存在：全量复制
        shutil.copytree(template_src, _dest, dirs_exist_ok=False)
        for f in _dest.rglob("*"):
            if f.is_file() and os.name != "nt":
                f.chmod(0o644)
    else:
        # 模板目录已存在：仅复制源目录中有但目标目录中缺少的文件
        for item in template_src.rglob("*"):
            rel = item.relative_to(template_src)
            target = _dest / rel
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif item.is_file() and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                if os.name != "nt":
                    target.chmod(0o644)

    # 植入初始 system prompt（仅当目标文件尚不存在时，不覆盖用户编辑的内容）
    prompts_src = template_src / "prompts" / "system.md"
    prompts_dir = trade_home / "prompts"
    prompts_dst = prompts_dir / "system.md"
    if prompts_src.is_file() and not prompts_dst.is_file():
        prompts_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(prompts_src, prompts_dst)
        if os.name != "nt":
            prompts_dst.chmod(0o644)


# ── 开机自启动 ────────────────────────────────────────────────────────────

def _auto_start_present() -> bool:
    """当前机器上是否已有 Trade 的开机自启项（用于更新时尊重用户的关闭决定）。

    近似的存在性检查即可：更新只决定「要不要重新注册」，不需要精确状态。
    任何异常都按"不存在"处理（宁可不碰自启配置）。
    """
    try:
        if os.name == "nt":
            from trade.post_install.win_setup import TASK_NAME

            r = subprocess.run(
                ["schtasks", "/query", "/tn", TASK_NAME],
                capture_output=True, timeout=15,
            )
            return r.returncode == 0
        if sys.platform == "darwin":
            return (
                Path.home() / "Library" / "LaunchAgents" / "com.trade.assistant.plist"
            ).is_file()
        if sys.platform == "linux":
            return (Path.home() / ".config" / "systemd" / "user" / "trade.service").is_file()
    except Exception:
        pass
    return False


def _ensure_auto_start(trade_dir: Path) -> None:
    """确保 Trade 在操作系统启动时自动运行（幂等操作：已存在则跳过）。

    支持的平台：
      - Windows: Task Scheduler 登录时触发
      - macOS:   launchd plist 用户级守护进程
      - Linux:   systemd user unit
    """
    if os.name == "nt":
        _ensure_windows_auto_start(trade_dir)
    elif sys.platform == "darwin":
        _ensure_macos_auto_start(trade_dir)
    elif sys.platform == "linux":
        _ensure_linux_auto_start(trade_dir)


def _ensure_windows_auto_start(trade_dir: Path) -> None:
    """Windows: 开机自启（隐藏窗口）+ 桌面快捷方式。

    委托给 `trade.post_install.win_setup` —— 那里是唯一实现，install.ps1 和
    服务启动路径也调它。历史教训：这段逻辑曾有三份互相不一致的拷贝，其中两份
    跑 python.exe（登录必弹终端窗口），只有文档里的手动教程是对的。
    """
    from trade.post_install.win_setup import ensure_windows_setup

    for msg in ensure_windows_setup(trade_dir):
        print(f"  {msg}")


def _ensure_macos_auto_start(trade_dir: Path) -> None:
    """macOS: 创建 launchd plist 用户级守护进程（Label: com.trade.assistant）。

    plist 写入 ~/Library/LaunchAgents/，login 时自动加载。
    """
    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_file = plist_dir / "com.trade.assistant.plist"
    if plist_file.is_file():
        print("  ✓ 开机自启动任务已存在")
        return

    # trade 命令路径（优先 ~/.local/bin/trade，其次 PATH 中的 trade）
    trade_bin = os.environ.get("HOME", str(Path.home())) + "/.local/bin/trade"
    plist_content = textwrap.dedent(f"""\
    <?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
    <plist version="1.0">
    <dict>
        <key>Label</key>
        <string>com.trade.assistant</string>
        <key>ProgramArguments</key>
        <array>
            <string>{trade_bin}</string>
            <string>--no-browser</string>
        </array>
        <key>RunAtLoad</key>
        <true/>
        <key>KeepAlive</key>
        <true/>
    </dict>
    </plist>""")

    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_file.write_text(plist_content, encoding="utf-8")
    # bootstrap 加载到当前用户的 GUI session
    subprocess.run(
        ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist_file)],
        capture_output=True, timeout=30,
    )
    print("  ✓ 已设置开机自启动")


def _ensure_linux_auto_start(trade_dir: Path) -> None:
    """Linux: 创建 systemd user unit → daemon-reload → enable → start。"""
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_file = unit_dir / "trade.service"
    if unit_file.is_file():
        print("  ✓ 开机自启动任务已存在")
        return

    py_exe = sys.executable
    server_py = str(trade_dir / "server.py")
    unit_content = textwrap.dedent(f"""\
    [Unit]
    Description=Smart Trade AI
    After=network.target

    [Service]
    Type=simple
    ExecStart={py_exe} {server_py} --no-browser
    Restart=on-failure
    RestartSec=10

    [Install]
    WantedBy=default.target
    """)

    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_file.write_text(unit_content, encoding="utf-8")
    subprocess.run(
        ["systemctl", "--user", "daemon-reload"],
        capture_output=True, timeout=30,
    )
    subprocess.run(
        ["systemctl", "--user", "enable", "trade.service"],
        capture_output=True, timeout=30,
    )
    subprocess.run(
        ["systemctl", "--user", "start", "trade.service"],
        capture_output=True, timeout=30,
    )
    print("  ✓ 已设置开机自启动")


# ── 可选依赖（best-effort）───────────────────────────────────────────────

# 客户语义检索用的向量扩展。**不是主链依赖**：不装则语义检索自动降级关键词，
# 其余功能零影响。单独装、失败只警告 —— 个别平台（如 Windows ARM）没有
# 对应 wheel，不能让一个可选能力把整次升级搞失败。
_OPTIONAL_DEPS = ("sqlite-vec>=0.1.6",)


def _install_optional_deps(emit, warnings: list[str]) -> None:
    """装可选依赖；已装则跳过，任何失败只记警告，绝不阻断升级。

    emit 由调用方传入（update_trade() 里的闭包，同时 print + 记 messages）——
    本函数是模块级的，拿不到那个闭包。
    """
    try:
        import sqlite_vec  # noqa: F401

        return  # 已装
    except ImportError:
        pass
    emit("→ Step 4b: 可选依赖（客户语义检索）...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", *_OPTIONAL_DEPS],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            emit("  ✓ sqlite-vec 已启用（客户语义检索可用）")
        else:
            emit("  ⚠ sqlite-vec 安装失败：语义检索降级为关键词（其余功能不受影响）")
            warnings.append("optional dep sqlite-vec failed to install")
    except Exception as e:  # 超时/环境异常都不该拖垮升级
        emit(f"  ⚠ 可选依赖安装跳过：{e}")
        warnings.append(f"optional dep install skipped: {e}")


# ── 一键更新主函数 ────────────────────────────────────────────────────────

def _refuse_reason_for_interpreter() -> str | None:
    """当前解释器是否允许执行升级；不允许时返回给用户看的原因（允许返回 None）。

    为什么必须挡：升级过程中的全部 `pip install` 都用 `sys.executable`。若 update_trade()
    是被**系统 python** 调起的（cron / launchd / 计划任务 / 用户手敲 python），依赖会装进
    **全局 site-packages** —— 既污染用户系统，又因为 Trade 的启动器指向自己的 venv，
    下次启动仍然缺依赖，白升一场。

    判据刻意保守（宁可放过、不可误拦）：只在**确知** Trade 的 venv 存在、且当前解释器
    不在其中时才拒绝。在开发机上从仓库直接跑（本机没有 trade venv）不会被拦。
    """
    venv_markers = [
        _get_trade_home() / "venv",
        Path.home() / ".trade" / "venv",
    ]
    # pyvenv.cfg 是两个平台上都可靠的 venv 标志
    existing = [v for v in venv_markers if (v / "pyvenv.cfg").is_file()]

    if sys.prefix == sys.base_prefix:
        # 根本不在任何 venv 里 → 一定会写进全局 site-packages
        return "当前解释器不在任何虚拟环境内，继续升级会污染系统 Python 的包目录。"

    # Windows 路径大小写不敏感 → 归一化后再比，避免把「就是同一个 venv」误判成不同
    here = os.path.normcase(str(Path(sys.prefix).resolve()))
    in_trade_venv = any(
        here == os.path.normcase(str(v.resolve())) for v in existing
    )
    if existing and not in_trade_venv:
        # 在某个 venv 里，但不是 Trade 的那个 → 装了也不会生效
        return "当前解释器不是 Trade 自己的运行环境，升级不会生效。"
    return None


def _git_head(trade_dir: Path) -> str | None:
    """读取检出当前的 HEAD sha；目录不存在 / 非 git 仓库 / 无 git 时返回 None。"""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(trade_dir), capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    sha = r.stdout.strip()
    return sha if r.returncode == 0 and len(sha) >= 7 else None


def _remote_main_sha_from(remote: str, cwd: Path) -> str | None:
    """解析 `remote` 的 main 分支当前提交 SHA；解析失败返回 None。

    禁止交互提示（GIT_TERMINAL_PROMPT=0）：私有仓库/凭证过期时会让 `git` 在
    后台服务里等账号密码，界面永远停在"更新中"。
    """
    try:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        r = subprocess.run(
            ["git", "ls-remote", remote, "refs/heads/main"],
            cwd=str(cwd), capture_output=True, text=True, timeout=60,
            env=env,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    parts = r.stdout.split()
    sha = parts[0].strip().lower() if parts else ""
    if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        return None
    return sha


def _remote_main_sha(trade_dir: Path) -> str | None:
    """解析 origin/main 当前的提交 SHA，用于把本次更新钉死在这个提交上。

    为什么先查远端：`git pull origin main` 拉的是"命令执行那一刻"的分支头，
    若拉取过程中远端被推了新提交，装进来的就未必是用户点更新时那个版本。
    先记下 SHA、拉取后再回读 HEAD 比对，不一致就中止 —— 宁可让用户重试，
    也不要把一个未经确认的提交装进本机。
    """
    return _remote_main_sha_from("origin", trade_dir)


def _verify_pinned_head(
    trade_dir: Path, target_sha: str, emit, errors: list[str],
) -> bool:
    """回读 HEAD，确认它正是本次钉选的提交；不一致记错误并返回 False。"""
    got = _git_head(trade_dir)
    if got == target_sha:
        emit(f"  ✓ 已停在钉选提交 {target_sha[:8]}")
        return True
    got_short = (got or "unknown")[:8]
    emit(f"  ❌ HEAD 与钉选提交不一致：期望 {target_sha[:8]}，实际 {got_short}")
    errors.append(f"pinned head mismatch: expected {target_sha[:8]}, got {got_short}")
    return False


def _prune_failed_migration_copies(backups_dir: Path, keep: int = 3) -> None:
    """只保留最近 `keep` 份 `*-failed-migration.db` 现场副本。

    每次迁移失败都会另存一份；不清理会无限累积（审计 P1-10 残留）。
    清理失败只忽略 —— 留盘比中断恢复安全。
    """
    try:
        olds = sorted(
            backups_dir.glob("trade-*-failed-migration.db"), reverse=True,
        )
        for stale in olds[keep:]:
            stale.unlink(missing_ok=True)
    except OSError:
        pass


def _restore_db_after_failed_migration(
    backup_path: Path, db_path: Path, emit, warnings: list[str],
) -> bool:
    """数据库迁移失败后，把库恢复到升级前的快照。

    为什么不能只回滚代码：Step 7 的迁移可能已经改了表结构（ALTER TABLE 不可逆），
    旧代码面对半迁移的库仍可能起不来。升级前那份备份本来就是为了这一刻。

    恢复前先把"迁移失败后的库"另存一份（`*-failed-migration.db`）—— 它可能已经是
    半迁移状态，但仍是排查迁移 bug 的唯一现场，不能直接覆盖掉。
    """
    import sqlite3

    if backup_path is None or not backup_path.is_file():
        warnings.append("no pre-upgrade db backup to restore")
        return False

    stamp = time.strftime("%Y%m%d-%H%M%S")
    failed_copy = backup_path.parent / f"trade-{stamp}-failed-migration.db"
    try:
        from trade.post_install.backup import snapshot_db

        snapshot_db(db_path, failed_copy)
        emit(f"  ℹ️ 迁移失败的库已另存：{failed_copy.name}")
        _prune_failed_migration_copies(backup_path.parent)
    except Exception as e:
        # 现场拷贝失败不阻断恢复：备份本身还在
        warnings.append(f"failed-migration snapshot skipped: {e}")

    try:
        # 用 SQLite 在线备份 API 写回，而不是 shutil.copy2：服务仍在运行，
        # 直接覆盖文件会与 WAL / 活跃连接打架。
        src = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
        try:
            dst = sqlite3.connect(str(db_path), timeout=30)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
    except Exception as e:
        emit(f"  ❌ 恢复数据库备份失败：{e}")
        emit(f"  💡 请手动用备份覆盖数据库：{backup_path}")
        warnings.append(f"db restore after failed migration failed: {e}")
        return False

    emit(f"  ↩ 数据库已恢复到升级前备份（{backup_path.name}）")
    return True


def _rollback_checkout(
    trade_dir: Path, target_sha: str, emit, warnings: list[str],
) -> bool:
    """把检出回退到升级前的提交，返回是否成功。

    为什么必须回滚：git pull 成功后，后面任何一步致命失败（pip 装不上、数据库
    迁移失败）都会留下「源码已是新版、依赖还是旧版」的半升级状态 —— 服务不重启，
    但下次重启就会用新代码配旧依赖启动，直接起不来（2026-10-21 审计 P0）。
    回到旧源码，至少让失败升级保持「可继续用旧版本运行」。

    为什么用 `reset --keep` 而不是 `--hard`：`--keep` 保留用户在运行目录里的
    未提交改动，且当回退会覆盖这些改动时**直接中止** —— `--hard` 会静默删掉
    用户的工作，比半升级更难挽回。
    """
    try:
        r = subprocess.run(
            ["git", "reset", "--keep", target_sha],
            cwd=str(trade_dir), capture_output=True, text=True, timeout=120,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as e:
        msg = f"rollback to {target_sha[:8]} failed: {e}"
        emit(f"  ❌ 回退失败：{e}")
        warnings.append(msg)
        return False

    if r.returncode != 0:
        detail = (r.stderr or r.stdout).strip()
        msg = f"rollback to {target_sha[:8]} failed: {detail[:200]}"
        emit(f"  ❌ 回退失败（可能有未提交改动与之冲突）：{detail[:200]}")
        emit(f"  💡 手动恢复：cd {trade_dir} && git reset --keep {target_sha}")
        warnings.append(msg)
        return False

    # 退出码不等于回退成功：`git reset --keep` 在遇到冲突的未提交改动时
    # **静默放弃、既不改工作树也不报错，退出码仍是 0**（2026-10-21 真机实测）。
    # 只信退出码会把"没回退"误报成"已回退" —— 用户以为回到了旧版本，
    # 实际代码还停在新版。唯一可靠的判据是回读 HEAD。
    now_head = _git_head(trade_dir)
    if now_head is None or not now_head.startswith(target_sha[:8]):
        msg = f"rollback to {target_sha[:8]} did not take effect (HEAD={now_head})"
        emit("  ❌ 回退未生效（工作区有与回退冲突的未提交改动，git 已放弃回退）")
        emit(f"  💡 手动恢复：cd {trade_dir} && git stash && git reset --keep {target_sha}")
        warnings.append(msg)
        return False

    emit(f"  ↩ 已回退代码到升级前版本（{target_sha[:8]}），继续用旧版本运行。")
    # Step 2/3 已把新代码的技能复制进 ~/.hermes/skills —— 回退代码后重新同步一次，
    # 保持「代码版本 ↔ 技能版本」自洽；失败只是多一条警告，不掩盖回滚本身成功。
    try:
        install_skills()
    except (SystemExit, Exception) as e:
        warnings.append(f"skills resync after rollback failed: {e}")
    return True


def update_trade() -> dict:
    """一键更新 Foreign Trade Assistant 系统。

    返回结构化结果: {"ok": bool, "version": str, "errors": list[str], "messages": list[str]}

    7 步更新流程（全部在 ~/.trade/foreign-trade-assistant/ 中执行，不依赖开发目录）：
      1. git pull / git clone
      2. install_skills()
      3. update_skills()
      4. pip install -e .
      5. template sync
      6. auto-start check
      7. database migration
    """
    trade_home = _get_trade_home()
    trade_dir = trade_home / "foreign-trade-assistant"
    # errors = 致命失败（git / pip / 数据库），必须阻止重启
    # warnings = 非致命失败（skills / 模板 / 开机自启），记录并上报但继续重启
    errors: list[str] = []
    warnings: list[str] = []
    messages: list[str] = []
    new_version = ""
    pre_update_db_backup: Path | None = None

    def _emit(msg: str) -> None:
        """同时 print 和记录到 messages（保持 CLI 和 API 兼容）。"""
        print(msg)
        messages.append(msg)

    # ── Step 0: 架构检测 ─────────────────────────────────────────────────
    from trade.bootstrap import check_native_architecture
    if not check_native_architecture():
        _emit("  ✗ 升级已中止：架构不匹配，继续升级会导致 Hermes 不可用。")
        return {
            "ok": False,
            "version": "",
            "errors": ["architecture_mismatch"],
            "warnings": warnings,
            "messages": messages,
        }

    # ── Step 0b: 解释器必须跑在 Trade 自己的 venv 内 ───────────────────────
    _refuse = _refuse_reason_for_interpreter()
    if _refuse:
        _emit(f"  ✗ 升级已中止：{_refuse}")
        _emit(f"    当前解释器: {sys.executable}")
        _emit("    请在 Trade 界面里点「更新」，或在终端执行 `trade update`。")
        return {
            "ok": False,
            "version": "",
            "errors": ["not_in_trade_venv"],
            "warnings": warnings,
            "messages": messages,
        }

    # ── Step 0c: 升级前数据库备份 ──────────────────────────────────────────
    # 为什么必须在 Step 1 之前：数据库迁移不可逆，一旦迁移失败或新版本行为有变，
    # 没有开工前的快照就无法回到"能跑"的状态。备份失败必须**中止升级** ——
    # 在没有可回退备份的情况下换代码 + 迁移 schema，比"升级失败"严重得多。
    try:
        from trade.post_install.backup import backup_db_before_upgrade

        pre_update_db_backup = backup_db_before_upgrade(
            trade_home / "data" / "trade.db",
            trade_home / "backups",
        )
        if pre_update_db_backup:
            _emit(f"  ✓ 升级前数据库备份：{pre_update_db_backup.name}")
        else:
            _emit("  ℹ️ 尚无数据库（首次安装），跳过备份")
    except Exception as e:
        _emit(f"  ❌ 升级前备份失败，已中止升级：{e}")
        errors.append(f"pre-upgrade backup failed: {e}")
        return {
            "ok": False, "version": "", "error": f"升级前备份失败：{e}",
            "errors": errors, "warnings": warnings, "messages": messages,
        }

    # 升级前的提交：Step 1 之后任何致命失败都要回退到这里（见 _rollback_checkout）。
    # clone 场景没有旧提交 —— 目录本身不存在，失败时无事可回退。
    pre_update_sha = _git_head(trade_dir) if trade_dir.is_dir() else None

    def _rollback_if_possible(reason: str) -> None:
        """致命失败后回退源码（有旧提交时）；回滚失败只记警告，不掩盖原始错误。"""
        if not pre_update_sha:
            return
        if _rollback_checkout(trade_dir, pre_update_sha, _emit, warnings):
            warnings.append(f"checkout rolled back after {reason}")

    # ── Step 1: git pull / clone ───────────────────────────────────────────
    # 本次更新钉选的提交（clone 也在 clone 后 checkout 到同一个 SHA）
    target_sha: str | None = None
    _REPO_URL = "https://github.com/chefroger/smart-trade-ai.git"
    if not trade_dir.is_dir():
        _emit("→ Step 1/7: git clone (install directory not found) ...")
        _emit(f"  Target: {trade_dir}")
        trade_dir.parent.mkdir(parents=True, exist_ok=True)
        # 首次安装同样钉选：clone 拿到的是 clone 那一刻的分支头，先记下 SHA
        target_sha = _remote_main_sha_from(_REPO_URL, trade_dir.parent)
        if not target_sha:
            _emit("  ❌ 无法解析远端 main 的最新提交（网络/代理或仓库不可达），已中止安装。")
            errors.append("cannot resolve remote main commit")
            return {
                "ok": False, "version": "",
                "error": "无法解析远端 main 的最新提交，请检查网络或代理后重试。",
                "errors": errors, "warnings": warnings, "messages": messages,
            }
        _emit(f"  ℹ️ 本次安装钉选提交：{target_sha[:8]}")
        try:
            clone_result = subprocess.run(
                ["git", "clone", _REPO_URL, str(trade_dir)],
                capture_output=True, text=True, timeout=300,
            )
        except FileNotFoundError:
            _emit("  ❌ git 命令未找到，请先安装 Git for Windows 并重启终端")
            errors.append("git not found")
            return {"ok": False, "version": "", "error": "Git 未安装或不在 PATH 中，请先安装 Git for Windows", "errors": errors, "warnings": warnings, "messages": messages}
        if clone_result.returncode != 0:
            err = clone_result.stderr.strip()
            _emit(f"  ❌ git clone failed: {err}")
            errors.append(f"git clone failed: {err}")
            return {"ok": False, "version": "", "error": err, "errors": errors, "warnings": warnings, "messages": messages}
        # 把本地 main 指到钉选提交（clone 期间远端可能被推进）；之后回读校验
        pinned = subprocess.run(
            ["git", "checkout", "-B", "main", target_sha],
            cwd=str(trade_dir), capture_output=True, text=True, timeout=120,
        )
        if pinned.returncode != 0:
            err = (pinned.stderr or pinned.stdout).strip()
            _emit(f"  ❌ 无法检出钉选提交 {target_sha[:8]}：{err[:200]}")
            errors.append(f"checkout pinned clone failed: {err[:200]}")
            _emit("  💡 已删除不完整的安装目录，请重试。")
            shutil.rmtree(trade_dir, ignore_errors=True)
            return {"ok": False, "version": "", "error": err[:200], "errors": errors, "warnings": warnings, "messages": messages}
        if not _verify_pinned_head(trade_dir, target_sha, _emit, errors):
            shutil.rmtree(trade_dir, ignore_errors=True)
            return {
                "ok": False, "version": "",
                "error": f"clone 后 HEAD 与钉选提交不一致（期望 {target_sha[:8]}），已删除不完整目录。",
                "errors": errors, "warnings": warnings, "messages": messages,
            }
        _emit(f"  ✓ Repository cloned to {trade_dir}")
    else:
        _emit("→ Step 1/7: git pull ...")
        # 先把"用户点更新这一刻远端 main 指向的提交"钉下来，拉取后核对
        target_sha = _remote_main_sha(trade_dir)
        if not target_sha:
            _emit("  ❌ 无法解析远端 main 的最新提交（网络/代理或仓库不可达），已中止升级。")
            errors.append("cannot resolve remote main commit")
            return {
                "ok": False, "version": "",
                "error": "无法解析远端 main 的最新提交，请检查网络或代理后重试。",
                "errors": errors, "warnings": warnings, "messages": messages,
            }
        _emit(f"  ℹ️ 本次更新钉选提交：{target_sha[:8]}")
        try:
            result = subprocess.run(
                ["git", "pull", "--ff-only", "origin", "main"],
                cwd=str(trade_dir), capture_output=True, text=True, timeout=120,
            )
        except FileNotFoundError:
            _emit("  ❌ git 命令未找到，请先安装 Git for Windows 并重启终端")
            errors.append("git not found")
            return {"ok": False, "version": "", "error": "Git 未安装或不在 PATH 中，请先安装 Git for Windows", "errors": errors, "warnings": warnings, "messages": messages}
        if result.returncode != 0:
            err_text = result.stderr.strip()
            _emit(f"  ⚠ git pull failed: {err_text}")
            _emit("  💡 尝试自动 stash 后重试...")
            stash = subprocess.run(
                ["git", "stash"], cwd=str(trade_dir),
                capture_output=True, text=True, timeout=30,
            )
            if stash.returncode == 0:
                pull2 = subprocess.run(
                    ["git", "pull", "--ff-only", "origin", "main"],
                    cwd=str(trade_dir), capture_output=True, text=True, timeout=120,
                )
                if pull2.returncode == 0:
                    _emit("  ✓ git pull (after stash) OK")
                    pop = subprocess.run(
                        ["git", "stash", "pop"], cwd=str(trade_dir),
                        capture_output=True, text=True, timeout=30,
                    )
                    # stash pop 可能因冲突失败，此时改动仍留在 stash 里，必须告知用户
                    if pop.returncode != 0:
                        _emit(f"  ⚠ git stash pop 冲突，改动仍留在 stash 中：{pop.stderr.strip()}")
                        _emit(f"  💡 请手动处理：cd {trade_dir} && git stash pop")
                        warnings.append("local changes remain stashed (git stash pop conflicted)")
                else:
                    err2 = pull2.stderr.strip()
                    _emit(f"  ❌ git pull failed after stash: {err2}")
                    # 关键：本地改动已被 stash 且未 pop，工作区看起来「改动消失了」——
                    # 必须明确告知用户改动在哪、怎么取回，不能静默吞掉
                    _emit("  ⚠ 你的本地改动已被暂存到 git stash（未自动恢复）")
                    _emit(f"  💡 恢复方式：cd {trade_dir} && git stash pop")
                    errors.append(f"git pull failed: {err2}")
                    warnings.append("local changes were stashed and not restored (run: git stash pop)")
                    return {"ok": False, "version": "", "error": err2, "errors": errors,
                            "warnings": warnings, "messages": messages}
            else:
                err_s = stash.stderr.strip()
                _emit(f"  ❌ git stash also failed: {err_s}")
                errors.append(f"git stash failed: {err_s}")
                return {"ok": False, "version": "", "error": err_s, "errors": errors, "warnings": warnings, "messages": messages}
        else:
            last_line = result.stdout.strip().split("\n")[-1] if result.stdout.strip() else "Already up-to-date."
            _emit(f"  ✓ {last_line}")

        # 回读 HEAD：只认钉选的那个提交。不一致说明拉取过程中远端被推进
        # （或工作区有异常），此时装进来的不是用户确认过的版本 —— 回退并中止。
        if not _verify_pinned_head(trade_dir, target_sha, _emit, errors):
            _rollback_if_possible("remote main moved during update")
            return {
                "ok": False, "version": "",
                "error": f"更新期间远端 main 发生变化（期望 {target_sha[:8]}），请重试。",
                "errors": errors, "warnings": warnings, "messages": messages,
            }

    # ── 读取更新后的版本号并写入 version.txt ─────────────────────────────
    try:
        import tomllib as _toml_v
    except ImportError:
        import tomli as _toml_v
    try:
        pyproject = trade_dir / "pyproject.toml"
        # 显式 utf-8：Windows 默认 cp1252，pyproject.toml 含中文注释会读失败
        data = _toml_v.loads(pyproject.read_text(encoding="utf-8"))
        new_version = data.get("project", {}).get("version", "")
        _emit(f"  ℹ️  Target version: v{new_version}")
    except Exception:
        pass

    # ── Step 2: install_skills ────────────────────────────────────────────
    # skills 同步有离线兜底，失败只记警告：代码与依赖都已就绪，
    # 若把它算作致命失败就会把用户锁在旧代码上，得不偿失
    _emit("→ Step 2/7: install skills ...")
    try:
        install_skills()
        _emit("  ✓ Skills installed")
    # 必须同时捕 SystemExit 与 Exception（两者**没有**继承关系）：
    #   - SystemExit：install_skills 内部会 sys.exit()
    #   - Exception：文件复制（shutil.copy2/copytree）遇到目录只读、磁盘满、
    #     杀软占用时会抛 OSError/PermissionError
    # 只捕前者会让后者穿透，而这一步被明确定义为「非致命」。穿透的后果是
    # 半升级状态：代码已 git pull 到新版、依赖没装、服务不重启、UI 只有一个 500。
    except (SystemExit, Exception) as e:
        msg = f"install_skills failed: {e}"
        _emit(f"  ⚠ {msg}（非致命，继续升级）")
        warnings.append(msg)

    # ── Step 3: update_skills ─────────────────────────────────────────────
    _emit("→ Step 3/7: update skills ...")
    try:
        update_skills()
        _emit("  ✓ Skills updated")
    except (SystemExit, Exception) as e:  # 理由同上：这一步同样是非致命
        msg = f"update_skills failed: {e}"
        _emit(f"  ⚠ {msg}（非致命，继续升级）")
        warnings.append(msg)

    # ── Step 4: pip install ───────────────────────────────────────────────
    # 与 install.sh Step 3 保持一致：先按 requirements.txt 装依赖，再用
    # --no-deps 装 Trade 自身。不能不带 --no-deps——Hermes 的 setup.py 已
    # 明确拒绝通过 pip 构建（直接抛 RuntimeError），它由安装脚本单独
    # editable 安装；让 pip 去解析这个依赖会让整次升级失败。
    _emit("→ Step 4/7: pip install ...")
    req_file = trade_dir / "requirements.txt"
    if req_file.is_file():
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file)],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            err = result.stderr.strip()
            _emit(f"  ❌ 依赖安装失败: {err}")
            errors.append(f"pip install -r requirements.txt failed: {err[:200]}")
            _rollback_if_possible("pip install -r requirements.txt failed")
            return {"ok": False, "version": "", "error": err[:200], "errors": errors, "warnings": warnings, "messages": messages}
    pip_args = [sys.executable, "-m", "pip", "install", "-e", str(trade_dir), "--no-deps"]
    result = subprocess.run(pip_args, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        err = result.stderr.strip()
        _emit(f"  ❌ pip install failed: {err}")
        errors.append(f"pip install failed: {err[:200]}")
        _rollback_if_possible("pip install -e . failed")
        return {"ok": False, "version": "", "error": err[:200], "errors": errors, "warnings": warnings, "messages": messages}
    _emit("  ✓ Package updated")

    # ── Step 4b: 可选依赖（best-effort，失败只警告）────────────────────────
    _install_optional_deps(_emit, warnings)

    # ── Step 5: template sync ─────────────────────────────────────────────
    _emit("→ Step 5/7: template sync ...")
    try:
        template_src = trade_dir / ".trade-template"
        trade_home = _get_trade_home()
        trade_home.mkdir(parents=True, exist_ok=True)
        _sync_trade_template(template_src, trade_home)
        _emit("  ✓ Templates synced")
    except Exception as e:
        _emit(f"  ⚠ Template sync failed: {e}")
        warnings.append(f"template sync failed: {e}")

    # ── Step 6: auto-start ────────────────────────────────────────────────
    # 尊重用户的关闭决定：已有自启项才重新注册；用户手动关掉的，更新不能
    # 又替他打开（审计 P2-20）。首次安装（clone，pre_update_sha=None）照常注册。
    _emit("→ Step 6/7: auto-start check ...")
    try:
        if pre_update_sha is None or _auto_start_present():
            _ensure_auto_start(trade_dir)
            _emit("  ✓ Auto-start OK")
        else:
            _emit("  ℹ️ 开机自启已被你关闭，更新不会重新打开（如需启用请手动设置）")
    except Exception as e:
        _emit(f"  ⚠ Auto-start setup failed: {e}")
        warnings.append(f"auto-start setup failed: {e}")

    # ── Step 7: database ──────────────────────────────────────────────────
    _emit("→ Step 7/7: database check ...")
    try:
        from trade.database import init_db
        db_path = init_db()
        _emit(f"  ✓ Database OK ({db_path})")
    except Exception as e:
        _emit(f"  ❌ Database check failed: {e}")
        errors.append(f"Database check failed: {e}")
        # 迁移失败可能已经改了表结构（ALTER TABLE 不可逆）：光回滚代码不够，
        # 把库也恢复到升级前的快照（Step 0c 的备份就是为这一刻留的）。
        if pre_update_db_backup is not None:
            if not _restore_db_after_failed_migration(
                pre_update_db_backup, trade_home / "data" / "trade.db",
                _emit, warnings,
            ):
                _emit(f"  ⚠ 数据库未能自动恢复，备份仍在：{pre_update_db_backup}")
        # DB 迁移失败同样回退源码：新代码 + 未迁移完的库，重启只会更糟
        _rollback_if_possible("database check failed")
        return {"ok": False, "version": "", "error": str(e), "errors": errors, "warnings": warnings, "messages": messages}

    # ── 结果 ──────────────────────────────────────────────────────────────
    # errors 只装致命失败（git pull/clone、pip install、数据库），
    # 非致命失败（skills、模板同步、开机自启）走 warnings，不影响重启
    has_critical_errors = bool(errors)
    ok = not has_critical_errors

    # 注意：这里**不再**写 version.txt。
    # version.txt 的语义是「正在运行的代码版本」，由 trade.app 在进程启动时写入。
    # 若在此处提前写入目标版本，重启前的窗口里 UI 会显示新版本号，
    # 一旦重启失败（或本次 ok=False）就成了「假升级成功」。

    if ok:
        # 有非致命警告时也重启，但把警告一并回报给前端
        if warnings:
            _emit(f"\n✅ Trade update complete（{len(warnings)} 项警告）. Restarting...")
        else:
            _emit("\n✅ Trade update complete. Restarting...")
    else:
        _emit("\n⚠️  Update completed with errors. No restart.")
    return {"ok": ok, "version": new_version, "errors": errors,
            "warnings": warnings, "messages": messages}
