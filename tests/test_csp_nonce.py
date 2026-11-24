"""O-17 第一步：内联 <script> 元素改用 per-request nonce。

`script-src-elem` 管住脚本元素；`script-src`/`script-src-attr` 暂时保留
unsafe-inline，供尚未迁移的内联事件属性使用（迁移完再删）。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "static" / "trade_chat.html").read_text(encoding="utf-8")


def test_csp_has_element_nonce_and_attr_fallback():
    from trade.app import _build_trade_csp

    csp = _build_trade_csp("test-nonce-123")
    assert "script-src-elem 'self' 'nonce-test-nonce-123'" in csp
    # 内联事件属性仍在迁移中：保留 attr 回退，避免整页交互失效
    assert "script-src-attr 'unsafe-inline'" in csp
    assert "script-src 'self' 'unsafe-inline'" in csp
    assert "style-src 'self' 'unsafe-inline'" in csp


def test_every_inline_script_has_nonce_placeholder():
    tags = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", HTML, re.IGNORECASE)
    assert tags, "页面应至少有内联引导脚本"
    for tag in tags:
        assert 'nonce="__TRADE_CSP_NONCE__"' in tag, tag


def test_handler_injects_nonce_per_request():
    src = (ROOT / "trade" / "app.py").read_text(encoding="utf-8")
    assert "_build_trade_csp(nonce)" in src
    assert 'html.replace("__TRADE_CSP_NONCE__", nonce)' in src
