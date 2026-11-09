"""文档提取缓存 DAO（租户内、内容哈希 + 模型 + 提取器版本）。

缓存只服务**概览 / 定位**类请求；具体数字、条款、报价一律本次全文读取
（「文档必须读完，不猜测，不截断，不以旧记忆编造」未变）。这里不读文件内容，
只负责存取"带版本号的读后感"。

租户 = 公司：`tenant_id` 存 `company_id` 的字符串形式。跨租户永不复用；
所有读/删都带 `tenant_id = ?` 条件，`purge_tenant()` 只删本租户。

失败语义：
- 写失败 → 静默回落（返回 False，主流程照常）；
- 读失败 / 行不完整 / 校验不过 → 视为未命中（返回 None），本单全文重读。
只捕获预期的存储类异常；其它异常照常抛出，由测试暴露。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger(__name__)

# 提取器逻辑版本：提示词、分类规则、解析器、facts 结构任一实际改动都必须递增。
EXTRACTOR_VERSION = "5"

STATUS_COMPLETE = "complete"
STATUS_UNCLASSIFIED = "unclassified"
STATUS_FAILED = "failed"
_STATUSES = frozenset({STATUS_COMPLETE, STATUS_UNCLASSIFIED, STATUS_FAILED})

KIND_MONEY = "money"
KIND_INFO = "info"
KIND_UNKNOWN = "unknown"
_KINDS = frozenset({KIND_MONEY, KIND_INFO, KIND_UNKNOWN})

_HASH_CHUNK = 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_SELECT_SQL = (
    "SELECT tenant_id, sha256, model, extractor_version, extracted_at, "
    "extraction_status, facts_json, summary_text, doc_kind, kind_reason, "
    "attempts, error_code FROM doc_extractions "
    "WHERE tenant_id = ? AND sha256 = ? AND model = ? AND extractor_version = ?"
)
_UPSERT_SQL = (
    "INSERT INTO doc_extractions (tenant_id, sha256, model, extractor_version, "
    "extracted_at, extraction_status, facts_json, summary_text, doc_kind, "
    "kind_reason, attempts, error_code) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
    "ON CONFLICT(tenant_id, sha256, model, extractor_version) DO UPDATE SET "
    "extracted_at=excluded.extracted_at, "
    "extraction_status=excluded.extraction_status, "
    "facts_json=excluded.facts_json, summary_text=excluded.summary_text, "
    "doc_kind=excluded.doc_kind, kind_reason=excluded.kind_reason, "
    "attempts=excluded.attempts, error_code=excluded.error_code"
)
_PURGE_SQL = "DELETE FROM doc_extractions WHERE tenant_id = ?"


@dataclass(frozen=True)
class CacheEntry:
    """一行提取缓存（facts_json 保持 JSON 文本，由调用方决定是否解析）。"""

    tenant_id: str
    sha256: str
    model: str
    extractor_version: str
    extracted_at: str
    extraction_status: str
    doc_kind: str
    facts_json: str = "{}"
    summary_text: str = ""
    kind_reason: str | None = None
    attempts: int = 1
    error_code: str | None = None

    @property
    def complete(self) -> bool:
        """提取完成（不代表分类是 info，也不代表可以被缓存旁路）。"""
        return self.extraction_status == STATUS_COMPLETE

    @property
    def cacheable_info(self) -> bool:
        """唯一允许作为 info 缓存证据的组合：complete + info。"""
        return self.complete and self.doc_kind == KIND_INFO

    def facts(self) -> dict:
        """解析 facts_json；调用方需自行处理异常（写入前已校验为 JSON 对象）。"""
        value = json.loads(self.facts_json or "{}")
        return value if isinstance(value, dict) else {}


_CACHE_OFF_VALUES = frozenset({"off", "0", "false", "no", "disabled"})


def cache_enabled() -> bool:
    """熔断开关：默认开，`TRADE_DOC_CACHE=off` 时完全退回现行行为。"""
    raw = os.environ.get("TRADE_DOC_CACHE", "").strip().lower()
    return raw not in _CACHE_OFF_VALUES


def tenant_key(company_id: int | str) -> str:
    """公司 → 缓存租户键（字符串形式，去首尾空白）。"""
    raw = str(company_id if company_id is not None else "").strip()
    if not raw:
        raise ValueError("tenant_id 不能为空")
    return raw


def normalize_model(model: str) -> str:
    """归一模型键：去空白、小写，保留 provider 前缀（换模型永不复用）。"""
    text = str(model or "").strip().lower()
    if ":" in text:
        # " provider : model " 与 "provider:model" 必须是同一个键
        provider, _, name = text.partition(":")
        text = f"{provider.strip()}:{name.strip()}"
    return text


def file_sha256(path: str | Path) -> str:
    """流式计算文件 SHA-256（不花 token）；读取失败由调用方处理。"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get(
    conn: sqlite3.Connection,
    *,
    tenant_id: int | str,
    sha256: str,
    model: str,
    extractor_version: str = EXTRACTOR_VERSION,
) -> CacheEntry | None:
    """按复合键读本租户的一行；缺失/损坏/校验不过 → None（fail closed）。"""
    try:
        tenant = tenant_key(tenant_id)
        digest = str(sha256 or "").strip().lower()
        model_key = normalize_model(model)
        version = str(extractor_version or "").strip()
        if not _SHA256_RE.match(digest) or not model_key or not version:
            return None
        row = conn.execute(
            _SELECT_SQL, (tenant, digest, model_key, version)
        ).fetchone()
    except (sqlite3.Error, OSError, ValueError) as exc:
        _log.debug("读取文档缓存失败（按未命中处理）：%s", exc)
        return None
    if row is None:
        return None
    return _row_to_entry(row)


