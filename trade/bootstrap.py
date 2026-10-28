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
import time
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
def _resolve_hermes_checkout() -> str:
    r"""解析 Hermes 源码目录（含 `hermes_cli` 包的那个目录）；找不到返回空串。

    候选顺序：
      1. `HERMES_HOME` —— 注意它是**数据根目录**（~/.hermes），checkout 在其下的
         `hermes-agent/`；若 HERMES_HOME 本身就指向 checkout 也接受
      2. 平台默认路径（macOS/Linux: `~/.hermes/hermes-agent`，
         Windows: `%LOCALAPPDATA%\hermes\hermes-agent`）
      3. 与 Trade 平级的 `trade_ai_assistant` 开发目录

    每个候选都必须真的含 `hermes_cli` 目录才采用 —— 否则会把不含包的路径插进
    sys.path（历史 bug：`trade` 包装脚本会 export HERMES_HOME=~/.hermes，
    于是插进去的是数据根目录，`import hermes_cli` 直接失败）。
    """
    def _is_checkout(path: Path) -> bool:
        """是否为可用的 Hermes checkout（含 hermes_cli 包）。"""
        return (path / "hermes_cli").is_dir()

    candidates: list[Path] = []
    _hermes_home = os.environ.get("HERMES_HOME", "").strip()
    if _hermes_home:
        _root = Path(_hermes_home)
        candidates.append(_root)                 # HERMES_HOME 本身即 checkout
        candidates.append(_root / "hermes-agent")  # 数据根目录下的 checkout
    if os.name == "nt":
        _local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        candidates.append(Path(_local) / "hermes" / "hermes-agent")
    else:
        candidates.append(Path.home() / ".hermes" / "hermes-agent")
    candidates.append(Path(__file__).resolve().parent.parent.parent / "trade_ai_assistant")

    for candidate in candidates:
        if _is_checkout(candidate):
            return str(candidate)
    return ""


def _adjust_sys_path():
    # PyInstaller 打包后 sys.frozen=True，不需要 sys.path 调整
    if getattr(sys, "frozen", False):
        return
    _trade_root = str(Path(__file__).resolve().parent.parent)
    if _trade_root not in sys.path:
        sys.path.insert(0, _trade_root)

    _hermes_checkout = _resolve_hermes_checkout()
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
# Hermes 与当前 Python 共存的**最低版本**：v0.21.6 起上游才把 Python 支持上界抬到
# 3.14（也是 `pm` 托管运行时的起点）；上一代硬性要求 <3.14，两侧互斥（实测 3.14 下
# 装 0.19.0 直接 `requires a different Python`）。**已无上限** —— 新版 Hermes 我们
# 都要跟，卡上限只会把自己锁死。
# 权威判据在 trade.hermes_compat.hermes_python_compat()（读 checkout 元数据，不导入
# Hermes）；这里的常量供 doctor / pre_install_check / 测试引用，两处由测试钉住一致。
_MIN_HERMES_VERSION = "0.21.6"


def dispatch_subcommands() -> bool:
    """处理子命令（update/backup/skills-update/open/doctor/company/osint），无需启动服务器。

    `open` 是桌面快捷方式的目标：确保服务在跑，然后打开界面。
    `doctor` 是安装后自检：验 Hermes 运行环境 / vision / Tavily / Trade 自身。
    `company` 是公司管理（作者用的隐藏功能，不写进用户文档）：见 trade.company_admin。
    `osint` 是 6 层背调的机器判定入口（skill 提示词也指向同一个命令，
    等价的跨平台写法是 `python -m trade.osint <目标>`）：见 trade.osint.cli。

    Returns True 表示已处理子命令并应退出进程。
    """
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("update", "backup", "skills-update", "open", "doctor", "company", "osint"):
        return False

    if cmd == "update":
        from trade.post_install import update_trade
        update_trade()
    elif cmd == "backup":
        from trade.post_install import backup_trade
        print(backup_trade())
    elif cmd == "open":
        from trade.opener import open_trade
        print(open_trade())
    elif cmd == "company":
        from trade.company_admin import main as company_main
        sys.exit(company_main(sys.argv[2:]))
    elif cmd == "osint":
        from trade.osint.cli import main as osint_main
        sys.exit(osint_main(sys.argv[2:]))
    elif cmd == "doctor":
        from trade.doctor import format_report, has_fatal_failure, run_doctor, save_doctor_result

        # 默认端到端验活；--quick 只查配置与工具表（零 token，安装脚本用）
        deep = "--quick" not in sys.argv[2:]
        results = run_doctor(deep=deep)
        save_doctor_result(results, deep=deep)
        print(format_report(results))
        # 致命项失败 → 非零退出，让安装脚本能据此中止
        sys.exit(1 if has_fatal_failure(results) else 0)
    else:  # skills-update
        from trade.post_install import update_skills
        update_skills()
    return True


# ── Hermes 版本检查 ──────────────────────────────────────────────────────


# ── Hermes 共存状态（启动降级用）─────────────────────────────────────────
# 旧版 Hermes 与当前 Python 互斥时，Trade 不能再像以前那样直接 `sys.exit(1)`：
# 桌面端（tradewin）会开出一个空白窗口，用户一句解释都看不到。改为「记录状态 +
# 降级启动」——跳过所有会碰 Hermes 的步骤，让服务照常起来，由界面显示升级面板。
_hermes_compat_state: dict | None = None


def hermes_compat_state() -> dict:
    """返回本次启动的 Hermes 共存判定结果（供 API / 界面读取），只计算一次。"""
    global _hermes_compat_state
    if _hermes_compat_state is None:
        from trade.hermes_compat import hermes_python_compat

        _hermes_compat_state = hermes_python_compat()
    return _hermes_compat_state


def hermes_is_usable() -> bool:
    """Hermes 当前是否可用于 agent 功能。

    两种明确不可用：
      - `too_old`        —— Hermes 版本低于共存下限（去升级 Hermes）
      - `python_too_old` —— Hermes 够新但它需要 3.14，而 Trade 的解释器更老
                            （去重装 Trade；升级 Hermes 在这里毫无用处）
    「未知」按可用处理（识别失败不等于不兼容，与既有门禁口径一致，避免误拦可用环境）。
    """
    return hermes_compat_state().get("verdict") not in ("too_old", "python_too_old")


