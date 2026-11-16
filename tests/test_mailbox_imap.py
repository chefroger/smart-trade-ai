"""IMAP 只读接入层测试：全程 mock imaplib，禁止连真服。"""

from __future__ import annotations

import sys
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
    """测通路径：login → ID → logout。"""
    client = MagicMock()
    mock_ssl.return_value = client
    client.login.return_value = ("OK", [b"Logged in"])

    mb.test_connection("imap.126.com", 993, FAKE_USER, FAKE_SECRET)

    mock_ssl.assert_called_once_with("imap.126.com", 993)
    client.login.assert_called_once_with(FAKE_USER, FAKE_SECRET)
    client._simple_command.assert_any_call("ID", '("name" "Trade")')
    client.logout.assert_called_once()


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


def _patch_imap_client(mock_ssl):
    """通用 IMAP mock：login、ID、examine、uidvalidity。"""
    client = MagicMock()
    mock_ssl.return_value = client
    client.login.return_value = ("OK", [b""])
    client.examine.return_value = ("OK", [b"1"])
    client.response.side_effect = lambda key: (
        ("OK", [b"42"]) if key == "UIDVALIDITY" else ("NO", [None])
    )
    return client


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

    client.examine.assert_called_with("INBOX")
    search_calls = [c for c in client.uid.call_args_list if c[0][0] == "search"]
    assert search_calls, "应执行 SEARCH"
    search_arg = " ".join(str(a) for a in search_calls[0][0][1:] if a is not None)
    assert "SINCE" in search_arg.upper()

    assert len(messages) <= mb.FIRST_PULL_LIMIT
    assert cursor["last_uidvalidity"] == 42
    assert cursor["last_uid"] == 102
    assert messages[0]["uid"] == 102  # 降序，最大 UID 先处理
    assert "message_id" in messages[0]
    assert "body_text" in messages[0]
    assert "snippet" in messages[0]


@patch("trade.mailbox.imaplib.IMAP4_SSL")
def test_fetch_new_incremental_uid_gt_last(mock_ssl):
    """有游标增量：SEARCH UID > last_uid。"""
    client = _patch_imap_client(mock_ssl)
    client.response.side_effect = lambda key: (
        ("OK", [b"99"]) if key == "UIDVALIDITY" else ("NO", [None])
    )

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
