"""聊天副驾悬浮窗（pywebview，惰性加载）。

铁律：界面上**没有外发入口**，也不提供任何外发/注入路径。已接线按钮只有：
复制草稿（换说法 / 深处理尚未接入，不渲染）。

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

# 只暴露已接线动作。换说法 / 深处理尚未接入，不渲染空壳按钮。
_BUTTONS = (
    ("copy", "复制草稿"),
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
    """渲染悬浮窗 HTML（纯函数，便于测试"无外发入口"与转义）。

    没有草稿时（读取中/识别中/失败/待确认）只显示状态，不渲染空文本框和
    一排点不动的按钮 —— 那会让窗口显得又空又怪。
    """
    has_draft = bool((draft or "").strip())
    button_html = "".join(
        f'<button data-action="{action}">{html.escape(label)}</button>'
        for action, label in _BUTTONS
    )
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'><style>",
        "body{font-family:-apple-system,'Segoe UI',sans-serif;margin:0;padding:14px;",
        "padding-top:34px;position:relative;background:#fff;color:#222;font-size:14px}",
        "textarea{width:100%;min-height:140px;box-sizing:border-box;font:inherit;",
        "border:1px solid #ddd;border-radius:8px;padding:10px}",
        ".row{display:flex;gap:8px;margin-top:10px}",
        "button{flex:1;padding:8px 10px;border:1px solid #ddd;border-radius:8px;",
        "background:#f7f7f7;cursor:pointer;font:inherit}",
        "button:hover{background:#eee}",
        "button.close{position:absolute;top:6px;right:8px;width:26px;height:26px;",
        "flex:none;padding:0;border:none;background:transparent;font-size:18px;",
        "line-height:1;color:#888}button.close:hover{background:#eee;color:#222}",
        ".muted{color:#666;font-size:12px}.status{color:#8a6d3b}",
        "</style></head><body>",
        "<button class='close' data-action='close' aria-label='关闭'>×</button>",
    ]
    if status:
        parts.append(f"<div class='status'>{html.escape(status)}</div>")
    if notice:
        parts.append(f"<div class='muted'>{html.escape(notice)}</div>")
    if summary:
        parts.append(f"<p class='muted'>{html.escape(summary)}</p>")
    if confirmation:
        parts.append(f"<p><b>{html.escape(confirmation)}</b></p>")
    if has_draft:
        parts.append(
            "<textarea id='draft' aria-label='草稿'>"
            f"{html.escape(draft)}</textarea>"
        )
        if sources:
            parts.append(f"<ul class='muted'>{_source_lines(sources)}</ul>")
        parts.append(f"<div class='row'>{button_html}</div>")
        parts.append("<div id='action-status' class='muted'></div>")
    parts.append(
        "<script>"
        "document.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{"
        "const a=b.dataset.action;const d=document.getElementById('draft');"
        "const t=d?d.value:'';const s=document.getElementById('action-status');"
        "if(!(window.pywebview&&window.pywebview.api)){"
        "if(a==='close'){window.close();}else{s.textContent='界面桥未就绪，请重开弹窗';}return;}"
        "Promise.resolve(window.pywebview.api.action(a,t)).then(r=>{"
        "if(!r||!s){return;} if(r.ok){s.textContent=r.message||'已完成';}"
        "else{s.textContent='失败：'+(r.error||'未知原因');}"
        "}).catch(e=>{if(s){s.textContent='失败：'+e;}});"
        "}));"
        "</script></body></html>"
    )
    return "".join(parts)


class _Bridge:
    """JS → Python 的唯一入口；只有复制/换说法/深处理/关闭，无外发能力。"""

    def __init__(
        self,
        *,
        on_copy: Callable[[str], None] | None = None,
        on_regenerate: Callable[[str], None] | None = None,
        on_deepen: Callable[[str], None] | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self.on_copy = on_copy
        self.on_regenerate = on_regenerate
        self.on_deepen = on_deepen
        self.on_close = on_close

    def action(self, action: str, text: str = "") -> dict:
        """执行按钮动作；返回给 JS 展示的状态（ok/message/error）。"""
        if action == "copy":
            return self._copy(text)
        if action == "regenerate":
            return self._call(self.on_regenerate, text, "已重新生成")
        if action == "deepen":
            return self._call(self.on_deepen, text, "已打开 trade")
        if action == "close":
            return self._close()
        return {"ok": False, "error": "未知操作"}

    def _close(self) -> dict:
        if self.on_close is None:
            return {"ok": False, "error": "关闭回调未接线"}
        try:
            self.on_close()
        except Exception as exc:
            _log.warning("关闭副驾弹窗失败：%s", exc)
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "message": "已关闭"}

    def _copy(self, text: str) -> dict:
        # 只有用户点"复制草稿"才会写剪贴板（任务书 §2 铁律 5）。
        if not (text or "").strip():
            return {"ok": False, "error": "没有草稿可复制"}
        try:
            import pyperclip

            pyperclip.copy(text)
            return {"ok": True, "message": "已复制到剪贴板"}
        except Exception as exc:
            _log.warning("复制草稿失败：%s", exc)
            return {"ok": False, "error": f"复制失败：{exc}"}

    def _call(
        self, fn: Callable[[str], None] | None, text: str, message: str
    ) -> dict:
        if fn is None:
            return {"ok": False, "error": "该功能尚未接入"}
        try:
            fn(text)
        except Exception as exc:
            _log.exception("副驾按钮回调失败")
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "message": message}


class FloatingWindow:
    """悬浮窗（需在主线程运行 `run()`）。"""

    def __init__(self, **callbacks: Any) -> None:
        self._bridge = _Bridge(**callbacks)
        # 未显式传入 on_close 时默认只收起；service 可再绑 dismiss（取消在途）。
        if self._bridge.on_close is None:
            self._bridge.on_close = self.hide
        self._window = None
        self._webview = None
        self._visible = False

    def set_dismiss_handler(self, fn: Callable[[], None]) -> None:
        """把 × / 关闭接到编排层（取消在途任务后再收起）。"""
        self._bridge.on_close = fn

    def is_visible(self) -> bool:
        return self._visible

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
        self._visible = True

    def hide(self) -> None:
        """收起悬浮窗（不销毁，热键再次触发时复用）。"""
        self._visible = False
        if self._window is None:
            return
        try:
            self._window.hide()
        except Exception as exc:
            _log.warning("收起悬浮窗失败：%s", exc)

    def prepare(self) -> None:
        """提前创建窗口（用于启动时暴露依赖缺失，不显示）。"""
        self._ensure_window()

    def _resize(self, height: int) -> None:
        if self._window is None:
            return
        try:
            self._window.resize(390, height)
        except Exception:
            pass

    def show_status(self, text: str) -> None:
        """显示状态（如"正在读取"、"该应用在拒读名单内"）。"""
        self._resize(180)
        self.show_html(render_panel_html(status=text))

    def show_error(self, text: str) -> None:
        """显示失败原因（不弹空草稿）。"""
        self._resize(200)
        self.show_html(render_panel_html(status=text))

    def show_result(self, *, draft: str = "", summary: str = "",
                    sources: Iterable[Any] = (), notice: str = "",
                    confirmation: str = "") -> None:
        self._resize(520 if (draft or "").strip() else 200)
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
        self._visible = False
        if self._window is None:
            return
        try:
            self._window.destroy()
        except Exception:
            pass
        self._window = None
