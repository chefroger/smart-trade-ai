"""Trade AI Assistant — B2B business layer."""

from __future__ import annotations


def _resolve_version() -> str:
    """解析当前代码版本号（2026-11-20 审计 C3）。

    优先用安装元数据；打包环境（PyInstaller）没有元数据时，退回读与运行
    代码配套的 pyproject.toml（_MEIPASS 或源码目录上一级）。
    都拿不到返回空串 —— 导出的 app_version 会显示 unknown，不编造版本。
    """
    try:
        # editable / 正常安装都有这份元数据
        from importlib.metadata import version as _pkg_version

        v = str(_pkg_version("smart-trade-ai") or "").strip()
        # 元数据存在就优先用它（与 pip 安装记录一致）
        if v:
            return v
    except Exception:
        pass

    try:
        import sys
        import tomllib
        from pathlib import Path
    except ImportError:
        return ""

    candidates = []
    _meipass = getattr(sys, "_MEIPASS", None)
    # 打包目录里的副本与被冻结的代码版本一致
    if _meipass:
        candidates.append(Path(_meipass) / "pyproject.toml")
    candidates.append(Path(__file__).resolve().parent.parent / "pyproject.toml")
    for path in candidates:
        try:
            # 不存在就试下一个候选
            if not path.is_file():
                continue
            with open(path, "rb") as fh:
                data = tomllib.load(fh)
            v = str(data.get("project", {}).get("version") or "").strip()
            # 读到就返回，读不到继续找
            if v:
                return v
        except Exception:
            continue
    return ""


__version__ = _resolve_version()
