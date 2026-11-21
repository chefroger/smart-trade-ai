"""`python -m trade.osint <目标>` / `trade osint <目标>` —— 6 层背调的机器判定入口。

## 为什么需要它（2026-10-14 修）

skill 提示词原先写的是"**调用 domain_whois(域名)**""调用 check_sanctions(公司名)"
这类**裸函数名** —— 而它们都不是 agent 的工具（agent 只有 Hermes 那套工具）。
模型没有确定的执行方式，只能自己想办法（用 execute_code 拼 import）或干脆
凭搜索印象组织结论。确定性管线 `osint_full_check()` 更是**全仓库无调用者**：
没有 API 端点、前端不调、CLI 也没有 —— 于是"6 层检测"在线上从未按设计跑过。

把整条管线包成一个**可执行的命令**后，提示词才能给出确定的执行方式：

    python -m trade.osint acme.com            # 人读的报告
    python -m trade.osint someone@acme.com --json   # 结构化（给程序/模型用）

命令在 Trade 自己的 venv 里跑（`python` 即该 venv 的解释器），跨平台一致，
不依赖 PATH 上有没有 `trade` 这个 console script。
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from trade.console import reconfigure_streams
from trade.osint.orchestrator import osint_full_check

_USAGE = (
    "用法：python -m trade.osint <邮箱|域名|公司名> "
    "[--json] [--progress] [--budget=150] [--target=<目标>] "
    "[--no-sanctions] [--no-tech-stack] [--no-linkedin]\n"
    "  --target=  显式指定目标（公司名含空格时可直接写，不必加引号）\n"
    "  --budget=  全局时间预算（秒，默认 150）\n"
    "  --progress 向 stderr 逐层输出 JSONL 进度事件"
)


def format_report(report: dict[str, Any]) -> str:
    """把 osint_full_check 的返回渲染成终端可读报告。

    各层的"降级/跳过/未执行"都**如实标注**（沿用管线自己的诚实降级约定）——
    报告里不许出现"看起来查过、其实没查"的表述。
    """
    lines: list[str] = []
    lines.append(f"══ 背调报告：{report.get('target', '')}（类型：{report.get('target_type', '?')}）══")
    # 未完成核验时分数为 None：必须显示「—」，不能落到 0/100 或沿用旧分数
    score = report.get("overall_score")
    score_text = f"{score}/100" if isinstance(score, int) else "—（未完成核验）"
    lines.append(
        f"综合评分：{score_text} ｜ 风险等级：{report.get('overall_rating', 'unknown')}"
    )
    flags = report.get("flags") or []
    lines.append("风险旗标：" + ("、".join(flags) if flags else "无"))

    # 制裁名单抓取时间与过期提醒（P0-1：coverage 每份名单都带 fetched_at）
    sanctions_cov = ((report.get("layers") or {}).get("sanctions") or {}).get("coverage") or {}
    for code, info in (sanctions_cov.get("lists") or {}).items():
        if info.get("stale_hours"):
            lines.append(f"⚠ 制裁名单过期：{info.get('label', code)}（{info['stale_hours']} 小时未更新）")

    # 未核验 / 未查渠道：关键层缺失直接影响结论，必须写在报告头部
    for u in report.get("unverified") or []:
        if u.get("required"):
            lines.append(f"⚠ 未核验：{u.get('label', u.get('layer'))} —— {u.get('reason', '')}")
        elif u.get("status") == "skipped":
            lines.append(f"未查（已关闭）：{u.get('label', u.get('layer'))}")

    layers = report.get("layers") or {}

    # ① 邮箱注册检测（holehe）
    er = layers.get("email_registration")
    if er is None:
        lines.append("\n① 邮箱注册检测：未执行（目标不是邮箱）")
    elif er.get("timed_out"):
        lines.append(f"\n① 邮箱注册检测：超时 —— {er['error']}")
    elif er.get("error"):
        lines.append(f"\n① 邮箱注册检测：降级 —— {er['error']}")
    else:
        lines.append(
            f"\n① 邮箱注册检测：查了 {er.get('checked_count', 0)} 个平台，"
            f"命中 {er.get('found_count', 0)} 个"
        )
        for r in (er.get("results") or [])[:10]:
            if r.get("exists"):
                lines.append(f"    · {r.get('site_display') or r.get('site')}：已注册")

    # ② 域名情报（WHOIS）
    di = layers.get("domain_intel") or {}
    if di.get("skipped"):
        lines.append(f"\n② 域名情报：跳过（{di.get('reason', '')}）")
    elif di.get("timed_out"):
        lines.append(f"\n② 域名情报：超时 —— {di['error']}")
    elif di.get("error"):
        lines.append(f"\n② 域名情报：降级 —— {di['error']}")
    elif di:
        lines.append(
            f"\n② 域名情报：{di.get('domain', '')} ｜ 已注册={di.get('registered')} "
            f"｜ 创建={di.get('creation_date')} ｜ 年龄={di.get('days_old')} 天"
            f"（{di.get('age_category') or '未知'}）"
        )
    else:
        lines.append("\n② 域名情报：未执行（无法从目标提取域名）")

    # ③ 企业邮箱验证
    ev = layers.get("email_verification")
    if ev is None:
        lines.append("\n③ 企业邮箱验证：未执行（目标不是邮箱）")
    elif ev.get("timed_out"):
        lines.append(f"\n③ 企业邮箱验证：超时 —— {ev.get('error', '')}")
    else:
        tail = f"（MX 查询未成：{ev['mx_error']}）" if ev.get("mx_error") else ""
        lines.append(
            f"\n③ 企业邮箱验证：个人邮箱={ev.get('is_personal')} ｜ MX={ev.get('mx_found')}{tail}"
        )
        for f in ev.get("risk_flags") or []:
            lines.append(f"    · 红旗：{f}")

    # ④ 技术栈检测
    ts = layers.get("tech_stack")
    if ts is None:
        lines.append("\n④ 技术栈检测：未执行")
    elif ts.get("timed_out"):
        lines.append(f"\n④ 技术栈检测：超时 —— {ts['error']}")
    elif ts.get("error"):
        lines.append(f"\n④ 技术栈检测：降级 —— {ts['error']}")
    else:
        techs = "、".join(ts.get("technologies") or []) or "未检出"
        lines.append(
            f"\n④ 技术栈检测：{techs}"
            f"\n    免费建站平台={ts.get('is_free_platform')} ｜ 企业级={ts.get('is_enterprise')} "
            f"｜ SSL={ts.get('ssl_valid')} ｜ 服务器={ts.get('server')}"
        )

    # ⑤ 制裁名单筛查
    sa = layers.get("sanctions")
    if sa is None:
        lines.append("\n⑤ 制裁名单筛查：未执行")
    else:
        cov = sa.get("coverage") or {}
        note = ""
        if sa.get("timed_out"):
            # 超时不是「查了没有」，必须写清楚本次未完成比对
            note = f" ｜ ⏱ {sa.get('error', '超时')}，本次未完成比对"
        elif cov.get("degraded"):
            note = f" ｜ ⚠ 降级：名单尚未成功下载（本地 {cov.get('total_entries', 0)} 条）"
        elif cov.get("total_entries"):
            note = f" ｜ 覆盖 {cov['total_entries']} 条"
        lines.append(
            f"\n⑤ 制裁名单筛查：命中={sa.get('is_sanctioned')} ｜ 风险={sa.get('risk_level')}{note}"
        )
        for hit in (sa.get("hits") or [])[:5]:
            lines.append(
                f"    · {hit.get('list_label') or hit.get('list')}：{hit.get('matched_value')}"
                f"（{hit.get('matched_field')}，置信 {hit.get('score')}）"
            )

    # ⑥ LinkedIn 核查（只生成指令，需浏览器执行）
    li = layers.get("linkedin")
    if li is None:
        lines.append("\n⑥ LinkedIn 核查：未执行")
    else:
        lines.append("\n⑥ LinkedIn 核查：已生成浏览器操作指令（**需人工/浏览器实际执行后才能下结论**）：")
        for s in li.get("steps") or []:
            lines.append(f"    · {s.get('url')}")

    recs = report.get("recommendations") or []
    if recs:
        lines.append("\n建议：")
        lines.extend(f"  {r}" for r in recs)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """命令入口，返回退出码。argv 缺省取 sys.argv[1:]。"""
    # 报告里有 ⚠/✗/① 等符号，Windows 管道（cp936/cp1252）下要先降级编码错误 ——
    # 否则会崩在"已经查完之后"，agent 只看到 UnicodeEncodeError，白跑一次。
    reconfigure_streams()
    args = list(sys.argv[1:] if argv is None else argv)
    opts: set[str] = set()
    targets: list[str] = []
    target_opt: str | None = None
    budget = 150.0

    for arg in args:
        if arg.startswith("--target="):
            # --target=Acme Corp（带空格的公司名）走显式目标
            target_opt = arg.split("=", 1)[1].strip()
        elif arg.startswith("--budget="):
            raw = arg.split("=", 1)[1].strip()
            try:
                budget = float(raw)
            except ValueError:
                print(f"✗ --budget 需要数字（收到 {raw!r}）。\n{_USAGE}")
                return 2
            if budget <= 0:
                print(f"✗ --budget 必须大于 0（收到 {budget}）。\n{_USAGE}")
                return 2
        elif arg.startswith("--"):
            opts.add(arg)
        else:
            targets.append(arg)

    if target_opt is not None:
        # 同时给 --target 和位置参数 → 目标不明确
        if targets:
            print(f"✗ --target 与位置参数不能同时使用。\n{_USAGE}")
            return 2
        targets = [target_opt]

    if not targets or not targets[0]:
        print(_USAGE)
        return 2
    if len(targets) > 1:
        print(f"✗ 一次只接受一个目标（收到 {len(targets)} 个）。\n{_USAGE}")
        return 2

    # --progress：逐层 JSONL 写到 stderr，stdout 的报告格式保持不变
    def _emit_progress(event: dict) -> None:
        print(json.dumps(event, ensure_ascii=False), file=sys.stderr, flush=True)

    try:
        report = asyncio.run(osint_full_check(
            targets[0],
            include_sanctions="--no-sanctions" not in opts,
            include_tech_stack="--no-tech-stack" not in opts,
            include_linkedin="--no-linkedin" not in opts,
            budget=budget,
            on_event=_emit_progress if "--progress" in opts else None,
        ))
    except Exception as e:  # 管线内部各层已各自兜底；这里只兜"整条起不来"
        print(f"✗ 背调执行失败：{type(e).__name__}: {e}")
        return 1

    # --json 给程序/模型消费；默认给人读
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str) if "--json" in opts
          else format_report(report))
    return 0
