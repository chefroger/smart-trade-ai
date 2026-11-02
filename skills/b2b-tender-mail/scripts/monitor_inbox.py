#!/usr/bin/env python3
"""增量监控收件箱（定时任务用）。

用法：
    python monitor_inbox.py --config mail_accounts.json

行为：
- 只取 UID 大于状态文件里 last_uid 的邮件；
- 无新邮件时**静默**（只记一条日志，不打扰用户）；
- 有新业务邮件时落盘并打印摘要；
- 拉取用 BODY.PEEK，不改已读状态。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _i18n_mail as _i18n  # noqa: E402
import tender_mail_core as core  # noqa: E402


def run_account(account: core.Account) -> int:
    """跑一次增量；返回本次落盘的邮件数。"""
    state_file = core.state_path_for(account)
    state = core.load_state(state_file)
    last_uid = int(state.get("last_uid", 0) or 0)
    last_check = _parse_state_time(state.get("last_check"))

    root = core.resolve_output_root(account)
    conn = core.connect(account)
    saved_count = 0
    try:
        since = core.since_date(last_check)
        uids = core.filter_new_uids(core.list_uids(conn, since), last_uid)
        if not uids:
            core.report_line("label.log", _i18n.t("no_new_mail", name=account.name))
            return 0

        for uid in uids:
            raw = core.fetch_raw(conn, uid)
            if not raw:
                continue
            parsed = core.parse_message(raw)

            reason = core.should_skip(parsed.sender, parsed.subject, account.blacklist)
            if reason:
                core.report_line("label.skip", _i18n.t("skipped_message", uid=uid,
                                                       subject=parsed.subject, reason=reason))
                last_uid = max(last_uid, uid)
                continue

            saved = core.save_mail(root, parsed, uid)
            saved_count += 1
            core.report_line("label.saved", str(saved))
            last_uid = max(last_uid, uid)

        core.save_state(state_file, datetime.now(), last_uid)
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return saved_count


def _parse_state_time(value) -> datetime | None:
    """解析状态文件里的 last_check；缺失或格式不对按首次运行处理。"""
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def main() -> int:
    """入口：逐账号跑一次增量。"""
    parser = argparse.ArgumentParser(description="增量监控收件箱")
    parser.add_argument("--config", default="mail_accounts.json", help="正式配置文件路径")
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

    total = 0
    for account in runnable:
        try:
            total += run_account(account)
        except Exception as e:  # 单账号失败不影响其它账号，也不让定时任务报错退出
            core.report_line("label.failed", _i18n.t("account_failed", name=account.name, error=e))
    if total:
        core.report_line("label.stats", _i18n.t("batch_stats", count=total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