def check_hermes_version() -> bool:
    """检查已安装的 Hermes 能否与当前 Python 共存，并打印终端提示。

    判据为 `trade.hermes_compat.hermes_python_compat()`：读 checkout 的 requires-python
    与版本号，**全程不导入 Hermes**。为什么不能用 import 判 —— 旧版 Hermes 在新 Python
    上崩的是「缺依赖的 ImportError」（缺 openai/pydantic-core 等），用户看到的是依赖
    天书，而不是「版本过旧、去升级」这个可行动的结论。

    Returns True 表示可用（含「未知」），False 表示版本过旧、必须先升级 Hermes。
    """
    state = hermes_compat_state()
    verdict = state.get("verdict")

    if verdict == "too_old":
        from trade.hermes_compat import incompatible_upgrade_steps

        print(f"  ✗ Hermes 版本过旧，无法与当前 Python 共存：{state.get('reason')}")
        print(f"    已安装: {state.get('version') or '未知'}    Python: {state.get('python')}")
        for line in incompatible_upgrade_steps():
            print(f"    {line}")
        return False

    if verdict == "python_too_old":
        # 问题在 Trade 这一侧（venv 太老），升级 Hermes 解决不了 —— 所以给的是重装指引。
        # 这条分支的存在本身就是一次事故的产物：漏掉它会让界面只显示
        # 「AI Agent 模块未加载」，用户完全无从下手。
        from trade.hermes_compat import incompatible_rebuild_steps

        print(f"  ✗ Trade 的运行环境需要重建：{state.get('reason')}")
        print(f"    Hermes: {state.get('version') or '未知'}    Trade 的 Python: {state.get('python')}")
        for line in incompatible_rebuild_steps():
            print(f"    {line}")
        return False

    if verdict == "unknown":
        print(f"  ⚠️ 无法确定 Hermes 版本（{state.get('reason')}）")
        print("     跳过版本检查，继续启动。")
        return True

    print(f"  ✓ Hermes {state.get('version') or '（版本未知）'}（与 Python {state.get('python')} 可共存）")
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


def _disable_hermes_lazy_installs() -> None:
    """设置上游的 sealed-venv 开关（无导入、幂等，可重复调用）。

    必须在**任何 Hermes 导入之前**生效 —— 子命令（doctor/osint/company/update）与
    版本检查都发生在 `load_env_and_set_yolo()` 之前，而新版本 Hermes 会在 import 时
    发现「当前解释器 ≠ 托管解释器」并重拉进程（runpy 重跑当前命令）；重拉环境里没有
    trade 包，进程直接以 ModuleNotFoundError 崩掉（2026-10-14 实测：本机升级到
    Hermes main 后 `trade doctor` 每次 2 秒内即崩，见 COMPATIBILITY.md）。
    `load_env_and_set_yolo()` 在 dotenv 之后会**再设一次**（防用户的 .env 顶掉）。
    """
    os.environ["HERMES_DISABLE_LAZY_INSTALLS"] = "1"


def _trade_site_packages() -> str:
    """当前解释器的 site-packages 目录（取不到返回空串）。"""
    try:
        if os.name == "nt":
            candidate = Path(sys.prefix) / "Lib" / "site-packages"
        else:
            candidate = (
                Path(sys.prefix)
                / "lib"
                / f"python{sys.version_info.major}.{sys.version_info.minor}"
                / "site-packages"
            )
        if candidate.is_dir():
            return str(candidate)
    except Exception:
        pass
    # 兜底：从 sys.path 里认出属于本解释器 prefix 的那一条
    try:
        prefix = os.path.normcase(str(Path(sys.prefix)))
        for entry in sys.path:
            if entry.endswith(("site-packages", "dist-packages")) and os.path.normcase(entry).startswith(prefix):
                return entry
    except Exception:
        pass
    return ""


def _activate_hermes_env_and_restore_trade_paths() -> None:
    """显式触发 Hermes 的 pm 激活，然后立刻把 Trade 自己的 site-packages 补回 sys.path。

    **为什么必须显式触发**：`pm/environments.py::activate_dependencies()` 在
    `import hermes_bootstrap` 时把 `sys.path` 整体换成 Hermes 托管环境的 site-packages，
    **按目录名剥掉进程原有的全部 site-packages**（Trade 的依赖就此全灭），并覆盖
    `PYTHONPATH`。让它「晚一点在某个 import 里发生」会让失败点飘忽 —— 历史事故就是
    agent 线程静默死亡、前端只显示「Agent 未返回有效回复」。所以这里主动触发一次，
    紧接着把路径补回去，让时序可预期。

    **为什么补在末尾**：Trade 与 Hermes 的依赖版本是 lockstep 的（`requirements.txt`
    与上游 pin 对齐），同版本时顺序无关；一旦漂移，让 **Hermes 的托管代际优先胜出**，
    避免 Trade 的老 pin 把 Hermes 需要的版本压下去。隔离实测确认 `openai` 来自托管代际。

    只在 Hermes 可用时调用 —— 降级模式（版本过旧）下绝不该 import Hermes。
    """
    trade_site = _trade_site_packages()
    try:
        import hermes_bootstrap  # noqa: F401 — 导入的副作用即目的
    except Exception:
        # Hermes 未安装或导入失败：交给调用方按「未知」处理，不在这里抛
        return

    # **唯一会「静默降级」的路径**：解析不到自己的 site-packages 时，下面两段补齐
    # 全部跳过 —— 进程表面还能跑，实际只剩 Hermes 的依赖（Trade 的被激活剥掉了）。
    # 2026-10-14 那次事故的现场就是这样：界面只显示「AI Agent 模块未加载」、
    # 完全指不到真因。所以这里必须响亮报出来，不能一声不响地继续。
    if not trade_site:
        print(
            "  ✗ 无法解析 Trade 自身的 site-packages —— Hermes 激活后可能已剥离 "
            "Trade 的依赖。请把这一行发给技术支持。"
        )

    # 激活剥掉了 Trade 的 site-packages → 补回（放末尾，让 Hermes 的依赖优先）。
    # 注意这段是**无条件**执行的：即使 hermes_bootstrap 已在 sys.modules 里、
    # 这次 import 没有任何副作用，也要确认路径在位（幂等）。
    if trade_site and trade_site not in sys.path:
        sys.path.append(trade_site)

    # 激活也用托管环境的路径覆盖了 PYTHONPATH；不补回来的话，Trade 起的子进程
    # （如走 holehe 的 OSINT Layer 1）会找不到 Trade 自己的依赖
    if trade_site:
        existing = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
        if trade_site not in existing:
            os.environ["PYTHONPATH"] = os.pathsep.join([*existing, trade_site])


