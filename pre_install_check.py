"""
pre_install_check: Verify hermes-agent is installed and compatible before trade install.

This module runs BEFORE pip install of the trade package.
It checks:
  1. Is hermes-agent installed at all?
  2. Is the installed version compatible with trade's requirements?
  3. If not compatible → print instructions to install from NousResearch/hermes-agent first.

Exit codes:
  0  = compatible, proceed with trade install
  1  = hermes-agent not found, must install first
  2  = hermes-agent version incompatible, must upgrade/downgrade
  3  = architecture mismatch (e.g. x86_64 Python on arm64 Mac)

Usage (run BEFORE pip install trade):
  python pre_install_check.py
"""

from __future__ import annotations

import json as _json
import sys
import urllib.request

# ─────────────────────────────────────────────────────────────────────────────
# Version compatibility matrix
# ─────────────────────────────────────────────────────────────────────────────

# trade requires hermes-agent from NousResearch/hermes-agent at or above this version.
# (Prior to v0.4.0, the chefroger/hermes-agent fork was used; now migrated to upstream.)
MIN_COMPATIBLE_VERSION = "0.13.0"

# 不是真实版本号的占位值：上游 main 在缺少安装印章时会把 __version__ 报成 "0.0.0"
_VERSION_PLACEHOLDERS = {"", "0.0.0", "0.0.0.0", "unknown", "none", "dev"}

# CLI 探测超时（秒）。冷启动实测约 2 秒，遇到慢盘/首次加载可能更久 ——
# 用 5 秒会把「正常但慢」误判成「未安装」，故放宽到 30。
_CLI_PROBE_TIMEOUT_SECONDS = 30

# If hermes-agent is installed from a different source,
# it may be incompatible even if version number looks OK.
# List of known-incompatible package names (PyPI releases from other sources).
INCOMPATIBLE_SOURCES: list[str] = [
    # No PyPI release for hermes-agent exists (it's git-only), so we check
    # the installed package's install location as a proxy for source.
]


# ─────────────────────────────────────────────────────────────────────────────
# Version parsing
# ─────────────────────────────────────────────────────────────────────────────

