"""聊天副驾设置（用户级）。

铁律：**默认关闭**。副驾功能完工前，任何路径都不得因为这份设置把 Trade
主功能卡住 —— 读写失败一律回落默认值，不抛异常。

存储：`$TRADE_HOME/copilot.json`（默认 `~/.trade/copilot.json`）。
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# 隐私说明版本：用户看过并同意当前版本，副驾才允许开启。
# 文案/读取范围/数据去向发生实质变化时必须递增。
REQUIRED_CONSENT_VERSION = 1

DEFAULT_CLIPBOARD_MAX_CHARS = 3000


def _trade_home() -> Path:
    raw = os.environ.get("TRADE_HOME", "").strip()
    if raw:
        return Path(raw)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "trade"
    return Path.home() / ".trade"


def default_settings_path() -> Path:
    return _trade_home() / "copilot.json"


def default_hotkey() -> str:
    return "cmd+shift+space" if sys.platform == "darwin" else "ctrl+shift+space"


@dataclass
class CopilotSettings:
    """副驾用户设置。所有字段都有安全默认值。"""

    # 总开关：默认关；必须看过隐私说明（consent_version）才能开启。
    enabled: bool = False
    consent_version: int = 0
    # 剪贴板通道：默认关（任务书 §6）。
    use_clipboard: bool = False
    clipboard_max_chars: int = DEFAULT_CLIPBOARD_MAX_CHARS
    # 用户自定义拒读条目（内置类别在 capture.py）。
    refused_apps: list[str] = field(default_factory=list)
    hotkey: str = field(default_factory=default_hotkey)
    # 采用草稿后回写客户记忆：默认关。
    write_memory: bool = False

    def consent_ok(self) -> bool:
        return int(self.consent_version or 0) >= REQUIRED_CONSENT_VERSION

    def can_enable(self) -> bool:
        return self.consent_ok()

    def sanitized(self) -> CopilotSettings:
        """把越界/坏类型的值收回安全范围（不抛错）。"""
        try:
            limit = int(self.clipboard_max_chars)
        except (TypeError, ValueError):
            limit = DEFAULT_CLIPBOARD_MAX_CHARS
        self.clipboard_max_chars = limit if limit > 0 else DEFAULT_CLIPBOARD_MAX_CHARS
        try:
            self.consent_version = max(0, int(self.consent_version))
        except (TypeError, ValueError):
            self.consent_version = 0
        if not isinstance(self.refused_apps, list):
            self.refused_apps = []
        self.refused_apps = [str(x) for x in self.refused_apps if str(x).strip()]
        self.enabled = bool(self.enabled) and self.consent_ok()
        self.use_clipboard = bool(self.use_clipboard)
        self.write_memory = bool(self.write_memory)
        self.hotkey = str(self.hotkey or default_hotkey())
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> CopilotSettings:
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in (data or {}).items() if k in known}).sanitized()


def load_settings(path: Path | None = None) -> CopilotSettings:
    """读取设置；文件不存在/损坏/无权限 → 默认值（永不抛错）。"""
    target = path or default_settings_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return CopilotSettings()
        return CopilotSettings.from_dict(data)
    except Exception:
        return CopilotSettings()


def save_settings(settings: CopilotSettings, path: Path | None = None) -> bool:
    """原子写入设置；任何失败只返回 False，不影响调用方（尤其不阻断 Trade）。"""
    target = path or default_settings_path()
    payload = settings.sanitized().to_dict()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, target)
        return True
    except Exception:
        return False
