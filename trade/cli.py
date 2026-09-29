"""命令行入口（打包内的 console script 目标）。

为什么需要这个模块：`[project.scripts]` 原先指向仓库根的 `server:main`，
而 `packages.find` 只收 `trade` 包 —— 顶层模块不被打包，pip 安装后
`trade` 命令直接 `ModuleNotFoundError: No module named 'server'`。

这里把「启动序列 + FastAPI 启动」收进包内，console script 只依赖 `trade.*`。
（`python server.py` 这条文档路径仍然可用，见仓库根的 server.py。）
"""

from __future__ import annotations


def run_server() -> None:
    """`trade` 命令入口：先跑启动序列，再进入 FastAPI 应用。

    启动序列（trade.bootstrap.setup）负责：日志过滤、sys.path 调整（让 Trade 的
    trade 包优先于 Hermes 的同名包）、子命令分发、架构与 Hermes 版本检查、
    .env 加载、YOLO 模式、skills 同步、数据库初始化。**不能跳过**。
    """
    from trade.app import main as _app_main
    from trade.bootstrap import setup

    setup()
    _app_main()
