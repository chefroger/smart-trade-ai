"""Hermes provider、模型和认证接口的兼容适配。"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any


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
