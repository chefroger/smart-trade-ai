"""Windows 开机自启 + 桌面快捷方式（幂等、自动、无声）。

## 为什么需要这个模块

客户的部署流程是「先装 Hermes，再让 Hermes 装 Trade」——**不经过 install.ps1**，
所以脚本里配好的自启拿不到，只能每次人工交代。这里把三件事收敛成一份代码，
由 install.ps1、`trade update`、以及**服务启动时**共同调用。

## 为什么原来的实现不满足要求

历史实现（两套，且互相不一致）：
  - `install.ps1`：`Register-ScheduledTask -Execute $PyCmd ...`（$PyCmd = python.exe）
  - `update.py`：`schtasks /create /tr '"py" "server.py" --no-browser'`

**两者都是控制台程序 → 登录时必然弹一个黑框终端。** 而 `docs/index.md` 里给客户的
手动教程用的是 VBS 隐藏窗口方案，反而是对的。本模块统一到后者。

## 统一后的结构

    trade-autostart.bat   把 trade 的输出重定向到 trade-autostart.log（失败可查）
    trade-autostart.vbs   以隐藏窗口启动上面的 bat（不弹终端）
    计划任务 SmartTradeAI  登录时运行 wscript.exe "<vbs>"（隐藏窗口）
    桌面快捷方式          指向 trade-open.vbs → `trade open`（起服务 + 开浏览器）

日志重定向很关键：隐藏窗口之后就看不到 stdout 了，没有日志文件等于把排查能力
一起藏了。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

TASK_NAME = "SmartTradeAI"
# 文档里的手动方案用的注册表项名。检测到就清掉，避免和计划任务双重启动。
LEGACY_RUN_VALUE = "TradeAutoStart"


# ── 纯逻辑（可测，不碰系统） ──────────────────────────────────────────────

def launcher_dir() -> Path:
    """启动器脚本与日志的存放目录（跨平台路径规范）。"""
    val = os.environ.get("TRADE_HOME", "").strip()
    if val:
        return Path(val)
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        return Path(local) / "trade"
    return Path.home() / ".trade"


def to_batch_path(path: str | Path) -> str:
    """把用户目录前缀换成环境变量引用，让写进 .bat 的内容保持**纯 ASCII**。

    为什么必须这么做：cmd.exe 按系统 OEM 代码页读取 .bat。中文用户名
    （`C:\\Users\\张伟\\AppData\\Local\\...`）直接写进去会解码成乱码 ——
    `docs/index.md` 里那段手动教程用 `-Encoding ASCII` 写 .bat，非 ASCII 字符
    被静默替换成 `?`，正是这个坑。用 `%LOCALAPPDATA%` / `%USERPROFILE%`
    在运行时展开，就完全绕开了编码问题。
    """
    p = str(path)
    for env_name in ("LOCALAPPDATA", "USERPROFILE"):
        prefix = os.environ.get(env_name, "")
        if prefix and p.lower().startswith(prefix.lower()):
            return f"%{env_name}%" + p[len(prefix):]
    return p


def _is_windows() -> bool:
    """当前是否 Windows。

    提为函数是为了**可注入**：测试里直接改 `os.name` 会连累 pathlib ——
    Windows 上 `os.name != "nt"` 会让 `Path()` 抛 NotImplementedError，
    把整个进程（含 pytest 自己）搞崩。这个坑已经踩过一次。
    """
    return os.name == "nt"


def resolve_trade_command(trade_dir: Path, *, executable: str | None = None) -> str:
    """返回启动 Trade 的**完整命令行**（不含参数，已做 batch 安全转换）。

    优先用与当前解释器同目录的 `trade.exe`（console script，在 venv 的 Scripts 里）——
    与文档里「用完整路径、不依赖 PATH」的做法一致，开机早期 PATH 未加载完也能跑。
    没有就退回 `"<python>" "<server.py>"`，行为等价、不依赖 console script 是否在 PATH。

    Args:
        executable: 解释器路径，默认 `sys.executable`。可注入以便测试 ——
                    直接改 `sys.executable` 是全局副作用，会波及同进程的其它调用。

    返回带引号、可直接拼进 .bat 的字符串。
    """
    exe = executable or sys.executable
    exe_dir = Path(exe).parent
    for name in ("trade.exe", "trade"):
        candidate = exe_dir / name
        if candidate.is_file():
            return f'"{to_batch_path(candidate)}"'
    return f'"{to_batch_path(exe)}" "{to_batch_path(trade_dir / "server.py")}"'


def build_autostart_bat(command: str, log_file: str) -> str:
    """开机自启用的 .bat：跑服务、不打开浏览器、输出重定向到日志。

    `--no-browser` 是必须的 —— 登录时不该弹浏览器；界面由桌面快捷方式负责打开。
    """
    return (
        "@echo off\r\n"
        f"{command} --no-browser > \"{log_file}\" 2>&1\r\n"
    )


def build_open_bat(command: str, log_file: str) -> str:
    """桌面快捷方式用的 .bat：起服务 + 开浏览器。"""
    return (
        "@echo off\r\n"
        f"{command} open > \"{log_file}\" 2>&1\r\n"
    )


def build_hidden_vbs(bat_path: Path) -> str:
    """VBS：以**隐藏窗口**启动 .bat，不等待返回。

    `Run(cmd, 0, False)` 的三个参数分别是：命令、窗口样式(0=隐藏)、是否等待结束。

    bat 路径同样要过 `to_batch_path` —— 让 VBS 也保持纯 ASCII。
    VBS 由 wscript 按系统 ANSI 代码页读取，中文用户名路径原样写进去依赖编码兜底；
    改成 `%LOCALAPPDATA%` 由 cmd 运行时展开就没有这个问题
    （`.bat` 与 `.vbs` 两侧现在用同一套路径规则）。
    """
    return (
        'Set WshShell = CreateObject("WScript.Shell")\r\n'
        f'WshShell.Run "cmd /c ""{to_batch_path(bat_path)}""", 0, False\r\n'
    )


