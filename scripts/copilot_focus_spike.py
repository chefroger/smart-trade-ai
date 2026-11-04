"""聊天副驾焦点 spike（macOS）。

验证：悬浮窗在不激活副驾进程的前提下显示，用户正在打字的窗口是否保持前台。

运行：python scripts/copilot_focus_spike.py
窗口约 4 秒后自动关闭，终端打印 before / after 前台应用名。
判定：before == after → 不抢焦点（通过）；否则失败。

2026-11-04 实测（macOS）：before='Google Chrome' → after='Google Chrome'，PASS。
关键做法：pywebview 窗口用 hidden=True；不调用 webview 的 show()（它会
activateIgnoringOtherApps）；改为原生 NSWindow：应用设为 Accessory +
NSFloatingWindowLevel + orderFrontRegardless。直接 focus=False + show() 会抢焦点。
"""

from __future__ import annotations

import sys
import threading
import time


def _frontmost_app() -> str:
    """当前系统前台应用名（优先 NSWorkspace，退回 Quartz 窗口列表）。"""
    try:
        from AppKit import NSWorkspace  # type: ignore

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return str(app.localizedName() or "") if app else ""
    except Exception:
        pass
    try:
        from trade.copilot.platform_darwin import _frontmost_window, _quartz

        quartz = _quartz()
        info = _frontmost_window(quartz) if quartz else None
        return info[1] if info else ""
    except Exception:
        return ""


def main() -> int:
    if sys.platform != "darwin":
        print("本 spike 仅适用于 macOS。")
        return 2
    try:
        import webview
    except ImportError:
        print("缺少 pywebview：pip install '.[desktop]'")
        return 2

    before = _frontmost_app()
    result: dict[str, str] = {}

    window = webview.create_window(
        "copilot focus spike",
        html="<html><body style='font-family:sans-serif'>focus spike</body></html>",
        width=320,
        height=160,
        x=80,
        y=80,
        frameless=True,
        on_top=True,
        focus=False,
        hidden=True,
        resizable=False,
    )

    def probe() -> None:
        # 等原生窗口就绪（probe 在 pywebview 的 GUI 线程之外运行）
        for _ in range(60):
            if getattr(window, "native", None) is not None:
                break
            time.sleep(0.05)

        def do_show() -> None:
            # 必须在主线程操作 AppKit。关键：不调用 pywebview 的 show()
            # （它会 activateIgnoringOtherApps），直接设辅助应用 + 浮层 +
            # orderFrontRegardless，后者显示但不激活。
            from AppKit import (  # type: ignore
                NSApp,
                NSApplicationActivationPolicyAccessory,
                NSFloatingWindowLevel,
            )

            NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
            native = window.native
            native.setLevel_(NSFloatingWindowLevel)
            native.orderFrontRegardless()

        try:
            from PyObjCTools import AppHelper  # type: ignore

            AppHelper.callAfter(do_show)
        except Exception as exc:  # PyObjC 缺失时直接报错，不回退到会抢焦点的 show()
            result["error"] = str(exc)
        time.sleep(2.5)
        result["after"] = _frontmost_app()
        try:
            window.destroy()
        except Exception:
            pass

    thread = threading.Thread(target=probe, daemon=True)
    thread.start()
    webview.start(gui="cocoa")
    thread.join(timeout=5)

    after = result.get("after", "")
    print(f"before: {before!r}")
    print(f"after : {after!r}")
    if result.get("error"):
        print(f"ERROR: {result['error']}")
        return 2
    ok = bool(before) and before == after
    print("PASS: 悬浮窗未抢焦点" if ok else "FAIL: 前台应用发生变化")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
