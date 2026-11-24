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
    assert "script-src 'self' 'nonce-test-nonce-123'" in csp
    assert "script-src-elem 'self' 'nonce-test-nonce-123'" in csp
    # 事件属性已迁移完：脚本指令里不得再出现 unsafe-inline
    assert "script-src-attr 'none'" in csp
    assert "script-src 'self' 'unsafe-inline'" not in csp
    assert "script-src-elem 'self' 'unsafe-inline'" not in csp
    # 样式元素只允许外部文件；属性级仍保留回退（400+ 处内联 style）
    assert "style-src-elem 'self'" in csp
    assert "style-src-attr 'unsafe-inline'" in csp


def test_every_inline_script_has_nonce_placeholder():
    tags = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", HTML, re.IGNORECASE)
    assert tags, "页面应至少有内联引导脚本"
    for tag in tags:
        assert 'nonce="__TRADE_CSP_NONCE__"' in tag, tag


def test_handler_injects_nonce_per_request():
    src = (ROOT / "trade" / "app.py").read_text(encoding="utf-8")
    assert "_build_trade_csp(nonce)" in src
    assert 'html.replace("__TRADE_CSP_NONCE__", nonce)' in src


def test_no_inline_event_attributes_remain():
    """O-17：HTML/JS 模板里不得再出现 on*= 内联事件（含 hover）。"""
    import re

    pattern = re.compile(
        r"\son(?:click|change|input|keydown|keyup|submit|load|error|"
        r"mouseover|mouseout|focus|blur)=",
        re.IGNORECASE,
    )
    files = [ROOT / "static" / "trade_chat.html", *sorted((ROOT / "static" / "js").glob("*.js"))]
    offenders = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            # data-onchange 等不算内联事件
            if text[max(0, match.start() - 5):match.start()] == "data-":
                continue
            offenders.append(f"{path.name}:{text[:match.start()].count(chr(10)) + 1}")
        # 动态 setAttribute('onclick', ...) 同样会被 CSP 拦截
        for match in re.finditer(r"setAttribute\(\s*['\"]on", text):
            offenders.append(f"{path.name}:{text[:match.start()].count(chr(10)) + 1} (setAttribute)")
    assert not offenders, f"仍存在内联事件属性: {offenders[:10]}"


def test_no_style_elements_in_page():
    """style-src-elem 只允许外部样式：页面不得出现内联 <style>。"""
    import re

    assert not re.search(r"<style[\s>]", HTML, re.IGNORECASE)
