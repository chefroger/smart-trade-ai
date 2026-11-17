"""IMAP 只读接入层测试：全程 mock imaplib，禁止连真服。"""

from __future__ import annotations

import socket
import sys
import threading
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade import mailbox as mb

FAKE_USER = "u@example.com"
FAKE_SECRET = "sixteencharscode"


# ==== 常量与预设 ====


def test_presets_contain_four_providers():
    """预设含 126/163/qq/gmail，端口均为 993。"""
    for key, host in (
        ("126", "imap.126.com"),
        ("163", "imap.163.com"),
        ("qq", "imap.qq.com"),
        ("gmail", "imap.gmail.com"),
    ):
        assert key in mb.PRESETS
        h, port = mb.PRESETS[key]
        assert h == host
        assert port == 993


# ==== 错误映射 ====


def test_map_imap_error_auth_535():
    """535 / Authentication failed → 授权码文案。"""
    msg = mb.map_imap_error(Exception("AUTHENTICATION failed 535"))
    assert "授权码" in msg
    msg2 = mb.map_imap_error(Exception("535 5.7.8"))
    assert "授权码" in msg2


def test_map_imap_error_timeout():
    """连接超时 → 网络检查文案。"""
    msg = mb.map_imap_error(TimeoutError("timed out"))
    assert "网络" in msg
    msg2 = mb.map_imap_error(Exception("connection timeout"))
    assert "网络" in msg2


def test_map_imap_error_imap_not_enabled():
    """未开启 IMAP → 引导去网页版开启。"""
    msg = mb.map_imap_error(Exception("IMAP not enabled for this account"))
    assert "开启" in msg and "IMAP" in msg


# ==== 正文处理 ====


def test_truncate_body_over_limit():
    """超过 5000 字截断并加固定标记。"""
    body = "x" * 5001
    out = mb.truncate_body(body)
    assert out.endswith(mb.BODY_TRUNC_MARK)
    assert len(out) == mb.BODY_MAX + len(mb.BODY_TRUNC_MARK)
    assert out.startswith("x" * mb.BODY_MAX)


def test_truncate_body_under_limit_unchanged():
    short = "hello"
    assert mb.truncate_body(short) == short


def test_html_to_text_keeps_breaks_and_content():
    """HTML 转纯文本保留换行与正文。"""
    text = mb.html_to_text("<p>hello<br>world</p>")
    assert "hello" in text
    assert "world" in text
    assert "hello" in text and "world" in text
    # br 应产生换行或至少两行语义分隔
    assert "\n" in text or text.replace("hello", "").replace("world", "").strip()


def test_extract_body_prefers_plain():
    """multipart 优先 text/plain。"""
    msg = EmailMessage()
    msg["Subject"] = "s"
    msg.set_content("plain body")
    msg.add_alternative("<p>html</p>", subtype="html")
    assert mb.extract_body(msg) == "plain body"


def test_extract_body_html_fallback():
    """仅 HTML 时去标签转文本。"""
    msg = EmailMessage()
    msg.set_content("<b>hi</b>", subtype="html")
    body = mb.extract_body(msg)
    assert "hi" in body


# ==== test_connection ====


@patch("trade.mailbox.imaplib.IMAP4_SSL")
def test_test_connection_login_id_logout(mock_ssl):
    """测通路径：login → ID → logout；建连带 socket 超时。"""
    import imaplib

    client = MagicMock()
    mock_ssl.return_value = client
    client.login.return_value = ("OK", [b"Logged in"])

    mb.test_connection("imap.126.com", 993, FAKE_USER, FAKE_SECRET)

    mock_ssl.assert_called_once_with(
        "imap.126.com", 993, timeout=mb.IMAP_SOCKET_TIMEOUT_SEC
    )
    client.login.assert_called_once_with(FAKE_USER, FAKE_SECRET)
    # 必须注册 ID，否则网易 SELECT 会 Unsafe Login
    assert "ID" in imaplib.Commands
    client._simple_command.assert_any_call(
        "ID", '("name" "Trade" "version" "1.0" "vendor" "smart-trade-ai")'
    )
    client.logout.assert_called_once()


def test_send_imap_id_registers_command():
    """_send_imap_id 把 ID 注册进 imaplib.Commands，避免 KeyError 被静默吞掉。"""
    import imaplib

    imaplib.Commands.pop("ID", None)
    client = MagicMock()
    client._simple_command.return_value = ("OK", [b"ID completed"])
    mb._send_imap_id(client)
    assert imaplib.Commands.get("ID") == ("AUTH",)
    client._simple_command.assert_called_once_with("ID", mb._ID_ARG)