def save(conn: sqlite3.Connection, entry: CacheEntry) -> bool:
    """写入一行（覆盖同键旧行）；不合法/写失败 → False，主流程照常。"""
    try:
        _validate_entry(entry)
        conn.execute(_UPSERT_SQL, (
            entry.tenant_id,
            entry.sha256,
            entry.model,
            entry.extractor_version,
            entry.extracted_at,
            entry.extraction_status,
            entry.facts_json,
            entry.summary_text,
            entry.doc_kind,
            entry.kind_reason,
            entry.attempts,
            entry.error_code,
        ))
        conn.commit()
        return True
    except ValueError as exc:
        _log.warning("拒绝写入不合法的文档缓存行：%s", exc)
        return False
    except (sqlite3.Error, OSError) as exc:
        _log.debug("写入文档缓存失败（静默回落）：%s", exc)
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        return False


def purge_tenant(conn: sqlite3.Connection, tenant_id: int | str) -> int:
    """只删本租户缓存行；返回删除行数。绝不整表清空。"""
    try:
        tenant = tenant_key(tenant_id)
        removed = conn.execute(_PURGE_SQL, (tenant,)).rowcount
        conn.commit()
        return int(removed or 0)
    except (sqlite3.Error, OSError, ValueError) as exc:
        _log.warning("清理文档缓存失败（tenant=%r）：%s", tenant_id, exc)
        return 0


def _row_to_entry(row) -> CacheEntry | None:
    """行 → CacheEntry；任何结构性问题按未命中处理。"""
    status = str(row[5] or "")
    kind = str(row[8] or "")
    if status not in _STATUSES or kind not in _KINDS:
        _log.debug("文档缓存行状态不合法（status=%r kind=%r），按未命中处理", status, kind)
        return None
    try:
        facts = json.loads(row[6] or "{}")
        attempts = int(row[10] or 0)
    except (TypeError, ValueError, json.JSONDecodeError):
        _log.debug("文档缓存行 JSON/计数不合法，按未命中处理")
        return None
    if not isinstance(facts, dict) or attempts < 1:
        _log.debug("文档缓存行结构不合法，按未命中处理")
        return None
    return CacheEntry(
        tenant_id=str(row[0]),
        sha256=str(row[1]),
        model=str(row[2]),
        extractor_version=str(row[3]),
        extracted_at=str(row[4]),
        extraction_status=status,
        doc_kind=kind,
        facts_json=str(row[6] or "{}"),
        summary_text=str(row[7] or ""),
        kind_reason=row[9],
        attempts=attempts,
        error_code=row[11],
    )


def _validate_entry(entry: CacheEntry) -> None:
    """写前结构校验：不合法绝不落库（避免把坏行留给后续命中）。"""
    if not tenant_key(entry.tenant_id):
        raise ValueError("tenant_id 为空")
    if not _SHA256_RE.match(str(entry.sha256 or "")):
        raise ValueError("sha256 不是 64 位十六进制")
    if not normalize_model(entry.model):
        raise ValueError("model 为空")
    if not str(entry.extractor_version or "").strip():
        raise ValueError("extractor_version 为空")
    if entry.extraction_status not in _STATUSES:
        raise ValueError(f"未知 extraction_status：{entry.extraction_status!r}")
    if entry.doc_kind not in _KINDS:
        raise ValueError(f"未知 doc_kind：{entry.doc_kind!r}")
    if int(entry.attempts) < 1:
        raise ValueError("attempts 必须 >= 1")
    try:
        facts = json.loads(entry.facts_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("facts_json 不是合法 JSON") from exc
    if not isinstance(facts, dict):
        raise ValueError("facts_json 必须是 JSON 对象")
