"""Hermes provider、模型和认证接口的兼容适配。"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

# ── Hermes 版本识别 ──────────────────────────────────────────────────────────
# 上游 main 把 hermes_cli.__version__ 改为惰性实现：只读安装印章
# install-stamp.json，读不到就返回 "0.0.0"（见 hermes_cli/__init__.py 的
# __getattr__，那是给旧更新器留的兼容面）。官方新口径是
# hermes_cli.version_info.get_version_info()：安装印章 → live git → unknown，
# 且明确选择降级而不是崩。
# Trade 只拿这个版本做启动门禁，所以必须区分「真实版本」与「识别不到」。

# 不是真实版本号的占位值（上游无安装印章时返回 0.0.0）
_VERSION_PLACEHOLDERS = frozenset({"", "0.0.0", "0.0.0.0", "unknown", "none", "dev"})


def _public_version_info() -> str | None:
    """新版 Hermes 的 base_version；接口不存在时返回 None。"""
    try:
        from hermes_cli.version_info import get_version_info
    except (ImportError, AttributeError):
        return None
    try:
        base = getattr(get_version_info(), "base_version", "") or ""
    except Exception:
        # 版本识别失败不应影响启动，交给调用方按「未知」处理
        return None
    return str(base) or None


def _legacy_version() -> str | None:
    """旧版 Hermes 的 hermes_cli.__version__ 字面量；不存在时返回 None。"""
    try:
        from hermes_cli import __version__ as version
    except (ImportError, AttributeError):
        return None
    return str(version) or None


def _checkout_version() -> str | None:
    """读 Hermes checkout 自带 pyproject.toml 的 version；读不到返回 None。"""
    try:
        import hermes_cli
        pyproject = Path(hermes_cli.__file__).resolve().parent.parent / "pyproject.toml"
        if not pyproject.is_file():
            return None
        import tomllib
        # 显式 utf-8：Windows 默认 cp1252
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        return str(data.get("project", {}).get("version", "")) or None
    except Exception:
        return None


def _is_real_version(value: str | None) -> bool:
    """判断是否是可用于 PEP 440 比较的真实版本号。"""
    if not value or value.strip().lower() in _VERSION_PLACEHOLDERS:
        return False
    try:
        from packaging.version import InvalidVersion, Version
    except ImportError:
        # 无法校验时保守认为可用，交给上层比较
        return True
    try:
        Version(value.strip())
    except InvalidVersion:
        return False
    return True


def hermes_version() -> str | None:
    """返回可比较的 Hermes 版本号；识别不到时返回 None。

    解析顺序（与上游 get_version_info 的口径一致）：
      1. hermes_cli.version_info.get_version_info().base_version（新版）
      2. hermes_cli.__version__（旧版字面量）
      3. checkout 里的 pyproject.toml（上游把版本号挪走时的兜底）

    占位值（0.0.0）与无法解析的字符串一律按「未知」返回 None ——
    调用方据此放宽门禁，而不是把识别失败当成版本不兼容。
    """
    for probe in (_public_version_info, _legacy_version, _checkout_version):
        value = probe()
        if _is_real_version(value):
            return str(value).strip()
    return None


# ── Python 共存判定（不导入 Hermes）────────────────────────────────────────
# Trade 是**进程内**嵌 Hermes（`from run_agent import AIAgent`），所以 Trade 的解释器
# 必须能加载 Hermes 及其全部依赖。而 Hermes 从 v0.21.6 起改为只支持 Python 3.14
# （requires-python 上界从 <3.14 翻到 <3.15），上一代则硬性要求 <3.14：
# 实测 3.14 下装 0.19.0 直接 `ERROR: Package 'hermes-agent' requires a different Python`。
# 两侧互斥，因此「旧 Hermes + 新版 Trade」永远不可能共存 —— 必须先升级 Hermes。
#
# 为什么不用 `import` 判：旧 Hermes 跑在 3.14 上，崩点是**缺依赖的 ImportError**，
# 不是版本错。用户看到的是天书，而我们需要的是「版本过旧、去升级」这个可行动的结论。

# 分界版本：这一版起上游才把 Python 支持上界抬到 3.14（也是 `pm` 托管运行时的起点）
_MIN_HERMES_VERSION_314 = "0.21.6"


def _checkout_pyproject() -> Path | None:
    """不导入 Hermes，直接定位 checkout 的 pyproject.toml；找不到返回 None。

    复用 `trade.bootstrap._resolve_hermes_checkout()`（纯路径判定，含 `hermes_cli/` 目录
    才算数）。延迟导入避免模块级循环：bootstrap 也在函数内延迟导入本模块。
    """
    try:
        from trade.bootstrap import _resolve_hermes_checkout
    except ImportError:
        return None
    checkout = _resolve_hermes_checkout()
    # 没解析到 checkout（未安装 Hermes）→ 交给上层按「未知」处理
    if not checkout:
        return None
    pyproject = Path(checkout) / "pyproject.toml"
    return pyproject if pyproject.is_file() else None


def _stamp_version() -> str | None:
    """读 checkout 根目录 install-stamp.json 的版本；读不到返回 None。

    上游把 pyproject 的 version 改成了占位 `0.0.0`（真实版本只在安装印章里），
    所以印章才是权威来源 —— 这与上游 version_info 的口径一致，只是不导入模块。
    """
    pyproject = _checkout_pyproject()
    if pyproject is None:
        return None
    stamp = pyproject.parent / "install-stamp.json"
    if not stamp.is_file():
        return None
    try:
        import json

        data = json.loads(stamp.read_text(encoding="utf-8-sig"))
    except Exception:
        # 印章损坏不应阻断启动，回退到 pyproject
        return None
    if not isinstance(data, dict):
        return None
    # baseVersion 优先（纯净版本号），displayVersion 带 +N.gHASH 派生后缀作兜底
    for key in ("baseVersion", "displayVersion", "version"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _read_checkout_metadata() -> tuple[str | None, str | None]:
    """读 checkout 的 (version, requires-python)；读不到的各项返回 None。

    version 取安装印章优先、pyproject 兜底。显式 utf-8：上游 pyproject 含非 ASCII
    注释，Windows 默认 cp1252 会解码失败。
    """
    version = _stamp_version()
    pyproject = _checkout_pyproject()
    if pyproject is None:
        return version, None
    try:
        import tomllib

        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except Exception:
        # 元数据读取失败不应阻断启动，交给上层按「未知」处理
        return version, None
    project = data.get("project", {})
    if not isinstance(project, dict):
        return version, None
    if version is None:
        version = str(project.get("version", "") or "") or None
    requires = str(project.get("requires-python", "") or "") or None
    return version, requires


def hermes_python_compat() -> dict[str, Any]:
    """判定已安装的 Hermes 能否与当前 Python 解释器共存；**全程不导入 Hermes**。

    判据取 Hermes 自己声明的 `requires-python`（机械真相，不依赖我们对版本号的理解），
    并用版本号下限做交叉确认——因为极老的版本可能声明了一个宽松的区间，但其依赖
    在 3.14 上照样装不出来。

    Returns:
        dict，字段：
          verdict: "ok" | "too_old" | "unknown"
          version: 读到的 Hermes 版本（识别不到为 None）
          requires_python: checkout 声明的 Python 区间
          python: 当前解释器版本（如 "3.14.7"）
          checkout: 解析到的 Hermes 源码目录
          reason: 给人看的判定依据（用于报错文案）
    """
    python_version = ".".join(str(part) for part in sys.version_info[:3])
    version, requires_python = _read_checkout_metadata()
    checkout = _checkout_pyproject()

    result: dict[str, Any] = {
        "verdict": "unknown",
        # 占位值（0.0.0）统一归一为 None —— 给用户看的版本号必须是真实版本
        "version": version if _is_real_version(version) else None,
        "requires_python": requires_python,
        "python": python_version,
        "checkout": str(checkout.parent) if checkout else None,
        "reason": "",
    }

    # 判据一：Hermes 声明的 Python 区间是否包含当前解释器。
    # 这是**权威判据**（上游自己声明的机械真相）：区间可解析且包含当前解释器时，
    # 即使版本号读不到（pyproject 是占位 0.0.0 且无印章）也能直接判「可共存」。
    requires_ok = False
    if requires_python:
        try:
            from packaging.specifiers import SpecifierSet

            if SpecifierSet(requires_python).contains(python_version):
                requires_ok = True
            else:
                result["verdict"] = "too_old"
                result["reason"] = (
                    f"Hermes 声明的 Python 区间 {requires_python} 不包含当前解释器 {python_version}"
                )
                return result
        except Exception:
            # 区间不可解析 → 不据此下结论，退化到版本号那条判据
            pass

    # 判据二：版本号下限（`pm` 托管运行时与 3.14 支持的起点）。
    # 极老的版本可能声明了宽松区间，但其依赖在 3.14 上照样装不出来，故需交叉确认。
    if _is_real_version(version):
        try:
            from packaging.version import Version

            if Version(str(version)) < Version(_MIN_HERMES_VERSION_314):
                result["verdict"] = "too_old"
                result["reason"] = (
                    f"Hermes {version} 低于共存所需的最低版本 {_MIN_HERMES_VERSION_314}"
                )
                return result
            requires_ok = True
        except Exception:
            pass

    # 任一判据确认可共存 → ok；两条都无结论 → unknown（识别失败不等于不兼容，
    # 与既有门禁口径一致，放宽放行以免误拦可用环境）
    if requires_ok:
        result["verdict"] = "ok"
        result["reason"] = f"Hermes 支持当前解释器 {python_version}"
        return result
    result["reason"] = "无法确定 Hermes 版本或 Python 区间，按未知放行"
    return result


def upgrade_steps() -> list[dict[str, str]]:
    """给用户照着做的 Hermes 升级步骤（结构化，终端与界面共用同一份文案）。

    受众是电脑小白：每一步都给**可直接复制粘贴**的完整命令，不写「运行相应的升级命令」
    这类需要用户自己推导的话。文案只有这一处来源，终端与前端都从这里取，避免两边漂移。

    Returns:
        步骤列表，每项 {"title": 标题, "detail": 怎么做, "command": 可复制的命令}。
    """
    # Windows 的重装命令与 POSIX 不同（PowerShell 没有 curl/bash 管道写法）
    reinstall = (
        "irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1 | iex"
        if os.name == "nt"
        else "curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash"
    )
    return [
        {
            "title": "让 Hermes 自己升级（最简单）",
            "detail": "复制下面这一行，粘贴到终端后回车，等它跑完。",
            "command": "hermes update",
        },
        {
            "title": "让 AI 帮你升级",
            "detail": "打开 Hermes，把下面这句话整句复制粘贴进去。",
            "command": "请把我自己的 Hermes 升级到最新版本",
        },
        {
            "title": "前两种都不行时，重装 Hermes",
            "detail": "复制下面这一行，粘贴到终端后回车。",
            "command": reinstall,
        },
    ]


def incompatible_upgrade_steps() -> list[str]:
    """把 upgrade_steps() 渲染成终端可读的行（给能看见终端的用户）。"""
    lines = ["", "【现在照着做 —— 三种方式，推荐第 1 种】", ""]
    for index, step in enumerate(upgrade_steps(), start=1):
        lines.append(f"{index}) {step['title']}")
        lines.append(f"   {step['detail']}")
        lines.append(f"       {step['command']}")
        lines.append("")
    lines.append("升级完成后，重新运行：  trade")
    return lines


def _public_provider_catalog() -> list[Any] | None:
    """读取 Hermes 新版统一 provider catalog；接口不存在时返回 None。"""
    try:
        from hermes_cli.provider_catalog import provider_catalog
    except (ImportError, AttributeError):
        return None
    return list(provider_catalog())


def _public_provider_models(provider: str) -> list[str] | None:
    """读取 Hermes 动态模型目录；接口不存在时返回 None。"""
    try:
        from hermes_cli.models import provider_model_ids
    except (ImportError, AttributeError):
        return None
    return list(provider_model_ids(provider))


def _public_auth_status(provider: str) -> dict[str, Any] | None:
    """读取 Hermes 统一认证状态；接口不存在时返回 None。"""
    try:
        from hermes_cli.auth import get_auth_status
    except (ImportError, AttributeError):
        return None
    status = get_auth_status(provider)
    return status if isinstance(status, dict) else None


def _legacy_registry() -> dict[str, Any]:
    """读取旧版 Hermes provider 注册表。"""
    try:
        from hermes_cli.auth import PROVIDER_REGISTRY
        registry = PROVIDER_REGISTRY
        if not isinstance(registry, dict):
            registry = getattr(getattr(sys.modules.get("hermes_cli"), "auth", None), "PROVIDER_REGISTRY", {})
    except (ImportError, AttributeError):
        registry = getattr(getattr(sys.modules.get("hermes_cli"), "auth", None), "PROVIDER_REGISTRY", {})
    return dict(registry) if isinstance(registry, dict) else {}


def _legacy_models(provider: str) -> list[str]:
    """读取旧版 Hermes 静态模型表，仅作为兼容兜底。"""
    try:
        from hermes_cli.models import _PROVIDER_MODELS
    except (ImportError, AttributeError):
        return []
    return list(_PROVIDER_MODELS.get(provider, []))


def _active_model_config() -> tuple[str, str]:
    """读取当前 provider 和 model，兼容 Hermes 两种配置格式。"""
    try:
        from hermes_cli.config import load_config
        config = load_config()
        if not isinstance(config, dict):
            hermes_cli = sys.modules.get("hermes_cli")
            config_module = hermes_cli.config if hermes_cli is not None else None
            config = config_module.load_config() if config_module is not None else {}
    except (ImportError, AttributeError):
        return "", ""
    model = config.get("model", {}) if isinstance(config, dict) else {}
    if isinstance(model, dict):
        return str(model.get("provider") or ""), str(model.get("default") or "")
    if isinstance(model, str):
        if ":" in model:
            provider, _, model_name = model.partition(":")
            return provider.strip(), model_name.strip()
        if "/" in model:
            provider, _, model_name = model.partition("/")
            return provider.strip(), model_name.strip()
        return "", model.strip()
    return "", ""


def _legacy_auth_status(provider: str, config: Any) -> dict[str, Any]:
    """按旧版 ProviderConfig 判断认证状态。"""
    if getattr(config, "auth_type", "") != "api_key":
        return {"logged_in": bool(config)}
    env_names = getattr(config, "api_key_env_vars", ()) or ()
    configured = any(os.getenv(name, "").strip() for name in env_names)
    return {"logged_in": configured, "auth_type": "api_key"}


def _record(provider_id: str, config: Any, public_catalog: bool) -> dict[str, Any]:
    """组合单个 provider 的稳定响应记录。"""
    name = getattr(config, "label", "") or getattr(config, "display_name", "") or provider_id
    auth_type = getattr(config, "auth_type", "") or "api_key"
    status = _public_auth_status(provider_id) if public_catalog else None
    if status is None:
        status = _legacy_auth_status(provider_id, config)
    models = _public_provider_models(provider_id) if public_catalog else None
    if models is None:
        models = _legacy_models(provider_id)
    logged_in = bool(status.get("logged_in") or status.get("configured"))
    return {
        "id": provider_id,
        "name": name,
        "auth_type": auth_type,
        "auth_status": status,
        "has_key": logged_in,
        "models": models[:50],
    }


def list_provider_records() -> list[dict[str, Any]]:
    """返回归一化 provider 记录，优先使用 Hermes 新版公开接口。"""
    catalog = _public_provider_catalog()
    if catalog is not None:
        records = []
        for item in catalog:
            provider_id = str(getattr(item, "slug", "") or "").strip()
            if provider_id:
                records.append(_record(provider_id, item, True))
        return records

    return [_record(provider_id, config, False) for provider_id, config in _legacy_registry().items()]


def current_model_config() -> tuple[str, str]:
    """返回当前 provider 和 model。"""
    return _active_model_config()


def snapshot_read_coverage(task_id: str) -> dict[str, dict[str, Any]] | None:
    """读取 Hermes 当前 task 的文件 coverage 快照；旧版没有接口时返回 None。"""
    try:
        from tools.file_read_coverage import snapshot_read_coverage as _snapshot
    except (ImportError, AttributeError):
        return None
    snapshot = _snapshot(task_id)
    return snapshot if isinstance(snapshot, dict) else None


def release_read_coverage(task_id: str) -> None:
    """释放指定 task 的读取记录；旧版 Hermes 没有该接口时静默跳过。"""
    if not task_id:
        return
    try:
        from tools.file_read_coverage import release_read_coverage as _release
    except (ImportError, AttributeError):
        return
    try:
        _release(task_id)
    except Exception:
        logging.getLogger(__name__).debug("release_read_coverage failed", exc_info=True)


def provider_is_configured(provider: str) -> bool | None:
    """返回 provider 是否已认证；无法使用新版认证接口时返回 None。"""
    status = _public_auth_status(provider)
    if status is not None:
        return bool(status.get("logged_in") or status.get("configured"))
    config = _legacy_registry().get(provider)
    if config is None:
        return False
    return bool(_legacy_auth_status(provider, config).get("logged_in"))
