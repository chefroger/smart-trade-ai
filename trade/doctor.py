"""`trade doctor` —— 安装后的端到端自检。

## 为什么需要（这台产品上踩过的坑都指向同一件事）

有三次故障都是"安装验证全过、第一次真实使用才炸"，而且报错指不出真因：

1. **Hermes 懒加载重启**：`import run_agent` 连带把进程 re-exec 到 Hermes 自带的
   Python（无 trade 包）→ `RelaunchExit(SystemExit)` → agent 线程静默死亡。
   `import` 层面的检查全都通过。
2. **Tavily 静默失败**：SSL 被拦时 web_search 每次失败但只写 warning，
   报告照常输出，用户以为搜过了。
3. **vision 工具根本不在场**：`DEFAULT_ENABLED_TOOLSETS` 漏了 `vision`，
   模型没有任何看图工具 —— 而 `check_vision_requirements()` 返回 True
   （那是能力门控，不是"工具在不在"）。

所以这里的原则是：**能发真实请求就发真实请求**，不做"配置看起来对"的检查。
特别是 vision，必须让配置好的模型真读一张图并回出预期文字 —— 只有这样才能
同时覆盖"工具有没有"和"模型能不能看"。

## 为什么不"让 Hermes 自查"

本项目已出现过模型编造自己执行记录的情况（会话 #84 声称"没有任何 OCR 组件参与"
并引用代码注释当证据）。让模型自省它自己的能力不可靠，所以这里是**确定性脚本**：
直接调 Hermes 的接口去验，不问模型"你能看图吗"。
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

# ── 数据模型 ──────────────────────────────────────────────────────────────

STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"


@dataclass
class CheckResult:
    """单项检查结果。

    Attributes:
        fatal: True 表示这一项失败时**应当阻断安装** —— 只给"Trade 根本用不了"
               的项，例如 agent 构造不出来、数据库不可写。降级项（搜索、记忆）
               一律 fatal=False：功能打折但仍可用，不该挡着人用。
    """

    name: str
    status: str
    detail: str
    fatal: bool = False

    @property
    def passed(self) -> bool:
        return self.status == STATUS_OK


# ── 检查 1：Hermes 运行环境 ───────────────────────────────────────────────

def check_hermes_runtime(*, agent_factory=None) -> list[CheckResult]:
    """Hermes 版本在窗口内，且 agent 真的能构造出来。

    构造 agent 是这里最关键的检查 —— 客户机上的 RelaunchExit 事故就发生在这一步，
    而任何"只看 import"的检查都发现不了。
    """
    out: list[CheckResult] = []

    try:
        from trade.bootstrap import _MAX_HERMES_VERSION, _MIN_HERMES_VERSION
        from trade.hermes_compat import hermes_version

        ver = hermes_version()
        if not ver:
            out.append(CheckResult(
                "Hermes 版本", STATUS_WARN,
                "识别不到版本（无安装印章时上游会报占位值），跳过窗口检查",
            ))
        else:
            from packaging.version import Version

            in_window = Version(_MIN_HERMES_VERSION) <= Version(ver) < Version(_MAX_HERMES_VERSION)
            out.append(CheckResult(
                "Hermes 版本", STATUS_OK if in_window else STATUS_FAIL,
                f"{ver}（要求 >={_MIN_HERMES_VERSION},<{_MAX_HERMES_VERSION}）",
                fatal=not in_window,
            ))
    except Exception as e:
        out.append(CheckResult("Hermes 版本", STATUS_WARN, f"检查失败：{e}"))

    try:
        factory = agent_factory
        if factory is None:
            from trade.helpers import create_agent

            factory = create_agent
        agent = factory()
        cls = f"{type(agent).__module__}.{type(agent).__name__}"
        out.append(CheckResult("Agent 构造", STATUS_OK, cls))
    except BaseException as e:
        # 捕 BaseException：RelaunchExit 继承 SystemExit，`except Exception` 抓不到 ——
        # 而那正是客户机上真实发生过的那种失败。
        out.append(CheckResult(
            "Agent 构造", STATUS_FAIL,
            f"{type(e).__name__}: {e}",
            fatal=True,
        ))

    return out


# ── 检查 2：原生 vision ───────────────────────────────────────────────────

VISION_PROBE_TEXT = "VISION-OK-{token}"


def _make_probe_image(text: str) -> bytes:
    """用 PyMuPDF 渲染一张含指定文字的 PNG（不引入 Pillow）。"""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=420, height=140)
    page.insert_text((30, 80), text, fontsize=34)
    pix = page.get_pixmap(dpi=110)
    data = pix.tobytes("png")
    doc.close()
    return data


def check_vision(*, tool_list_provider=None, vision_prober=None) -> list[CheckResult]:
    """两段检查：工具在不在场 + 模型能不能真读出来。

    分开是必要的：工具在场不代表模型能看（provider/模型不支持多模态），
    模型能看也不代表 Hermes 会把工具交给它（toolset 没启用）——
    历史上这两个洞各踩过一次。
    """
    out: list[CheckResult] = []

    # 2a. 工具表（静态，零成本）—— 抓"vision toolset 没启用"
    try:
        provider = tool_list_provider
        if provider is None:
            provider = _agent_tool_names
        names = provider()
        has = "vision_analyze" in names
        out.append(CheckResult(
            "vision 工具在场", STATUS_OK if has else STATUS_FAIL,
            "vision_analyze 在工具表中" if has else (
                f"工具表里没有 vision_analyze（共 {len(names)} 个工具）—— "
                "检查 trade/helpers.py 的 DEFAULT_ENABLED_TOOLSETS 是否含 vision"
            ),
            fatal=not has,
        ))
    except Exception as e:
        out.append(CheckResult("vision 工具在场", STATUS_WARN, f"检查失败：{e}"))

    # 2b. 真读一张图（端到端）—— 抓"模型其实看不见"
    token = f"{random.randint(1000, 9999)}"
    expected = VISION_PROBE_TEXT.format(token=token)
    try:
        prober = vision_prober
        if prober is None:
            prober = _probe_vision_live
        ok, detail = prober(expected)
        out.append(CheckResult(
            "vision 读图", STATUS_OK if ok else STATUS_FAIL,
            detail,
            # 模型读不了图 → 图片类需求全废，但纯文字仍可用。按降级处理。
            fatal=False,
        ))
    except Exception as e:
        out.append(CheckResult("vision 读图", STATUS_WARN, f"探测失败：{e}"))

    return out


def _agent_tool_names() -> list[str]:
    """构造一次 agent 并取出它的工具名列表。"""
    from trade.helpers import create_agent

    agent = create_agent()
    tools = getattr(agent, "tools", None) or getattr(agent, "tool_definitions", None)
    if isinstance(tools, dict):
        return sorted(tools.keys())
    if isinstance(tools, list):
        names = set()
        for t in tools:
            if isinstance(t, dict):
                fn = t.get("function") or t
                if fn.get("name"):
                    names.add(fn["name"])
        return sorted(names)
    return []


def _probe_vision_live(expected_text: str) -> tuple[bool, str]:
    """直接给配置好的模型发一张含 `expected_text` 的图，看它能否读出来。

    走 provider 的原生多模态接口（与 Hermes 的 native 通道同一套线格式），
    比让 agent 跑一整轮工具调用便宜得多，而结论一样硬。
    """
    import base64

    from trade.helpers import get_agent_kwargs

    kwargs = get_agent_kwargs()
    provider, model = kwargs.get("provider"), kwargs.get("model")
    api_key = kwargs.get("api_key")
    base_url = kwargs.get("base_url") or None
    if not (provider and model and api_key):
        return False, "provider/model/api_key 未配置完整，无法探测"

    png = _make_probe_image(expected_text)
    b64 = base64.b64encode(png).decode()

    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)
    resp = client.chat.completions.create(
        model=model,
        # 400 而不是 60：推理模型（deepseek-flash）会用掉一部分预算做推理，
        # 给 60 时实测正文为空且 finish_reason=length —— 预算全被推理吃光。
        max_tokens=400,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "只回复图片里的那行文字，不要任何其它内容。"},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }],
    )
    choice = resp.choices[0]
    return _judge_vision_response(
        expected_text,
        choice.message.content or "",
        choice.finish_reason or "",
        model=model,
    )


def _judge_vision_response(
    expected_text: str, content: str, finish_reason: str, *, model: str = ""
) -> tuple[bool, str]:
    """判定探测结果。拆成纯函数是为了可测，也为了让措辞可被断言。

    真机踩到的坑：deepseek-flash 是**推理模型**，`max_tokens` 给小了会被
    推理过程吃光预算，正文为空且 `finish_reason="length"` —— 看起来像
    "模型看不见图"，其实是预算不足。这两种原因的排查方向完全不同，
    不能混成一句"未读出"。
    """
    text = content.strip()
    if expected_text in text:
        return True, f"{model} 正确读出探测文字".strip()
    if not text and finish_reason == "length":
        return False, (
            "模型未给出正文：token 预算被推理过程占满（finish_reason=length）。"
            "这是探测参数问题，不代表模型看不见图"
        )
    return False, f"{model} 未读出探测文字（返回：{text[:60]!r}）".strip()


# ── 检查 3：Tavily 搜索 ───────────────────────────────────────────────────

def check_tavily(*, searcher=None) -> list[CheckResult]:
    """Tavily key 存在，且**真能搜出结果**。

    只查 key 存在是不够的 —— 本机实测过 SSL 被拦时每次搜索都失败却只写 warning，
    用户以为搜过了。所以这里必须发一次真实搜索。
    """
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not key:
        return [CheckResult(
            "Tavily 搜索", STATUS_WARN,
            "未配置 TAVILY_API_KEY（不注册也能用，但联网搜索与客户背调质量会下降）",
        )]

    try:
        search = searcher or _probe_tavily_live
        ok, detail = search(key)
        return [CheckResult("Tavily 搜索", STATUS_OK if ok else STATUS_WARN, detail)]
    except Exception as e:
        return [CheckResult("Tavily 搜索", STATUS_WARN, f"探测失败：{e}")]


def _probe_tavily_live(api_key: str) -> tuple[bool, str]:
    """发一次最小搜索请求，确认真的能拿到结果。"""
    base = os.environ.get("TAVILY_BASE_URL", "https://api.tavily.com").rstrip("/")
    req = urllib.request.Request(
        f"{base}/search",
        data=json.dumps({"api_key": api_key, "query": "test", "max_results": 1}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    n = len(payload.get("results") or [])
    if n:
        return True, "搜索可用"
    return False, "接口有响应但没有返回结果"


# ── 检查 4：Trade 自身 ────────────────────────────────────────────────────

def check_trade(*, chat_prober=None, db_prober=None) -> list[CheckResult]:
    """数据库可写 + 走一次真实对话回合。

    真实对话是这套自检里最值钱的一项：客户机上那次故障的表现就是"聊天空回复"，
    而所有静态检查（/api/status、providers、面板能开）当时都是通过的。
    """
    out: list[CheckResult] = []

    try:
        prober = db_prober or _probe_db
        ok, detail = prober()
        out.append(CheckResult("数据库", STATUS_OK if ok else STATUS_FAIL, detail, fatal=not ok))
    except Exception as e:
        out.append(CheckResult("数据库", STATUS_FAIL, f"{type(e).__name__}: {e}", fatal=True))

    try:
        chat = chat_prober or _probe_chat_live
        ok, detail = chat()
        out.append(CheckResult(
            "对话回合", STATUS_OK if ok else STATUS_FAIL, detail, fatal=not ok,
        ))
    except BaseException as e:
        out.append(CheckResult(
            "对话回合", STATUS_FAIL, f"{type(e).__name__}: {e}", fatal=True,
        ))

    return out


def _probe_db() -> tuple[bool, str]:
    """确认数据库可读写。

    **只在库文件不存在时才 init_db()**：init_db 会做一次迁移前备份
    （打印 "Database backed up"），而无条件调用等于每跑一次自检就多一个备份文件。
    自检是诊断工具，不该产生这种副作用。
    """
    from trade.database import get_connection, init_db
    from trade.post_install.skills import _get_trade_home

    if not (_get_trade_home() / "data" / "trade.db").is_file():
        init_db()  # 全新环境：先把库建起来

    conn = get_connection()
    try:
        conn.execute("SELECT 1").fetchone()
    finally:
        conn.close()
    return True, "可读写"


def _probe_chat_live() -> tuple[bool, str]:
    """走一次真实 agent 回合 —— 空回复即失败。"""
    from trade.helpers import create_agent

    agent = create_agent()
    start = time.time()
    reply = agent.chat("请只回复两个字：正常")
    elapsed = time.time() - start
    if reply and str(reply).strip():
        return True, f"收到回复（{elapsed:.1f}s）"
    return False, "agent 返回空回复 —— 这正是客户机上那种「Agent 未返回有效回复」的表现"


# ── 编排、持久化、报告 ────────────────────────────────────────────────────

def run_doctor(*, deep: bool = True) -> list[CheckResult]:
    """跑全部检查。deep=False 时跳过所有真实请求（快检，零 token）。"""
    results: list[CheckResult] = []
    results += check_hermes_runtime()
    if deep:
        results += check_vision()
        results += check_tavily()
        results += check_trade()
    else:
        try:
            names = _agent_tool_names()
            results.append(CheckResult(
                "vision 工具在场",
                STATUS_OK if "vision_analyze" in names else STATUS_FAIL,
                "vision_analyze 在工具表中" if "vision_analyze" in names else "工具表缺少 vision_analyze",
                fatal="vision_analyze" not in names,
            ))
        except Exception as e:
            results.append(CheckResult("vision 工具在场", STATUS_WARN, f"检查失败：{e}"))
    return results


def has_fatal_failure(results: list[CheckResult]) -> bool:
    """是否存在应阻断安装的失败。"""
    return any(r.fatal and r.status == STATUS_FAIL for r in results)


def format_report(results: list[CheckResult]) -> str:
    """人类可读的自检报告。

    汇总分三档，措辞与用户动作一一对应：
      - **致命失败** → Trade 无法正常使用，必须先修
      - **非致命失败** → 该功能不可用（如读不了图），要修但不挡着用
      - **降级** → 功能打折（如没配搜索），可忽略
    历史 bug：原实现只统计 fatal 与 warn，**非致命的 FAIL 两边都不算**，
    于是落到 else 说"全部通过" —— 真机跑出来时明明有 ✗。
    """
    icon = {STATUS_OK: "✓", STATUS_WARN: "⚠", STATUS_FAIL: "✗"}
    lines = ["", "══ Trade 自检 ══"]
    for r in results:
        lines.append(f"  {icon.get(r.status, '?')} {r.name}: {r.detail}")

    failed = [r for r in results if r.status == STATUS_FAIL]
    fatal = [r for r in failed if r.fatal]
    non_fatal = [r for r in failed if not r.fatal]
    warn = [r for r in results if r.status == STATUS_WARN]

    lines.append("")
    if fatal:
        lines.append(
            f"  ✗ {len(fatal)} 项致命问题，Trade 无法正常使用 —— "
            f"请先按上面的提示修复：{'、'.join(r.name for r in fatal)}"
        )
    if non_fatal:
        lines.append(
            f"  ✗ {len(non_fatal)} 项功能不可用（不影响基本使用）："
            f"{'、'.join(r.name for r in non_fatal)}"
        )
    if warn:
        lines.append(f"  ⚠ {len(warn)} 项降级（功能打折但可用）")
    if not (fatal or non_fatal or warn):
        lines.append("  ✓ 全部通过")
    return "\n".join(lines)


# ── 何时跑（首次跑；未过则重试） ──────────────────────────────────────────

def _state_file() -> Path:
    from trade.post_install.skills import _get_trade_home

    return _get_trade_home() / "data" / "doctor.json"


def _fingerprint() -> str:
    """配置指纹：provider/model/Trade 版本任一变化都应重跑自检。"""
    parts = []
    try:
        from trade.helpers import get_agent_kwargs

        kw = get_agent_kwargs()
        parts += [str(kw.get("provider") or ""), str(kw.get("model") or "")]
    except Exception:
        parts.append("unknown")
    try:
        from trade.app import _running_code_version

        parts.append(str(_running_code_version() or ""))
    except Exception:
        pass
    return "|".join(parts)


def should_run_doctor() -> bool:
    """没有记录、上次未过、或配置变了 → 该跑。

    未过时**每次启动都重试**：客户改完配置重启就自动恢复，不用记得手动跑。
    """
    path = _state_file()
    if not path.is_file():
        return True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return True
    if not data.get("passed"):
        return True
    return data.get("fingerprint") != _fingerprint()


def save_doctor_result(results: list[CheckResult], *, deep: bool = True) -> None:
    """落盘自检结果（供下次启动判断是否需要重跑，也供 /api/status 展示）。"""
    path = _state_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        passed = not any(r.status != STATUS_OK for r in results)
        path.write_text(json.dumps({
            "passed": passed,
            "deep": deep,
            "at": datetime.now().isoformat(timespec="seconds"),
            "fingerprint": _fingerprint(),
            "results": [asdict(r) for r in results],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass  # 自检结果落盘失败不该影响任何主流程


def load_doctor_result() -> dict | None:
    """读上次的自检结果（给 /api/status 与前端用）。"""
    path = _state_file()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
