"""邮箱 IMAP 只读接入：测通、游标拉取、正文处理与错误映射（标准库 only）。"""

from __future__ import annotations

import imaplib
import re
from datetime import UTC, datetime, timedelta
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any

# ==== 预设与常量 ====

PRESETS: dict[str, tuple[str, int]] = {
    "126": ("imap.126.com", 993),
    "163": ("imap.163.com", 993),
    "qq": ("imap.qq.com", 993),
    "gmail": ("imap.gmail.com", 993),
}

BODY_MAX = 5000
BODY_TRUNC_MARK = "…（正文过长，仅显示前 5000 字）"
SNIPPET_MAX = 200
FIRST_PULL_DAYS = 90
FIRST_PULL_LIMIT = 500

_INBOX = "INBOX"
_ID_ARG = '("name" "Trade")'


class MailboxError(Exception):
    """带小白可读 message 的邮箱错误。"""


# ==== 错误映射 ====


def map_imap_error(exc: BaseException) -> str:
    """将 IMAP/网络异常映射为可操作中文说明。"""
    text = str(exc).lower()
    # 535 / 鉴权失败：引导填授权码而非登录密码
    if "535" in text or "authentication" in text or "auth" in text and "fail" in text:
        return "密码栏要填邮箱的 16 位授权码，不是网页登录密码"
    # 超时：网络或地址
    if isinstance(exc, TimeoutError) or "timeout" in text or "timed out" in text:
        return "连接超时，请检查网络与 IMAP 服务器地址是否正确"
    # 未开 IMAP
    if "imap not enabled" in text or "imap disabled" in text or "未开启" in str(exc):
        return "该邮箱未开启 IMAP，请先在邮箱网页版设置里开启 IMAP 服务"
    return "邮箱连接失败，请检查地址、授权码与服务器设置"


# ==== 正文处理 ====


class _HTMLTextExtractor(HTMLParser):
    """简单 HTML→纯文本，保留块级与换行标签的断行。"""

    _BLOCK = frozenset({"p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"})

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        # br 与块级标签换行
        if t == "br":
            self._parts.append("\n")
        elif t in self._BLOCK:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._BLOCK:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        raw = "".join(self._parts)
        lines = [ln.strip() for ln in raw.splitlines()]
        return "\n".join(ln for ln in lines if ln)


def html_to_text(html: str) -> str:
    """HTML 去标签转纯文本，尽量保留换行。"""
    if not html:
        return ""
    parser = _HTMLTextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # 畸形 HTML：降级剥标签
        return re.sub(r"<[^>]+>", " ", html).strip()
    return parser.get_text()


def truncate_body(text: str) -> str:
    """正文超过 BODY_MAX 时截断并加固定标记。"""
    if len(text) <= BODY_MAX:
        return text
    return text[:BODY_MAX] + BODY_TRUNC_MARK


def _snippet_from_body(body: str) -> str:
    """摘要取正文前 SNIPPET_MAX 字符。"""
    compact = body.replace("\n", " ").strip()
    if len(compact) <= SNIPPET_MAX:
        return compact
    return compact[:SNIPPET_MAX]


def extract_body(msg: Message) -> str:
    """优先 text/plain；仅 HTML 则转纯文本；跳过附件。"""
    plain: str | None = None
    html: str | None = None

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", "")).lower()
            # 附件不解析正文
            if "attachment" in disp:
                continue
            if ctype == "text/plain" and plain is None:
                payload = part.get_payload(decode=True)
                if payload is not None:
                    plain = _decode_payload(part, payload)
            elif ctype == "text/html" and html is None:
                payload = part.get_payload(decode=True)
                if payload is not None:
                    html = _decode_payload(part, payload)
    else:
        ctype = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload is not None:
            decoded = _decode_payload(msg, payload)
            if ctype == "text/plain":
                plain = decoded
            elif ctype == "text/html":
                html = decoded

    if plain:
        return plain.strip()
    if html:
        return html_to_text(html)
    return ""


def _decode_payload(part: Message, payload: bytes) -> str:
    """按 charset 解码邮件分片。"""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _decode_mime_header(value: str | None) -> str:
    """解码主题等 MIME 编码头。"""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _parse_address_list(value: str | None) -> list[str]:
    """From/To 拆成地址列表（保留原始显示名解析后的邮箱串）。"""
    if not value:
        return []
    from email.utils import getaddresses

    return [addr for _name, addr in getaddresses([value]) if addr]


def _parse_received_at(msg: Message) -> str:
    """Date 头转 ISO 本地时间字符串；失败用当前 UTC。"""
    raw = msg.get("Date")
    if raw:
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone().replace(microsecond=0).isoformat()
        except Exception:
            pass
    return datetime.now(UTC).astimezone().replace(microsecond=0).isoformat()


def _message_id_from_headers(msg: Message, uidvalidity: int, uid: int) -> str:
    """Message-ID；缺失时用 X-GM-MSGID 或 uidvalidity:uid。"""
    mid = (msg.get("Message-ID") or "").strip()
    if mid:
        return mid
    gm = (msg.get("X-GM-MSGID") or "").strip()
    if gm:
        return f"gmail:{gm}"
    return f"{uidvalidity}:{uid}"


# ==== IMAP 连接 ====


def _send_imap_id(client: imaplib.IMAP4_SSL) -> None:
    """登录后发送 RFC2971 ID，自报 Trade（网易必需，其他厂商无害）。"""
    try:
        client._simple_command("ID", _ID_ARG)  # noqa: SLF001 — imaplib 无公开 ID API
    except Exception:
        # ID 失败不阻断测通/拉取（部分服务器不支持）
        pass