@patch("trade.mailbox.imaplib.IMAP4_SSL")
def test_test_connection_auth_fail_raises_mailbox_error(mock_ssl):
    """登录失败抛 MailboxError，含可映射小白文案。"""
    client = MagicMock()
    mock_ssl.return_value = client
    client.login.side_effect = Exception("535 Authentication failed")

    with pytest.raises(mb.MailboxError) as exc_info:
        mb.test_connection("imap.qq.com", 993, FAKE_USER, FAKE_SECRET)

    assert "授权码" in str(exc_info.value)


# ==== fetch_new ====


def _make_raw_email(
    *,
    subject: str = "Test",
    from_addr: str = "sender@example.com",
    to_addr: str = "u@example.com",
    body: str = "body text",
    message_id: str = "<mid@test>",
) -> bytes:
    """构造最小 RFC822 字节串供 mock fetch 返回。"""
    msg = EmailMessage()
    msg["Message-ID"] = message_id
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = "Mon, 16 Nov 2026 10:00:00 +0800"
    msg.set_content(body)
    return msg.as_bytes()


def _patch_imap_client(mock_ssl, uidvalidity: bytes = b"42"):
    """通用 IMAP mock：login、ID、select(readonly)、真实形态 UIDVALIDITY。"""
    client = MagicMock()
    mock_ssl.return_value = client
    client.login.return_value = ("OK", [b""])
    client.select.return_value = ("OK", [b"1"])
    # 真实 imaplib：response("UIDVALIDITY") → ("UIDVALIDITY", [b"n"])
    client.response.side_effect = lambda key: (
        ("UIDVALIDITY", [uidvalidity]) if key == "UIDVALIDITY" else ("NO", [None])
    )
    return client


def test_fetch_new_uses_real_imaplib_methods():
    """所调 imaplib 方法必须在真实 IMAP4 上存在（防 mock 自带 examine 掩盖）。"""
    import imaplib

    for name in ("select", "uid", "response", "login", "logout"):
        assert hasattr(imaplib.IMAP4, name), f"IMAP4 缺少 {name}"
    assert not hasattr(imaplib.IMAP4, "examine"), "不得依赖不存在的 examine()"


@patch("trade.mailbox.imaplib.IMAP4_SSL")
def test_fetch_new_first_pull_since_90d_uid_desc_limit_500(mock_ssl):
    """无游标首拉：SINCE 90 天、UID 降序最多 500，返回游标更新。"""
    client = _patch_imap_client(mock_ssl)

    def uid_side_effect(cmd, *args):
        if cmd == "search":
            return ("OK", [b"100 101 102"])
        if cmd == "fetch":
            uid_arg = args[-1] if args else ""
            uid_num = uid_arg.split()[0] if uid_arg else "100"
            return (
                "OK",
                [
                    (
                        uid_num.encode(),
                        {b"RFC822": _make_raw_email(message_id=f"<m{uid_num}>")},
                    )
                ],
            )
        return ("NO", [None])

    client.uid.side_effect = uid_side_effect

    row = {
        "host": "imap.126.com",
        "port": 993,
        "username": FAKE_USER,
        "last_uid": None,
        "last_uidvalidity": None,
    }
    messages, cursor = mb.fetch_new(row, FAKE_SECRET)

    client.select.assert_called_with("INBOX", readonly=True)
    search_calls = [c for c in client.uid.call_args_list if c[0][0] == "search"]
    assert search_calls, "应执行 SEARCH"
    search_arg = " ".join(str(a) for a in search_calls[0][0][1:] if a is not None)
    assert "SINCE" in search_arg.upper()
    # O-5：英文月份，不含中文
    assert not any("\u4e00" <= ch <= "\u9fff" for ch in search_arg)

    assert len(messages) <= mb.FIRST_PULL_LIMIT
    assert cursor["last_uidvalidity"] == 42
    assert cursor["last_uid"] == 102
    assert cursor["truncated"] is False
    assert cursor["is_first_pull"] is True
    assert messages[0]["uid"] == 102  # 降序，最大 UID 先处理
    assert "message_id" in messages[0]
    assert "body_text" in messages[0]
    assert "snippet" in messages[0]


