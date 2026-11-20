"""Trade AI Assistant — B2B business layer."""

from __future__ import annotations


def _resolve_version() -> str:
    """解析当前代码版本号（2026-11-20 审计 C3）。

    **pyproject.toml 优先**：它描述的是「正在运行这份代码」的版本。
    pip 的安装元数据可能是旧的 —— editable 安装后改了 pyproject 却没重跑
    `pip install -e .`，元数据会一直停在旧值（实测 0.6.8 vs 实际 0.7.7），
    拿它当版本号会让导出包和界面都显示错误版本。
    元数据只作兜底（打包环境往往只带元数据、不带 pyproject）。
    都拿不到返回空串 —— 导出的 app_version 会显示 unknown，不编造版本。
    """
    try:
        import sys
        import tomllib
        from pathlib import Path
    except ImportError:
        tomllib = None

    if tomllib is not None:
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

    try:
        # 兜底：没有 pyproject 的打包/安装环境
        from importlib.metadata import version as _pkg_version

        return str(_pkg_version("smart-trade-ai") or "").strip()
    except Exception:
        return ""


__version__ = _resolve_version()
