"""公司数据导出 / 导入 API。"""

from __future__ import annotations

import json
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path
from tempfile import mkstemp
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
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
from trade.company.transfer.preflight import analyze_package

router = APIRouter(tags=["company-transfer"])

MAX_UPLOAD_BYTES = MAX_PACKAGE_BYTES + (100 << 20)
_RATE_LOCK = threading.Lock()
_RATE: dict[str, list[float]] = {}
_JOBS: dict[str, dict] = {}
_JOB_LOCK = threading.Lock()
_MAX_JOBS = 100
_JOB_TTL = 24 * 3600

# 两阶段导入的预检结果：upload_id → 临时包 + 预检快照（30 分钟有效）
_PENDING: dict[str, dict] = {}
_PENDING_LOCK = threading.Lock()
_PENDING_TTL = 30 * 60
# 进程崩溃残留的临时上传包存活上限（模块导入时扫一次）
_ORPHAN_UPLOAD_TTL = 24 * 3600


def _prune_pending() -> None:
    """清掉过期或被认领后遗留的预检条目，并删除对应临时包。

    条目本身只含路径，删除文件放在锁外做，避免慢 I/O 卡住并发确认。
    """
    now = time.time()
    stale_paths: list[Path] = []
    with _PENDING_LOCK:
        for key, entry in list(_PENDING.items()):
            # 已过期，或已被确认（正常流程会立即 pop，此处仅防御性兜底）
            if entry.get("expires_at", 0) < now or entry.get("claimed"):
                popped = _PENDING.pop(key, None)
                # 确实摘到条目且记录了临时包：记下路径，锁外再删
                if popped and popped.get("zip_path") is not None:
                    stale_paths.append(Path(popped["zip_path"]))
    for path in stale_paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # 删不掉不影响任何功能：残留文件由下次孤儿清理兜底
            continue


def _cleanup_orphan_uploads() -> None:
    """删除 24 小时前残留的临时上传包（进程崩溃后无人回收）。

    只认 `trade-company-upload-*` 前缀的普通文件，绝不碰运行中的新文件。
    """
    cutoff = time.time() - _ORPHAN_UPLOAD_TTL
    for path in Path(tempfile.gettempdir()).glob("trade-company-upload-*"):
        try:
            # 只删超过保留期且确实是文件的条目
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except OSError:
            # 单个文件删不掉（权限/竞态）：跳过，不影响启动
            continue


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


def _require_paid_feature() -> None:
    """导入/导出是付费能力：未激活（试用）时不开放。

    与界面门禁一致（static/js/api.js 的 _licenseActivated）。界面隐藏是
    用户体验，这里才是真正的边界 —— 否则试用用户直接调 API 就能用。
    许可证读取异常时**放行**（可用性优先，不能因为读不到状态就锁住付费用户）。
    """
    try:
        from trade.license import license_state

        state, _message = license_state()
    except Exception:  # noqa: BLE001 — 读不到状态不阻断
        return
    if state != "active":
        raise HTTPException(
            status_code=402,
            detail="公司数据导入/导出为付费功能，激活后可用。",
        )


def _set_job(job_id: str, **updates) -> None:
    with _JOB_LOCK:
        job = _JOBS.setdefault(job_id, {})
        job.update(updates)
        job["updated_at"] = time.time()


