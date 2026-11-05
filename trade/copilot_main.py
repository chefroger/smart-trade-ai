"""聊天副驾独立进程入口（`trade copilot` / `python -m trade.copilot_main`）。

为什么独立进程：pywebview 的 GUI 事件循环必须在主线程；Trade 主进程跑
uvicorn，不能把悬浮窗塞进后台线程。副驾进程只负责热键/托盘/悬浮窗，
不启动 Trade 服务，也不影响 Trade 的可用性。

前提：设置里已开启副驾并同意隐私说明；否则直接退出。
"""

from __future__ import annotations

import argparse
import sys


def _first_active_company_id() -> int | None:
    try:
        from trade.company import list_all

        for row in list_all():
            if row.get("is_active", True):
                return int(row["id"])
    except Exception:
        return None
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trade copilot", description="聊天副驾")
    parser.add_argument("--company-id", type=int, default=0, help="绑定公司 ID")
    args = parser.parse_args(argv)

    from trade.copilot.settings import load_settings

    settings = load_settings()
    if not settings.enabled or not settings.consent_ok():
        print("副驾未开启（或未同意隐私说明），退出。")
        return 2

    company_id = args.company_id or _first_active_company_id()
    if not company_id:
        print("没有可用的公司，副驾无法启动。")
        return 2

    # 草稿生成会 import Hermes；必须先准备好路径（与 Trade 主进程一致）。
    try:
        from trade.bootstrap import prepare_hermes_import_paths

        prepare_hermes_import_paths()
    except Exception as exc:
        print(f"准备 Hermes 运行环境失败：{exc}")
        return 2

    from trade.copilot.service import CopilotService
    from trade.copilot.ui import FloatingWindow

    try:
        ui = FloatingWindow()
        ui.prepare()  # 提前暴露 pywebview 缺失等问题
    except Exception as exc:
        print(f"悬浮窗不可用：{exc}")
        return 2

    service = CopilotService(company_id, settings=settings, ui=ui)
    hotkey_ok, hotkey_reason = service.start_hotkey()
    tray_ok, tray_reason = service.start_tray()
    print(f"副驾已启动：公司 {company_id}")
    if not hotkey_ok:
        print(f"  热键不可用：{hotkey_reason}")
    if not tray_ok:
        print(f"  托盘不可用：{tray_reason}")

    try:
        ui.run()
    except Exception as exc:
        print(f"副驾界面异常退出：{exc}")
        return 1
    finally:
        service.stop_hotkey()
        service.stop_tray()
    return 0


if __name__ == "__main__":
    sys.exit(main())
