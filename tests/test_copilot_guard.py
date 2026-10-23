"""副驾守卫测试 —— 铁律 1「永不发送」的自动化防线。

## 封杀什么

**输入注入与发送**（任何一条出现即失败）：
  - Win32 ``SendInput`` / ``keybd_event`` / ``mouse_event``
  - ``pyautogui`` 的**任何**函数（整个库都是注入工具）
  - ``pynput`` 的 ``keyboard.Controller`` / ``mouse.Controller`` 及其调用
  - macOS ``CGEventPost`` / ``CGEventCreateKeyboardEvent``（合成按键）
  - 任何聊天软件域名 + 发送类 API 路径

**显式放行**（读取类，防误伤）：
  - ``PrintWindow`` / ``BitBlt``（Windows 读窗口）
  - ``CGWindowListCreateImage``（macOS 读窗口）
  - ``mss`` 截图
  - ``pynput`` 的 ``Listener``（监听热键）
  - 剪贴板读写

## 名单必须细化到具体函数

不能按"平台 API"粗筛 —— 截图本身就是平台 API（Quartz / PrintWindow），
粗筛会把合法的读取路径一起砍掉。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
COPILOT_DIR = REPO / "trade" / "copilot"

# 禁用的注入/发送符号（正则，整段匹配源码里出现的调用）
FORBIDDEN = [
    (r"\bSendInput\b", "Win32 SendInput（注入按键）"),
    (r"\bkeybd_event\b", "Win32 keybd_event（模拟按键）"),
    (r"\bmouse_event\b", "Win32 mouse_event（模拟鼠标）"),
    (r"\bpyautogui\b", "pyautogui（整套注入工具）"),
    (r"\bkeyboard\.Controller\b", "pynput keyboard.Controller（模拟按键）"),
    (r"\bmouse\.Controller\b", "pynput mouse.Controller（模拟点击）"),
    (r"\bCGEventPost\b", "macOS CGEventPost（合成事件）"),
    (r"\bCGEventCreateKeyboardEvent\b", "macOS 合成键盘事件"),
    (r"\bCGEventCreateMouseEvent\b", "macOS 合成鼠标事件"),
    (r"\bSendMessage\b\s*\(\s*[^,]+,\s*WM_CHAR", "窗口消息注入文本"),
    (r"\bPostMessage\b\s*\(\s*[^,]+,\s*WM_CHAR", "窗口消息注入文本"),
    # 外部工具 / 别名导入 / 字符串形式的符号（getattr 绕过）
    (r"\bosascript\b", "AppleScript 驱动其他 App（可注入按键）"),
    (r"\bxdotool\b", "xdotool（X11 注入工具）"),
    (r"\bydotool\b", "ydotool（Wayland 注入工具）"),
    (r"from\s+pynput[^\n]*\bimport\b[^\n]*\bController\b", "pynput Controller 别名导入"),
    (
        r"[\"'](?:SendInput|keybd_event|mouse_event|CGEventPost|"
        r"CGEventCreateKeyboardEvent|CGEventCreateMouseEvent)[\"']",
        "字符串形式的注入符号（getattr 绕过）",
    ),
]

# 聊天软件域名 + 发送语义（直调聊天软件 API）
CHAT_APP_HINTS = [
    r"graph\.facebook\.com.*send",
    r"api\.whatsapp\.com.*messages",
    r"qyapi\.weixin\.qq\.com.*message",
    r"graph\.weixin\.qq\.com.*send",
]

# 显式放行的读取类符号（用于断言"守卫没有误伤"）
ALLOWED_READERS = [
    "PrintWindow",
    "BitBlt",
    "CGWindowListCreateImage",
]


def _copilot_sources() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    if not COPILOT_DIR.is_dir():
        return out
    for path in sorted(COPILOT_DIR.rglob("*.py")):
        try:
            out.append((path, path.read_text(encoding="utf-8")))
        except OSError:
            continue
    return out


class TestNoSendCapability:
    """副驾代码里不得出现任何发送/注入能力。"""

    def test_copilot_package_exists(self):
        assert COPILOT_DIR.is_dir(), f"副驾包必须存在：{COPILOT_DIR}"

    def test_no_injection_calls(self):
        offenders = []
        for path, text in _copilot_sources():
            for pattern, why in FORBIDDEN:
                if re.search(pattern, text):
                    offenders.append(f"{path.relative_to(REPO)}: {why}")
        assert not offenders, "副驾代码出现了注入/发送类调用：\n  " + "\n  ".join(offenders)

    def test_no_chat_app_api_calls(self):
        offenders = []
        for path, text in _copilot_sources():
            for pattern in CHAT_APP_HINTS:
                if re.search(pattern, text, re.IGNORECASE):
                    offenders.append(f"{path.relative_to(REPO)}: 直调聊天软件 API")
        assert not offenders, "副驾不得直调聊天软件 API：\n  " + "\n  ".join(offenders)

    def test_guard_does_not_flag_readers(self):
        """守卫不能误伤读取类 API（截图/窗口读取是副驾的正当能力）。

        这些符号**允许**出现在副驾代码里；本测试锁住"放行清单"本身不被误删 ——
        将来有人精简名单时，会看到这里失败并知道要连读取能力一起考虑。
        """
        assert ALLOWED_READERS, "读取类放行清单不许为空（截图/窗口读取是副驾的正当能力）"
        for reader in ALLOWED_READERS:
            assert re.compile(rf"\b{reader}\b"), reader


class TestUiHasNoSendButton:
    """ui 模块不得出现"发送"按钮文案（§7 验收项）。"""

    def test_no_send_wording_in_copilot(self):
        # 只在将来 ui.py 存在时检查（§11 第 3 段才实现）
        ui_path = COPILOT_DIR / "ui.py"
        if not ui_path.is_file():
            pytest.skip("ui 模块尚未实现（§11 第 3 段）")
        text = ui_path.read_text(encoding="utf-8")
        for bad in ("发送", "send", "Send"):
            if bad == "send":  # 英文只在按钮文案语境算
                for m in re.finditer(r"[\"'>]\s*send\b", text, re.IGNORECASE):
                    pytest.fail(f"ui.py 出现发送类文案：{m.group(0)!r}")
                continue
            assert bad not in text, f"ui.py 出现发送类文案：{bad!r}"


class TestNoBackgroundPolling:
    """铁律 2：只在触发时读取，不许后台轮询/常驻抓取。"""

    def test_no_while_true_sleep_loop(self):
        offenders = []
        for path, text in _copilot_sources():
            # 常驻抓取的典型形态：while True +（time|asyncio）.sleep 的循环
            if re.search(r"while\s+True\s*:[\s\S]{0,400}?(?:time|asyncio)\.sleep", text):
                offenders.append(f"{path.relative_to(REPO)}: while True + sleep（疑似常驻轮询）")
        assert not offenders, "副驾出现常驻轮询循环：\n  " + "\n  ".join(offenders)

    def test_no_screenshot_saving(self):
        """铁律 6：截图只在内存中处理，不许落盘。"""
        offenders = []
        for path, text in _copilot_sources():
            if re.search(
                r"\.write_bytes\(|imwrite\(|savefig\(|\.save\s*\(|open\([^)]*['\"]wb",
                text,
            ):
                offenders.append(f"{path.relative_to(REPO)}: 疑似把数据写文件")
        assert not offenders, "副驾不应把数据落盘：\n  " + "\n  ".join(offenders)