def _parse_version(version_str: str) -> tuple[int, int, int]:
    """Parse 'X.Y.Z' into (major, minor, patch) integers.

    Falls back to (0,0,0) for unparseable strings.
    Strips 'v' prefix (e.g. 'v0.12.0' → 0.12.0).
    """
    clean = version_str.lstrip("v").strip()
    try:
        parts = clean.split(".")
        return (int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
    except (ValueError, IndexError):
        return (0, 0, 0)


def _judge_installed_version(installed: str | None, required: str) -> str:
    """判定已安装的 Hermes 版本，返回 'ok' / 'too_old' / 'unknown'。

    'unknown' 覆盖三种「识别不到」的情形 —— 这几种都不能当成版本过旧，
    否则会卡死安装流程，而且给出的提示是误导的：
      1. 占位值：上游 main 无安装印章时把 __version__ 报成 "0.0.0"
      2. 带后缀的派生版本：如 "0.21.4+5045"、"v0.21.5-490-gabc1234"
      3. 无法解析的字符串：如 "git.abc1234"
    """
    raw = str(installed or "").strip()
    # 先去 PEP 440 本地版本段（+5045）与 git 后缀（-490-gabc1234）再判
    base = raw.lstrip("v").split("+", 1)[0].split("-", 1)[0].strip()
    if (
        not base
        or raw.lower() in _VERSION_PLACEHOLDERS
        or base.lower() in _VERSION_PLACEHOLDERS
    ):
        return "unknown"
    # 只接受纯数字的 X[.Y[.Z]]；其它形态按未知处理（保守方向是放行而不是拦截）
    parts = base.split(".")
    if len(parts) > 3 or not all(part.isdigit() for part in parts):
        return "unknown"
    if _compare_versions(base, required) < 0:
        return "too_old"
    return "ok"


def _compare_versions(installed: str, required: str) -> int:
    """Compare two version strings.

    Returns:  -1 if installed < required
               0 if installed == required
              +1 if installed > required
    """
    inst = _parse_version(installed)
    req = _parse_version(required)
    if inst < req:
        return -1
    elif inst > req:
        return +1
    else:
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# hermes-agent version detection
# ─────────────────────────────────────────────────────────────────────────────

def get_installed_hermes_version() -> str | None:
    """Attempt to detect the installed hermes-agent version string.

    Tries in order:
      1. `hermes --version` CLI (fast, works if CLI is on PATH)
      2. Import the `hermes_cli` package and read __version__
      3. Scan sys.path for the `hermes_cli` package directory

    NOTE: the distribution is named `hermes-agent`, but its **importable package
    is `hermes_cli`** —— 回退探测必须用这个名字，否则必然 ImportError。

    Returns None if hermes-agent is not installed at all.
    """
    import shutil
    import subprocess

    # Try CLI first
    hermes_bin = shutil.which("hermes")
    if hermes_bin:
        try:
            result = subprocess.run(
                [hermes_bin, "--version"],
                capture_output=True, text=True, timeout=_CLI_PROBE_TIMEOUT_SECONDS,
            )
            # Output format: 'hermes X.Y.Z' or just 'X.Y.Z'
            raw = result.stdout.strip() or result.stderr.strip()
            # Extract version number
            for word in raw.split():
                if word[0].isdigit() or word.startswith("v"):
                    return word.lstrip("v")
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    # Try importing the package（包名是 hermes_cli，不是 hermes_agent）
    try:
        import hermes_cli
        return getattr(hermes_cli, "__version__", None) or _find_version_in_path()
    except ImportError:
        pass

    # Last resort: scan site-packages
    return _find_version_in_path()


def _find_version_in_path() -> str | None:
    """Scan sys.path for hermes-agent package and read its version file."""
    import pathlib

    for prefix in sys.path:
        p = pathlib.Path(prefix)
        if not p.is_dir():
            continue
        # Try the hermes_cli package directory（发行名是 hermes-agent，导入名不是）
        pkg = p / "hermes_cli"
        if pkg.is_dir():
            # Check for __version__ in __init__.py
            init_file = pkg / "__init__.py"
            if init_file.is_file():
                content = init_file.read_text(encoding="utf-8", errors="ignore")
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith("__version__"):
                        parts = line.split("=", 1)
                        if len(parts) == 2:
                            return parts[1].strip().strip("'\"").strip("v")
            # Check for PKG-INFO or METADATA
            for fname in ("PKG-INFO", "METADATA", "version"):
                vfile = pkg.parent / fname
                if vfile.is_file():
                    content = vfile.read_text(encoding="utf-8", errors="ignore")[:500]
                    for cline in content.splitlines():
                        cline = cline.strip()
                        if cline.startswith("Version:"):
                            return cline.split(":", 1)[1].strip().lstrip("v")
    return None


def is_hermes_from_official_source() -> bool:
    """Check if installed hermes-agent came from NousResearch/hermes-agent.

    Since hermes-agent has no PyPI release, we check the install location:
    - Path contains 'NousResearch' → official ✓
    - Path contains 'chefroger' → old fork (deprecated, may be outdated) ✗
    - Anything else (homebrew, apt, etc.) → unknown, assume OK

    Returns True if confirmed from official source or if not installed at all.
    """
    import pathlib

    for prefix in sys.path:
        p = pathlib.Path(prefix)
        if not p.is_dir():
            continue
        pkg = p / "hermes_agent"
        if pkg.is_dir():
            path_str = str(pkg.resolve())
            if "NousResearch" in path_str:
                return True
            if "chefroger" in path_str:
                return False
    # Not found in site-packages → treat as not installed (caller decides)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# GitHub API — check latest NousResearch release / commit
# ─────────────────────────────────────────────────────────────────────────────

def get_latest_official_version() -> str | None:
    """Query GitHub API for the latest release tag on NousResearch/hermes-agent."""
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/NousResearch/hermes-agent/releases/latest",
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "trade-pre-install-check/1.0"},
            timeout=10,
        )
        with urllib.request.urlopen(req) as resp:
            data = _json.loads(resp.read())
            tag = data.get("tag_name", "")
            return tag.lstrip("v") or None
    except Exception:
        return None


def get_latest_official_commit() -> str | None:
    """Get the latest commit SHA on main branch of NousResearch/hermes-agent."""
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/NousResearch/hermes-agent/commits/main",
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "trade-pre-install-check/1.0"},
            timeout=10,
        )
        with urllib.request.urlopen(req) as resp:
            data = _json.loads(resp.read())
            return data.get("sha", "")[:7] or None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Print helpers
# ─────────────────────────────────────────────────────────────────────────────

def print_header():
    print("=" * 60)
    print("  Trade Pre-Install Check — Hermes Agent Compatibility")
    print("=" * 60)


def print_ok(msg: str):
    print(f"\u2705 {msg}")


def print_fail(msg: str):
    print(f"\u274c {msg}")


def print_warn(msg: str):
    print(f"\u26a0\ufe0f {msg}")


def print_info(msg: str):
    print(f"   {msg}")


# ─────────────────────────────────────────────────────────────────────────────
# Main check logic
# ─────────────────────────────────────────────────────────────────────────────

