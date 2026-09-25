"""
Trade AI Assistant — 一键系统更新。

update_trade() 按序执行 7 个步骤：
  1. git pull（在运行目录拉取最新代码）
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
    """Windows: 创建 Task Scheduler 登录时自动运行的后台任务。"""
    task_name = "SmartTradeAI"
    check = subprocess.run(
        ["schtasks", "/query", "/tn", task_name],
        capture_output=True, text=True, timeout=30,
    )
    if check.returncode == 0:
        print("  ✓ 开机自启动任务已存在")
        return

    py_exe = sys.executable
    server_py = str(trade_dir / "server.py")
    result = subprocess.run(
        [
            "schtasks", "/create", "/tn", task_name,
            "/tr", f'"{py_exe}" "{server_py}" --no-browser',
            "/sc", "onlogon",
            "/rl", "limited",  # 用户权限运行，不请求管理员
            "/f",  # 强制创建，覆盖同名任务
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode == 0:
        print("  ✓ 已设置开机自启动")
    else:
        print(f"  ⚠ 开机自启动设置失败: {result.stderr.strip()}")


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


# ── 一键更新主函数 ────────────────────────────────────────────────────────

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
    trade_dir = _get_trade_home() / "foreign-trade-assistant"
    errors: list[str] = []
    messages: list[str] = []
    new_version = ""

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
            "messages": messages,
        }

    # ── Step 1: git pull / clone ───────────────────────────────────────────
    if not trade_dir.is_dir():
        _emit("→ Step 1/7: git clone (install directory not found) ...")
        _emit(f"  Target: {trade_dir}")
        trade_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            clone_result = subprocess.run(
                ["git", "clone", "https://github.com/chefroger/smart-trade-ai.git",
                 str(trade_dir)],
                capture_output=True, text=True, timeout=300,
            )
        except FileNotFoundError:
            _emit("  ❌ git 命令未找到，请先安装 Git for Windows 并重启终端")
            errors.append("git not found")
            return {"ok": False, "version": "", "error": "Git 未安装或不在 PATH 中，请先安装 Git for Windows", "errors": errors, "messages": messages}
        if clone_result.returncode != 0:
            err = clone_result.stderr.strip()
            _emit(f"  ❌ git clone failed: {err}")
            errors.append(f"git clone failed: {err}")
            return {"ok": False, "version": "", "error": err, "errors": errors, "messages": messages}
        _emit(f"  ✓ Repository cloned to {trade_dir}")
    else:
        _emit("→ Step 1/7: git pull ...")
        try:
            result = subprocess.run(
                ["git", "pull", "--ff-only", "origin", "main"],
                cwd=str(trade_dir), capture_output=True, text=True, timeout=120,
            )
        except FileNotFoundError:
            _emit("  ❌ git 命令未找到，请先安装 Git for Windows 并重启终端")
            errors.append("git not found")
            return {"ok": False, "version": "", "error": "Git 未安装或不在 PATH 中，请先安装 Git for Windows", "errors": errors, "messages": messages}
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
                    subprocess.run(
                        ["git", "stash", "pop"], cwd=str(trade_dir),
                        capture_output=True, text=True, timeout=30,
                    )
                else:
                    err2 = pull2.stderr.strip()
                    _emit(f"  ❌ git pull failed after stash: {err2}")
                    errors.append(f"git pull failed: {err2}")
                    return {"ok": False, "version": "", "error": err2, "errors": errors, "messages": messages}
            else:
                err_s = stash.stderr.strip()
                _emit(f"  ❌ git stash also failed: {err_s}")
                errors.append(f"git stash failed: {err_s}")
                return {"ok": False, "version": "", "error": err_s, "errors": errors, "messages": messages}
        else:
            last_line = result.stdout.strip().split("\n")[-1] if result.stdout.strip() else "Already up-to-date."
            _emit(f"  ✓ {last_line}")

    # ── 读取更新后的版本号并写入 version.txt ─────────────────────────────
    try:
        import tomllib as _toml_v
    except ImportError:
        import tomli as _toml_v
    try:
        pyproject = trade_dir / "pyproject.toml"
        data = _toml_v.loads(pyproject.read_text())
        new_version = data.get("project", {}).get("version", "")
        _emit(f"  ℹ️  Target version: v{new_version}")
    except Exception:
        pass

    # ── Step 2: install_skills ────────────────────────────────────────────
    _emit("→ Step 2/7: install skills ...")
    try:
        install_skills()
        _emit("  ✓ Skills installed")
    except SystemExit:
        msg = "install_skills failed"
        _emit(f"  ⚠ {msg}")
        errors.append(msg)

    # ── Step 3: update_skills ─────────────────────────────────────────────
    _emit("→ Step 3/7: update skills ...")
    try:
        update_skills()
        _emit("  ✓ Skills updated")
    except SystemExit:
        msg = "update_skills failed"
        _emit(f"  ⚠ {msg}")
        errors.append(msg)

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
            return {"ok": False, "version": "", "error": err[:200], "errors": errors, "messages": messages}
    pip_args = [sys.executable, "-m", "pip", "install", "-e", str(trade_dir), "--no-deps"]
    result = subprocess.run(pip_args, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        err = result.stderr.strip()
        _emit(f"  ❌ pip install failed: {err}")
        errors.append(f"pip install failed: {err[:200]}")
        return {"ok": False, "version": "", "error": err[:200], "errors": errors, "messages": messages}
    _emit("  ✓ Package updated")

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

    # ── Step 6: auto-start ────────────────────────────────────────────────
    _emit("→ Step 6/7: auto-start check ...")
    try:
        _ensure_auto_start(trade_dir)
        _emit("  ✓ Auto-start OK")
    except Exception as e:
        _emit(f"  ⚠ Auto-start setup failed: {e}")

    # ── Step 7: database ──────────────────────────────────────────────────
    _emit("→ Step 7/7: database check ...")
    try:
        from trade.database import init_db
        db_path = init_db()
        _emit(f"  ✓ Database OK ({db_path})")
    except Exception as e:
        _emit(f"  ❌ Database check failed: {e}")
        errors.append(f"Database check failed: {e}")
        return {"ok": False, "version": "", "error": str(e), "errors": errors, "messages": messages}

    # ── 结果 ──────────────────────────────────────────────────────────────
    has_critical_errors = bool(errors)  # pip install / database 等关键步骤失败
    ok = not has_critical_errors

    # ── 写入版本标记文件（/api/status 直接读取，零中间层） ──────────────
    if ok and new_version:
        try:
            data_dir = _get_trade_home() / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "version.txt").write_text(new_version)
            _emit(f"  ✓ Version marker written: {new_version}")
        except Exception as e:
            _emit(f"  ⚠ Failed to write version marker: {e}")

    if ok:
        _emit("\n✅ Trade update complete. Restarting...")
    else:
        _emit("\n⚠️  Update completed with errors. No restart.")
    return {"ok": ok, "version": new_version, "errors": errors, "messages": messages}
