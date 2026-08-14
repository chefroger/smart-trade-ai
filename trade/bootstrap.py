"""
Trade AI Assistant — 启动引导模块。

负责：日志过滤、sys.path 调整、子命令分发、Hermes 版本检查、
.env 加载、YOLO 模式设置、Skills 同步。
"""

import hashlib
import logging as _logging
import os
import shutil
import sys
import warnings as _warnings
from pathlib import Path


# ── 日志噪声过滤 ────────────────────────────────────────────────────────────
# 在任何 Hermes import 之前安装日志过滤器，
# 确保 Hermes 启动时的可选工具缺失警告被正确屏蔽
class _ToolImportNoiseFilter(_logging.Filter):
    """过滤 Hermes 启动时无关的可选工具缺失警告。"""
    _NOISE = ("Could not import tool module", "No module named 'hermes_cli.tools'")
    def filter(self, record: _logging.LogRecord) -> bool:
        return not any(p in record.getMessage() for p in self._NOISE)


_logging.getLogger().addFilter(_ToolImportNoiseFilter())
_warnings.filterwarnings("ignore", message=r".*Could not import tool module.*")
_warnings.filterwarnings("ignore", message=r".*No module named 'hermes_cli\.tools'.*")


# ── sys.path 调整：Trade 包优先于 Hermes ──────────────────────────────────
# Hermes 也有 `trade/` 包；我们的 `trade/` 必须优先。
# NOTE: 当 hermes-agent 作为独立 pip 包发布后，此块可移除。
def _adjust_sys_path():
    # PyInstaller 打包后 sys.frozen=True，不需要 sys.path 调整
    if getattr(sys, "frozen", False):
        return
    _trade_root = str(Path(__file__).resolve().parent.parent)
    if _trade_root not in sys.path:
        sys.path.insert(0, _trade_root)

    # Hermes 源码路径优先级：
    # 1. HERMES_HOME 环境变量
    # 2. 平台默认路径（macOS/Linux: ~/.hermes/, Windows: %LOCALAPPDATA%\hermes\）
    # 3. 与 Trade 平级的 trade_ai_assistant 开发目录
    _hermes_checkout = os.environ.get("HERMES_HOME", "").strip()
    if not _hermes_checkout:
        if os.name == "nt":
            _local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
            _default = Path(_local) / "hermes" / "hermes-agent"
        else:
            _default = Path.home() / ".hermes" / "hermes-agent"
        if _default.is_dir():
            _hermes_checkout = str(_default)
    if not _hermes_checkout:
        _dev_hermes = str(Path(__file__).resolve().parent.parent.parent / "trade_ai_assistant")
        if Path(_dev_hermes).is_dir():
            _hermes_checkout = _dev_hermes

    if _hermes_checkout and _hermes_checkout not in sys.path:
        # Hermes 放在第 1 位，Trade 仍在第 0 位（避免 trade/ 包名冲突）
        sys.path.insert(1, _hermes_checkout)

    # 如果 HERMES_HOME 未设置但我们找到了 Hermes 路径，注入环境变量
    # 防止 hermes_constants.get_hermes_home() 在 Windows 上回退到
    # Path.home() / ".hermes"（Path.home() 在 SYSTEM 用户下指向 System32）
    if not os.environ.get("HERMES_HOME") and _hermes_checkout:
        _hermes_home_dir = str(Path(_hermes_checkout).parent)
        os.environ["HERMES_HOME"] = _hermes_home_dir


# ── 子命令分发 ────────────────────────────────────────────────────────────
_MIN_HERMES_VERSION = "0.13.0"
_MAX_HERMES_VERSION = "0.21.0"  # exclusive upper bound: bumped 2026-08-03 for v0.20.0 compatibility


def dispatch_subcommands() -> bool:
    """处理子命令（update/backup/skills-update），无需启动服务器。

    Returns True 表示已处理子命令并应退出进程。
    """
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("update", "backup", "skills-update"):
        return False

    if cmd == "update":
        from trade.post_install import update_trade
        update_trade()
    elif cmd == "backup":
        from trade.post_install import backup_trade
        print(backup_trade())
    else:  # skills-update
        from trade.post_install import update_skills
        update_skills()
    return True


