"""
Foreign Trade Assistant — standalone FastAPI server.

Start:
    python server.py
    python server.py --port 8080

引导逻辑在 trade.bootstrap 中，app factory 在 trade.app 中。
"""

from trade.app import main
from trade.bootstrap import setup


def run() -> None:
    """完整启动：先跑启动序列，再进入 FastAPI 应用。"""
    setup()
    main()


# 必须放在守卫内：本文件在仓库根、未被打包进 pip 包，但历史上被
# console script 当成 `server:main` 的目标 —— 那样单单 `from server import main`
# 就会连带执行整套启动流程（含起服务）。入口已改为 trade.cli:run_server。
if __name__ == "__main__":
    run()
