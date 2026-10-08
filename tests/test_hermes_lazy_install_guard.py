"""禁用 Hermes 懒加载重启 —— Trade 必须待在自己的 venv 里。

## 为什么需要这个约束（客户机实测）

2026-10-08 客户机上「公司网站诊断」时前端只显示「⚠️ Agent 未返回有效回复」。
真实原因不在 Trade 配置、也不在 API key：

`trade/helpers.py` 的 `from run_agent import AIAgent` 会连带执行 Hermes 的
`hermes_bootstrap.py`。该模块判断「当前解释器 ≠ Hermes 的 store 解释器」后，按
「借用启动」处理，把 `server.py` **重新 exec 到 Hermes 自带的那个 Python**：

    %LOCALAPPDATA%\\hermes\\tools\\python-3.14.7+...\\python.exe

那个解释器里没有 trade 包，子进程死在：

    server.py line 11: from trade.app import main
    ModuleNotFoundError: No module named 'trade'   → 退出码 1

父进程随即 `raise RelaunchExit(1)`。而 `RelaunchExit` 继承 **SystemExit**（属
BaseException，不是 Exception），Trade 的重试循环与所有 `except Exception` 都抓不到，
agent 线程直接死亡（`Future exception was never retrieved`），前端既收不到
`response` 也收不到 `error`，落到兜底文案。

## 为什么安装时的验证查不出来

单纯 `import run_agent` 不报错 —— relaunch 到 store python 后能成功，只是白跑一遍。
**只有重新执行 `server.py`（需要 trade 包）才炸。** 于是 `/api/status`、
`/api/trade/models/providers`、面板能打开全部通过，看起来一切正常，一聊天就废。

这也正是 `COMPATIBILITY.md` 自己写明的盲区：「签名不变但行为变了」——
`hermes_bootstrap` 是较新上游 main 引入的（安装印章 0.21.5+9141），
`run_agent` 这个符号与参数都没动，静态符号核对查不出来。

## 修法

H 上游为此提供了正式的 sealed-venv 模式开关（`tools/lazy_deps.py`：
`if os.environ.get("HERMES_DISABLE_LAZY_INSTALLS") == "1":`）。Trade 在
`load_env_and_set_yolo()` 里程序化设上它，作用域仅限 Trade 进程树 ——
不影响用户自己那个 `hermes` CLI。
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade import bootstrap

FLAG = "HERMES_DISABLE_LAZY_INSTALLS"


def _stub_hermes(monkeypatch, *, env_writes: dict | None = None):
    """把 load_env_and_set_yolo 需要的两个 Hermes 符号换成假模块。

    CI 里 Hermes 不可导入（见 conftest / ci_sim.sh），而本函数正是要在真实
    启动路径上调用的，所以测试必须自己提供替身，不能依赖真 Hermes。

    Args:
        env_writes: 假的 load_hermes_dotenv 在「加载 .env」时要写入的环境变量。
                    用于验证 Trade 的取值**不被 .env 覆盖**。
    """
    pkg = types.ModuleType("hermes_cli")
    env_loader = types.ModuleType("hermes_cli.env_loader")

    def _fake_load(**_kwargs):
        # 模拟 load_hermes_dotenv 的行为：它用 os.environ[name] = value 直接覆盖
        for k, v in (env_writes or {}).items():
            os.environ[k] = v

    env_loader.load_hermes_dotenv = _fake_load
    constants = types.ModuleType("hermes_constants")
    constants.get_hermes_home = lambda: Path("/tmp/fake-hermes-home")

    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.env_loader", env_loader)
    monkeypatch.setitem(sys.modules, "hermes_constants", constants)


class TestLazyInstallDisabled:
    """load_env_and_set_yolo 必须把懒加载重启关掉。"""

    def test_flag_is_set(self, monkeypatch):
        """核心契约：调用后环境变量为 "1"。"""
        monkeypatch.delenv(FLAG, raising=False)
        _stub_hermes(monkeypatch)

        bootstrap.load_env_and_set_yolo()

        assert os.environ.get(FLAG) == "1", (
            "未禁用 Hermes 懒加载重启 —— agent 会被 exec 到 Hermes 的 store python，"
            "那里没有 trade 包，agent 线程会以 RelaunchExit(SystemExit) 静默死亡"
        )

    def test_trade_value_wins_over_dotenv(self, monkeypatch):
        """Trade 的取值必须**压过** .env —— 否则用户 .env 里写了 0 就又复发了。

        `load_hermes_dotenv` 是 `os.environ[name] = value` 直接覆盖（见
        hermes_cli/env_loader.py 的赋值处），所以设值动作必须发生在 load 之后。
        """
        monkeypatch.delenv(FLAG, raising=False)
        # 假设用户的 .env 里把它显式关掉了
        _stub_hermes(monkeypatch, env_writes={FLAG: "0"})

        bootstrap.load_env_and_set_yolo()

        assert os.environ.get(FLAG) == "1", (
            "被 .env 覆盖了 —— 说明设值早于 load_hermes_dotenv，顺序反了"
        )

    def test_yolo_still_set(self, monkeypatch):
        """同一次调用里 YOLO 模式也要照旧设置（防止改动误伤现有行为）。"""
        monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
        _stub_hermes(monkeypatch)

        bootstrap.load_env_and_set_yolo()

        assert os.environ.get("HERMES_YOLO_MODE") == "true"
