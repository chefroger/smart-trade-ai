"""运行环境重建（/system/rebuild-venv）的测试。

背景：2026-10-14 之前装的机器，trade 的 venv 跑的是 Python 3.11~3.13，而 Hermes
从 v0.21.6 起只发 3.14 的依赖集（见 COMPATIBILITY.md 的「当前策略」）。这类机器
一旦升级 trade 就必然进降级模式 —— agent 起不来，界面显示「需要重建运行环境」。

原来的界面给用户的是一行 `curl … | bash`，让他自己开终端粘 —— 而客群是电脑小白，
这一行实际等于「软件坏了」。这个端点把「复制命令」变成「点一次按钮」。

这里测的是**子进程脚本的结构**（顺序错了就等于没做防护），不实际执行重建 ——
真的重建要 5~10 分钟且会替换 venv，属于端到端验证的范畴。
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def fake_trade_home(tmp_path, monkeypatch):
    """造一个带安装脚本的假 TRADE_HOME。"""
    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    scripts = tmp_path / "foreign-trade-assistant" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "install.sh").write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    (scripts / "install.ps1").write_text("# fake\n", encoding="utf-8")
    return tmp_path


@pytest.mark.skipif(
    os.name == "nt",
    reason="这组验证的是 POSIX 分支（/bin/sh）；Windows 分支见下面的 TestVenvRebuildScriptWindows",
)
class TestVenvRebuildScript:
    """子进程脚本的**顺序**就是它的正确性。

    每一步的理由（顺序不能换）：
      1. 等 2 秒 —— 让本次 HTTP 响应先发回浏览器，否则前端只看到连接被掐断
      2. 杀当前进程 —— 腾出 venv 与 9119 端口
      3. 跑安装脚本 —— 脚本本身是原子的（失败保留旧 venv）
      4. **无论成败都启动 Trade** —— 失败了也要用旧环境把服务拉回来。
         漏掉这一步，用户面对的是一台彻底打不开的机器，比升级前还糟。
    """

    def _posix_script(self, fake_trade_home):
        from trade.app import _venv_rebuild_script

        built = _venv_rebuild_script()
        assert built is not None, "POSIX 下应该能构造出重建脚本"
        argv, log_file = built
        assert argv[0] == "/bin/sh" and argv[1] == "-c"
        return argv[2], log_file

    def test_waits_before_killing_itself(self, fake_trade_home):
        """先 sleep 再 kill —— 否则前端收不到「重建已开始」这个响应。"""
        script, _ = self._posix_script(fake_trade_home)
        assert "sleep 2" in script, "没有等待就直接杀进程，前端会看到连接被掐断"
        assert script.index("sleep 2") < script.index("kill -TERM"), (
            "kill 排在 sleep 之前 —— HTTP 响应还没发出去就把自己杀了"
        )

    def test_installs_after_killing(self, fake_trade_home):
        """重建必须在旧进程退出之后 —— 否则是在自己脚下换地板。"""
        script, _ = self._posix_script(fake_trade_home)
        assert script.index("kill -TERM") < script.index("install.sh"), (
            "还在跑就先重建，venv 正被本进程占用"
        )

    def test_always_starts_trade_even_if_rebuild_fails(self, fake_trade_home):
        """重建失败也必须把服务拉起来 —— 这是「不把能用的机器搞坏」的最后一环。

        安装脚本本身是原子的（失败保留旧 venv），所以失败后用旧环境启动，
        用户拿到的是「升级没成功，但软件还能用」，而不是一台打不开的机器。
        """
        script, _ = self._posix_script(fake_trade_home)
        # 必须是有分支的（成功/失败都往下走），不是 `install.sh && exec trade`
        assert "if /bin/bash" in script, "重建失败会跳过后面的启动步骤"
        start_at = script.index("exec ")
        assert start_at > script.index("install.sh"), "启动排在重建之前"
        # trade 启动器必须带 --no-browser（后台拉起，不能弹用户浏览器）
        assert "--no-browser" in script[start_at:], "拉起服务时没有 --no-browser"

    def test_log_file_is_under_trade_home(self, fake_trade_home):
        """日志落到 TRADE_HOME/logs —— 服务停掉后它是唯一的事后线索。"""
        _, log_file = self._posix_script(fake_trade_home)
        assert str(fake_trade_home) in log_file
        assert log_file.endswith("rebuild-venv.log")

    def test_returns_none_when_install_script_missing(self, tmp_path, monkeypatch):
        """找不到安装脚本时不能硬跑 —— 返回 None 让调用方如实报错。"""
        monkeypatch.setenv("TRADE_HOME", str(tmp_path))  # 空目录，没有 scripts/
        from trade.app import _venv_rebuild_script

        assert _venv_rebuild_script() is None


@pytest.mark.skipif(
    os.name != "nt",
    reason="只在 Windows 上跑：验证 cmd 分支（macOS/Linux 上是 sh 分支）",
)
class TestVenvRebuildScriptWindows:
    """Windows 分支：cmd + taskkill + PowerShell。

    ⚠️ 这条分支在开发机（macOS）上没法真跑，只能静态核对结构 —— 所以这里钉的是
    「该有的命令都在、顺序对」。真机行为要靠 Windows 用户反馈。

    2026-10-16：这组用例是因为 CI 挂掉才补的 —— 原来那 4 条把 POSIX 的期望
    （argv == /bin/sh）写死了，在 windows-latest 上必然失败。
    """

    def test_uses_cmd_taskkill_and_powershell_in_order(self, fake_trade_home):
        from trade.app import _venv_rebuild_script

        built = _venv_rebuild_script()
        assert built is not None, "Windows 下应该能构造出重建脚本"
        argv, log_file = built
        assert argv[0] == "cmd" and argv[1] == "/c"
        script = argv[2]

        # 顺序与 POSIX 分支同构：等响应 → 杀旧进程 → 重建 → 拉起服务
        assert "timeout /t 2" in script, "没有等待就直接杀进程，前端会看到连接被掐断"
        assert "taskkill" in script
        assert script.index("timeout /t 2") < script.index("taskkill")
        assert script.index("taskkill") < script.index("powershell"), "还在跑就先重建了"
        assert "install.ps1" in script and "-File" in script
        assert "--no-browser" in script, "拉起服务时没有 --no-browser"
        assert str(fake_trade_home) in log_file


class TestWindowsLauncherPath:
    """app.py 找 trade.cmd 的位置，必须与 install.ps1 **实际生成**它的位置一致。

    这是一个**跨文件契约**：两边各自演化、谁也不知道对方，正是这类 bug 的温床。
    2026-10-16 评审抓到过一次真实后果 —— app.py 写的是 `%LOCALAPPDATA%\\trade\\trade.cmd`
    而 install.ps1 写在 `%LOCALAPPDATA%\\local\\bin\\trade.cmd`，差了 `local\\bin` 一层。
    于是 Windows 用户点「开始重建」→ venv 重建**全部成功** → 最后一步 `start` 找不到
    文件 → 服务起不来，界面卡在「正在重建」直到 15 分钟超时。
    比不重建更糟：用户以为一切正常在推进。

    这组是纯文本核对，任何平台都跑（不需要 Windows）。
    """

    def test_app_py_points_at_local_bin(self):
        src = (ROOT / "trade" / "app.py").read_text(encoding="utf-8")
        line = next(
            (ln for ln in src.splitlines() if "launcher" in ln and "trade.cmd" in ln),
            None,
        )
        assert line, "app.py 里没找到 launcher 的 trade.cmd 推导"
        for part in ('"local"', '"bin"', '"trade.cmd"'):
            assert part in line, (
                f"launcher 路径缺 {part}，与 install.ps1 的 $LocalBin 不一致：{line.strip()}"
            )

    def test_installer_writes_to_the_same_place(self):
        """锁住契约的另一端：install.ps1 必须把 trade.cmd 放进 LOCALAPPDATA\\local\\bin。"""
        ps1 = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
        assert "$LocalBin = \"$env:LOCALAPPDATA\\local\\bin\"" in ps1, (
            "install.ps1 的 $LocalBin 变了 —— 若确实要改，app.py 的 launcher 必须同步"
        )
        assert '"$LocalBin\\trade.cmd"' in ps1, (
            "install.ps1 不再把 trade.cmd 写进 $LocalBin —— 契约断了"
        )


class TestRebuildEndpointGuard:
    """端点必须只在**确实需要重建**时才动手。

    缺了这道闸，界面按钮被误触（或前端状态过期）就会在健康的机器上白停
    5~10 分钟服务 —— 那正是当初把「系统更新」按钮藏起来的同类风险。
    """

    def test_endpoint_checks_fix_before_scheduling(self, monkeypatch, fake_trade_home):
        import trade.app as app_module

        scheduled: list[bool] = []
        monkeypatch.setattr(app_module, "_schedule_venv_rebuild", lambda: scheduled.append(True) or True)

        # 不需要重建：fix 是别的值 → 必须拒绝，且**不派发**子进程
        monkeypatch.setattr(
            "trade.bootstrap.hermes_compat_state",
            lambda: {"fix": "upgrade_hermes"},
        )
        router = app_module._create_system_router()
        endpoint = next(
            r.endpoint for r in router.routes
            if getattr(r, "path", "") == "/system/rebuild-venv"
        )

        class _Req:
            headers = {"X-Hermes-Session-Token": ""}

        result = endpoint(_Req())
        assert result["ok"] is False
        assert not scheduled, "明明不需要重建，却派发了子进程"
