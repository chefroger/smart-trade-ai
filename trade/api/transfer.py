"""公司数据导出 / 导入 API。"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from tempfile import mkstemp
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from trade.api.deps import require_company, require_session
from trade.company.transfer import (
    MAX_PACKAGE_BYTES,
    AmbiguousCompanyError,
    PackageTooLargeError,
    TransferError,
)
from trade.company.transfer.exporter import export_company
from trade.company.transfer.importer import import_company

router = APIRouter(tags=["company-transfer"])

MAX_UPLOAD_BYTES = MAX_PACKAGE_BYTES + (100 << 20)
_RATE_LOCK = threading.Lock()
_RATE: dict[str, list[float]] = {}
_JOBS: dict[str, dict] = {}
_JOB_LOCK = threading.Lock()
_MAX_JOBS = 100
_JOB_TTL = 24 * 3600


def _prune_jobs() -> None:
    """清掉过期任务，避免长期运行时 `_JOBS` 无限增长（审计 O-4）。"""
    now = time.time()
    with _JOB_LOCK:
        stale = [key for key, job in _JOBS.items()
                 if now - job.get("updated_at", 0) > _JOB_TTL]
        for key in stale:
            _JOBS.pop(key, None)
        for key in list(_JOBS)[:max(0, len(_JOBS) - _MAX_JOBS)]:
            _JOBS.pop(key, None)


def _rate_ok(key: str, limit: int, window: float) -> bool:
    now = time.monotonic()
    with _RATE_LOCK:
        stamps = [stamp for stamp in _RATE.get(key, []) if now - stamp < window]
        if len(stamps) >= limit:
            _RATE[key] = stamps
            return False
        stamps.append(now)
        _RATE[key] = stamps
        return True


def _cleanup(path: str) -> None:
    Path(path).unlink(missing_ok=True)


def _set_job(job_id: str, **updates) -> None:
    with _JOB_LOCK:
        job = _JOBS.setdefault(job_id, {})
        job.update(updates)
        job["updated_at"] = time.time()


def _run_import(job_id: str, zip_path: Path, target_company_id: int | None,
                force_new: bool) -> None:
    _set_job(job_id, status="running", phase="importing")
    try:
        report = import_company(
            zip_path, target_company_id=target_company_id, force_new=force_new
        )
        _set_job(job_id, status="done", phase="done", report=report)
    except AmbiguousCompanyError as exc:
        _set_job(job_id, status="error", code="ambiguous_company",
                 candidates=exc.candidates, error=str(exc))
    except TransferError as exc:
        _set_job(job_id, status="error", code="invalid_package", error=str(exc))
    except Exception as exc:  # noqa: BLE001 — 返回可读错误
        _set_job(job_id, status="error", code="import_failed", error=str(exc))
    finally:
        zip_path.unlink(missing_ok=True)


@router.get("/companies/{company_id}/export")
def export_company_package(company_id: int, cid: int = Depends(require_company)):
    """下载单个公司的数据包。"""
    if cid != company_id:
        raise HTTPException(status_code=403, detail="导出目标与 X-Company-ID 不一致")
    if not _rate_ok(f"export:{cid}", 2, 60):
        raise HTTPException(status_code=429, detail="导出过于频繁，请稍后再试")
    try:
        result = export_company(company_id)
    except PackageTooLargeError as exc:
        return JSONResponse(
            status_code=413,
            content={
                "code": "package_too_large",
                "limit_bytes": exc.limit_bytes,
                "measured_bytes": exc.measured_bytes,
                "hint": "数据包过大（压缩后 >1GB 或解压后超过导入上限），请手动拷贝数据库、公司目录和桌面资料库",
                "paths": exc.paths,
            },
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = f"trade-company-{(result['company'].get('slug') or company_id)}.zip"
    # 桌面目录超限时包内不含资料库文件：把「需手动拷贝」的路径带到响应头，
    # 前端下载完据此提醒；放在 manifest 里用户看不到。
    headers: dict[str, str] = {}
    if result.get("manual_paths") or result.get("warnings"):
        payload = json.dumps({
            "manual_paths": result.get("manual_paths") or [],
            "warnings": result.get("warnings") or [],
        }, ensure_ascii=False)
        headers["X-Trade-Export-Warnings"] = quote(payload, safe="")
    return FileResponse(
        result["path"],
        media_type="application/zip",
        filename=filename,
        headers=headers,
        background=BackgroundTask(_cleanup, result["path"]),
    )


@router.post("/companies/import-package", status_code=202)
async def import_company_package(
    file: Annotated[UploadFile, File()],
    target_company_id: Annotated[int | None, Form()] = None,
    force_new: Annotated[bool, Form()] = False,
    _session: str = Depends(require_session),
):
    """上传公司数据包，后台导入并返回 job_id。

    注意：调用方不要带 X-Company-ID；新公司尚未绑定。
    """
    if not _rate_ok("import", 1, 300):
        raise HTTPException(status_code=429, detail="导入过于频繁，请稍后再试")
    fd, temp_name = mkstemp(prefix="trade-company-upload-", suffix=".zip")
    total = 0
    try:
        with open(fd, "wb") as out:
            while True:
                chunk = await file.read(1 << 20)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="数据包超过上传上限")
                out.write(chunk)
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    _prune_jobs()
    job_id = uuid.uuid4().hex
    _set_job(job_id, status="queued", phase="queued")
    thread = threading.Thread(
        target=_run_import,
        args=(job_id, Path(temp_name), target_company_id, force_new),
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id, "status": "queued"}


@router.get("/companies/import-package/{job_id}")
def import_company_status(job_id: str, _session: str = Depends(require_session)):
    with _JOB_LOCK:
        job = dict(_JOBS.get(job_id) or {})
    if not job:
        raise HTTPException(status_code=404, detail="导入任务不存在或已过期")
    return job
