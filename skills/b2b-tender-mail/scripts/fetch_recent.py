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

import _i18n_mail as _i18n  # noqa: E402
import tender_mail_core as core  # noqa: E402


def run_account(account: core.Account, days: int) -> dict[str, int]:
    """抓一个账号最近 N 天的邮件，返回统计。"""
    root = core.resolve_output_root(account)
    stats = {"询价": 0, "招标": 0, "未分类": 0, "附件": 0, "跳过": 0}

    conn = core.connect(account)
    try:
        since = datetime.now() - timedelta(days=days)
        uids = core.list_uids(conn, since)
        core.report_line("label.info", _i18n.t("fetched_since", name=account.name,
                                               date=f"{since:%Y-%m-%d}", count=len(uids)))

        for uid in uids:
            raw = core.fetch_raw(conn, uid)
            if not raw:
                continue
            parsed = core.parse_message(raw)

            reason = core.should_skip(parsed.sender, parsed.subject, account.blacklist)
            if reason:
                stats["跳过"] += 1
                core.report_line("label.skip", _i18n.t("skipped_message", uid=uid,
                                               subject=parsed.subject, reason=reason))
                continue

            saved = core.save_mail(root, parsed, uid, classify=True)
            stats["附件"] += len(parsed.attachments)
            category = core.classify_subject(parsed.subject) or "未分类"
            stats[category] = stats.get(category, 0) + 1
            core.report_line("label.saved", str(saved))
    finally:
        try:
            conn.logout()
        except Exception:
            pass

    core.report_line(
        "label.stats",
        _i18n.t("stats_line", name=account.name, rfq=stats["询价"],
                tender=stats["招标"], other=stats["未分类"],
                attachments=stats["附件"], skipped=stats["跳过"], root=root),
    )
    return stats


def main() -> int:
    """入口：读配置 → 逐账号抓取 → 打印统计。"""
    parser = argparse.ArgumentParser(description="近 N 天补抓招标/询价邮件")
    parser.add_argument("--config", default="mail_accounts.json", help="正式配置文件路径")
    parser.add_argument("--days", type=int, default=2, help="回看天数（默认 2）")
    parser.add_argument("--lang", choices=("zh", "en"), default=None,
                        help="输出语言（默认读 TRADE_LANG，否则中文）")
    args = parser.parse_args()
    _i18n.set_language(args.lang)

    accounts = core.load_config(args.config)
    if not accounts:
        core.main_hint()
        return 1

    runnable, skipped = core.select_runnable(accounts)
    for acc, reason in skipped:
        core.report_line("label.skipped_account", f"{acc.name}：{reason}")

    if not runnable:
        core.report_line("label.notice", _i18n.t("no_runnable"))
        return 1

    for account in runnable:
        try:
            run_account(account, args.days)
        except Exception as e:  # 单个账号失败不影响其它账号
            core.report_line("label.failed", _i18n.t("account_failed", name=account.name, error=e))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