# ── Hermes 版本检查 ──────────────────────────────────────────────────────


def check_hermes_version() -> bool:
    """验证已安装的 Hermes 版本与当前 Trade 版本兼容。

    使用 packaging.version 进行 PEP 440 版本比较。
    Returns True 表示兼容，False 表示不兼容。
    """
    from packaging.version import Version

    try:
        from hermes_cli import __version__ as _hv
    except ImportError:
        print("  ✗ Cannot import Hermes. Is hermes-agent installed?")
        print("    Install: pip install hermes-agent")
        return False

    current = Version(_hv)
    min_v = Version(_MIN_HERMES_VERSION)
    max_v = Version(_MAX_HERMES_VERSION)

    if not (min_v <= current < max_v):
        print(f"  ✗ Hermes version {_hv} is not compatible with this release.")
        print(f"    Foreign Trade Assistant requires hermes-agent >={_MIN_HERMES_VERSION},<{_MAX_HERMES_VERSION}.")
        print(f"    Installed: {_hv}")
        print(f"    Run: pip install 'hermes-agent>={_MIN_HERMES_VERSION},<{_MAX_HERMES_VERSION}'")
        return False

    print(f"  ✓ Hermes {_hv} (compatible: >={_MIN_HERMES_VERSION},<{_MAX_HERMES_VERSION})")
    return True


