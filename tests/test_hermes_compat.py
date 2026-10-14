"""Hermes provider 兼容层测试。"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def compat_module(monkeypatch):
    """加载兼容层并隔离 Hermes 模块。"""
    for name in list(sys.modules):
        if name == "trade.hermes_compat":
            del sys.modules[name]
    import trade.hermes_compat as compat
    return compat


def test_provider_catalog_uses_public_catalog_and_model_api(monkeypatch, compat_module):
    """新 Hermes 公开目录和模型 API 应成为主路径。"""
    catalog = [SimpleNamespace(slug="openai", label="OpenAI", auth_type="api_key", tab="keys")]
    auth = {"logged_in": True, "auth_type": "api_key"}
    monkeypatch.setattr(compat_module, "_public_provider_catalog", lambda: catalog)
    monkeypatch.setattr(compat_module, "_public_provider_models", lambda provider: ["gpt-5"])
    monkeypatch.setattr(compat_module, "_public_auth_status", lambda provider: auth)

    result = compat_module.list_provider_records()

    assert result == [{
        "id": "openai",
        "name": "OpenAI",
        "auth_type": "api_key",
        "auth_status": auth,
        "has_key": True,
        "models": ["gpt-5"],
    }]


def test_provider_catalog_falls_back_when_public_apis_missing(monkeypatch, compat_module):
    """旧版 Hermes 没有公开接口时应继续返回旧注册表数据。"""
    class Provider:
        name = "Legacy"
        display_name = "Legacy"
        auth_type = "api_key"
        api_key_env_vars = ["LEGACY_KEY"]
        base_url_env_var = ""

    monkeypatch.setattr(compat_module, "_public_provider_catalog", lambda: None)
    monkeypatch.setattr(compat_module, "_public_provider_models", lambda provider: None)
    monkeypatch.setattr(compat_module, "_public_auth_status", lambda provider: None)
    monkeypatch.setattr(compat_module, "_legacy_registry", lambda: {"legacy": Provider()})
    monkeypatch.setattr(compat_module, "_legacy_models", lambda provider: ["legacy-model"])
    monkeypatch.setenv("LEGACY_KEY", "configured")

    result = compat_module.list_provider_records()

    assert result[0]["id"] == "legacy"
    assert result[0]["has_key"] is True
    assert result[0]["models"] == ["legacy-model"]


def test_auth_status_does_not_require_api_key_for_oauth(monkeypatch, compat_module):
    """OAuth 已登录状态不能因没有 API key 环境变量而被误判。"""
    monkeypatch.setattr(compat_module, "_public_provider_catalog", lambda: [
        SimpleNamespace(slug="nous", label="Nous", auth_type="oauth_device_code", tab="accounts")
    ])
    monkeypatch.setattr(compat_module, "_public_provider_models", lambda provider: [])
    monkeypatch.setattr(compat_module, "_public_auth_status", lambda provider: {
        "logged_in": True, "auth_type": "oauth_device_code"
    })

    result = compat_module.list_provider_records()

    assert result[0]["has_key"] is True
    assert result[0]["auth_type"] == "oauth_device_code"


# ── Hermes 版本识别 ─────────────────────────────────────────────────────────
# 上游 main 把 hermes_cli.__version__ 改为「惰性读安装印章，读不到返回 "0.0.0"」
# （见 hermes_cli/__init__.py 的 __getattr__），而 Trade 用它做启动门禁。
# 占位值必须视为「未知」：否则会以 0.0.0 < 0.13.0 拒绝启动，且提示信息是误导的。


def test_version_prefers_new_version_info_api(monkeypatch, compat_module):
    """新版 get_version_info() 优先于旧的 __version__。"""
    monkeypatch.setattr(compat_module, "_public_version_info", lambda: "0.21.5")
    monkeypatch.setattr(compat_module, "_legacy_version", lambda: "0.21.4")

    assert compat_module.hermes_version() == "0.21.5"


def test_version_falls_back_to_legacy_literal(monkeypatch, compat_module):
    """旧版 Hermes 没有 version_info 时回退到 __version__ 字面量。"""
    monkeypatch.setattr(compat_module, "_public_version_info", lambda: None)
    monkeypatch.setattr(compat_module, "_legacy_version", lambda: "0.21.4")

    assert compat_module.hermes_version() == "0.21.4"


def test_version_falls_back_to_checkout_pyproject(monkeypatch, compat_module):
    """两个接口都取不到时，读 checkout 自带的 pyproject.toml。"""
    monkeypatch.setattr(compat_module, "_public_version_info", lambda: None)
    monkeypatch.setattr(compat_module, "_legacy_version", lambda: None)
    monkeypatch.setattr(compat_module, "_checkout_version", lambda: "0.20.0")

    assert compat_module.hermes_version() == "0.20.0"


@pytest.mark.parametrize("placeholder", ["0.0.0", "unknown", "", "none", "  "])
def test_placeholder_versions_are_treated_as_unknown(monkeypatch, compat_module, placeholder):
    """安装印章缺失时上游返回 0.0.0 —— 那是占位值，不是真实版本号。"""
    monkeypatch.setattr(compat_module, "_public_version_info", lambda: placeholder)
    monkeypatch.setattr(compat_module, "_legacy_version", lambda: placeholder)
    monkeypatch.setattr(compat_module, "_checkout_version", lambda: None)

    assert compat_module.hermes_version() is None


@pytest.mark.parametrize("bad", ["git.abc1234", "not-a-version", "v0.21.5-490-gabc1234"])
def test_unparseable_versions_are_treated_as_unknown(monkeypatch, compat_module, bad):
    """无法做 PEP 440 比较的字符串也按未知处理，避免启动时抛 InvalidVersion。"""
    monkeypatch.setattr(compat_module, "_public_version_info", lambda: bad)
    monkeypatch.setattr(compat_module, "_legacy_version", lambda: bad)
    monkeypatch.setattr(compat_module, "_checkout_version", lambda: None)

    assert compat_module.hermes_version() is None


class TestHermesPythonCompat:
    """共存判定：读 checkout 元数据，**全程不导入 Hermes**。

    为什么不能靠 import 判：旧版 Hermes 在新 Python 上崩的是「缺依赖的 ImportError」
    （缺 openai / pydantic-core 等），用户看到的是依赖天书，而不是「版本过旧、去升级」
    这个可行动的结论。所以这里同时钉住「不导入」这件事本身。
    """

    @staticmethod
    def _stub(monkeypatch, compat, *, version, requires, python=(3, 14, 7)):
        """把元数据与解释器版本注入判定函数（判定是相对解释器的）。"""
        monkeypatch.setattr(compat, "_read_checkout_metadata", lambda: (version, requires))
        monkeypatch.setattr(sys, "version_info", python)

    def test_old_hermes_rejected_on_new_python(self, monkeypatch, compat_module):
        """0.19 声明 <3.14，在 3.14 上必须判不兼容（实测 pip 直接拒装）。"""
        self._stub(monkeypatch, compat_module, version="0.19.0", requires=">=3.11,<3.14")

        result = compat_module.hermes_python_compat()

        assert result["verdict"] == "too_old"
        assert result["version"] == "0.19.0"

    def test_new_hermes_accepted_on_new_python(self, monkeypatch, compat_module):
        """0.22.0 声明 <3.15，含 3.14 → 可共存。"""
        self._stub(monkeypatch, compat_module, version="0.22.0", requires=">=3.11,<3.15")

        assert compat_module.hermes_python_compat()["verdict"] == "ok"

    def test_floor_applies_regardless_of_interpreter(self, monkeypatch, compat_module):
        """版本下限与解释器无关：新版 Trade 的 venv 恒为 Python 3.14，老 Hermes
        不可能共存 —— 所以即便判定的解释器是 3.13（本身能跑 0.21.5），也一律判过旧。
        否则会给出错误补救：「升级 Hermes」在 3.13 上反而会把两套都弄坏。
        """
        self._stub(
            monkeypatch, compat_module,
            version="0.21.5", requires=">=3.11,<3.14", python=(3, 13, 5),
        )

        assert compat_module.hermes_python_compat()["verdict"] == "too_old"

    def test_version_below_floor_rejected_even_with_loose_specifier(
        self, monkeypatch, compat_module
    ):
        """区间宽松但版本低于下限时仍要拦：极老版本的依赖在 3.14 上照样装不出来。"""
        self._stub(monkeypatch, compat_module, version="0.13.0", requires=">=3.9")

        assert compat_module.hermes_python_compat()["verdict"] == "too_old"

    def test_placeholder_version_falls_back_to_specifier(self, monkeypatch, compat_module):
        """pyproject 是占位 0.0.0 时，版本归一为 None，但仍靠区间判出可共存。"""
        self._stub(monkeypatch, compat_module, version="0.0.0", requires=">=3.11,<3.15")

        result = compat_module.hermes_python_compat()

        assert result["verdict"] == "ok"
        assert result["version"] is None

    def test_unreadable_metadata_is_unknown_not_incompatible(
        self, monkeypatch, compat_module
    ):
        """识别不到一律按「未知」放行 —— 识别失败不等于不兼容。"""
        self._stub(monkeypatch, compat_module, version=None, requires=None)

        assert compat_module.hermes_python_compat()["verdict"] == "unknown"

    def test_detection_never_imports_hermes(self, monkeypatch, compat_module):
        """命门：判定过程不得把任何 Hermes 模块拉进 sys.modules。"""
        self._stub(monkeypatch, compat_module, version="0.19.0", requires=">=3.11,<3.14")
        before = set(sys.modules)

        compat_module.hermes_python_compat()

        leaked = {
            name for name in set(sys.modules) - before
            if name.split(".")[0] in ("hermes_cli", "run_agent", "hermes_constants", "hermes_bootstrap")
        }
        assert leaked == set()


class TestHermesVersionGate:
    """启动门禁：只有「明确过旧」才拦；识别不到时警告并继续。"""

    @staticmethod
    def _stub_state(monkeypatch, bootstrap, verdict):
        monkeypatch.setattr(bootstrap, "_hermes_compat_state", None)
        monkeypatch.setattr(
            bootstrap, "hermes_compat_state",
            lambda: {"verdict": verdict, "reason": "r", "version": "0.19.0", "python": "3.14.7"},
        )

    def test_too_old_is_rejected_with_actionable_steps(self, monkeypatch, capsys):
        """过旧时返回 False，并把三条可照做的升级步骤打到终端。"""
        from trade import bootstrap

        self._stub_state(monkeypatch, bootstrap, "too_old")

        assert bootstrap.check_hermes_version() is False
        out = capsys.readouterr().out
        assert "hermes update" in out          # 主路径命令必须出现
        assert "升级完成后" in out              # 收尾指引

    def test_unknown_warns_and_continues(self, monkeypatch, capsys):
        """拿不到版本（如 main 上无安装印章）→ 打印警告但继续启动。"""
        from trade import bootstrap

        self._stub_state(monkeypatch, bootstrap, "unknown")

        assert bootstrap.check_hermes_version() is True
        assert "无法确定" in capsys.readouterr().out

    def test_ok_is_accepted(self, monkeypatch, capsys):
        """可共存时正常通过。"""
        from trade import bootstrap

        self._stub_state(monkeypatch, bootstrap, "ok")

        assert bootstrap.check_hermes_version() is True
        assert "可共存" in capsys.readouterr().out


class TestUpgradeSteps:
    """给小白看的升级步骤：必须每条都能直接复制粘贴。"""

    def test_steps_are_copy_pasteable(self, compat_module):
        steps = compat_module.upgrade_steps()

        assert len(steps) == 3
        # 主路径就是上游自己的一键升级命令
        assert steps[0]["command"] == "hermes update"
        # 每条都必须带一条可直接复制的完整命令，不能是「运行相应的升级命令」这类空话
        assert all(step["command"].strip() for step in steps)

    def test_terminal_rendering_includes_every_command(self, compat_module):
        lines = "\n".join(compat_module.incompatible_upgrade_steps())

        for step in compat_module.upgrade_steps():
            assert step["command"] in lines


class TestDegradedStartup:
    """Hermes 过旧时必须**降级起服务**，而不是退出。

    这是整个方案的地基：桌面端（tradewin）先起服务线程再开窗口，一旦在起服务前退出，
    用户只会看到一个空白窗口。所以这里钉住两件事：跳过会 import Hermes 的步骤、
    且启动后台升级。
    """

    @staticmethod
    def _stub_setup(monkeypatch, bootstrap, *, usable, calls):
        """把 setup() 的每一步替换成记录器，只留我们要验证的分支逻辑。"""
        monkeypatch.setattr(bootstrap, "_disable_hermes_lazy_installs", lambda: None)
        monkeypatch.setattr(bootstrap, "_adjust_sys_path", lambda: None)
        monkeypatch.setattr(bootstrap, "dispatch_subcommands", lambda: False)
        monkeypatch.setattr(bootstrap, "check_native_architecture", lambda: True)
        monkeypatch.setattr(bootstrap, "check_hermes_version", lambda: usable)
        monkeypatch.setattr(bootstrap, "load_env_and_set_yolo", lambda: calls.append("env"))
        for name in ("sync_b2b_skills", "ensure_document_deps", "ensure_desktop_integration"):
            monkeypatch.setattr(bootstrap, name, (lambda n: lambda: calls.append(n))(name))
        monkeypatch.setattr(
            bootstrap, "_start_hermes_upgrade_in_background",
            lambda: calls.append("upgrade"),
        )
        monkeypatch.setattr(bootstrap, "start_doctor_if_needed", lambda: calls.append("doctor"))

    def test_too_old_skips_hermes_steps_and_starts_upgrade(self, monkeypatch, capsys):
        from trade import bootstrap

        calls: list[str] = []
        self._stub_setup(monkeypatch, bootstrap, usable=False, calls=calls)

        bootstrap.setup()  # 不抛 SystemExit 即通过

        assert "env" not in calls, "过旧时不该跑会 import Hermes 的步骤"
        assert "doctor" not in calls, "过旧时端到端自检要起 agent，必须跳过"
        assert "upgrade" in calls, "过旧时必须启动后台升级"
        # 不碰 Hermes 的步骤照常跑，保持功能完整
        assert "sync_b2b_skills" in calls and "ensure_desktop_integration" in calls
        assert "降级模式" in capsys.readouterr().out

    def test_optional_step_failure_does_not_block_startup(self, monkeypatch, capsys):
        """任一可选项抛异常都绝不能挡住起服务 —— 否则用户见不到升级界面。"""
        from trade import bootstrap

        calls: list[str] = []
        self._stub_setup(monkeypatch, bootstrap, usable=False, calls=calls)

        def _boom() -> None:
            raise RuntimeError("boom")

        # 让第一步就炸：降级模式仍必须走到「启动升级」
        monkeypatch.setattr(bootstrap, "sync_b2b_skills", _boom)

        bootstrap.setup()  # 不抛异常即通过

        assert "upgrade" in calls
        assert "跳过" in capsys.readouterr().out

    def test_usable_path_still_runs_hermes_steps(self, monkeypatch):
        """正常路径不受影响：该跑的 Hermes 步骤一个不少。"""
        from trade import bootstrap

        calls: list[str] = []
        self._stub_setup(monkeypatch, bootstrap, usable=True, calls=calls)

        bootstrap.setup()

        assert calls == ["env", "sync_b2b_skills", "ensure_document_deps",
                         "ensure_desktop_integration", "doctor"]