@patch("trade.mailbox.imaplib.IMAP4_SSL")
def test_fetch_new_incremental_uid_gt_last(mock_ssl):
    """有游标增量：SEARCH UID > last_uid。"""
    client = _patch_imap_client(mock_ssl, uidvalidity=b"99")

    def uid_side_effect(cmd, *args):
        if cmd == "search":
            joined = " ".join(str(a) for a in args if a is not None)
            assert "101" in joined or "100:101" in joined.replace(",", ":")
            return ("OK", [b"101"])
        if cmd == "fetch":
            return (
                "OK",
                [
                    (
                        b"101",
                        {b"RFC822": _make_raw_email(message_id="<new>", body="new mail")},
                    )
                ],
            )
        return ("NO", [None])

    client.uid.side_effect = uid_side_effect

    row = {
        "host": "imap.163.com",
        "port": 993,
        "username": FAKE_USER,
        "last_uid": 100,
        "last_uidvalidity": 99,
    }
    messages, cursor = mb.fetch_new(row, FAKE_SECRET)

    search_calls = [c for c in client.uid.call_args_list if c[0][0] == "search"]
    assert search_calls
    # 增量不应再用 SINCE 全量首拉
    search_parts = search_calls[0][0][1:]
    search_str = " ".join(str(p) for p in search_parts if p is not None).upper()
    assert "101" in search_str
    assert len(messages) == 1
    assert messages[0]["uid"] == 101
    assert cursor["last_uid"] == 101
    assert cursor["is_first_pull"] is False


@patch("trade.mailbox.imaplib.IMAP4_SSL")
def test_fetch_new_uidvalidity_change_full_rescan(mock_ssl):
    """UIDVALIDITY 变化时走首拉（SINCE），不走增量。"""
    client = _patch_imap_client(mock_ssl, uidvalidity=b"200")

    def uid_side_effect(cmd, *args):
        if cmd == "search":
            joined = " ".join(str(a) for a in args if a is not None).upper()
            assert "SINCE" in joined
            return ("OK", [b"5"])
        if cmd == "fetch":
            return (
                "OK",
                [(b"5", {b"RFC822": _make_raw_email(message_id="<uv>")})],
            )
        return ("NO", [None])

    client.uid.side_effect = uid_side_effect
    row = {
        "host": "imap.qq.com",
        "port": 993,
        "username": FAKE_USER,
        "last_uid": 100,
        "last_uidvalidity": 99,  # 与服务器 200 不同
    }
    messages, cursor = mb.fetch_new(row, FAKE_SECRET)
    assert cursor["last_uidvalidity"] == 200
    assert cursor["is_first_pull"] is True
    assert len(messages) == 1


@patch("trade.mailbox.imaplib.IMAP4_SSL")
def test_fetch_new_first_pull_truncated_flag(mock_ssl, monkeypatch):
    """首拉 UID 数 ≥ FIRST_PULL_LIMIT 时 truncated=True（用小上限加速）。"""
    monkeypatch.setattr(mb, "FIRST_PULL_LIMIT", 3)
    client = _patch_imap_client(mock_ssl)
    uid_list = b"1 2 3 4 5"

    def uid_side_effect(cmd, *args):
        if cmd == "search":
            return ("OK", [uid_list])
        if cmd == "fetch":
            uid_num = str(args[0]) if args else "1"
            return (
                "OK",
                [(uid_num.encode(), {b"RFC822": _make_raw_email(message_id=f"<t{uid_num}>")})],
            )
        return ("NO", [None])

    client.uid.side_effect = uid_side_effect
    row = {
        "host": "imap.126.com",
        "port": 993,
        "username": FAKE_USER,
        "last_uid": None,
        "last_uidvalidity": None,
    }
    messages, cursor = mb.fetch_new(row, FAKE_SECRET)
    assert cursor["truncated"] is True
    assert cursor["is_first_pull"] is True
    assert len(messages) == 3


def test_uidvalidity_parses_real_imaplib_shape():
    """_uidvalidity 接受真实形态 ('UIDVALIDITY', [b'n'])。"""
    client = MagicMock()
    client.response.return_value = ("UIDVALIDITY", [b"98765"])
    assert mb._uidvalidity(client) == 98765


def test_imap_since_date_english_month():
    """SINCE 日期用英文月份，不依赖 locale。"""
    from datetime import datetime

    s = mb._imap_since_date(datetime(2026, 11, 17))
    assert s == "17-Nov-2026"


