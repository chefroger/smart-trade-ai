#!/usr/bin/env python3
"""近 N 天按时间窗口补抓招标/询价邮件（查漏用）。

用法：
    python fetch_recent.py --config mail_accounts.json --days 2

行为：
- 按主题关键词分成「询价 / 招标」两类，各自落盘（分类只影响目录，不丢邮件）；
- 打印分类统计（询价几封、招标几封、附件几个、输出目录）；
- 不动已读状态、不发不删不移邮件。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 允许从任意目录运行（脚本由定时任务调用时 cwd 不确定）
sys.path.insert(0, str(Path(__file__).resolve().parent))

import tender_mail_core as core  # noqa: E402


def run_account(account: core.Account, days: int) -> dict[str, int]:
    """抓一个账号最近 N 天的邮件，返回统计。"""
    root = core.resolve_output_root(account)
    stats = {"询价": 0, "招标": 0, "未分类": 0, "附件": 0, "跳过": 0}

    conn = core.connect(account)
    try:
        since = datetime.now() - timedelta(days=days)
        uids = core.list_uids(conn, since)
        core.report_line("信息", f"{account.name}：{since:%Y-%m-%d} 之后共 {len(uids)} 封")

        for uid in uids:
            raw = core.fetch_raw(conn, uid)
            if not raw:
                continue
            parsed = core.parse_message(raw)

            reason = core.should_skip(parsed.sender, parsed.subject, account.blacklist)
            if reason:
                stats["跳过"] += 1
                core.report_line("跳过", f"UID {uid}「{parsed.subject}」—— {reason}")
                continue

            saved = core.save_mail(root, parsed, uid, classify=True)
            stats["附件"] += len(parsed.attachments)
            category = core.classify_subject(parsed.subject) or "未分类"
            stats[category] = stats.get(category, 0) + 1
            core.report_line("落盘", f"{saved}")
    finally:
        try:
            conn.logout()
        except Exception:
            pass

    core.report_line(
        "统计",
        f"{account.name}：询价 {stats['询价']} 封、招标 {stats['招标']} 封、"
        f"未分类 {stats['未分类']} 封、附件 {stats['附件']} 个、跳过 {stats['跳过']} 封；"
        f"输出目录 {root}",
    )
    return stats


def main() -> int:
    """入口：读配置 → 逐账号抓取 → 打印统计。"""
    parser = argparse.ArgumentParser(description="近 N 天补抓招标/询价邮件")
    parser.add_argument("--config", default="mail_accounts.json", help="正式配置文件路径")
    parser.add_argument("--days", type=int, default=2, help="回看天数（默认 2）")
    args = parser.parse_args()

    accounts = core.load_config(args.config)
    if not accounts:
        core.main_hint()
        return 1

    runnable, skipped = core.select_runnable(accounts)
    for acc, reason in skipped:
        core.report_line("跳过账号", f"{acc.name}：{reason}")

    if not runnable:
        core.report_line("提示", "没有可运行的账号（全部被跳过）")
        return 1

    for account in runnable:
        try:
            run_account(account, args.days)
        except Exception as e:  # 单个账号失败不影响其它账号
            core.report_line("失败", f"{account.name}：{e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
