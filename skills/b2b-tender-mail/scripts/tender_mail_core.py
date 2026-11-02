"""招标邮件抓取核心（纯 Python 标准库，无第三方依赖）。

供本目录三个入口脚本共用：

    fetch_recent.py           近 N 天按时间窗口补抓
    monitor_inbox.py          增量监控（定时任务用，无新邮件时静默）
    backfill_attachments.py   给已归档但缺附件的邮件补附件

设计约束（来自任务书）：
- **只读**：不发、不删、不移动邮件；拉取一律用 `BODY.PEEK`，连已读状态都不动。
- **增量**：状态文件记 last_check 与 last_uid；只取 UID 大于上次的。
- **配置外置**：账号与授权码只在用户自己复制的正式配置里，代码里只有占位符。
- **落盘根目录**：环境变量 > 配置文件 > 默认值；服务账户下不得用 `~` 解析桌面。
- **查重**：附件按 MD5 去重，同天同主题加 UID 后缀，正文内联小图不当附件。
"""

from __future__ import annotations

import hashlib
import imaplib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from pathlib import Path

# ── 常量与默认值 ──────────────────────────────────────────────────────────

#: 账号配置里缺省端口。IMAP over SSL 的标准端口。
DEFAULT_IMAP_PORT = 993

#: 落盘根目录的环境变量名（优先级最高）。
ENV_OUTPUT_ROOT = "TENDER_MAIL_OUTPUT_DIR"

#: 主题分类关键词 —— 只放通用词，不绑具体公司 / 平台 / 语言。
RFQ_KEYWORDS = ("询价", "报价请求", "rfq", "inquiry", "enquiry", "quotation request")
TENDER_KEYWORDS = ("招标", "投标", "tender", "bid", "rfp", "rfq-tender")

#: 默认黑名单（主题/发件人命中即跳过）。可被配置项覆盖。
#: 这些是「系统类噪音」，不是业务邮件；跳过必须在报告里说明，不当成漏抓。
DEFAULT_BLACKLIST = (
    "验证码",
    "安全提醒",
    "安全警告",
    "系统通知",
    "自动回复",
    "退信",
    "投递失败",
    "订阅",
    "unsubscribe",
    "no-reply",
    "noreply",
    "do-not-reply",
    "mailer-daemon",
    "postmaster",
    "verification code",
    "security alert",
    "auto-reply",
    "out of office",
    "delivery status notification",
)

#: 正文内联图片（签名、Logo）的识别特征。
INLINE_CONTENT_TYPES = ("image/png", "image/jpeg", "image/gif", "image/jpg")

#: 文件名里的非法字符（Windows 禁用的那组，加上路径分隔符）。
_ILLEGAL_NAME_CHARS = r'[<>:"/\\|?*\x00-\x1f]'


# ── 数据结构 ──────────────────────────────────────────────────────────────

@dataclass
class Account:
    """一个邮箱账号的 IMAP 配置。"""

    email: str
    imap_host: str
    imap_port: int
    auth_code: str
    output_dir: str = ""
    state_file: str = ""
    blacklist: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        """账号标识（日志里只打这个，不打授权码）。"""
        return self.email or self.imap_host


@dataclass
class ParsedMail:
    """一封邮件解析后的字段。"""

    sender: str
    subject: str
    date: datetime
    body: str
    attachments: list[tuple[str, bytes]]


# ── 配置加载 ──────────────────────────────────────────────────────────────

def load_config(path: str | Path) -> list[Account]:
    """读正式配置文件（用户从 .example.json 复制后填写）。

    结构：``{"accounts": [{email, imap_host, imap_port, auth_code,
    output_dir, state_file, blacklist?}]}``。
    文件不存在或 JSON 损坏时返回空列表 —— 由调用方明确打印「未配置」，
    不假装抓了。
    """
    p = Path(path).expanduser()
    if not p.is_file():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []

    accounts: list[Account] = []
    for item in raw.get("accounts", []):
        if not isinstance(item, dict):
            continue
        port = item.get("imap_port", DEFAULT_IMAP_PORT)
        try:
            port = int(port)
        except (TypeError, ValueError):
            port = DEFAULT_IMAP_PORT
        accounts.append(
            Account(
                email=str(item.get("email", "")).strip(),
                imap_host=str(item.get("imap_host", "")).strip(),
                imap_port=port,
                auth_code=str(item.get("auth_code", "")).strip(),
                output_dir=str(item.get("output_dir", "")).strip(),
                state_file=str(item.get("state_file", "")).strip(),
                blacklist=[str(x) for x in item.get("blacklist", [])],
            )
        )
    return accounts