def _run_import(job_id: str, zip_path: Path, target_company_id: int | None,
                force_new: bool, customer_decisions: dict[int, str] | None = None) -> None:
    _set_job(job_id, status="running", phase="importing")
    try:
        report = import_company(
            zip_path,
            target_company_id=target_company_id,
            force_new=force_new,
            customer_decisions=customer_decisions,
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
    # 越权判断先于付费判断：跨公司请求应先得到 403，不暴露「这是付费功能」
    if cid != company_id:
        raise HTTPException(status_code=403, detail="导出目标与 X-Company-ID 不一致")
    _require_paid_feature()
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
    request: Request,
    file: Annotated[UploadFile, File()],
    target_company_id: Annotated[int | None, Form()] = None,
    force_new: Annotated[bool, Form()] = False,
    preflight: Annotated[bool, Form()] = False,
    _session: str = Depends(require_session),
):
    """上传公司数据包，后台导入并返回 job_id。

    preflight=true 时只读分析并返回同名客户冲突清单（200），不创建导入任务；
    调用方拿到 upload_id 后再走确认端点。

    注意：调用方不要带 X-Company-ID；新公司尚未绑定。
    """
    # 越权判断先于付费判断：跨公司请求应先得到 403，不暴露「这是付费功能」
    # 导入是显式指定目标公司的写操作，不能被用来绕过 session 的公司绑定
    # （2026-11-11 审计 P2-3）。未绑定时（新公司/首次导入）照常放行。
    from trade.api.deps import _ACTIVE_COMPANY, _company_bind_lock

    token = request.headers.get("X-Hermes-Session-Token", "")
    with _company_bind_lock:
        bound = _ACTIVE_COMPANY.get(token)
    if target_company_id is not None and bound is not None and bound != target_company_id:
        raise HTTPException(
            status_code=403,
            detail="只能导入到当前绑定的公司，请先切换到目标公司再导入。",
        )
    _require_paid_feature()
    if not preflight:
        # 旧的一步导入会在同名客户上静默按名字合并，用户没有任何选择机会。
        # 先于限流拦截，避免错误调用消耗导入配额（2026-11-23 审计 P2 残留）。
        await file.close()
        raise HTTPException(
            status_code=409,
            detail="请先上传预检（preflight=true），确认同名客户处置后再导入",
        )
    # 预检只读分析使用独立宽松限流，避免预检或包校验失败锁死后续 5 分钟正式导入
    if not _rate_ok("import_preflight", 10, 60):
        await file.close()
        raise HTTPException(status_code=429, detail="预检请求过于频繁，请稍后再试")
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

    _prune_pending()
    # 预检模式：只读分析，登记结果后立即返回，不创建任何导入任务
    if preflight:
        try:
            result = analyze_package(
                Path(temp_name),
                target_company_id=target_company_id,
                force_new=force_new,
            )
        except zipfile.BadZipFile as exc:
            # 上传的根本不是 zip：删掉临时文件后给出可读提示
            _cleanup(temp_name)
            raise HTTPException(
                status_code=400, detail="文件不是有效的公司数据包（zip）"
            ) from exc
        except AmbiguousCompanyError as exc:
            # 目标机有多个同名公司：返回候选让调用方指定目标，不做猜测
            _cleanup(temp_name)
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "目标机存在多个同名公司，请指定要合并的目标公司",
                    "candidates": exc.candidates,
                },
            )
        except TransferError as exc:
            # 包内容不合规（格式/版本/schema）：属于可预期的客户端错误
            _cleanup(temp_name)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — 预检失败不能影响其它接口
            _cleanup(temp_name)
            raise HTTPException(
                status_code=500, detail="预检失败，请稍后重试"
            ) from exc

        # 未显式传 target_company_id 时，analyze_package 可能按名称/slug 自动匹配已有公司；
        # 若当前会话已绑定其它公司，同样必须拦截跨公司合并导入。
        auto_target = ((result.get("company") or {}).get("target") or {})
        auto_target_id = auto_target.get("id") if isinstance(auto_target, dict) else None
        if bound is not None and auto_target_id is not None and int(auto_target_id) != bound:
            _cleanup(temp_name)
            raise HTTPException(
                status_code=403,
                detail="只能导入到当前绑定的公司，请先切换到目标公司再导入。",
            )

        upload_id = uuid.uuid4().hex
        now = time.time()
        with _PENDING_LOCK:
            _PENDING[upload_id] = {
                "zip_path": Path(temp_name),
                "preflight": result,
                "target_company_id": target_company_id,
                "force_new": force_new,
                "created_at": now,
                "expires_at": now + _PENDING_TTL,
                "claimed": False,
            }
        # 预检成功返回 200（路由默认 202 只适用于「已开始导入」）
        return JSONResponse(
            status_code=200,
            content={
                "upload_id": upload_id,
                "expires_in": _PENDING_TTL,
                **result,
            },
        )

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


