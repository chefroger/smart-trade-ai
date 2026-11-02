#!/usr/bin/env python3
"""给已归档但缺附件的邮件补附件（不重拉整批邮件）。

用法：
    python backfill_attachments.py --config mail_accounts.json [--root <落盘根目录>]

原理：
- 扫落盘目录里的 ``.txt``，读其中的 ``UID：`` 行；
- 如果同名 ``_附件/`` 目录不存在或为空，就按该 UID 用 BODY.PEEK 重新拉一次，
  只写附件，不重写邮件正文、不动已有文件；
- 附件仍按 MD5 去重。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tender_mail_core as core  # noqa: E402

_UID_RE = re.compile(r"^UID：\s*(\d+)\s*$", re.MULTILINE)


def find_missing(day_dir: Path) -> list[tuple[Path, int]]:
    """在日期目录里找出「有正文、但缺附件目录」的邮件。"""
    missing: list[tuple[Path, int]] = []
    for text_file in sorted(day_dir.glob("*.txt")):
        try:
            content = text_file.read_text(encoding="utf-8")
        except OSError:
            continue
        m = _UID_RE.search(content)
        if not m:
            continue
        att_dir = text_file.parent / f"{text_file.stem}_附件"
        if att_dir.is_dir() and any(att_dir.iterdir()):
            continue
        missing.append((text_file, int(m.group(1))))
    return missing


def run_account(account: core.Account, root: Path | None) -> int:
    """补一个账号的附件；返回补成功的邮件数。"""
    base = root or core.resolve_output_root(account)
    if not base.is_dir():
        core.report_line("提示", f"落盘目录不存在：{base}")
        return 0

    targets: list[tuple[Path, int]] = []
    for day_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        targets.extend(find_missing(day_dir))
    if not targets:
        core.report_line("日志", f"{account.name}：没有缺附件的邮件")
        return 0

    conn = core.connect(account)
    fixed = 0
    try:
        for text_file, uid in targets:
            raw = core.fetch_raw(conn, uid)
            if not raw:
                core.report_line("失败", f"UID {uid} 拉取为空（{text_file.name}）")
                continue
            parsed = core.parse_message(raw)
            if not parsed.attachments:
                core.report_line("留档", f"UID {uid} 原邮件本身没有附件（{text_file.name}）")
                continue

            att_dir = text_file.parent / f"{text_file.stem}_附件"
            att_dir.mkdir(parents=True, exist_ok=True)
            seen = core._existing_md5s(att_dir)
            added = 0
            for filename, data in parsed.attachments:
                digest = core.attachment_md5(data)
                if digest in seen:
                    continue
                out = core._unique_file(att_dir / core.safe_filename(filename or "附件"))
                out.write_bytes(data)
                seen[digest] = out
                added += 1
            if added:
                fixed += 1
                core.report_line("补附件", f"{att_dir}（新增 {added} 个）")
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return fixed


def main() -> int:
    """入口：逐账号补附件。"""
    parser = argparse.ArgumentParser(description="补招标邮件的缺失附件")
    parser.add_argument("--config", default="mail_accounts.json", help="正式配置文件路径")
    parser.add_argument("--root", default="", help="落盘根目录（缺省按配置解析）")
    args = parser.parse_args()

    accounts = core.load_config(args.config)
    if not accounts:
        core.main_hint()
        return 1

    root = Path(args.root).expanduser() if args.root else None
    runnable, skipped = core.select_runnable(accounts)
    for acc, reason in skipped:
        core.report_line("跳过账号", f"{acc.name}：{reason}")

    total = 0
    for account in runnable:
        try:
            total += run_account(account, root)
        except Exception as e:  # 单账号失败不影响其它账号
            core.report_line("失败", f"{account.name}：{e}")
    core.report_line("统计", f"本次补齐 {total} 封邮件的附件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
