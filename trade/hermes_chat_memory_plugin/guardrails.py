"""工具层守卫：文件路径白名单 + 命令白名单（审计 P1-3 / P1-20）。

为什么必须放在插件钩子里：Trade 不改 Hermes，也不能依赖 prompt 约束 ——
客户消息里的提示注入可以让模型直接调 `read_file("/etc/passwd")` 或
`terminal("curl ... | sh")`。Hermes 提供 `pre_tool_call` 钩子，返回
`{"action": "block", "message": ...}` 就能在工具执行前否决（YOLO 模式也挡得住）。

规则（默认开启，`TRADE_TOOL_GUARD=off` 可关闭）：

- `read_file` / `write_file` / `patch` / `search_files`：`path` 必须落在当前
  公司白名单根目录内（公司数据目录、工作目录、本公司文档库）。缺 path、
  相对路径、未绑定公司 → 一律拒绝（fail-closed）。
- `terminal`：只放行 `python -m trade.osint …` / `trade osint …`（技能里唯一
  需要的命令）；含 shell 元字符（; & | < > ` $() 换行）的一律拒绝。
- `execute_code`：永久拒绝（技能不依赖，任意 Python 等于无沙箱）。

残留（未覆盖，如实记录）：`browser` 工具可能导航本地/下载文件；cron 等
未绑定公司的运行没有公司上下文，会被 fail-closed 挡住（需要文件能力的
定时任务会明确失败，而不是静默越权）。
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path

# 文件工具 → 路径参数名（都与 Hermes tools/file_tools.py 的 schema 一致）
_FILE_TOOLS = frozenset({"read_file", "write_file", "patch", "search_files"})

# 允许的终端命令（argv 前缀）。只认 OSINT 机器判定入口 —— SKILL.md 里唯一
# 需要 shell 的命令；其余一律走文件工具或由 Trade 自己的端点完成。
_ALLOWED_ARGV_PREFIXES = (
    ("python", "-m", "trade.osint"),
    ("python3", "-m", "trade.osint"),
    ("trade", "osint"),
)

# shell 元字符：命中就拒绝 —— 否则 "python -m trade.osint x && rm -rf ~" 会被
# 前缀匹配放行。$ 与反引号单独列（命令替换）。
_SHELL_META = (";", "&", "|", "<", ">", "`", "$", "\n", "\r")


def guard_enabled() -> bool:
    """`TRADE_TOOL_GUARD` 关闭值：off/0/false/no（大小写不敏感）；其余视为开启。"""
    raw = os.environ.get("TRADE_TOOL_GUARD", "").strip().lower()
    return raw not in {"off", "0", "false", "no"}


def _current_company_id() -> int | None:
    try:
        from trade.agent_context import current_company_id

        return current_company_id()
    except Exception:
        return None


def _allowed_roots(company_id: int | None) -> list[Path]:
    if not company_id:
        return []
    try:
        from trade.helpers import _allowed_path_roots

        return _allowed_path_roots(company_id)
    except Exception:
        return []


def _path_within(path: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _block(message: str) -> dict:
    return {"action": "block", "message": message}


def _check_file_path(tool_name: str, args: dict) -> dict | None:
    raw = args.get("path")
    if not isinstance(raw, str) or not raw.strip():
        return _block(
            f"trade 工具守卫：{tool_name} 必须显式传绝对路径（path）。"
            "请使用 Trade Context / 文档库中给出的绝对路径。"
        )
    candidate = raw.strip()
    if not (candidate.startswith("/") or candidate.startswith("~")
            or candidate.startswith("\\") or (len(candidate) > 1 and candidate[1] == ":")):
        return _block(
            f"trade 工具守卫：只接受绝对路径，收到相对路径 {candidate!r}。"
            "请使用 Trade Context / 文档库中给出的绝对路径。"
        )
    company_id = _current_company_id()
    roots = _allowed_roots(company_id)
    if not roots:
        return _block(
            "trade 工具守卫：当前会话没有绑定公司，文件访问已拒绝。"
            "请在 Trade 聊天界面里发起请求。"
        )
    try:
        resolved = Path(candidate).expanduser().resolve()
    except (OSError, ValueError):
        return _block(f"trade 工具守卫：无法解析路径 {candidate!r}。")
    if not _path_within(resolved, roots):
        return _block(
            "trade 工具守卫：路径不在当前公司允许范围内，已拒绝。"
            "只能访问公司数据目录、工作目录和本公司文档库。"
        )
    return None


def _check_terminal(args: dict) -> dict | None:
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        return _block("trade 工具守卫：终端命令为空。")
    if any(meta in command for meta in _SHELL_META):
        return _block(
            "trade 工具守卫：终端命令包含 shell 元字符（; & | < > ` $ 或换行），已拒绝。"
        )
    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        return _block("trade 工具守卫：终端命令无法解析，已拒绝。")
    if not any(
        tuple(argv[: len(prefix)]) == prefix for prefix in _ALLOWED_ARGV_PREFIXES
    ):
        return _block(
            "trade 工具守卫：只允许执行 OSINT 判定命令"
            "（python -m trade.osint …）。"
            "读取/搜索文件请用 read_file / search_files，写入请用 write_file。"
        )

    workdir = args.get("workdir")
    if workdir:
        gated = _check_file_path("terminal", {"path": workdir})
        if gated is not None:
            return gated
    return None


def check_tool_call(tool_name: str, args: dict | None) -> dict | None:
    """返回 block 指令或 None（放行）。纯函数，便于单测。"""
    if not guard_enabled():
        return None
    if tool_name == "execute_code":
        return _block(
            "trade 工具守卫：execute_code 已停用（任意 Python 等于无沙箱）。"
            "需要读文件用 read_file / search_files。"
        )
    if tool_name in _FILE_TOOLS:
        return _check_file_path(tool_name, args if isinstance(args, dict) else {})
    if tool_name == "terminal":
        return _check_terminal(args if isinstance(args, dict) else {})
    return None


def on_pre_tool_call(tool_name: str = "", args=None, **_kw) -> dict | None:
    """Hermes `pre_tool_call` 钩子入口；永不抛异常（抛异常会 fail-closed 且难排查）。"""
    try:
        return check_tool_call(tool_name, args if isinstance(args, dict) else {})
    except Exception:
        return _block("trade 工具守卫：内部异常，已拒绝本次工具调用。")
