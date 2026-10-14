"""CLI 输出的跨平台守卫：Windows 代码页下的 `✓ ✗ ⚠` 会直接让 `print` 崩。

## 为什么要单独一个模块

控制台输出不受影响（PEP 528 直接写 UTF-16），但**重定向/管道**时 Windows 用的是
本地代码页（中文机 cp936、英文机 cp1252），而 `✓ ✗ ⚠` 不在其中 —— `print` 抛
UnicodeEncodeError。危险之处在于它**崩在动作之后**：报告打不出来，操作者会以为
操作没执行（客户机常被远程操作，输出正是走管道）。

三处用法都踩过同一个坑：`trade company`（删除动作已完成却崩在报告上）、
`python -m trade.osint`（agent 通过管道收输出）、以及将来的任何 CLI 报告。

只降级 `errors`、不改编码：控制台里中文照常，个别符号变 `?` 而已。
"""

from __future__ import annotations

import sys


def reconfigure_streams() -> None:
    """把 stdout/stderr 的编码错误降级为替换（幂等，可重复调用）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass  # 被包装/已关闭的流（pytest 捕获、GUI 环境）—— 无所谓