def select_runnable(accounts: list[Account]) -> tuple[list[Account], list[tuple[Account, str]]]:
    """挑出可以跑的账号，其余连同跳过原因一起返回。

    授权码为空、缺 IMAP 主机、缺邮箱地址 → 跳过并**明确列出**。
    这是任务书探针 1 的一条：不能假装抓了。
    """
    runnable: list[Account] = []
    skipped: list[tuple[Account, str]] = []
    for acc in accounts:
        if not acc.email:
            skipped.append((acc, "缺 email"))
        elif not acc.imap_host:
            skipped.append((acc, "缺 imap_host"))
        elif not acc.auth_code:
            skipped.append((acc, "授权码为空"))
        else:
            runnable.append(acc)
    return runnable, skipped


# ── 落盘根目录解析 ────────────────────────────────────────────────────────

def default_output_root() -> Path:
    """默认落盘根目录：桌面。

    **服务账户下不能用 ``~`` 推断桌面**：系统服务 / 计划任务的用户目录可能
    不是当前登录用户的桌面，文件会写到看不见的地方。所以这里只在
    ``HOME`` 可用时返回，调用方必须自己判断；需要服务账户时请显式配置
    ``output_dir`` 或用环境变量。
    """
    home = os.environ.get("HOME") or os.environ.get("USERPROFILE")
    if not home:
        raise RuntimeError(
            "无法确定桌面路径（HOME/USERPROFILE 缺失）。"
            "请显式设置 output_dir 或环境变量 " + ENV_OUTPUT_ROOT
        )
    return Path(home) / "Desktop"


def resolve_output_root(account: Account) -> Path:
    """按「环境变量 > 配置文件 > 默认值」解析落盘根目录。"""
    env_root = os.environ.get(ENV_OUTPUT_ROOT, "").strip()
    if env_root:
        return Path(env_root).expanduser()
    if account.output_dir.strip():
        return Path(account.output_dir).expanduser()
    return default_output_root()


# ── 主题与分类 ────────────────────────────────────────────────────────────

def safe_filename(name: str) -> str:
    """替换文件名非法字符（Windows 禁用字符 + 路径分隔符）。"""
    cleaned = re.sub(_ILLEGAL_NAME_CHARS, "_", name).strip(" .")
    return cleaned or "未命名"


