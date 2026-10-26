"""
Trade AI Assistant — 公司工作目录管理。

负责在用户桌面创建按外贸业务流程分类的目录结构，复制 .trade-template 模板骨架，
并将 workspace 子目录自动注册为 Hermes document library。
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

from trade import library as _library_module

# ── 工作目录分类 ──────────────────────────────────────────────────────────

# 每个公司自动在桌面创建的工作目录结构，每个子目录对应一条 library 记录
# 格式: (目录名, 描述)
_WORK_DIR_CATEGORIES: list[tuple[str, str]] = [
    ("报价单", "客户报价、价格谈判记录"),
    ("合同", "销售合同、采购合同、协议"),
    ("客户资料", "客户公司信息、联系人、需求"),
    ("产品规格", "产品参数表、规格书、技术文档"),
    ("发票", "商业发票、形式发票"),
    ("物流单据", "装箱单、提单、报关单、货运记录"),
    ("认证资质", "ISO认证、CE证书、检测报告"),
    ("营销素材", "产品图片、视频、公司介绍PPT、社媒素材"),
    ("海关数据", "进出口海关数据 CSV/Excel，采购商分析、贸易模式"),
]


# ── 基础目录工具 ──────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    """将公司名称转换为 URL 安全的 slug 标识（仅小写字母、数字、连字符）。

    用于生成文件系统目录名，确保跨平台兼容。
    当名称无法生成有效 slug 时，使用带随机后缀的唯一后备值，避免多公司冲突。
    """
    import uuid

    slug = name.lower().strip()
    if not slug:
        return f"company-{uuid.uuid4().hex[:6]}"  # 空输入 → 唯一后备值
    slug = re.sub(r"[^\w\s-]", "", slug)   # 移除非单词字符（Unicode 模式下 \w 含 CJK）
    slug = re.sub(r"[_\s]+", "-", slug)    # 下划线/空格 → 连字符
    slug = re.sub(r"--+", "-", slug)       # 合并连续连字符
    return slug.strip("-") or f"company-{uuid.uuid4().hex[:6]}"  # 兜底 → 唯一后缀


def _validate_slug(slug: str) -> str:
    """校验 slug 合法性（仅含字母数字和连字符，不含路径穿越字符）。

    Args:
        slug: 待校验的 slug 字符串

    Returns:
        合法的小写 slug

    Raises:
        ValueError: slug 包含非法字符或可能造成路径穿越
    """
    if not slug or not slug.strip():
        raise ValueError("Slug cannot be empty")
    slug = slug.strip().lower()
    if ".." in slug or "/" in slug or "\\" in slug:
        raise ValueError("Slug contains invalid characters")
    if not re.match(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", slug):
        raise ValueError(
            "Slug must contain only lowercase letters, digits, and hyphens"
        )
    return slug


# ── 模板目录创建 ──────────────────────────────────────────────────────────

def _ensure_data_dir(slug: str, trade_home: Path) -> Path:
    """创建并返回公司 slug 对应的数据目录（~/.trade/{slug}/）。

    复制 .trade-template 模板骨架，将内部的 'company-slug' 占位目录
    重命名为真实的 slug。模板目录结构：
      ~/.trade/{slug}/
        companies/{slug}/   ← 从 'company-slug' 重命名
        libraries/{slug}/
        clients/{slug}/

    Args:
        slug: 公司 slug 标识
        trade_home: Trade 数据根目录（~/.trade/）

    Returns:
        创建或已存在的公司数据目录路径
    """
    target = trade_home / slug

    # 模板源查找优先级：PyInstaller _MEIPASS > 运行时目录 > 开发目录
    _meipass = getattr(sys, "_MEIPASS", None)
    if _meipass:
        template_src = Path(_meipass) / ".trade-template"
    else:
        # 运行时目录优先（update_trade 同步后模板在此）
        _runtime_tmpl = trade_home / ".trade-template"
        if _runtime_tmpl.is_dir():
            template_src = _runtime_tmpl
        else:
            template_src = Path(__file__).resolve().parent.parent.parent / ".trade-template"

    if target.exists():
        return target  # 目标目录已存在，无需重复创建

    if template_src.exists():
        # 从源码目录复制模板骨架到用户数据目录
        shutil.copytree(template_src, target, dirs_exist_ok=False)
        # 将 companies/ 内部的占位目录 'company-slug' 重命名为真实 slug
        _rename_company_placeholder(target / "companies", slug)
        # 递归重命名嵌套的 'library-slug' / 'client-slug' 占位目录
        _rename_template_placeholders(target / "companies" / slug, slug)
    else:
        # 无模板可用时，直接创建空目录
        target.mkdir(parents=True, exist_ok=True)

    return target


def _rename_company_placeholder(companies_dir: Path, slug: str) -> None:
    """将 companies/ 内部的 'company-slug' 目录重命名为真实 slug。"""
    src = companies_dir / "company-slug"
    dst = companies_dir / slug
    if src.exists() and not dst.exists():
        src.rename(dst)


def _rename_template_placeholders(base: Path, slug: str) -> None:
    """递归将模板中的 'library-slug' 和 'client-slug' 占位目录重命名为真实 slug。

    模板中预设了这些占位目录，创建公司时需要用公司 slug 替换。
    """
    if not base.is_dir():
        return
    for p in sorted(base.rglob("*")):
        if p.is_dir():
            if p.name in ("library-slug", "client-slug"):
                p.rename(p.parent / slug)


# ── 桌面路径获取 ──────────────────────────────────────────────────────────

def _get_desktop_path() -> Path:
    """获取当前用户的实际桌面路径（处理 OneDrive 重定向等场景）。

    Windows 上使用 SHGetFolderPathW API 获取真实桌面路径，
    macOS/Linux 回退到 ~/Desktop。
    """
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            # CSIDL_DESKTOPDIRECTORY = 16，获取物理桌面路径（含 OneDrive 重定向）
            ctypes.windll.shell32.SHGetFolderPathW(None, 16, None, 0, buf)
            desktop = buf.value.strip()
            if desktop and Path(desktop).is_dir():
                return Path(desktop)
        except Exception:
            pass
        # API 调用失败时回退到 USERPROFILE\Desktop
        fallback = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
        if fallback.is_dir():
            return fallback
        return Path.home()

    # macOS / Linux
    desktop = Path.home() / "Desktop"
    if desktop.is_dir():
        return desktop
    # macOS 中文语言环境
    desktop_cn = Path.home() / "桌面"
    if desktop_cn.is_dir():
        return desktop_cn
    return Path.home()


# ── 桌面工作目录创建 ──────────────────────────────────────────────────────

def _setup_work_directory(
    company_name: str, slug: str, suggested_name: str = ""
) -> tuple[Path, bool]:
    """在用户桌面创建公司工作目录，包含外贸业务流程分类子目录。

    如果目标目录已存在，自动尝试加数字后缀（如 "我的公司-2"）。
    在 pytest 测试环境中将目录写到临时位置而非桌面。

    Args:
        company_name: 公司名称（用作默认目录名）
        slug: 公司 slug（用于路径穿越校验）
        suggested_name: 用户指定的替代目录名（重命名场景），为空则用公司名

    Returns:
        (work_dir_path, is_new) — 目录绝对路径 + 是否为新创建
    """
    # 测试环境检测：pytest 在 sys.modules 中 → 写到临时目录而非桌面
    _in_test = "pytest" in sys.modules
    if _in_test:
        trade_home = os.environ.get("TRADE_HOME", "")
        if trade_home:
            base = Path(trade_home) / "work"
        else:
            import tempfile
            base = Path(tempfile.mkdtemp(prefix="trade-work-"))
    else:
        base = _get_desktop_path()

    # 确定目录名（用户指定优先，否则用公司名）
    dir_name = (suggested_name.strip() if suggested_name.strip()
                else company_name.strip())

    # 路径穿越防护：目录名不能包含 .. 或 NUL
    if ".." in dir_name or "\0" in dir_name:
        raise ValueError("Invalid directory name")

    # 清理文件名中的非法字符（<>"/\|?* → 连字符）
    dir_name = re.sub(r'[<>:"/\\|?*]', '-', dir_name).strip()

    work_dir = base / dir_name

    # 二次确认：解析后的路径必须在 base 子目录内（防御组合攻击）
    try:
        work_dir.resolve().relative_to(base.resolve())
    except ValueError:
        raise ValueError("Path traversal detected")

    is_new = True

    # 同名目录已存在时，数字后缀递增直到找到空闲名称
    if work_dir.exists():
        suffix = 2
        while True:
            alt_name = f"{dir_name}-{suffix}"
            alt_dir = base / alt_name
            if not alt_dir.exists():
                work_dir = alt_dir
                break
            suffix += 1
            if suffix > 99:
                # 极端情况：1-99 后缀全被占用 → 用时间戳兜底
                import time
                ts = int(time.time())
                work_dir = base / f"{dir_name}-{ts}"
                while work_dir.exists():
                    ts += 1
                    work_dir = base / f"{dir_name}-{ts}"
                break
        is_new = False

    # 创建目录结构（exist_ok=True 防止 TOCTOU 竞争条件）
    work_dir.mkdir(parents=True, exist_ok=True)
    for cat_name, _ in _WORK_DIR_CATEGORIES:
        (work_dir / cat_name).mkdir(parents=True, exist_ok=True)

    return work_dir, is_new


def _register_work_libraries(company_id: int, work_dir: Path) -> list[dict]:
    """将工作目录的每个子目录注册为 Hermes document library。

    为 _WORK_DIR_CATEGORIES 中定义的每个分类目录创建一条 library 记录，
    使 Hermes Agent 能通过 read_file / search_files 工具访问这些目录。

    Args:
        company_id: 公司数据库 ID
        work_dir: 工作目录根路径

    Returns:
        创建的 library 记录列表（每个元素含 id/name/root_path 等字段）
    """
    libraries = []
    for cat_name, cat_desc in _WORK_DIR_CATEGORIES:
        cat_path = work_dir / cat_name
        lib = _library_module.create(
            name=cat_name,
            root_path=str(cat_path),
            description=cat_desc,
            company_id=company_id,
        )
        libraries.append(lib)
    return libraries