def is_vbs_launcher_task(task_xml: str, expected_vbs: Path | None = None) -> bool:
    """判断已存在的计划任务是不是「**正确的**隐藏式启动器」。

    历史判据太松：只要 XML 里同时出现 `wscript` 与 `.vbs` 就算通过 —— 于是一个
    被注册坏的命令（路径被引号截断、指向别的 vbs、参数丢失）会被当成好的，
    **永远不修**，而症状恰是"开机弹终端窗口"或"开机什么都不发生"。

    现在的判据（三条全中才算对）：
      1. `<Command>` 的可执行文件名是 wscript（或其全路径）
      2. `<Arguments>` 里出现 .vbs
      3. 传了 expected_vbs 时，参数里的 vbs 文件名必须与之一致

    拿不到 XML（空串）返回 False —— 让调用方走"替换"路径。
    """
    import re

    xml = task_xml or ""
    if not xml:
        return False

    m_cmd = re.search(r"<Command>(.*?)</Command>", xml, re.S | re.I)
    m_args = re.search(r"<Arguments>(.*?)</Arguments>", xml, re.S | re.I)
    if not m_cmd:
        return False

    command = m_cmd.group(1).strip().strip('"')
    # 只取可执行文件名比较，路径里带不带 wscript 字样都不影响判断
    exe = command.replace("/", "\\").rsplit("\\", 1)[-1].lower()
    if exe not in ("wscript.exe", "wscript"):
        return False

    args = (m_args.group(1) if m_args else "").strip()
    if ".vbs" not in args.lower():
        return False

    if expected_vbs is not None:
        # 参数里必须引用我们那个 vbs（防止任务指向了残留的旧脚本）
        if expected_vbs.name.lower() not in args.lower():
            return False

    return True


# ── 需要碰系统的部分（命令可注入，便于测试） ──────────────────────────────

