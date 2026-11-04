"""聊天副驾悬浮窗（pywebview，惰性加载）。

铁律：界面上**没有外发入口**，也不提供任何外发/注入路径。按钮只有三个：
复制草稿、换一种说法、打开 trade 深处理。

焦点：macOS 上按 2026-11-04 spike 验证过的方式显示 —— pywebview 窗口
`hidden=True`，不调用 `show()`（它会 activateIgnoringOtherApps），改为原生
NSWindow：Accessory 激活策略 + NSFloatingWindowLevel + orderFrontRegardless。
"""

from __future__ import annotations

import html
import logging
import sys
from collections.abc import Callable, Iterable
from typing import Any

_log = logging.getLogger(__name__)

_BUTTONS = (
    ("copy", "复制草稿"),
    ("regenerate", "换一种说法"),
    ("deepen", "打开 trade 深处理"),
)


def available() -> tuple[bool, str]:
    try:
        import webview  # noqa: F401
    except Exception as exc:
        return False, f"缺少依赖 pywebview，悬浮窗不可用：{exc}"
    return True, ""


def _source_lines(sources: Iterable[Any]) -> str:
    rows = []
    for src in sources or ():
        label = getattr(src, "label", "") or ""
        value = getattr(src, "value", "") or ""
        if label or value:
            rows.append(f"<li>{html.escape(str(label))}：{html.escape(str(value))}</li>")
    return "".join(rows)


def render_panel_html(
    *,
    status: str = "",
    draft: str = "",
    summary: str = "",
    sources: Iterable[Any] = (),
    confirmation: str = "",
    notice: str = "",
) -> str:
    """渲染悬浮窗 HTML（纯函数，便于测试"无外发入口"与转义）。"""
    button_html = "".join(
        f'<button data-action="{action}">{html.escape(label)}</button>'
        for action, label in _BUTTONS
    )
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'><style>",
        "body{font-family:-apple-system,'Segoe UI',sans-serif;margin:0;padding:14px;",
        "background:#fff;color:#222;font-size:14px}",
        "textarea{width:100%;min-height:140px;box-sizing:border-box;font:inherit;",
        "border:1px solid #ddd;border-radius:8px;padding:10px}",
        ".row{display:flex;gap:8px;margin-top:10px}",
        "button{flex:1;padding:8px 10px;border:1px solid #ddd;border-radius:8px;",
        "background:#f7f7f7;cursor:pointer;font:inherit}",
        "button:hover{background:#eee}",
        ".muted{color:#666;font-size:12px}.status{color:#8a6d3b}",
        "</style></head><body>",
    ]
    if status:
        parts.append(f"<div class='status'>{html.escape(status)}</div>")
    if notice:
        parts.append(f"<div class='muted'>{html.escape(notice)}</div>")
    if summary:
        parts.append(f"<p class='muted'>{html.escape(summary)}</p>")
    if confirmation:
        parts.append(f"<p><b>{html.escape(confirmation)}</b></p>")
    parts.append(
        "<textarea id='draft' aria-label='草稿'>"
        f"{html.escape(draft or '')}</textarea>"
    )
    if sources:
        parts.append(f"<ul class='muted'>{_source_lines(sources)}</ul>")
    parts.append(f"<div class='row'>{button_html}</div>")
    parts.append(
        "<script>"
        "document.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{"
        "const a=b.dataset.action;const t=document.getElementById('draft').value;"
        "if(window.pywebview&&window.pywebview.api){window.pywebview.api.action(a,t);}"
        "}));"
        "</script></body></html>"
    )
    return "".join(parts)


class _Bridge:
    """JS → Python 的唯一入口；只允许三个行为，没有任何外发能力。"""

    def __init__(
        self,
        *,
        on_copy: Callable[[str], None] | None = None,
        on_regenerate: Callable[[str], None] | None = None,
        on_deepen: Callable[[str], None] | None = None,
    ) -> None:
        self.on_copy = on_copy
        self.on_regenerate = on_regenerate
        self.on_deepen = on_deepen

    def action(self, action: str, text: str = "") -> None:
        if action == "copy":
            self._copy(text)
        elif action == "regenerate":
            self._call(self.on_regenerate, text)
        elif action == "deepen":
            self._call(self.on_deepen, text)

    def _copy(self, text: str) -> None:
        # 只有用户点"复制草稿"才会写剪贴板（任务书 §2 铁律 5）。
        try:
            import pyperclip

            pyperclip.copy(text or "")
        except Exception as exc:
            _log.warning("复制草稿失败：%s", exc)

    @staticmethod
    def _call(fn: Callable[[str], None] | None, text: str) -> None:
        if fn is None:
            return
        try:
            fn(text)
        except Exception:
            _log.exception("副驾按钮回调失败")


class FloatingWindow:
    """悬浮窗（需在主线程运行 `run()`）。"""

    def __init__(self, **callbacks: Any) -> None:
        self._bridge = _Bridge(**callbacks)
        self._window = None
        self._webview = None

    def _ensure_window(self):
        if self._window is not None:
            return self._window
        ok, reason = available()
        if not ok:
            raise RuntimeError(reason)
        import webview

        self._webview = webview
        self._window = webview.create_window(
            "聊天副驾",
            html=render_panel_html(status="副驾已就绪"),
            width=390,
            height=460,
            frameless=True,
            on_top=True,
            focus=False,
            hidden=True,
            resizable=True,
            js_api=self._bridge,
        )
        return self._window

    def show_html(self, content: str) -> None:
        window = self._ensure_window()
        window.load_html(content)
        self._show_nonactivating(window)

    def show_result(self, *, draft: str = "", summary: str = "",
                    sources: Iterable[Any] = (), notice: str = "",
                    confirmation: str = "") -> None:
        self.show_html(
            render_panel_html(
                draft=draft,
                summary=summary,
                sources=sources,
                notice=notice,
                confirmation=confirmation,
            )
        )

    def _show_nonactivating(self, window) -> None:
        if sys.platform == "darwin":
            try:
                from PyObjCTools import AppHelper

                def _show() -> None:
                    from AppKit import (  # type: ignore
                        NSApp,
                        NSApplicationActivationPolicyAccessory,
                        NSFloatingWindowLevel,
                    )

                    NSApp.setActivationPolicy_(
                        NSApplicationActivationPolicyAccessory
                    )
                    native = window.native
                    native.setLevel_(NSFloatingWindowLevel)
                    native.orderFrontRegardless()

                AppHelper.callAfter(_show)
                return
            except Exception as exc:
                _log.warning("macOS 非激活显示失败，退回 pywebview.show：%s", exc)
        try:
            window.show()
        except Exception as exc:
            _log.warning("显示悬浮窗失败：%s", exc)

    def run(self) -> None:
        self._ensure_window()
        self._webview.start(gui="cocoa" if sys.platform == "darwin" else None)

    def close(self) -> None:
        if self._window is None:
            return
        try:
            self._window.destroy()
        except Exception:
            pass
        self._window = None
