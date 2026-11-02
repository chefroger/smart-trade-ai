"""中英双语的输出文案（本 skill 自带，不跨目录 import）。

为什么每个 skill 各带一份：Hermes 把每个 skill 目录**单独**同步到
`~/.hermes/skills/<name>/`，跨 skill 的 import 在用户机器上会直接失败。
所以这里刻意复制一份极小的实现，而不是做共享模块。

语言优先级：`--lang` > 环境变量 `TRADE_LANG` > 默认 `zh`。
"""

from __future__ import annotations

import os

_ZH = {
    # 报告行标签
    "label.info": "信息",
    "label.skip": "跳过",
    "label.saved": "落盘",
    "label.stats": "统计",
    "label.failed": "失败",
    "label.notice": "提示",
    "label.log": "日志",
    "label.kept": "留档",
    "label.attachments": "补附件",
    "label.skipped_account": "跳过账号",
    # 抓取
    "fetched_since": "{name}：{date} 之后共 {count} 封",
    "skipped_message": "UID {uid}「{subject}」—— {reason}",
    "stats_line": (
        "{name}：询价 {rfq} 封、招标 {tender} 封、未分类 {other} 封、"
        "附件 {attachments} 个、跳过 {skipped} 封；输出目录 {root}"
    ),
    "no_runnable": "没有可运行的账号（全部被跳过）",
    "account_failed": "{name}：{error}",
    # 监控
    "no_new_mail": "{name}：无新邮件",
    "batch_stats": "本次共落盘 {count} 封",
    # 补附件
    "root_missing": "落盘目录不存在：{path}",
    "no_missing_attachments": "{name}：没有缺附件的邮件",
    "fetch_empty": "UID {uid} 拉取为空（{file}）",
    "mail_has_no_attachment": "UID {uid} 原邮件本身没有附件（{file}）",
    "attachments_added": "{dir}（新增 {count} 个）",
    "backfill_stats": "本次补齐 {count} 封邮件的附件",
    # 归档正文的文件头
    "hdr_from": "发件人",
    "hdr_subject": "主题",
    "hdr_date": "日期",
    # 配置提示
    "config_hint": (
        "配置：把 mail_accounts.example.json 复制成 mail_accounts.json 并填写；"
        "落盘根目录可用环境变量 TENDER_MAIL_OUTPUT_DIR 覆盖。"
    ),
}

_EN = {
    "label.info": "Info",
    "label.skip": "Skipped",
    "label.saved": "Saved",
    "label.stats": "Summary",
    "label.failed": "Failed",
    "label.notice": "Notice",
    "label.log": "Log",
    "label.kept": "Note",
    "label.attachments": "Attachments",
    "label.skipped_account": "Account skipped",
    "fetched_since": "{name}: {count} message(s) since {date}",
    "skipped_message": "UID {uid} \"{subject}\" -- {reason}",
    "stats_line": (
        "{name}: RFQ {rfq}, tender {tender}, other {other}, "
        "attachments {attachments}, skipped {skipped}; output {root}"
    ),
    "no_runnable": "No usable account (all skipped)",
    "account_failed": "{name}: {error}",
    "no_new_mail": "{name}: no new mail",
    "batch_stats": "Saved {count} message(s) this run",
    "root_missing": "Output directory does not exist: {path}",
    "no_missing_attachments": "{name}: no mail missing attachments",
    "fetch_empty": "UID {uid} returned no content ({file})",
    "mail_has_no_attachment": "UID {uid} itself has no attachment ({file})",
    "attachments_added": "{dir} ({count} added)",
    "backfill_stats": "Attachments completed for {count} message(s)",
    "hdr_from": "From",
    "hdr_subject": "Subject",
    "hdr_date": "Date",
    "config_hint": (
        "Setup: copy mail_accounts.example.json to mail_accounts.json and fill it in; "
        "override the output root with TENDER_MAIL_OUTPUT_DIR."
    ),
}

_LANG = "zh"


def set_language(value: str | None) -> None:
    """设置输出语言（zh / en）。非法值忽略，保持原语言。"""
    global _LANG
    if value and str(value).lower() in ("zh", "en"):
        _LANG = str(value).lower()


def current_language() -> str:
    """当前语言（先看显式设置，再看 TRADE_LANG）。"""
    return _LANG if _LANG != "zh" else (os.environ.get("TRADE_LANG") or "zh").lower()


def t(key: str, **kw) -> str:
    """取一条文案并格式化；未知 key 原样返回，便于发现漏翻。"""
    table = _EN if current_language() == "en" else _ZH
    template = table.get(key) or _ZH.get(key) or key
    try:
        return template.format(**kw)
    except (KeyError, IndexError):
        return template