def _run(cmd: list[str], timeout: int = 30):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _write_script(path: Path, content: str) -> None:
    """写 .bat / .vbs 脚本，按 cmd.exe 实际读取的编码写。

    正常情况下内容已被 `to_batch_path` 转成纯 ASCII（路径走环境变量展开），
    此时编码无关紧要。只有自定义安装目录含非 ASCII 且不在用户目录下时才会走到
    兜底分支 —— 那时必须用 **mbcs（系统 ANSI 代码页）**，因为 cmd/wscript 就是
    按它读脚本的；用 UTF-8 写会乱码，用 ASCII 写会把字符替换成 `?`（静默写坏）。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = content.encode("ascii")
    except UnicodeEncodeError:
        codec = "mbcs" if os.name == "nt" else "utf-8"
        data = content.encode(codec, errors="replace")
    path.write_bytes(data)


def ensure_launcher_scripts(trade_dir: Path) -> dict:
    """生成/刷新 bat + vbs 启动器。返回路径字典。"""
    d = launcher_dir()
    autostart_bat = d / "trade-autostart.bat"
    autostart_vbs = d / "trade-autostart.vbs"
    open_bat = d / "trade-open.bat"
    open_vbs = d / "trade-open.vbs"
    autostart_log = to_batch_path(d / "trade-autostart.log")
    open_log = to_batch_path(d / "trade-open.log")

    command = resolve_trade_command(trade_dir)

    _write_script(autostart_bat, build_autostart_bat(command, autostart_log))
    _write_script(autostart_vbs, build_hidden_vbs(autostart_bat))
    _write_script(open_bat, build_open_bat(command, open_log))
    _write_script(open_vbs, build_hidden_vbs(open_bat))

    return {
        "autostart_bat": autostart_bat,
        "autostart_vbs": autostart_vbs,
        "open_bat": open_bat,
        "open_vbs": open_vbs,
        "autostart_log": autostart_log,
    }


def _query_task_xml() -> str:
    """读现有计划任务的 XML；不存在或读不到返回空串。"""
    result = _run(["schtasks", "/query", "/tn", TASK_NAME, "/xml"])
    if result.returncode != 0:
        return ""
    return result.stdout or ""


def ensure_scheduled_task(vbs_path: Path) -> str:
    """注册（或替换）开机自启计划任务。返回一句结果说明。

    替换逻辑：已存在但**不是** VBS 启动的（即旧的 python.exe 版本，会弹窗）→
    注销后按新方式重建。客户机上残留的旧任务因此能自动修好，不需要人工干预。
    """
    existing = _query_task_xml()
    if existing and is_vbs_launcher_task(existing, expected_vbs=vbs_path):
        return "✓ 开机自启动已是隐藏式启动器，跳过"

    if existing:
        # 旧式（python.exe）—— 会弹终端窗口，重建
        _run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"])

    # 用 schtasks 注册，执行体是 wscript.exe（VBS 负责隐藏窗口）
    trigger_arg = f'wscript.exe "{vbs_path}"'
    result = _run([
        "schtasks", "/create", "/tn", TASK_NAME,
        "/tr", trigger_arg,
        "/sc", "onlogon",
        "/rl", "limited",   # 用户权限，不请求管理员
        "/f",
    ])
    if result.returncode != 0:
        return f"⚠ 开机自启动设置失败：{(result.stderr or '').strip()}"
    if existing:
        return "✓ 已替换旧版开机自启任务（新版本不弹终端窗口）"
    return "✓ 已设置开机自启动（隐藏窗口）"


# 桌面上**不该出现**的启动器脚本名（它们只在 launcher_dir() 里）：
# 把 .vbs/.bat 直接放桌面等于多一个可执行文件 —— 容易被误删、也可能被杀软拦。
_STRAY_LAUNCHER_NAMES = (
    "trade-autostart.vbs",
    "trade-open.vbs",
    "trade-autostart.bat",
    "trade-open.bat",
)


def find_stray_desktop_launchers(desktop: Path) -> list[Path]:
    """找出桌面上遗留的启动器脚本（本不该在那）。

    只**报告**不删除：那可能是用户自己特意放的，删桌面上的文件必须由人决定。
    """
    found: list[Path] = []
    for name in _STRAY_LAUNCHER_NAMES:
        p = desktop / name
        if p.is_file():
            found.append(p)
    return found


def ensure_desktop_shortcut(open_vbs: Path) -> str:
    """在**真实桌面**创建 Trade 快捷方式（指向 VBS → `trade open`）。

    用 PowerShell 的 WScript.Shell COM 创建 .lnk —— 不引入 pywin32 依赖。
    桌面路径用 workdir._get_desktop_path()（Windows 走 SHGetFolderPathW），
    OneDrive 重定向桌面的机器上也不会放错地方。
    """
    from trade.company.workdir import _get_desktop_path

    desktop = _get_desktop_path()
    if not desktop.is_dir():
        return "⚠ 未找到桌面目录，跳过快捷方式"

    lnk = desktop / "Trade.lnk"
    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$sc = $ws.CreateShortcut('{lnk}'); "
        f"$sc.TargetPath = 'wscript.exe'; "
        f"$sc.Arguments = '\"{open_vbs}\"'; "
        "$sc.WorkingDirectory = $env:USERPROFILE; "
        "$sc.Description = '打开 Trade 外贸 AI 助手'; "
        "$sc.Save()"
    )
    result = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps])
    if result.returncode != 0 or not lnk.is_file():
        return f"⚠ 桌面快捷方式创建失败：{(result.stderr or '').strip()}"

    # 桌面上只该有 .lnk —— 启动器脚本一律在 launcher_dir()。检测到遗留就如实说，
    # 但**不自动删**：那可能是用户自己放的，删桌面文件得由人决定。
    stray = find_stray_desktop_launchers(desktop)
    if stray:
        names = "、".join(p.name for p in stray)
        return (
            f"✓ 已创建桌面快捷方式：{lnk.name}\n"
            f"  ⚠ 桌面还留着启动器脚本（本不该在这里，可安全删除）：{names}"
        )
    return f"✓ 已创建桌面快捷方式：{lnk.name}"


def remove_legacy_run_entry() -> str:
    """清理文档手动方案留下的注册表 Run 项（否则会和计划任务双重启动）。"""
    result = _run([
        "reg", "query", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
        "/v", LEGACY_RUN_VALUE,
    ])
    if result.returncode != 0:
        return ""  # 不存在 → 无事可做
    _run([
        "reg", "delete", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
        "/v", LEGACY_RUN_VALUE, "/f",
    ])
    return "✓ 已清理旧的手动注册表自启项（改由计划任务统一管理）"


def ensure_windows_setup(trade_dir: Path) -> list[str]:
    """Windows 一站式配置：启动器脚本 → 计划任务 → 桌面快捷方式。

    幂等：重复调用不会重复建东西，也不会覆盖用户改过的正确配置。
    每一步失败只记一条说明，不抛异常 —— 调用方（服务启动路径）不能因此挂掉。
    """
    if not _is_windows():
        return []

    messages: list[str] = []
    try:
        scripts = ensure_launcher_scripts(trade_dir)
    except Exception as e:
        return [f"⚠ 生成启动器脚本失败：{e}"]

    try:
        messages.append(ensure_scheduled_task(scripts["autostart_vbs"]))
    except Exception as e:
        messages.append(f"⚠ 注册开机自启失败：{e}")

    try:
        legacy = remove_legacy_run_entry()
        if legacy:
            messages.append(legacy)
    except Exception:
        pass  # 清理失败不影响主流程

    try:
        messages.append(ensure_desktop_shortcut(scripts["open_vbs"]))
    except Exception as e:
        messages.append(f"⚠ 创建桌面快捷方式失败：{e}")

    return messages


def trade_dir_from_module() -> Path:
    """由本模块位置推导仓库根（server.py 所在目录）。"""
    return Path(__file__).resolve().parent.parent.parent