class _Decision(BaseModel):
    """单个同名客户的处置选择。"""

    source_id: int
    action: Literal["merge", "create"]


class ConfirmImportBody(BaseModel):
    """确认导入请求体：逐对选择 + 可选默认动作。"""

    customer_decisions: list[_Decision] = []
    default_action: Literal["merge", "create"] | None = None


@router.post("/companies/import-package/{upload_id}/confirm", status_code=202)
def confirm_import_package(upload_id: str, body: ConfirmImportBody,
                           _session: str = Depends(require_session)):
    """确认预检结果并启动后台导入。

    校验失败（未知客户 / 未补全选择）不消耗 upload_id，用户可以补选后重试。
    """
    _prune_pending()
    now = time.time()
    # 键统一成字符串：预检返回的 source_id 可能被 JSON 写成 "7"，而模型
    # 解析出的决定是 int 7 —— 直接比对会让合法决定恒 400（审计 O-5）。
    decisions: dict[str, str] = {}
    with _PENDING_LOCK:
        entry = _PENDING.get(upload_id)
        # 不存在（从未创建 / 已被确认清理）：让用户重新选文件
        if entry is None:
            raise HTTPException(status_code=410, detail="导入链接已过期，请重新选择文件")
        # 已过期：移出登记表并删掉临时包
        if entry.get("expires_at", 0) < now:
            popped = _PENDING.pop(upload_id, None)
            if popped and popped.get("zip_path") is not None:
                _cleanup(str(popped["zip_path"]))
            raise HTTPException(status_code=410, detail="导入链接已过期，请重新选择文件")
        # 已被另一个请求认领：不允许两个导入并行跑
        if entry.get("claimed"):
            raise HTTPException(status_code=409, detail="导入正在进行中")

        conflicts = (entry.get("preflight") or {}).get("conflicts") or []
        conflict_ids = [
            conflict.get("source_id") for conflict in conflicts
            if conflict.get("source_id") is not None
        ]
        known = {str(cid) for cid in conflict_ids}
        for decision in body.customer_decisions:
            # 指向本次预检之外的客户：拒绝，且不消耗 upload_id
            if str(decision.source_id) not in known:
                raise HTTPException(status_code=400, detail="未知的客户选择")
            decisions[str(decision.source_id)] = decision.action
        # 有冲突未选择：能靠默认动作补齐就补，否则要求用户补选
        missing = [cid for cid in conflict_ids if str(cid) not in decisions]
        if missing and body.default_action is not None:
            for cid in missing:
                decisions[str(cid)] = body.default_action
            missing = []
        # 仍有缺失：返回 409 + missing，条目保持可用
        if missing:
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "还有同名客户未选择处置方式",
                    "missing": missing,
                },
            )

        # 校验全部通过准备真正启动后台写库前检查正式导入配额（不消耗在缺决定/400 上）
        if not _rate_ok("import", 1, 300):
            raise HTTPException(status_code=429, detail="导入过于频繁，请稍后再试")

        # 校验通过：认领并移出登记表，重复确认一律 410
        entry["claimed"] = True
        _PENDING.pop(upload_id, None)
        zip_path = entry.get("zip_path")
        # 必须用预检时保存的目标，避免「预检 A 公司、确认 B 公司」
        target_company_id = entry.get("target_company_id")
        force_new = entry.get("force_new")

    _prune_jobs()
    job_id = uuid.uuid4().hex
    _set_job(job_id, status="queued", phase="queued")
    thread = threading.Thread(
        target=_run_import,
        args=(job_id, zip_path, target_company_id, force_new, decisions),
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


# 模块导入时清理一次进程崩溃残留的临时上传包。任何失败都必须吞掉：
# 清理是锦上添花，绝不能影响应用启动或其它接口（可用性优先）。
try:
    _cleanup_orphan_uploads()
except Exception:  # noqa: BLE001 — 启动路径禁止因清理失败而中断
    pass
