"""工具层守卫：文件路径白名单 + 命令白名单（审计 P1-3 / P1-20）。

为什么必须放在插件钩子里：Trade 不改 Hermes，也不能依赖 prompt 约束 ——
客户消息里的提示注入可以让模型直接调 `read_file("/etc/passwd")` 或
`terminal("curl ... | sh")`。Hermes 提供 `pre_tool_call` 钩子，返回
`{"action": "block", "message": ...}` 就能在工具执行前否决（YOLO 模式也挡得住）。

规则（默认开启，`TRADE_TOOL_GUARD=off` 可关闭）：

- `read_file` / `write_file` / `patch` / `search_files`：`path` 必须落在当前
  公司白名单根目录内（公司数据目录、工作目录、本公司文档库）。缺 path、
  相对路径、未绑定公司 → 一律拒绝（fail-closed）。
- `write_file` / `patch` 额外拒绝两类高敏文件：公司 identity
  (`companies/{slug}/agent-identity.md`) 与公司 prompts 目录下的 `*.md`
  —— 它们在白名单根内，但运行时会作为系统提示读入，允许改写等于允许持久化
  提示注入。
- `vision_analyze`：`image_url` 为 http(s)/data URL 时放行；本地路径（含
  `file://`）与文件工具同一套白名单校验。
- `terminal`：只放行 `python -m trade.osint …` / `trade osint …`（技能里唯一
  需要的命令）；含 shell 元字符（; & | < > ` $() 换行）的一律拒绝。
- `execute_code`：拒绝（技能不依赖，任意 Python 等于无沙箱）。

残留（未覆盖，如实记录）：`browser` 工具可能导航本地/下载文件；
未绑定公司的运行（如 Gateway 里的 cron）没有公司上下文，文件访问退化为
「所有活跃公司白名单目录的并集」—— 仍挡住系统路径，但无法区分公司。
守卫随插件加载而生效：插件未部署/未启用或旧版 Hermes 无 `register_hook`
时整套规则缺席，启动自检见 `trade.bootstrap.verify_tool_guard_ready`。
"""

from __future__ import annotations

import json
import os
import shlex
from datetime import datetime
from pathlib import Path

# 文件工具 → 路径参数名（都与 Hermes tools/file_tools.py 的 schema 一致）
_FILE_TOOLS = frozenset({"read_file", "write_file", "patch", "search_files"})

# 可写文件工具：对其额外做"高敏文件"判断（identity / prompts）
_WRITE_TOOLS = frozenset({"write_file", "patch"})

# vision_analyze 的 image_url 允许的远程形态；其余按本地路径处理
_REMOTE_IMAGE_PREFIXES = ("http://", "https://", "data:")

# 公司 identity 文件名（连字符是现行模板，下划线是历史写法）
_IDENTITY_FILENAMES = frozenset({"agent-identity.md", "agent_identity.md"})

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


# ── 宿主钩子能力标记 ─────────────────────────────────────────────────────
# 旧版 Hermes 的插件 ctx 没有 register_hook：插件照常加载，但守卫不会生效。
# 这件事只有插件运行在 Hermes 进程里时才知道，所以由插件落一个标记文件，
# Trade 侧读它来避免「部署+启用=ok」的误报。


def _hook_state_path() -> Path:
    from trade.post_install.skills import _get_trade_home

    return _get_trade_home() / "data" / "tool_guard.json"


def report_hook_support(supported: bool) -> None:
    """插件注册钩子时调用；写失败绝不影响插件加载。"""
    try:
        # 值没变就不重写（每次 agent 构造都会走到这里，避免无谓磁盘写入）
        if recorded_hook_support() == bool(supported):
            return
        path = _hook_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "hooks": bool(supported),
                    "at": datetime.now().isoformat(timespec="seconds"),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001 — 标记失败不能让插件加载失败
        pass