def load_env_and_set_yolo():
    """加载 Hermes .env、开启 YOLO 模式，并禁用 Hermes 的懒加载重启。

    注意：pm 激活后的恢复**不在这里**做，而在 `prepare_hermes_import_paths()` ——
    它必须早于**任何** Hermes import（含子命令 doctor/osint），见其 docstring。
    """
    from hermes_cli.env_loader import load_hermes_dotenv
    from hermes_constants import get_hermes_home

    load_hermes_dotenv(hermes_home=get_hermes_home())
    os.environ["HERMES_YOLO_MODE"] = "true"

    # 禁用 Hermes 的「借用启动」：否则 `from run_agent import AIAgent` 会连带执行
    # hermes_bootstrap.py，它发现当前解释器不是 Hermes 的 store 解释器后，会把
    # server.py 重新 exec 到 Hermes 自带的 Python —— 那个解释器里没有 trade 包，
    # 于是子进程以 ModuleNotFoundError 退出，父进程 raise RelaunchExit(1)。
    # RelaunchExit 继承 SystemExit（BaseException），Trade 的 except Exception 抓不到，
    # agent 线程静默死亡，前端只会看到「Agent 未返回有效回复」（客户机实测，2026-10-08）。
    #
    # 这是上游正式的 sealed-venv 开关（Hermes tools/lazy_deps.py）。作用域仅限本进程树，
    # 不影响用户自己那个 hermes CLI；这里必须在 load_hermes_dotenv **之后**再设一次 ——
    # 该函数会用 os.environ[name] = value 覆盖，顺序反了会被用户的 .env 顶掉
    # （setup() 开头已先设过一次，覆盖子命令分发与版本检查这两个更早的窗口）。
    _disable_hermes_lazy_installs()


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

    # 停用 skill 的运行时残留要清掉（P1-13）：升级后没重装/没更新的老机器上，
    # ~/.hermes/skills/auto-smtp-email/ 会一直留到下一次安装；启动时也清一次。
    from trade.post_install.skills import _purge_blocked_skills
    from trade.skill_registry import _BLOCKED_SKILLS

    _purge_blocked_skills(_hermes_skills)

    synced = 0
    for skill_dir in sorted(_project_skills.iterdir()):
        if not skill_dir.is_dir() or not (
            skill_dir.name.startswith("b2b-") or skill_dir.name.startswith("auto-") or skill_dir.name == "chat-memory"
        ):
            continue
        if skill_dir.name in _BLOCKED_SKILLS:
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


# ── Hermes 插件同步（chat-memory） ────────────────────────────────────────

def _local_chat_memory_plugin_source() -> Path | None:
    """定位 chat-memory 插件的"源目录"（即 trade 仓库内自带的那个副本）。

    三个候选位置（按"该用谁"优先级）：
      1. PyInstaller _MEIPASS（打包后的运行目录）
      2. 运行时目录 ~/.trade/foreign-trade-assistant/hermes_chat_memory_plugin
         （upgrade 拉到本地的副本）
      3. 开发目录 <repo>/trade/hermes_chat_memory_plugin

    这与 _local_skills_sync 的源定位策略同构，照抄。
    """
    _meipass = getattr(sys, "_MEIPASS", None)
    if _meipass:
        cand = Path(_meipass) / "trade" / "hermes_chat_memory_plugin"
        if cand.is_dir():
            return cand

    _trade_home = os.environ.get("TRADE_HOME", "").strip()
    if not _trade_home:
        if os.name == "nt":
            _local = os.environ.get(
                "LOCALAPPDATA", str(Path.home() / "AppData" / "Local")
            )
            _trade_home = str(Path(_local) / "trade")
        else:
            _trade_home = str(Path.home() / ".trade")
    cand = Path(_trade_home) / "foreign-trade-assistant" / "trade" / "hermes_chat_memory_plugin"
    if cand.is_dir():
        return cand

    cand = Path(__file__).resolve().parent / "hermes_chat_memory_plugin"
    if cand.is_dir():
        return cand
    return None