def normalize_subject(subject: str) -> str:
    """主题归一化：去回复/转发前缀、折叠空白、限长。

    只做展示与命名用途，不改原文字段。
    """
    text = decode_mime_header(subject or "")
    text = re.sub(r"^\s*((re|fw|fwd|回复|转发)\s*[:：]\s*)+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:120] or "无主题"


def classify_subject(subject: str) -> str | None:
    """按主题关键词分「询价 / 招标」，无命中返回 None。

    只用通用词；具体公司名、平台名、语言专属词一律不写。
    """
    low = (subject or "").lower()
    if any(k in low for k in RFQ_KEYWORDS):
        return "询价"
    if any(k in low for k in TENDER_KEYWORDS):
        return "招标"
    return None


def should_skip(sender: str, subject: str, blacklist: list[str] | None = None) -> str | None:
    """黑名单判断：命中返回原因（用于报告），未命中返回 None。

    匹配发件人与主题，大小写不敏感。黑名单可由账号配置覆盖。
    """
    rules = blacklist if blacklist else list(DEFAULT_BLACKLIST)
    haystack = f"{sender}\n{subject}".lower()
    for rule in rules:
        if rule and rule.lower() in haystack:
            return f"命中黑名单：{rule}"
    return None


# ── 增量 ──────────────────────────────────────────────────────────────────

def load_state(path: str | Path) -> dict:
    """读状态文件；不存在或损坏时返回空 dict（视为首次运行）。"""
    p = Path(path).expanduser()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(path: str | Path, last_check: datetime, last_uid: int) -> None:
    """写状态文件（last_check 与 last_uid）。"""
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {"last_check": last_check.strftime("%Y-%m-%dT%H:%M:%S"), "last_uid": int(last_uid)},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def filter_new_uids(uids: list[int], last_uid: int) -> list[int]:
    """只保留 UID 大于上次的，且升序。

    探针 1：状态 last_uid=100 时，UID ≤100 不重复抓，>100 才抓。
    """
    return sorted(u for u in uids if u > int(last_uid))


def since_date(last_check: datetime | None, now: datetime | None = None) -> datetime:
    """计算 SINCE 日期：首次运行回看最近 24 小时；之后从上次检查日期起。"""
    now = now or datetime.now()
    if last_check is None:
        return now - timedelta(days=1)
    # 留一天余量：跨时区的服务端可能比本地晚一天
    return last_check - timedelta(days=1)


# ── IMAP 拉取（只读） ─────────────────────────────────────────────────────

def fetch_raw(conn, uid: int) -> bytes:
    """按 UID 拉整封邮件原文，**不置已读标志**。

    用 ``BODY.PEEK[]`` 而不是 ``RFC822``：不少 IMAP 服务端会把后者标成已读。
    探针 2 直接断言这条命令含 PEEK 语义。
    """
    status, data = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
    if status != "OK":
        raise RuntimeError(f"UID {uid} 拉取失败：{status}")
    for item in data:
        if isinstance(item, tuple) and len(item) >= 2:
            return item[1]
    return b""


def list_uids(conn, since: datetime) -> list[int]:
    """列出收件箱里 SINCE 指定日期之后的 UID（升序、整数）。"""
    date_str = since.strftime("%d-%b-%Y")
    status, data = conn.uid("SEARCH", None, f'(SINCE {date_str})')
    if status != "OK":
        return []
    uids: list[int] = []
    for chunk in data:
        if not chunk:
            continue
        for token in chunk.split():
            try:
                uids.append(int(token))
            except (TypeError, ValueError):
                continue
    return sorted(uids)


# ── 解析 ──────────────────────────────────────────────────────────────────

def decode_mime_header(value: str | None) -> str:
    """解码 MIME 编码的头部（中文/其它非 ASCII 主题、发件人）。"""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except (UnicodeDecodeError, LookupError):
        return value


def _part_text(part: Message) -> str:
    """取文本部件内容，解码失败时退回宽松解码。"""
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def is_inline_image(part: Message) -> bool:
    """判断部件是不是正文内联小图（签名 / Logo）。

    判定：Content-Type 为图片，且（Content-ID 存在 或 disposition=inline）。
    真正的业务附件通常是 attachment 且没有 Content-ID。
    """
    ctype = (part.get_content_type() or "").lower()
    if ctype not in INLINE_CONTENT_TYPES:
        return False
    has_cid = bool(part.get("Content-ID"))
    disposition = (part.get_content_disposition() or "").lower()
    return has_cid or disposition == "inline"


def parse_message(raw: bytes) -> ParsedMail:
    """解析邮件原文：发件人、主题、日期、正文文本、附件。"""
    msg = message_from_bytes(raw)

    sender = decode_mime_header(msg.get("From"))
    subject = decode_mime_header(msg.get("Subject"))
    date = _parse_date(msg.get("Date"))

    body_chunks: list[str] = []
    attachments: list[tuple[str, bytes]] = []

    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            disposition = (part.get_content_disposition() or "").lower()
            filename = decode_mime_header(part.get_filename())
            if filename and disposition == "attachment":
                payload = part.get_payload(decode=True) or b""
                attachments.append((filename, payload))
                continue
            # 内联图片（签名/Logo）不进附件目录
            if is_inline_image(part):
                continue
            if (part.get_content_type() or "").startswith("text/") and disposition != "attachment":
                body_chunks.append(_part_text(part))
    else:
        if (msg.get_content_type() or "").startswith("text/"):
            body_chunks.append(_part_text(msg))

    return ParsedMail(
        sender=sender,
        subject=subject,
        date=date,
        body="\n".join(c for c in body_chunks if c.strip()),
        attachments=attachments,
    )


def _parse_date(value: str | None) -> datetime:
    """解析邮件 Date 头；无法解析时用当前时间（不因此丢邮件）。"""
    from email.utils import parsedate_to_datetime

    if value:
        try:
            dt = parsedate_to_datetime(value)
            if dt is not None:
                return dt.replace(tzinfo=None)
        except (TypeError, ValueError):
            pass
    return datetime.now()


# ── 落盘 ──────────────────────────────────────────────────────────────────

def attachment_md5(data: bytes) -> str:
    """附件内容 MD5（去重键）。"""
    return hashlib.md5(data).hexdigest()


def _existing_md5s(directory: Path) -> dict[str, Path]:
    """扫描目录里已有附件的 MD5 → 路径映射。"""
    result: dict[str, Path] = {}
    if not directory.is_dir():
        return result
    for f in directory.iterdir():
        if f.is_file():
            try:
                result[attachment_md5(f.read_bytes())] = f
            except OSError:
                continue
    return result


def _unique_file(base: Path, suffix: str = "") -> Path:
    """同名文件冲突时追加序号（``name(2).ext``）。"""
    if not base.exists():
        return base
    stem, ext = base.stem, base.suffix
    i = 2
    while True:
        candidate = base.with_name(f"{stem}{suffix}({i}){ext}")
        if not candidate.exists():
            return candidate
        i += 1


def save_mail(
    root: Path,
    parsed: ParsedMail,
    uid: int,
    *,
    classify: bool = False,
) -> Path:
    """把一封邮件按 ``<日期>/<日期>_<主题>.txt`` 落盘，附件放同名 ``_附件/``。

    规则（任务书）：
      - 同天同主题冲突 → 文件名加 ``_<UID>``，不互相覆盖；
      - 附件按 MD5 去重，同内容只留一份；
      - 正文内联小图已在解析阶段排除。

    classify=True 时按「询价 / 招标」分子目录（近 N 天补抓用）。
    """
    day = parsed.date.strftime("%Y-%m-%d")
    subject = safe_filename(normalize_subject(parsed.subject))

    target_root = root
    if classify:
        category = classify_subject(parsed.subject)
        if category:
            target_root = root / category

    day_dir = target_root / day
    day_dir.mkdir(parents=True, exist_ok=True)

    base_name = f"{day}_{subject}"
    text_path = day_dir / f"{base_name}.txt"
    if text_path.exists():
        # 同天同主题：第二封加 UID 后缀
        text_path = day_dir / f"{base_name}_{uid}.txt"
    text_path = _unique_file(text_path)

    text_path.write_text(
        "\n".join(
            [
                f"发件人：{parsed.sender}",
                f"主题：{parsed.subject}",
                f"日期：{parsed.date.strftime('%Y-%m-%d %H:%M:%S')}",
                f"UID：{uid}",
                "",
                parsed.body,
            ]
        ),
        encoding="utf-8",
    )

    if parsed.attachments:
        att_dir = day_dir / f"{text_path.stem}_附件"
        att_dir.mkdir(parents=True, exist_ok=True)
        seen = _existing_md5s(att_dir)
        for filename, data in parsed.attachments:
            digest = attachment_md5(data)
            if digest in seen:
                continue  # 同内容只留一份
            name = safe_filename(filename or "附件")
            out = _unique_file(att_dir / name)
            out.write_bytes(data)
            seen[digest] = out

    return text_path


# ── IMAP 连接 ─────────────────────────────────────────────────────────────

def connect(account: Account):
    """连接并选中收件箱（只读模式）。失败抛出异常，由调用方记录后跳过该账号。"""
    conn = imaplib.IMAP4_SSL(account.imap_host, account.imap_port)
    conn.login(account.email, account.auth_code)
    # readonly=True：连「已读」标志都不动
    conn.select("INBOX", readonly=True)
    return conn


def state_path_for(account: Account) -> Path:
    """状态文件路径：配置优先，否则落在配置目录旁的 ``<email>.state.json``。"""
    if account.state_file.strip():
        return Path(account.state_file).expanduser()
    root = resolve_output_root(account)
    return root / ".tender-mail-state" / f"{safe_filename(account.email)}.state.json"


def report_line(kind: str, text: str) -> None:
    """统一的一行报告输出。"""
    print(f"[{kind}] {text}")


def main_hint() -> None:
    """三个入口脚本共用的一句提示。"""
    print(
        "配置：把 mail_accounts.example.json 复制成 mail_accounts.json 并填写；"
        f"落盘根目录可用环境变量 {ENV_OUTPUT_ROOT} 覆盖。",
        file=sys.stderr,
    )