def check_architecture() -> str | None:
    """Check for architecture mismatch on Apple Silicon.

    Returns a warning string if there's a potential issue, or None if all clear.
    """
    import platform
    import subprocess

    sys_machine = platform.machine()
    py_machine = platform.machine()  # same call — Python reports the runtime arch

    # Only warn on macOS
    if sys.platform != "darwin":
        return None

    # Get hardware architecture from uname (not Python's emulated view)
    try:
        result = subprocess.run(
            ["uname", "-m"], capture_output=True, text=True, timeout=5,
        )
        hw_arch = result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        hw_arch = ""

    # If hardware is arm64 (M-series) but Python is x86_64 (Rosetta)
    if hw_arch == "arm64" and py_machine == "x86_64":
        return (
            f"Architecture mismatch detected: hardware is {hw_arch} (Apple Silicon) "
            f"but Python is {py_machine} (Rosetta).\n"
            "This may cause Hermes dependencies (pydantic-core, psutil, etc.) "
            "to fail with Mach-O architecture errors.\n\n"
            "Fix: Install native arm64 Python via Homebrew:\n"
            "  brew install python@3.12\n"
            "  # If Homebrew itself is under Rosetta, reinstall it:\n"
            "  # /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"\n"
            "Then re-run this check with the native Python."
        )

    # If hardware is x86_64 AND we're on macOS — could be Intel Mac or Rosetta M-series
    if hw_arch == "x86_64" and sys_machine == "x86_64":
        # Check if we're actually on an M-series Mac under Rosetta
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.optional.arm64"],
                capture_output=True, text=True, timeout=5,
            )
            if result.stdout.strip() == "1":
                return (
                    "You are running on an Apple Silicon Mac under Rosetta emulation.\n"
                    "Hermes dependencies may fail when compiled as x86_64 binaries.\n\n"
                    "Fix: Use native arm64 Python:\n"
                    "  arch -arm64 /bin/bash  # start an arm64 shell\n"
                    "  brew install python@3.12  # native arm64 Python\n"
                    "Then re-run this check."
                )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    return None


def run_check() -> int:
    """Run all checks. Returns exit code (0=ok, 1=not installed, 2=incompatible)."""
    print_header()

    # Step 0: architecture check — 不匹配时阻断安装（exit code 3）
    arch_error = check_architecture()
    if arch_error:
        print_fail(arch_error)
        print()
        print("  架构不匹配会导致 Hermes 依赖（pydantic-core, psutil 等）编译为错误架构，")
        print("  无法加载。请先修正 Python 架构再重新运行此检查。")
        return 3

    installed_version = get_installed_hermes_version()

    # Case 1: not installed at all
    if installed_version is None:
        print_fail("hermes-agent is NOT installed.")
        print()
        print_warn("Hermes Agent must be installed BEFORE trade.")
        print()
        _print_install_instructions()
        return 1

    print_info(f"Installed hermes-agent version: {installed_version}")
    from_official = is_hermes_from_official_source()
    print_info(f"Installed from NousResearch/hermes-agent: {'yes' if from_official else 'NO (old chefroger fork)'}")

    # Case 2: installed but wrong source (old chefroger fork)
    if not from_official:
        print_fail("hermes-agent is installed from the old chefroger/hermes-agent fork (deprecated).")
        print_warn("Trade now uses the upstream: https://github.com/NousResearch/hermes-agent")
        print()
        print_info("Please uninstall the current version first:")
        print_info("  pip uninstall hermes-agent")
        print_info("  # or: uv pip uninstall hermes-agent")
        print()
        _print_install_instructions()
        return 2

    # Case 3: installed from official source, check version compatibility
    verdict = _judge_installed_version(installed_version, MIN_COMPATIBLE_VERSION)
    if verdict == "unknown":
        print_warn(f"Cannot tell the version from the reported value: {installed_version!r}")
        print_info("  (upstream reports 0.0.0 when a checkout has no install stamp)")
        print_info("  Skipping the minimum-version check and continuing.")
        print()
        return 0
    if verdict == "too_old":
        print_fail(f"hermes-agent version {installed_version} is too old.")
        print_warn(f"Trade requires version >= {MIN_COMPATIBLE_VERSION} from NousResearch/hermes-agent.")
        print()
        print_info("Please upgrade:")
        print_info("  pip install --upgrade hermes-agent")
        print_info("  # or: cd ~/.hermes/hermes-agent && uv pip install -e . --upgrade")
        print()
        _print_install_instructions_compat()
        return 2

    print_ok(f"hermes-agent {installed_version} from NousResearch/hermes-agent — compatible.")
    print()
    return 0


def _print_install_instructions():
    """Print installation instructions for NousResearch/hermes-agent."""
    print("=" * 60)
    print("  Install Hermes Agent")
    print("=" * 60)
    print()
    print("  Option A — One-liner (recommended):")
    print("    curl -fsSL \\")
    print("      https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh \\")
    print("      | bash")
    print()
    print("  Option B — Manual install:")
    print("    git clone --branch main \\")
    print("      https://github.com/NousResearch/hermes-agent.git \\")
    print("      ~/.hermes/hermes-agent")
    print("    cd ~/.hermes/hermes-agent")
    print("    uv pip install -e .   # or: pip install -e .")
    print()
    print("  After installation, re-run this check:")
    print("    python pre_install_check.py")
    print()


def _print_install_instructions_compat():
    """Print upgrade instructions for incompatible version."""
    print("=" * 60)
    print("  Upgrade Hermes Agent")
    print("=" * 60)
    print()
    print("  cd ~/.hermes/hermes-agent")
    print("  git pull origin main")
    print("  uv pip install -e . --upgrade")
    print()
    print("  Or re-run the official installer:")
    print("    curl -fsSL \\")
    print("      https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh \\")
    print("      | bash")
    print()
    print("  Then verify:")
    print("    python pre_install_check.py")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    exit_code = run_check()
    sys.exit(exit_code)
