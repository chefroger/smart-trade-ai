"""
Trade AI Assistant — 文档库管理 API 路由。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from trade import library as library_module
from trade.api.deps import require_company
from trade.api.models import LibraryCreate, LibraryUpdate

router = APIRouter(tags=["libraries"])


@router.post("/upload-files")
async def upload_to_work_dir(
    subdir: str = Form(),
    files: list[UploadFile] = File(),  # noqa: B008
    x_company_id: int = Depends(require_company),
):
    """上传文件到公司桌面工作目录的指定子目录。

    拖入文件/目录后，用户选择一个子目录（如「合同」），
    文件写入该子目录下，保留浏览器传来的相对路径结构。
    """
    # 1. 校验子目录名（与 company.py _WORK_DIR_CATEGORIES 同步）
    from trade.company import _WORK_DIR_CATEGORIES
    _valid_subdirs = frozenset(name for name, _ in _WORK_DIR_CATEGORIES)
    if subdir not in _valid_subdirs:
        raise HTTPException(status_code=400, detail=f"无效的子目录: {subdir}")

    # 2. 获取公司桌面工作目录：从 extra1 取已保存的路径，不存在时重建
    from trade import company as _co
    co = _co.get(x_company_id)
    if not co:
        raise HTTPException(status_code=404, detail="公司不存在")

    work_dir = None
    tc = _co.get_trade_company(x_company_id)
    if tc and tc.get("extra1"):
        # 已保存的工作目录路径，直接使用
        import json as _json
        try:
            _extra = _json.loads(tc["extra1"])
            saved = Path(_extra.get("work_dir", ""))
            if saved.is_dir():
                work_dir = saved
        except Exception:
            pass

    if work_dir is None:
        # 没有保存过路径，在桌面上查找公司名匹配的已存在目录。
        # 必须用 workdir._get_desktop_path()（Windows 走 SHGetFolderPathW 拿真实桌面）——
        # 自己猜 ~/Desktop 在 OneDrive 重定向桌面（C:\Users\x\OneDrive\Desktop）时
        # 找不到真实目录，于是新建一个「公司名-2」，而文档库记录仍指向原目录
        # → AI 读不到刚上传的文件。
        import re as _re

        from trade.company.workdir import _get_desktop_path

        co_name_clean = _re.sub(r'[<>:"/\\|?*]', '-', co["name"]).strip()
        candidate = _get_desktop_path() / co_name_clean
        if candidate.is_dir():
            work_dir = candidate
        if work_dir is None:
            # 实在找不到，创建新目录
            from trade.company import _setup_work_directory
            work_dir, _ = _setup_work_directory(co["name"], co["slug"])
        # 保存路径供后续使用
        try:
            import json as _json
            _co.update_trade_company(x_company_id, extra1=_json.dumps({"work_dir": str(work_dir)}))
        except Exception:
            pass

    target_dir = work_dir / subdir
    target_dir.mkdir(parents=True, exist_ok=True)

    # 3. 路径穿越检测 + 文件大小限制
    _path_traversal_pattern = re.compile(r"\.\.|^[/\\]|[<>:\"|?*]")
    _MAX_FILE_BYTES = 100 * 1024 * 1024  # 单文件 100MB 上限

    uploaded = []
    for f in files:
        rel = getattr(f, "filename", "") or ""
        if not rel:
            rel = os.path.basename(f.filename or "untitled")

        parts = Path(rel).parts
        safe_parts = []
        for p in parts:
            if _path_traversal_pattern.search(p):
                cleaned = p.replace("..", "_")
                cleaned = re.sub(r"[<>:\"|?*]", "_", cleaned)
                safe_parts.append("_sanitized_" + cleaned)
            else:
                safe_parts.append(p)
        safe_parts = [p for p in safe_parts if p and p != "."]
        if not safe_parts:
            safe_parts = ["untitled"]

        dest = target_dir.joinpath(*safe_parts)
        try:
            dest.resolve().relative_to(work_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"路径穿越拒绝: {rel}")

        dest.parent.mkdir(parents=True, exist_ok=True)
        # NUL 字节拒绝
        if "\0" in rel:
            raise HTTPException(status_code=400, detail="文件名含非法字符")
        # 逐个文件大小预检（利用 Starlette 在 multipart part header 中的 size 信息）
        f_size = getattr(f, "size", None)
        if f_size is not None and f_size > _MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail=f"文件过大: {rel} ({f_size} bytes)")
        # 分块读取防止内存耗尽：达到上限即中止
        chunks = []
        total = 0
        while True:
            chunk = await f.read(1024 * 1024)  # 1MB 分块
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_FILE_BYTES:
                raise HTTPException(status_code=413, detail=f"文件过大: {rel}")
            chunks.append(chunk)
        content = b"".join(chunks)
        if not content:
            raise HTTPException(status_code=400, detail=f"空文件: {rel}")
        dest.write_bytes(content)
        uploaded.append(str(dest.relative_to(work_dir)))

    return {
        "uploaded": len(uploaded),
        "files": uploaded,
        "target_path": str(target_dir),
    }


@router.get("/libraries")
def list_libraries(
    x_company_id: int = Depends(require_company),
):
    """列出当前公司的所有文档库。"""
    return library_module.list_by_company(x_company_id)


@router.post("/libraries")
def create_library(
    payload: LibraryCreate,
    x_company_id: int = Depends(require_company),
):
    """创建文档库（关联到当前公司下的本地目录）。"""
    return library_module.create(
        payload.name, payload.root_path, payload.description,
        company_id=x_company_id,
    )


@router.get("/libraries/{library_id}")
def get_library(
    library_id: int,
    x_company_id: int = Depends(require_company),
):
    """获取单个文档库详情。"""
    lib = library_module.get(library_id, company_id=x_company_id)
    if not lib:
        raise HTTPException(status_code=404, detail="Library not found")
    return lib


@router.put("/libraries/{library_id}")
def update_library(
    library_id: int,
    payload: LibraryUpdate,
    x_company_id: int = Depends(require_company),
):
    """更新文档库字段。"""
    kwargs = payload.model_dump(exclude_none=True)
    result = library_module.update(library_id, company_id=x_company_id, **kwargs)
    if not result:
        raise HTTPException(status_code=404, detail="Library not found")
    return result


@router.delete("/libraries/{library_id}")
def delete_library(
    library_id: int,
    x_company_id: int = Depends(require_company),
):
    """删除文档库。"""
    if not library_module.delete(library_id, company_id=x_company_id):
        raise HTTPException(status_code=404, detail="Library not found")
    return {"ok": True}


@router.get("/libraries/{library_id}/files")
def count_library_files(
    library_id: int,
    x_company_id: int = Depends(require_company),
):
    """统计文档库目录中的文件数量。"""
    lib = library_module.get(library_id, company_id=x_company_id)
    if not lib:
        raise HTTPException(status_code=404, detail="Library not found")
    return {"count": library_module.count_files(library_id, company_id=x_company_id)}