def recorded_hook_support() -> bool | None:
    """读取插件上次报告的钩子支持：True / False / None（还没加载过）。"""
    try:
        data = json.loads(_hook_state_path().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — 缺失/损坏都按"未知"处理
        return None
    value = data.get("hooks") if isinstance(data, dict) else None
    return value if isinstance(value, bool) else None


def _current_company_id() -> int | None:
    try:
        from trade.agent_context import current_company_id

        return current_company_id()
    except Exception:
        return None


def _allowed_roots(company_id: int | None) -> list[Path]:
    from trade.helpers import _allowed_path_roots

    if company_id:
        return _allowed_path_roots(company_id)

    # 未绑定公司（典型是 Gateway 里的 cron 任务）：允许**所有活跃公司**的白名单
    # 目录并集 —— 仍挡住 ~/.ssh、/etc 等任意路径，但不至于让定时文档任务全部失效。
    try:
        from trade.database import get_connection

        conn = get_connection()
        try:
            ids = [
                int(r[0]) for r in conn.execute(
                    "SELECT id FROM companies WHERE is_active = 1"
                ).fetchall()
            ]
        finally:
            conn.close()
    except Exception:
        return []
    roots: list[Path] = []
    for cid in ids:
        for root in _allowed_path_roots(cid):
            if root not in roots:
                roots.append(root)
    return roots


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


def _is_sensitive_write_target(path: Path, roots: list[Path]) -> bool:
    """白名单根内、但一旦可写就会变成持久化提示注入的文件。

    两类（都相对于公司 data_dir 根）：
      - `companies/{slug}/agent-identity.md`（运行时优先读入 system prompt）
      - `prompts/*.md`（公司级提示词目录）
    """
    for root in roots:
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        parts = [p.lower() for p in rel.parts]
        if len(parts) == 3 and parts[0] == "companies" and path.name.lower() in _IDENTITY_FILENAMES:
            return True
        if len(parts) == 2 and parts[0] == "prompts" and path.suffix.lower() == ".md":
            return True
    return False


def _check_vision_image(args: dict) -> dict | None:
    """`image_url` 允许远程/data URL；本地路径走同一套白名单校验。"""
    raw = args.get("image_url") or args.get("image_path") or args.get("path")
    if not isinstance(raw, str) or not raw.strip():
        return _block(
            "trade 工具守卫：vision_analyze 必须显式给 image_url（http(s)/data URL 或公司目录内的绝对路径）。"
        )
    target = raw.strip()
    if target.lower().startswith(_REMOTE_IMAGE_PREFIXES):
        return None
    if target.lower().startswith("file://"):
        from urllib.parse import unquote, urlparse

        target = unquote(urlparse(target).path)
        # Windows 的 file:///C:/x 会留下前导 "/C:"，还原成盘符形态
        if os.name == "nt" and len(target) > 2 and target[0] == "/" and target[2] == ":":
            target = target[1:]
    return _check_file_path("vision_analyze", {"path": target})


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
    if tool_name in _WRITE_TOOLS and _is_sensitive_write_target(resolved, roots):
        return _block(
            "trade 工具守卫：不允许改写公司身份文件或系统提示词"
            "（agent-identity.md / prompts/*.md）。"
            "身份与提示词的变更请通过 Trade 界面设置完成。"
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
    if tool_name == "vision_analyze":
        return _check_vision_image(args if isinstance(args, dict) else {})
    if tool_name == "terminal":
        return _check_terminal(args if isinstance(args, dict) else {})
    return None


def on_pre_tool_call(tool_name: str = "", args=None, **_kw) -> dict | None:
    """Hermes `pre_tool_call` 钩子入口；永不抛异常（抛异常会 fail-closed 且难排查）。"""
    try:
        return check_tool_call(tool_name, args if isinstance(args, dict) else {})
    except Exception:
        return _block("trade 工具守卫：内部异常，已拒绝本次工具调用。")