def _imap_connect(host: str, port: int, username: str, secret: str) -> imaplib.IMAP4_SSL:
    """建立 SSL 连接并登录，附带 ID。"""
    client = imaplib.IMAP4_SSL(host, int(port))
    client.login(username, secret)
    _send_imap_id(client)
    return client


def test_connection(host: str, port: int, username: str, secret: str) -> None:
    """连通并登录成功即返回；失败抛 MailboxError。"""
    client: imaplib.IMAP4_SSL | None = None
    try:
        client = _imap_connect(host, port, username, secret)
    except Exception as exc:
        raise MailboxError(map_imap_error(exc)) from exc
    finally:
        if client is not None:
            try:
                client.logout()
            except Exception:
                pass


def _uidvalidity(client: imaplib.IMAP4_SSL) -> int:
    """EXAMINE 后读取 UIDVALIDITY。"""
    typ, data = client.response("UIDVALIDITY")
    if typ != "OK" or not data:
        return 0
    val = data[0]
    if isinstance(val, bytes):
        val = val.decode("ascii", errors="replace")
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _parse_uid_search(data: list[bytes | None]) -> list[int]:
    """解析 UID SEARCH 响应为整数列表。"""
    if not data or data[0] is None:
        return []
    raw = data[0]
    if isinstance(raw, bytes):
        raw = raw.decode("ascii", errors="replace")
    uids: list[int] = []
    for token in str(raw).split():
        try:
            uids.append(int(token))
        except ValueError:
            continue
    return uids


def _fetch_uid_message(client: imaplib.IMAP4_SSL, uid: int) -> Message | None:
    """BODY.PEEK[] 拉取单封，不改 \\Seen。"""
    typ, data = client.uid("fetch", str(uid), "(BODY.PEEK[])")
    if typ != "OK" or not data or data[0] is None:
        return None
    part = data[0]
    if not isinstance(part, tuple) or len(part) < 2:
        return None
    raw = part[1]
    if isinstance(raw, dict):
        raw = raw.get(b"BODY[]") or raw.get(b"RFC822")
    if not isinstance(raw, (bytes, bytearray)):
        return None
    return message_from_bytes(bytes(raw))


def _row_str(row: dict[str, Any], key: str, default: str = "") -> str:
    v = row.get(key)
    return str(v) if v is not None else default


def fetch_new(mailbox_row: dict, secret: str) -> tuple[list[dict], dict]:
    """只读拉取新邮件；返回 (messages, cursor_update)。不写库。

    messages 含 message_id/from_addr/to_addrs/subject/snippet/body_text/received_at/uid。
    cursor_update 含 last_uidvalidity / last_uid（本轮见到的最大 UID）。
    """
    host = _row_str(mailbox_row, "host")
    port = int(mailbox_row.get("port") or 993)
    username = _row_str(mailbox_row, "username") or _row_str(mailbox_row, "email_address")
    last_uid = mailbox_row.get("last_uid")
    last_v = mailbox_row.get("last_uidvalidity")
    last_uid_i = int(last_uid) if last_uid is not None else None
    last_v_i = int(last_v) if last_v is not None else None

    client: imaplib.IMAP4_SSL | None = None
    messages: list[dict] = []
    max_uid = 0
    uidvalidity = 0

    try:
        client = _imap_connect(host, port, username, secret)
        typ, _data = client.examine(_INBOX)
        if typ != "OK":
            raise MailboxError("无法打开收件箱（只读）")
        uidvalidity = _uidvalidity(client)

        incremental = (
            last_uid_i is not None
            and last_v_i is not None
            and uidvalidity == last_v_i
        )

        if incremental:
            # 增量：UID > last_uid，升序拉取
            criteria = f"UID {last_uid_i + 1}:*"
            typ, data = client.uid("search", None, criteria)
            if typ != "OK":
                raise MailboxError("搜索新邮件失败")
            uids = sorted(_parse_uid_search(data))
        else:
            # 首拉或 UIDVALIDITY 变化：SINCE 90 天，UID 降序最多 500
            since = datetime.now(UTC) - timedelta(days=FIRST_PULL_DAYS)
            since_str = since.strftime("%d-%b-%Y")
            typ, data = client.uid("search", None, f"SINCE {since_str}")
            if typ != "OK":
                raise MailboxError("搜索邮件失败")
            uids = sorted(_parse_uid_search(data), reverse=True)[:FIRST_PULL_LIMIT]

        for uid in uids:
            msg = _fetch_uid_message(client, uid)
            if msg is None:
                continue
            body_raw = extract_body(msg)
            body_text = truncate_body(body_raw)
            record = {
                "message_id": _message_id_from_headers(msg, uidvalidity, uid),
                "from_addr": _decode_mime_header(msg.get("From")),
                "to_addrs": _parse_address_list(msg.get("To")),
                "subject": _decode_mime_header(msg.get("Subject")),
                "snippet": _snippet_from_body(body_raw),
                "body_text": body_text,
                "received_at": _parse_received_at(msg),
                "uid": uid,
            }
            messages.append(record)
            if uid > max_uid:
                max_uid = uid

        cursor_update = {
            "last_uidvalidity": uidvalidity,
            "last_uid": max_uid if max_uid else (last_uid_i or 0),
        }
        return messages, cursor_update
    except MailboxError:
        raise
    except Exception as exc:
        raise MailboxError(map_imap_error(exc)) from exc
    finally:
        if client is not None:
            try:
                client.logout()
            except Exception:
                pass