def sync_chat_memory_plugin() -> None:
    """把 trade 自带的 chat-memory 插件部署到 ~/.hermes/plugins/chat-memory/。

    部署是**幂等**的：文件存在且内容一致就不写。安装脚本与每次 setup() 都调它，
    所以旧版升级时这步会自动让用户的 Hermes 看到新插件。

    副本来自 trade 仓库内的 <repo>/trade/hermes_chat_memory_plugin/（_local_chat_memory_plugin_source），
    目标位置 ~/.hermes/plugins/chat-memory/。与 _local_skills_sync 同样的"hash 比对、逐文件复制"，
    但因为是**目录级**（不是文件级），且插件要求 plugin.yaml + __init__.py + tools.py 三件同存，
    这里用"全文件 hash 集合相等"的判断避免误判。
    """
    src_root = _local_chat_memory_plugin_source()
    if src_root is None:
        # 开发环境改了 trade 的目录结构（极少见）；不抛、不影响主流程
        print("  chat-memory plugin: source not found, skipping")
        return

    # 目标位置：~/.hermes/plugins/chat-memory/
    # 路径来源与 _local_skills_sync 一致 —— 走 _get_hermes_home()（HERMES_HOME 优先）
    from trade.post_install.skills import _get_hermes_home

    _hermes_home = _get_hermes_home()
    dst_root = _hermes_home / "plugins" / "chat-memory"

    if not src_root.is_dir():
        print(f"  chat-memory plugin: source missing {src_root}, skipping")
        return

    # 收集源端的相对路径 → 内容 hash；只处理"真文件"（排除 __pycache__、.pyc 等）
    src_hashes: dict[str, str] = {}
    for p in src_root.rglob("*"):
        if p.is_file() and p.suffix not in {".pyc", ".pyo"}:
            rel = p.relative_to(src_root).as_posix()
            try:
                src_hashes[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
            except OSError:
                continue

    if not src_hashes:
        print("  chat-memory plugin: no source files, skipping")
        return

    # 收集目标端现有文件 → hash
    dst_hashes: dict[str, str] = {}
    if dst_root.is_dir():
        for p in dst_root.rglob("*"):
            if p.is_file() and p.suffix not in {".pyc", ".pyo"}:
                rel = p.relative_to(dst_root).as_posix()
                try:
                    dst_hashes[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
                except OSError:
                    continue

    if src_hashes == dst_hashes:
        print("  chat-memory plugin: up-to-date")
        return

    # 不同：整体覆盖（增量写容易漏改 .pyc / __pycache__ 等，不如整目录重写）
    if dst_root.exists():
        shutil.rmtree(dst_root)
    dst_root.mkdir(parents=True, exist_ok=True)
    copied = 0
    for rel in src_hashes:
        src_file = src_root / rel
        dst_file = dst_root / rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst_file)
        copied += 1
    print(f"  chat-memory plugin: deployed {copied} files to {dst_root}")


# ── 写 ~/.hermes/config.yaml：仅追加 chat-memory 到 enabled ───────────────

# 重要约束：trade 在 0.21.6+ 起以"插件形式"为 Hermes 提供 chat_memory_list 工具。
# 插件是 opt-in —— 不在 config.yaml 的 plugins.enabled 里写进去，Hermes 不会加载。
# 这函数只**追加**两个键（plugins.enabled 与 enabled_toolsets），其它键一行不碰：
# ① 用文件级 read_text/write_text（不走 hermes_cli.config.load_config，避免它的副作用
#    —— 比如它会触发迁移、覆写注释、规范化键顺序，把用户的格式搅乱）；
# ② 仅修改这两个键的**列表值**（list），不动 dict/str/int；
# ③ 已是 list 时只在末尾追加 "chat-memory"（去重）；
# ④ 不是 list → 静默 skip + log 警告（不覆盖用户改坏的数据）；
# ⑤ 用户的 plugins.disabled 包含 "chat-memory" → 跳过（disallow 总是赢）；
# ⑥ 用户**已有** "chat-memory" → 跳过（幂等）。
# 写盘前先备份 .bak —— 不是为了 rollback（fail-safe），是为了让"我刚才误改了什么"能查。

def _read_yaml_simple(path: Path) -> str:
    """只读文本返回（不做 yaml 解析 —— 避免把注释/格式/键顺序搅乱）。"""
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _write_yaml_with_backup(path: Path, content: str) -> None:
    """写盘前在 .bak 留一份，幂等（多轮 setup 不会反复覆盖 .bak）。"""
    if path.is_file():
        bak = path.with_suffix(path.suffix + ".bak")
        # .bak 自身已存在时不重写 —— 保留最旧的一份
        if not bak.is_file():
            try:
                shutil.copy2(path, bak)
            except OSError:
                pass  # 备份失败不阻断主流程
    path.write_text(content, encoding="utf-8")


def _patch_yaml_list(text: str, key_path: tuple[str, ...], value: str) -> str:
    """在 yaml 文本里把 key_path 路径下的 list 追加 value；**不改动其它任何内容**。

    设计原则（这是写用户 Hermes 配置的函数，安全性优先于功能）：
      - **只在值确实是 list 时追加**；值是 dict / 标量 / 形态不明 → 原样返回
        （宁可不生效，也不能破坏用户配置 —— 在 dict 后面混一个 list 会直接产出非法 yaml）；
      - 文本级追加（不重新 dump yaml）→ 保留用户的注释、键顺序、缩进风格；
      - 目标 key 不存在时，只在**父 key 存在且为空值**时插一行；父 key 也不存在 → 原样返回
        （由调用方决定整块追加）。

    支持的两种 list 形态（`~/.hermes/config.yaml` 的实际形态）：
        key: [a, b]           ← 行内
        key:
          - a
          - b                 ← 多行
    """
    if not text:
        return text

    lines = text.splitlines(keepends=True)
    target = key_path[-1]

    def _indent_of(line: str) -> str:
        body = line.lstrip()
        return line[: len(line) - len(body)]

    # ① 目标 key 已存在 → 按它的值形态决定
    for i, ln in enumerate(lines):
        stripped = ln.lstrip()
        if stripped.rstrip() != target + ":" and not stripped.startswith(target + ":"):
            continue
        indent = _indent_of(ln)
        inline = stripped[len(target) + 1:].strip()

        # 行内 list：key: [a, b]
        if inline.startswith("["):
            if value in inline:
                return text  # 已存在 → 幂等
            if not inline.endswith("]"):
                return text  # 跨行/畸形 → 不动
            inner = inline[1:-1].strip().rstrip(",")
            body = f"[{inner}, {value}]" if inner else f"[{value}]"
            lines[i] = f"{indent}{target}: {body}\n"
            return "".join(lines)

        # 行内标量（key: foo）→ 不是 list，不动
        if inline:
            return text

        # 多行：由**第一个子行**决定形态
        block_indent: str | None = None
        existing: list[str] = []
        insert_at: int | None = None
        for j in range(i + 1, len(lines)):
            jl = lines[j]
            jstrip = jl.lstrip()
            if not jstrip:
                continue
            child_indent = _indent_of(jl)
            if len(child_indent) <= len(indent):
                insert_at = j  # 子块结束（空值 / 同级 key）
                break
            if block_indent is None:
                if not jstrip.startswith("- "):
                    return text  # 第一个子行不是 list item → 是 dict/嵌套，不动
                block_indent = child_indent
            if len(child_indent) < len(block_indent):
                insert_at = j  # 缩进回退 → list 块到此结束
                break
            if len(child_indent) == len(block_indent) and jstrip.startswith("- "):
                existing.append(jstrip[2:].strip())
        if value in existing:
            return text  # 幂等
        # 没有子行（`key:` 后直接是同级 key 或文件末尾）→ 按"空 list"处理，
        # 插一个 list item，把它变成 `[value]`
        if block_indent is None:
            block_indent = indent + "  "
        if insert_at is None:
            insert_at = len(lines)
        lines.insert(insert_at, f"{block_indent}- {value}\n")
        return "".join(lines)

    # ② 目标 key 不存在 → 只在**父 key 是顶层且空值**时插一行
    if len(key_path) < 2:
        return text
    parent = key_path[-2]
    for i, ln in enumerate(lines):
        stripped = ln.lstrip()
        if stripped.rstrip() != parent + ":" and not stripped.startswith(parent + ":"):
            continue
        if _indent_of(ln):
            return text  # 父 key 不是顶层（我们的用法是顶层 plugins:）→ 不动
        if stripped[len(parent) + 1:].strip():
            return text  # plugins: {...} 行内有值 → 不动
        lines.insert(i + 1, f"  {target}: [{value}]\n")
        return "".join(lines)
    return text


_CHAT_MEMORY_PLUGIN_KEY = "chat-memory"
# 没有配置文件时写下的最小骨架（**只**写这一个键，不碰工具集键）
_FRESH_CONFIG_SKELETON = (
    "# Written by trade-bootstrap on first install.\n"
    "# Trade only touches plugins.enabled below; everything else in this file is yours.\n"
    "plugins:\n"
    "  enabled: [chat-memory]\n"
)


def ensure_chat_memory_plugin_enabled() -> None:
    """把 chat-memory 加进 ~/.hermes/config.yaml 的 `plugins.enabled`。

    **为什么必须做**：Hermes 的插件是 **opt-in** —— `gate_manifest` 里
    `if enabled is None or not names & enabled: → 跳过`，即插件目录摆在
    `~/.hermes/plugins/` 不算数，必须在这份配置的 allow-list 里列出来（见
    `hermes_cli/plugins_discovery.py::_get_enabled_plugins` 的 docstring）。

    **为什么不管工具集键**（enabled_toolsets / default_toolsets）：启用插件工具集的键名
    取决于用户自己的 Hermes 配置写法（`default_toolsets` / `enabled_toolsets` /
    per-profile 各有不同），trade 无法可靠推断；写错只会在用户配置里留下无用段。所以
    这里只做「plugins.enabled」这一件确定的事。

    安全约束（这是写**用户的**配置，安全性优先于功能）：
      - 只动 `plugins.enabled` 一个键；其它键一行不碰；
      - 先用 PyYAML **只读**地确认值形态：是 list 或缺失才继续；是 dict/标量 → 不动；
      - `plugins.disabled` 含 chat-memory → 直接跳过（deny-list 总是赢）；
      - 文本级追加（不重新 dump yaml）→ 保留用户的注释、键顺序、缩进；
      - 写盘前留 `.bak`（只留最旧一份，多轮调用不反复覆盖）；
      - 任何失败只打印警告 —— 写不了配置不能挡住 trade 启动（插件降级为"不生效"）。

    降级模式（Hermes 不可用）也会调它：不碰 Hermes、只写一个 yaml，与"现在能不能加载
    插件"解耦 —— 先把配置写好，等下次 Hermes 启动就生效。
    """
    from trade.post_install.skills import _get_hermes_home

    config_path = _get_hermes_home() / "config.yaml"
    original = _read_yaml_simple(config_path)

    # ── 没有配置文件 → 建最小骨架 ────────────────────────────────────────
    if not original.strip():
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            _write_yaml_with_backup(config_path, _FRESH_CONFIG_SKELETON)
            print(f"  Hermes config: created {config_path} with plugins.enabled=[chat-memory]")
        except OSError as exc:
            print(f"  ⚠️ failed to write Hermes config: {exc}")
        return

    # ── 只读地确认当前值形态（解析失败一律不动）────────────────────────────
    data = _try_load_yaml(original)
    if not isinstance(data, dict):
        print("  Hermes config: not parseable as a mapping, leaving it alone")
        return
    plugins = data.get("plugins")
    if isinstance(plugins, dict):
        disabled = plugins.get("disabled")
        if isinstance(disabled, list) and _CHAT_MEMORY_PLUGIN_KEY in disabled:
            print("  Hermes config: chat-memory is in plugins.disabled, skipping")
            return
        enabled_val = plugins.get("enabled")
        if enabled_val is not None and not isinstance(enabled_val, list):
            print(
                "  Hermes config: plugins.enabled is "
                f"{type(enabled_val).__name__}, not a list — leaving it alone"
            )
            return

    # ── 文本级追加 ──────────────────────────────────────────────────────
    try:
        new_text = _patch_yaml_list(original, ("plugins", "enabled"), _CHAT_MEMORY_PLUGIN_KEY)
    except Exception as exc:  # noqa: BLE001 — 任何解析意外都只警告，不改文件
        print(f"  ⚠️ failed to patch Hermes config: {exc}")
        return

    # 配置里根本没有 plugins 段（_patch_yaml_list 会原样返回）→ 追加整块。
    # 注意判据用解析结果而不是字符串搜索：注释里的 "plugins:" 不该被当成已有段。
    if new_text == original and plugins is None:
        sep = "" if original.endswith("\n") else "\n"
        new_text = original + sep + _FRESH_CONFIG_SKELETON.split("\n", 2)[2]

    if new_text == original:
        print("  Hermes config: chat-memory already enabled, no change")
        return

    try:
        _write_yaml_with_backup(config_path, new_text)
        print(f"  Hermes config: enabled chat-memory in {config_path}")
    except OSError as exc:
        print(f"  ⚠️ failed to write Hermes config: {exc}")


def _try_load_yaml(text: str):
    """只读解析 yaml；失败返回 None（调用方据此放弃改动，绝不覆盖）。"""
    try:
        import yaml

        return yaml.safe_load(text)
    except Exception:  # noqa: BLE001 — 用户的 yaml 可能有任何语法问题
        return None


def verify_tool_guard_ready(announce: bool = False) -> dict:
    """检查工具守卫是否真的会加载：插件已部署 + 在 `plugins.enabled` 里。

    守卫（文件白名单 / terminal / execute_code）全部挂在 chat-memory 插件上，
    插件没加载就等于**整套守卫静默缺席**，而主聊天仍带着全工具集继续跑。
    回答三件事：插件已部署、已在 plugins.enabled、宿主钩子能力已知为 True。
    旧版 Hermes 没有 register_hook 时插件会写 hooks=False；标记从未写过（None）
    视为**未知**，不算 ok —— 不能让它看起来像"已确认安全"。

    `announce=True` 时把问题打到 stderr（启动路径用）；`/api/status` 轮询用
    默认 False，避免每次请求都刷屏。
    """
    from trade.post_install.skills import _get_hermes_home

    hermes_home = _get_hermes_home()
    deployed = (hermes_home / "plugins" / "chat-memory" / "guardrails.py").is_file()

    enabled = False
    config_path = hermes_home / "config.yaml"
    try:
        data = _try_load_yaml(config_path.read_text(encoding="utf-8"))
    except OSError:
        data = None
    if isinstance(data, dict):
        plugins = data.get("plugins")
        if isinstance(plugins, dict):
            enabled_list = plugins.get("enabled")
            disabled_list = plugins.get("disabled")
            enabled = (
                isinstance(enabled_list, list)
                and _CHAT_MEMORY_PLUGIN_KEY in enabled_list
                and not (isinstance(disabled_list, list) and _CHAT_MEMORY_PLUGIN_KEY in disabled_list)
            )

    # 旧版 Hermes 的插件 ctx 没有 register_hook：插件能加载但守卫不生效，
    # 只靠"部署+启用"会误报 ok。插件每次注册时把能力写进标记文件。
    try:
        from trade.hermes_chat_memory_plugin.guardrails import recorded_hook_support

        hooks = recorded_hook_support()
    except Exception:  # noqa: BLE001 — 读不到标记就按"未知"处理
        hooks = None

    # hooks 未知（标记从未写过）不算 ok：不能让它看起来像"已确认安全"。
    ok = deployed and enabled and hooks is True
    state = {"ok": ok, "deployed": deployed, "enabled": enabled, "hooks": hooks}
    if announce and not ok:
        reasons = []
        if not deployed:
            reasons.append("插件文件未部署")
        if not enabled:
            reasons.append("~/.hermes/config.yaml 的 plugins.enabled 未启用 chat-memory")
        if hooks is False:
            reasons.append("当前 Hermes 不支持 register_hook，守卫无法挂载")
        elif hooks is None and deployed and enabled:
            reasons.append("宿主钩子状态未知（插件尚未记录）")
        print(
            "  ⚠️ 工具安全守卫未生效（" + "；".join(reasons) + "）："
            "文件路径白名单、terminal 命令白名单、execute_code 拒绝当前都不起作用。"
            "请重启 Trade；若仍提示，检查 Hermes 配置里的 plugins.enabled 或升级 Hermes。",
            file=sys.stderr,
        )
    return state


def tool_guard_chat_block_reason() -> str | None:
    """聊天前的守卫门控：守卫确定不可用时返回阻断文案，否则 None。

    放在 agent 构造**之后**调用：旧版 Hermes 的钩子能力要等插件在 agent
    构造时加载才知道；在那之前阻断会让标记永远无法刷新（死锁）。
    `TRADE_TOOL_GUARD=off` 是显式退出开关，不阻断。
    """
    try:
        from trade.hermes_chat_memory_plugin.guardrails import guard_enabled

        if not guard_enabled():
            return None
    except Exception:  # noqa: BLE001 — 读不到开关按开启处理（安全侧）
        pass

    state = verify_tool_guard_ready()
    if state["ok"]:
        return None
    if state.get("hooks") is False:
        return (
            "⚠️ 当前 Hermes 版本不支持工具钩子（register_hook），"
            "文件与命令安全守卫无法生效，聊天已暂停。请先升级 Hermes，再重启 Trade。"
        )
    reasons = []
    if not state.get("deployed"):
        reasons.append("插件未部署")
    if not state.get("enabled"):
        reasons.append("插件未启用")
    # 两边都缺失（无插件、无配置）常见于测试/开发直连或尚未 setup：
    # 只告警不阻断，否则测试环境与首次启动会直接锁死聊天。
    if not reasons:
        return None
    if not state.get("deployed") and not state.get("enabled"):
        return None
    return (
        "⚠️ 工具安全守卫未生效（" + "、".join(reasons) + "），聊天已暂停。"
        "请重启 Trade；若仍提示，检查 ~/.hermes/config.yaml 的 plugins.enabled 是否包含 chat-memory。"
    )


def background_github_skills_sync():
    """后台 daemon 线程：启动后静默同步一次，此后每天中午 12:30 定时同步。

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
        # 此后：每天中午 12:30 定时同步（夜里电脑可能关机，选白天时段）
        while True:
            now = _dt.datetime.now()
            next_run = now.replace(hour=12, minute=30, second=0, microsecond=0)
            if next_run <= now:
                next_run += _dt.timedelta(days=1)
            _time.sleep((next_run - now).total_seconds())
            _sync_once()

    t = threading.Thread(target=_run, daemon=True)
    t.start()


# ── 文档解析依赖 ─────────────────────────────────────────────────────────

# PDF / 旧版 Office 解析必需。两者缺失时 Hermes 不报错，而是把 PDF 当纯文本
# 读成乱码，用户拿到的是垃圾内容；页数与扫描页检测也会退化成「未知」。
# anydoc 走 Hermes 自己的懒加载机制（与其 pyproject 保持一致），
# pypdfium2 不是 Hermes 的懒加载项，直接 pip 安装。
_HERMES_DOC_FEATURE = "tool.doc_extract"
_REQUIRED_DOC_MODULES: tuple[tuple[str, str], ...] = (
    ("anydoc", "firecrawl-anydoc==0.2.4"),
    ("pypdfium2", "pypdfium2>=4.30.0,<6.0"),
)


def _importable(name: str) -> bool:
    """模块是否可导入（不触发网络，只做导入探测）。"""
    import importlib.util
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _document_deps_missing() -> list[tuple[str, str]]:
    """返回缺失的 (模块名, pip 规格) 列表。"""
    return [(module, spec) for module, spec in _REQUIRED_DOC_MODULES if not _importable(module)]


def _pip_install(specs: tuple[str, ...] | list[str]) -> None:
    """用当前解释器安装依赖。"""
    import subprocess
    subprocess.run(
        [sys.executable, "-m", "pip", "install", *specs],
        capture_output=True, timeout=600, check=True,
    )


def _install_document_deps() -> None:
    """强制安装缺失的文档解析依赖；失败只记录，不影响启动。"""
    missing = _document_deps_missing()
    if not missing:
        return
    modules = {module for module, _ in missing}
    # anydoc 优先交给 Hermes，复用它的 venv/uv 与约束逻辑。
    pip_specs: list[str] = []
    for module, spec in missing:
        if module == "anydoc":
            try:
                from tools import lazy_deps
                lazy_deps.ensure(_HERMES_DOC_FEATURE, prompt=False)
                modules.discard("anydoc")
                continue
            except Exception as exc:
                print(f"  Documents: Hermes 安装 {spec} 失败（{exc}），改用 pip")
        pip_specs.append(spec)
    if not pip_specs:
        return
    try:
        _pip_install(pip_specs)
    except Exception as exc:
        print(f"  Documents: 安装 {', '.join(pip_specs)} 失败（{exc}）—— PDF 可能无法解析")


def ensure_document_deps():
    """确保 PDF 解析依赖已安装。

    Hermes 把 anydoc 列为 core 依赖，但精简安装或旧环境可能缺失；
    pypdfium2 是页数与扫描页检测的回退路径。缺失时后台补齐，不阻塞启动。
    """
    missing = _document_deps_missing()
    if not missing:
        return
    names = "、".join(module for module, _ in missing)
    print(f"  Documents: 缺少 {names}（PDF 解析必需），后台安装中...")
    import threading

    def _run():
        _install_document_deps()
        if not _document_deps_missing():
            print("  Documents: 文档解析依赖已就绪")

    threading.Thread(target=_run, daemon=True).start()


# ── 一键 setup ───────────────────────────────────────────────────────────


def prepare_hermes_import_paths() -> bool:
    """把 sys.path 准备到「可以 import Hermes」，返回 Hermes 是否可用。

    供 `setup()` 与**安装脚本的自检**共用 —— 两者都必须在**任何 Hermes import 之前**调用。
    2026-10-15 干净机器实测踩到的两个坑都源于「漏调这一步」：

      1. 不调 `_adjust_sys_path()` 就 import → `No module named 'run_agent'`。
         Hermes 不再装进 Trade 的 venv（见 COMPATIBILITY.md 的「当前策略」），
         全靠这里把 checkout 插进 sys.path。
      2. 不调 `_activate_hermes_env_and_restore_trade_paths()` → Hermes 的 pm 激活会
         按目录名把 venv 的 site-packages 从 sys.path 踢掉且**不会自己恢复**，于是
         后续 `import holehe` / `sqlite_vec` 全部误报「未安装」（其实装了）。

    Returns:
        Hermes 是否可用。False 时调用方**不得** import Hermes（过旧会崩在缺依赖上）。
    """
    _disable_hermes_lazy_installs()
    _adjust_sys_path()
    usable = hermes_is_usable()
    # 只有明确可用才触发激活：过旧时 import Hermes 只会崩在缺依赖上
    if usable:
        _activate_hermes_env_and_restore_trade_paths()
    return usable


def setup():
    """执行 Trade 启动所需的所有引导步骤。

    调用顺序：
    0. Hermes 懒加载守卫（必须最先 —— 它只是设个环境变量，而后面每步都可能 import Hermes）
    1. 架构检查（不匹配 → 退出：Hermes 的 C 扩展根本装不上，降级也没有意义）
    2. 路径准备：sys.path + pm 激活后的恢复（见 prepare_hermes_import_paths）
    3. Hermes 共存检查（**过旧不再退出**，见下）
    4. 子命令分发（doctor/osint/… 会 import Hermes，所以必须在第 2 步之后）
    5. .env 加载 + YOLO 设置（需 Hermes）
    6. Skills 同步 / 文档依赖 / 桌面集成（失败不阻断）
    7. 端到端自检（要起 agent，需 Hermes）

    **第 1、4 步的顺序与 2026-10-15 之前相反**，这是干净机器实测逼出来的：
    子命令分发（尤其 `trade doctor`）会在自己的代码里 import Hermes，若排在路径准备
    之前，doctor 就成了「第一个 import Hermes 的人」—— pm 激活剥离 site-packages 后
    没有任何人恢复，导致 doctor 自己后面的依赖检查全部误报「未安装」。

    第 3 步为什么改成降级而不是退出：桌面端（tradewin）先起服务线程再开窗口，
    一旦在起服务前退出，用户只会看到一个空白窗口、一句解释都没有 —— 而 Trade 的
    用户群基本是电脑小白，这等于让他们以为软件坏了。改为「记录状态 + 跳过碰 Hermes
    的步骤 + 照常起服务」，界面才能显示升级面板把他们引到正确的动作上。
    """
    # 第 0 步：只设环境变量，必须先于一切可能 import Hermes 的动作
    _disable_hermes_lazy_installs()

    # 第 1 步：架构检查在路径准备之前 —— 它不需要 Hermes，而架构不符时后面全是白跑
    if not check_native_architecture():
        sys.exit(1)

    # 第 2 步：路径准备（含 pm 激活后的恢复），必须在任何 Hermes import 之前
    prepare_hermes_import_paths()

    # 第 3 步：共存检查，**故意不退出**（理由见 docstring）
    hermes_usable = check_hermes_version()

    # 第 4 步：子命令分发。排在路径准备之后 —— doctor/osint 自己会 import Hermes
    if dispatch_subcommands():
        sys.exit(0)

    if not hermes_usable:
        # 过旧时跳过所有会 import Hermes 的步骤：load_env_and_set_yolo() 会 import
        # hermes_cli.env_loader / hermes_constants，端到端自检要起 agent —— 两者在
        # 旧 Hermes + 新 Python 下都会崩，服务就起不来了，升级面板也就无从显示。
        # 两种不可用的**用户动作完全不同**，提示必须分开，否则会把用户引到白折腾的路上
        _fix = hermes_compat_state().get("fix")
        if _fix == "rebuild_trade_venv":
            print("  ⚠️ Trade 的运行环境过旧，本次以降级模式启动：界面会给出重建步骤。")
        else:
            print("  ⚠️ Hermes 不可用，本次以降级模式启动：界面会引导你升级 Hermes。")
        # 剩下这几步本意是「不碰 Hermes、照常跑以保持功能完整」，但它们**间接**仍会
        # 摸到 Hermes（`_local_skills_sync` 要 `hermes_constants` 解析数据目录、
        # `ensure_document_deps` 会试 Hermes 的 lazy_deps）。这里逐个兜住：
        # 降级模式唯一不可违反的不变量是**服务必须起得来** —— 任一可选项失败都绝不能
        # 把升级界面挡在门外，那会让用户彻底无从下手。
        for _optional_step in (sync_b2b_skills, sync_chat_memory_plugin, ensure_chat_memory_plugin_enabled, lambda: verify_tool_guard_ready(announce=True), ensure_document_deps, ensure_desktop_integration):
            try:
                _optional_step()
            except Exception as exc:  # noqa: BLE001 — 见上：降级模式必须走到起服务
                print(f"  ⚠️ {_optional_step.__name__} 跳过（{exc}）")
        # 只有「Hermes 过旧」才自动升级 Hermes。「Trade 运行环境过旧」时跑 hermes update
        # 毫无用处（问题在 Trade 这一侧），反而会让用户等一场没有结果的升级。
        if _fix == "upgrade_hermes":
            _start_hermes_upgrade_in_background()
        return

    load_env_and_set_yolo()
    sync_b2b_skills()
    sync_chat_memory_plugin()
    ensure_chat_memory_plugin_enabled()
    verify_tool_guard_ready(announce=True)
    ensure_document_deps()
    ensure_desktop_integration()
    start_doctor_if_needed()


def _start_hermes_upgrade_in_background() -> None:
    """降级模式下自动在后台升级 Hermes。

    用户明确要求「版本过低就直接帮用户升级」—— 桌面端用户看不到终端，让他们自己敲
    命令等于没做。升级本身会先查 GitHub 可达性（见 trade.hermes_upgrade）：网络不通
    绝不开始，否则失败会同时弄坏 Hermes 与 Trade。

    这里吞掉所有异常：自动升级失败不能反过来挡住服务启动，否则界面就出不来了。
    """
    try:
        from trade.hermes_upgrade import start_upgrade

        start_upgrade()
    except Exception as exc:  # noqa: BLE001 — 启动路径必须永不因升级失败而中断
        print(f"  ⚠️ 后台升级 Hermes 启动失败：{exc}")


def start_doctor_if_needed() -> None:
    """首次启动跑一次端到端自检；未通过则每次启动重试。

    为什么放在启动路径：客户的安装流程是「装 Hermes → 让 Hermes 装 Trade」，
    不会主动去调 `trade doctor` —— 只有启动这一步是必然发生的。

    为什么放后台线程而不是阻塞启动：
      - 自检要发真实请求（含一次对话回合），会拖慢启动几十秒
      - 自检失败不该妨碍 Trade 起服务（致命项的后果由 doctor 报告与安装脚本处理）
    为什么不是每次启动都跑：端到端验活要花 token 和 Tavily 配额，
    所以只在"没跑过 / 上次没过 / 配置变了"时跑（见 doctor.should_run_doctor）。
    """
    try:
        from trade.doctor import should_run_doctor

        if not should_run_doctor():
            return
    except Exception:
        return  # 判断失败就不跑，绝不因为自检影响启动

    import threading

    def _run() -> None:
        try:
            # 稍等，避免和启动阶段抢资源（skills 同步、文档依赖安装都在跑）
            time.sleep(5)
            from trade.doctor import (
                format_report,
                run_doctor,
                save_doctor_result,
            )

            print("[doctor] 首次运行自检中（会发一次真实对话与图片请求）...")
            results = run_doctor(deep=True)
            save_doctor_result(results)
            print(format_report(results))
        except Exception as e:
            # 自检自身出错绝不冒泡 —— 它只是诊断工具
            print(f"[doctor] 自检未能完成：{e}")

    threading.Thread(target=_run, name="trade-doctor", daemon=True).start()


def ensure_desktop_integration() -> None:
    """Windows：幂等地配好开机自启（隐藏窗口）与桌面快捷方式。

    为什么放在**服务启动**而不是只在安装脚本里：客户的部署流程是
    「装 Hermes → 让 Hermes 装 Trade」，**不经过 install.ps1** —— 只在脚本里配
    等于没配，用户得每次人工交代。放在这里，任何安装路径都会自动完成。

    行为约定：
      - 只在 Windows 执行（macOS/Linux 的自启由 install.sh 的 launchd/systemd 负责）
      - 幂等：已配好就跳过；检测到旧的会弹窗的任务（python.exe）会替换掉
      - 失败只打印警告，**绝不阻断启动** —— 自启是便利功能，不是运行前提
      - `TRADE_SKIP_AUTOSTART_SETUP=1` 可整体关掉（不想被改系统设置的用户）
    """
    if os.name != "nt":
        return
    if os.environ.get("TRADE_SKIP_AUTOSTART_SETUP", "").strip() == "1":
        return

    try:
        from trade.post_install.win_setup import ensure_windows_setup, trade_dir_from_module

        for msg in ensure_windows_setup(trade_dir_from_module()):
            print(f"  {msg}")
    except Exception as e:
        # 自启配置是便利功能，失败绝不能影响 Trade 本身能不能用
        print(f"  ⚠ 桌面集成设置跳过：{e}")