def _search_arm64_python() -> str | None:
    """搜索 Apple Silicon 上的原生 arm64 Python。返回路径或 None。"""
    import subprocess

    for candidate in (
        "/opt/homebrew/bin/python3.13",
        "/opt/homebrew/bin/python3.12",
        "/opt/homebrew/bin/python3.11",
        "/opt/homebrew/bin/python3",
    ):
        import os as _os
        if not _os.path.isfile(candidate):
            continue
        try:
            arch = subprocess.run(
                [candidate, "-c", "import platform; print(platform.machine())"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            if arch == "arm64":
                return candidate
        except Exception:
            continue
    return None


def _restart_with_arm64_python(arm64_py: str) -> None:
    """用 arm64 Python 重新执行当前命令，替换当前进程。"""
    import subprocess

    print(f"  ✓ 检测到原生 arm64 Python: {arm64_py}")
    print("  🔄 正在切换到原生架构重启...")

    # 如果当前在 venv 内，检查 venv 是否是 arm64
    venv = os.environ.get("VIRTUAL_ENV", "")
    if venv:
        venv_python = Path(venv) / "bin" / "python"
        try:
            venv_arch = subprocess.run(
                [str(venv_python), "-c", "import platform; print(platform.machine())"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
        except Exception:
            venv_arch = ""
        if venv_arch == "arm64":
            print("  ✓ Venv 已经是 arm64，直接用 venv python 重启")
            arm64_py = str(venv_python)

    # execve: 替换当前进程，保留环境变量和命令行参数
    os.execve(arm64_py, [arm64_py] + sys.argv, os.environ)


def check_native_architecture(auto_repair: bool = True) -> bool:
    """全面检测平台与 Python 架构匹配性，必要时自动修复。

    在 Apple Silicon (arm64) Mac 上尤为重要：如果 Python 是 x86_64 (Rosetta)，
    pip 会安装 x86_64 的 C 扩展（pydantic-core, psutil 等），导致 Hermes 无法
    加载，Trade API 返回 422。

    当 auto_repair=True 且找到 arm64 Python 时，自动重启进程（execve），用户无感。

    检测维度：
      - 操作系统类型（Darwin / Linux / Windows）
      - CPU 硬件架构（arm64 / x86_64）
      - Python 进程架构（platform.machine）
      - Rosetta 翻译层（sysctl proc_translated）
      - Apple Silicon 能力（sysctl hw.optional.arm64）
      - 虚拟环境架构一致性

    Returns True 表示架构匹配（安全启动），False 表示不匹配且无法修复。
    """
    import platform as _platform
    import subprocess as _sp

    os_name = _platform.system()          # Darwin / Linux / Windows
    py_machine = _platform.machine()      # Python 进程的架构

    # ── 通用检测：所有平台 ──────────────────────────────────────────────
    # 获取硬件 CPU 架构（通过 uname，不受 Python 架构影响）
    try:
        hw_arch = _sp.run(
            ["uname", "-m"], capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception:
        hw_arch = ""

    # ── macOS 专项检测 ──────────────────────────────────────────────────
    if os_name == "Darwin":
        # 检测 Rosetta 翻译层
        under_rosetta = False
        try:
            translated = _sp.run(
                ["sysctl", "-n", "sysctl.proc_translated"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            under_rosetta = translated == "1"
        except Exception:
            pass

        # 检测硬件是否支持 arm64（Apple Silicon 或有 Rosetta 的 Intel）
        hw_supports_arm64 = False
        try:
            arm64_opt = _sp.run(
                ["sysctl", "-n", "hw.optional.arm64"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            hw_supports_arm64 = arm64_opt == "1"
        except Exception:
            pass

        # Case 1: Rosetta 模式 — Python 运行在翻译层上
        if under_rosetta:
            print("  平台: Apple Silicon (Rosetta 翻译层)")
            print(f"  Python: {py_machine}  硬件: {hw_arch}")

            if auto_repair:
                arm64_py = _search_arm64_python()
                if arm64_py:
                    _restart_with_arm64_python(arm64_py)
                    return True

            print("  ✗ Python 运行在 Rosetta (x86_64 翻译) 下")
            print("    这会导致 Hermes C 扩展编译为 x86_64 后无法加载。")
            print()
            print("    修复：安装原生 arm64 Homebrew Python:")
            print("      /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"")
            print("      brew install python@3.12")
            return False

        # Case 2: Apple Silicon 原生模式
        if hw_supports_arm64 and py_machine == "arm64" and hw_arch == "arm64":
            return True  # 一切正常

        # Case 3: arm64 硬件 + x86_64 Python（无 Rosetta 标记的 Rosetta 场景）
        if hw_arch == "arm64" and py_machine == "x86_64":
            if auto_repair:
                arm64_py = _search_arm64_python()
                if arm64_py:
                    _restart_with_arm64_python(arm64_py)
                    return True

            print("  ✗ 架构不匹配：CPU arm64，但 Python x86_64")
            print("    修复：使用原生 arm64 Python 重新运行")
            return False

        # Case 4: Intel Mac + arm64 Python（极罕见 — 交叉编译或容器）
        if hw_arch == "x86_64" and py_machine == "arm64":
            print("  ⚠ 架构异常：CPU x86_64，但 Python arm64")
            print("    请安装与 CPU 匹配的 Python 版本")
            return False

        return True

    # ── Linux 检测 ──────────────────────────────────────────────────────
    if os_name == "Linux":
        # Linux ARM (树莓派/ARM 服务器) — Python 架构需匹配硬件
        if hw_arch == "aarch64" and py_machine == "x86_64":
            print("  ⚠ 架构不匹配：CPU 是 aarch64 (ARM)，但 Python 是 x86_64")
            print("    请安装原生 ARM64 Python")
            return False
        if hw_arch == "x86_64" and py_machine == "aarch64":
            print("  ⚠ 架构不匹配：CPU 是 x86_64，但 Python 是 aarch64")
            return False
        return True

    # ── Windows 检测 ────────────────────────────────────────────────────
    if os_name == "Windows":
        # Windows ARM (Snapdragon X) — 检查是否存在 x86/x64 模拟
        if hw_arch.lower() in ("arm64", "aarch64") and py_machine == "AMD64":
            print("  ⚠ Windows ARM 上运行 x64 Python — Hermes C 扩展可能不兼容")
            print("    建议安装原生 ARM64 Python")
            return False
        if hw_arch.lower() in ("arm64", "aarch64") and py_machine == "ARM64":
            return True
        # x86_64 硬件 + AMD64 Python — 标准 x86_64 Windows
        return True

    # ── 未知 OS ─────────────────────────────────────────────────────────
    return True


# ── .env 加载 + YOLO 模式 ────────────────────────────────────────────────


def load_env_and_set_yolo():
    """加载 Hermes .env 并开启 YOLO 模式（跳过工具审批）。"""
    from hermes_cli.env_loader import load_hermes_dotenv
    from hermes_constants import get_hermes_home

    load_hermes_dotenv(hermes_home=get_hermes_home())
    os.environ["HERMES_YOLO_MODE"] = "true"


# ── Skills 同步 ──────────────────────────────────────────────────────────


def _local_skills_sync():
    """仅做本地 hash 比对同步，不访问 GitHub。

    从项目目录（或 PyInstaller/运行时目录）复制 skills 到 Hermes，
    比对外部哈希避免重复写入。速度远快于 GitHub 下载。
    """
    from hermes_constants import get_hermes_home

    # 优先级：PyInstaller _MEIPASS > 运行时目录 > 开发目录
    _meipass = getattr(sys, "_MEIPASS", None)
    if _meipass:
        _project_skills = Path(_meipass) / "skills"
    else:
        _trade_home = os.environ.get("TRADE_HOME", "").strip()
        if not _trade_home:
            if os.name == "nt":
                _local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
                _trade_home = str(Path(_local) / "trade")
            else:
                _trade_home = str(Path.home() / ".trade")
        _runtime_skills = Path(_trade_home) / "foreign-trade-assistant" / "skills"
        if _runtime_skills.is_dir():
            _project_skills = _runtime_skills
        else:
            _project_root = Path(__file__).resolve().parent.parent
            _project_skills = _project_root / "skills"
    if not _project_skills.is_dir():
        return

    _hermes_skills = get_hermes_home() / "skills"
    _hermes_skills.mkdir(parents=True, exist_ok=True)

    synced = 0
    for skill_dir in sorted(_project_skills.iterdir()):
        if not skill_dir.is_dir() or not (
            skill_dir.name.startswith("b2b-") or skill_dir.name.startswith("auto-") or skill_dir.name == "chat-memory"
        ):
            continue
        src = skill_dir / "SKILL.md"
        if not src.is_file():
            continue
        dst_dir = _hermes_skills / skill_dir.name
        dst = dst_dir / "SKILL.md"
        src_hash = hashlib.sha256(src.read_bytes()).hexdigest()
        if dst.is_file():
            dst_hash = hashlib.sha256(dst.read_bytes()).hexdigest()
            if src_hash == dst_hash:
                continue
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        synced += 1

    if synced > 0:
        print(f"  Skills synced: {synced} updated (local)")
    else:
        print("  Skills: up-to-date")


def sync_b2b_skills():
    """启动时从本地复制 skills 到 Hermes（仅 hash 比对，不访问网络）。

    安装/升级时 install-trade-skills 已处理初始复制，
    这里做增量同步确保运行时目录变更对齐。
    后台 GitHub 同步由 app.py 在服务启动后异步触发。
    """
    _local_skills_sync()


def background_github_skills_sync():
    """后台 daemon 线程：启动后静默同步一次，此后每天凌晨 3 点定时同步。

    失败不影响服务运行，仅记录日志。
    更新后 skill_router 的 mtime 缓存自动失效，下次请求热加载新内容，无需重启。
    """
    import datetime as _dt
    import threading
    import time as _time

    def _sync_once():
        try:
            from trade.post_install import update_skills
            update_skills()
        except SystemExit:
            pass  # update_skills 内部 sys.exit 转为静默返回
        except Exception:
            pass  # 静默失败，不影响主服务

    def _run():
        _time.sleep(10)  # 首次：等服务完全就绪
        _sync_once()
        # 此后：每天凌晨 3 点定时同步
        while True:
            now = _dt.datetime.now()
            next_run = now.replace(hour=3, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += _dt.timedelta(days=1)
            _time.sleep((next_run - now).total_seconds())
            _sync_once()

    t = threading.Thread(target=_run, daemon=True)
    t.start()


# ── 一键 setup ───────────────────────────────────────────────────────────


def setup():
    """执行 Trade 启动所需的所有引导步骤。

    调用顺序：
    1. sys.path 调整
    2. 子命令分发（如果是子命令则直接 exit）
    3. Hermes 版本检查
    4. .env 加载 + YOLO 设置
    5. Skills 同步
    """
    _adjust_sys_path()

    if dispatch_subcommands():
        sys.exit(0)

    # 架构检查必须在 Hermes 版本检查之前 —— 架构不匹配时 Hermes 无法导入
    if not check_native_architecture():
        sys.exit(1)

    if not check_hermes_version():
        sys.exit(1)

    load_env_and_set_yolo()
    sync_b2b_skills()