# ==== 假 IMAP 服务器 + 真实 imaplib（非 MagicMock）====


class _FakeImapServer:
    """最小 IMAP 会话：LOGIN / ID / SELECT / UID SEARCH / UID FETCH / LOGOUT。"""

    def __init__(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.port = self._sock.getsockname()[1]
        self._thread: threading.Thread | None = None
        self._raw = _make_raw_email(message_id="<fake-real@test>", body="hello-real")

    def start(self) -> None:
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def _serve(self) -> None:
        try:
            conn, _addr = self._sock.accept()
        except OSError:
            return
        with conn:
            # greeting 带 CAPABILITY，避免客户端立刻发 CAPABILITY 命令卡死
            conn.sendall(b"* OK [CAPABILITY IMAP4rev1 AUTH=PLAIN] Fake IMAP ready\r\n")
            buf = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\r\n" in buf:
                    line, buf = buf.split(b"\r\n", 1)
                    text = line.decode("ascii", errors="replace")
                    parts = text.split(" ", 2)
                    if len(parts) < 2:
                        continue
                    tag, cmd = parts[0], parts[1].upper()
                    rest = parts[2] if len(parts) > 2 else ""
                    if cmd == "CAPABILITY":
                        conn.sendall(b"* CAPABILITY IMAP4rev1 AUTH=PLAIN\r\n")
                        conn.sendall(f"{tag} OK CAPABILITY completed\r\n".encode())
                    elif cmd == "LOGIN":
                        conn.sendall(f"{tag} OK LOGIN completed\r\n".encode())
                    elif cmd == "ID":
                        conn.sendall(f"{tag} OK ID completed\r\n".encode())
                    elif cmd in ("SELECT", "EXAMINE"):
                        # select(readonly=True) 实际发协议动词 EXAMINE
                        conn.sendall(b"* 1 EXISTS\r\n")
                        conn.sendall(b"* OK [UIDVALIDITY 98765] UIDs valid\r\n")
                        conn.sendall(
                            f"{tag} OK [UIDVALIDITY 98765] {cmd} completed\r\n".encode()
                        )
                    elif cmd == "UID" and rest.upper().startswith("SEARCH"):
                        conn.sendall(b"* SEARCH 7\r\n")
                        conn.sendall(f"{tag} OK UID SEARCH completed\r\n".encode())
                    elif cmd == "UID" and rest.upper().startswith("FETCH"):
                        # BODY.PEEK[] 字面量
                        payload = self._raw
                        conn.sendall(
                            b"* 1 FETCH (UID 7 BODY[] {%d}\r\n" % len(payload)
                        )
                        conn.sendall(payload)
                        conn.sendall(b")\r\n")
                        conn.sendall(f"{tag} OK UID FETCH completed\r\n".encode())
                    elif cmd in ("LOGOUT", "CLOSE"):
                        conn.sendall(b"* BYE\r\n")
                        conn.sendall(f"{tag} OK LOGOUT\r\n".encode())
                        return
                    else:
                        conn.sendall(f"{tag} OK {cmd}\r\n".encode())


def test_fetch_new_against_real_imaplib_fake_server(monkeypatch):
    """假服务器 + 真实 imaplib.IMAP4：select/UIDVALIDITY/拉取通路。"""
    import imaplib

    server = _FakeImapServer()
    server.start()

    def _plain_connect(host, port, username, secret):
        # 不用 SSL：假服务器是明文；仍走真实 imaplib 协议解析
        client = imaplib.IMAP4(host, int(port), timeout=mb.IMAP_SOCKET_TIMEOUT_SEC)
        client.login(username, secret)
        mb._send_imap_id(client)
        return client

    monkeypatch.setattr(mb, "_imap_connect", _plain_connect)
    try:
        row = {
            "host": "127.0.0.1",
            "port": server.port,
            "username": FAKE_USER,
            "last_uid": None,
            "last_uidvalidity": None,
        }
        messages, cursor = mb.fetch_new(row, FAKE_SECRET)
    finally:
        server.close()

    assert cursor["last_uidvalidity"] == 98765
    assert cursor["last_uid"] == 7
    assert len(messages) == 1
    assert messages[0]["body_text"].strip() == "hello-real"
    assert messages[0]["message_id"] == "<fake-real@test>"
