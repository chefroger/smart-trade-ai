"""文档解析与提取（缓存写入的唯一来源）。

流程：`parse_document()` 先做确定性解析（文本 + 表格五元组 + 坐标），
再由用户配置的**对话模型**输出分类、摘要与补充 facts（思考档强制 low）。
缓存只存"从文件里读到的事实"，不存原文、不存结论。

刻意不把文件名喂给模型：分类只看内容（任务书 §五：不得按文件名判断）。
解析/提取失败一律返回 `failed` 结果，不写可命中行；主流程回落全文读取。
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trade import doc_cache

_log = logging.getLogger(__name__)

DEFAULT_EXTRACT_TIMEOUT = 60.0
# failed 行最多重提次数；达到后同一 (tenant, sha, model, version) 不再自动重试。
MAX_CACHE_ATTEMPTS = 3
# 单次请求最多预热多少个文件（大目录靠多次请求逐步建缓存，不卡主流程）。
DEFAULT_WARM_LIMIT = 5
_MAX_TEXT_CHARS = 120_000
_MAX_TABLE_ROWS = 200
_MAX_TABLE_COLS = 50
_MAX_SHEETS = 3
_MAX_PARSED_FACTS = 500
_MAX_MODEL_FACTS = 300

_TEXT_SUFFIXES = frozenset({
    ".txt", ".md", ".markdown", ".json", ".yaml", ".yml", ".xml",
    ".html", ".htm", ".log", ".ini", ".cfg", ".conf", ".sql",
})
_CSV_SUFFIXES = frozenset({".csv", ".tsv"})

_SUBTOTAL_RE = re.compile(r"(合计|小计|总计|total|subtotal)", re.IGNORECASE)
_NUM_UNIT_RE = re.compile(
    r"^\s*(?:([^\d\s]{1,8})\s*)?([-+]?\d[\d,]*(?:\.\d+)?)\s*([^\d\s].*)?$"
)

CLASSIFY_RULES = """\
## 分类（doc_kind，必填）
- money：报价单/参数表/PI/合同/价格表；含价格、金额、规格数字、合同条款，
  或含金额类数值表（Excel 金额/数量表）、金额类统计指标（销售额、成本、利润）。
- info：公司介绍/产品介绍/宣传册等资料；纯比率/数量型统计指标（增长率、占比、
  合格率）不含金额的归 info，但数字必须带口径（同比/环比、统计周期）。
- unknown：分不出来。
边界拿不准一律 money（fail-closed）。分类只能看内容，不得根据文件名判断。
"""

_TRADE_FACTS_GUIDE = """\
## facts（每条必须带原文位置）
页码/段落；表格用 sheet + 行 + 列坐标。字段包括：
产品/型号、规格参数、价格、币种、数量阶梯、有效期、交期、客户/供应商、日期、单号。
表格数值按五元组：sheet 名 + 行标签 + 列标签 + 数值 + 单位；合计/小计行单独标。
统计指标：指标名 + 数值 + 单位 + 口径/定义 + 统计周期 + 对比基数（同比/环比/目标值）。
没有口径的统计数字不要输出。
"""

EXTRACT_PROMPT = """\
你是文档提取器。只做提取与分类：不回答问题、不给建议、不补全原文没有的内容。

严格输出这个 JSON（不要解释文字、不要 markdown 代码块）：
{"doc_kind": "money|info|unknown", "kind_reason": "一句话依据",
 "summary": "忠实摘要（不超过 200 字，只概括文档内容）",
 "facts": [{"name": "字段名", "value": "原文数值或文本", "unit": "单位",
            "location": {"page": 1}}]}

规则：
- 只依据下面给定的文档内容；找不到的事实不要输出。
- summary 是摘要，不是对任何问题的回答。
""" + CLASSIFY_RULES + _TRADE_FACTS_GUIDE


@dataclass
class ParsedDocument:
    """确定性解析结果（模型只看 text / facts）。"""

    path: Path
    text: str = ""
    facts: list[dict] = field(default_factory=list)
    truncated: bool = False
    needs_ocr: bool = False
    unsupported: bool = False
    error: str = ""


@dataclass
class ExtractionResult:
    """一次提取的结果；failed 行只用于计数，不写可命中内容。"""

    status: str
    doc_kind: str = doc_cache.KIND_UNKNOWN
    kind_reason: str = ""
    summary: str = ""
    facts: list[dict] = field(default_factory=list)
    error_code: str = ""
    truncated: bool = False

    @property
    def cacheable(self) -> bool:
        """只有 complete + info 才可能作为 info 缓存证据（由调用方再判 scope）。"""
        return self.status == doc_cache.STATUS_COMPLETE and self.doc_kind == doc_cache.KIND_INFO


# 解析器行为版本：解析阈值、异常处理、坐标规则改动时递增。
# 与 doc_cache.EXTRACTOR_VERSION 同步 —— 解析器变了，旧 complete 行必须作废。
_PARSER_REVISION = "3"


def extractor_fingerprint() -> str:
    """提示词 + 分类规则 + 解析器源码的指纹。

    解析器源码也计入哈希：只改解析逻辑而忘记递增 doc_cache.EXTRACTOR_VERSION
    时，测试会直接失败（审计 P2-2）。测试按"版本 → 指纹"映射钉住。
    """
    import hashlib
    import inspect

    parser_source = "".join(
        inspect.getsource(fn)
        for fn in (
            _parse_xlsx, _parse_docx, _parse_pdf, _table_facts,
            _split_value_unit, _xlsx_has_uncached_formula,
        )
    )
    payload = (
        EXTRACT_PROMPT + CLASSIFY_RULES + _TRADE_FACTS_GUIDE
        + _PARSER_REVISION + parser_source
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _extract_timeout() -> float:
    raw = os.environ.get("TRADE_DOC_EXTRACT_TIMEOUT", "").strip()
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_EXTRACT_TIMEOUT
    return value if value > 0 else DEFAULT_EXTRACT_TIMEOUT


def _warm_limit() -> int:
    raw = os.environ.get("TRADE_DOC_EXTRACT_PER_REQUEST", "").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_WARM_LIMIT
    return value if value > 0 else DEFAULT_WARM_LIMIT


def warm_cache(paths, *, tenant_id, limit: int | None = None) -> int:
    """best-effort 预热：缓存未命中的文件做一次提取并写回。

    只在主流程已经读完文件后调用；任何失败都静默回落（不阻断聊天）。
    同一文件已有 complete/unclassified 行则跳过；failed 行最多重试
    `MAX_CACHE_ATTEMPTS` 次。
    """
    if not doc_cache.cache_enabled():
        return 0
    resolved = resolve_extraction_model()
    if resolved is None:
        return 0
    model_key = resolved[2]
    total = limit if limit is not None else _warm_limit()
    warmed = 0
    conn = None
    try:
        from trade.database import get_connection

        conn = get_connection()
        for path in paths:
            if warmed >= total:
                break
            try:
                digest = doc_cache.file_sha256(path)
            except OSError:
                continue
            existing = doc_cache.get(
                conn, tenant_id=tenant_id, sha256=digest, model=model_key
            )
            if existing is not None:
                if existing.extraction_status != doc_cache.STATUS_FAILED:
                    continue
                if existing.attempts >= MAX_CACHE_ATTEMPTS:
                    continue
            attempts = existing.attempts + 1 if existing else 1
            try:
                result = asyncio.run(extract_document(path))
            except Exception as exc:
                # 单个文件的解析/提取异常不能带走整轮预热线程。
                _log.warning("预热提取失败（%s）：%s", path, exc)
                continue
            doc_cache.save(conn, to_cache_entry(
                result, tenant_id=tenant_id, sha256=digest,
                model=model_key, attempts=attempts,
            ))
            warmed += 1
    except (sqlite3.Error, OSError) as exc:
        _log.debug("预热文档缓存失败（不影响主流程）：%s", exc)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return warmed


def resolve_extraction_model() -> tuple[str, str, str] | None:
    """解析"当次实际对话模型"：返回 (provider, model, 归一化缓存键)。"""
    try:
        from trade.hermes_compat import current_model_config

        provider, model = current_model_config()
    except Exception as exc:
        _log.warning("读取当前对话模型失败：%s", exc)
        return None
    provider = (provider or "").strip()
    model = (model or "").strip()
    if not provider or not model:
        return None
    key = doc_cache.normalize_model(f"{provider}:{model}")
    return provider, model, key


def parse_document(path: str | Path) -> ParsedDocument:
    """按扩展名做确定性解析；不支持的格式返回 unsupported=True（不猜内容）。"""
    target = Path(path)
    suffix = target.suffix.lower()
    try:
        if suffix in _TEXT_SUFFIXES:
            return _clip(ParsedDocument(target, text=_decode(target.read_bytes())))
        if suffix in _CSV_SUFFIXES:
            return _parse_csv(target)
        if suffix == ".xlsx":
            return _parse_xlsx(target)
        if suffix == ".docx":
            return _parse_docx(target)
        if suffix == ".pdf":
            return _parse_pdf(target)
    except (OSError, ValueError, KeyError) as exc:
        _log.debug("解析文档失败（%s）：%s", target.name, exc)
        return ParsedDocument(target, error=f"{type(exc).__name__}: {exc}")
    return ParsedDocument(target, unsupported=True)


async def extract_document(
    path: str | Path, *, timeout: float | None = None
) -> ExtractionResult:
    """解析 + 模型提取 + 分类。任何一步失败都返回 failed，不猜、不跳过。"""
    parsed = parse_document(path)
    if parsed.unsupported:
        return _failed("unsupported_type")
    if parsed.error:
        return _failed("parse_error")
    if parsed.needs_ocr:
        return _failed("needs_ocr")
    if parsed.truncated:
        # 截断的提取不得自称完整：不写缓存，本次及以后都全文读。
        return _failed("truncated")
    if not parsed.text.strip() and not parsed.facts:
        return _failed("empty")

    resolved = resolve_extraction_model()
    if resolved is None:
        return _failed("model_unavailable")
    provider, model, _key = resolved

    prompt = (
        EXTRACT_PROMPT
        + "\n\n## 文档内容\n\n"
        + (parsed.text.strip() or "（无文本，仅表格结构）")
        + "\n\n## 解析出的表格事实\n\n"
        + json.dumps(parsed.facts[:_MAX_PARSED_FACTS], ensure_ascii=False)
    )
    messages = [{"role": "user", "content": prompt}]
    try:
        raw = await _call_model(
            messages,
            provider=provider,
            model=model,
            timeout=timeout if timeout is not None else _extract_timeout(),
        )
    except Exception as exc:  # 模型调用边界：网络/超时/服务商错误一律降级为 failed
        _log.warning("文档提取模型调用失败：%s", exc)
        return _failed("model_error")

    obj = _parse_json_object(raw)
    if obj is None:
        return _failed("parse_error")

    kind = str(obj.get("doc_kind") or "").strip().lower()
    if kind not in {doc_cache.KIND_MONEY, doc_cache.KIND_INFO, doc_cache.KIND_UNKNOWN}:
        kind = doc_cache.KIND_UNKNOWN
    # 代码级兜底（审计 P2-1）：内容里已有金额/币种/报价特征时，模型说 info 也不认。
    if kind == doc_cache.KIND_INFO and _looks_like_money(parsed):
        kind = doc_cache.KIND_MONEY
    summary = str(obj.get("summary") or "").strip()[:2000]
    model_facts = _coerce_facts(obj.get("facts"))
    facts = _merge_facts(parsed.facts, model_facts)
    status = (
        doc_cache.STATUS_COMPLETE
        if kind in {doc_cache.KIND_MONEY, doc_cache.KIND_INFO}
        else doc_cache.STATUS_UNCLASSIFIED
    )
    return ExtractionResult(
        status=status,
        doc_kind=kind,
        kind_reason=str(obj.get("kind_reason") or "").strip()[:500],
        summary=summary,
        facts=facts,
    )


def to_cache_entry(
    result: ExtractionResult,
    *,
    tenant_id: int | str,
    sha256: str,
    model: str,
    attempts: int = 1,
    extracted_at: str = "",
):
    """把提取结果转成缓存行；failed 行不保留 facts/summary。"""
    from datetime import UTC, datetime

    failed = result.status == doc_cache.STATUS_FAILED
    facts_json = (
        "{}"
        if failed
        else json.dumps(
            {"facts": result.facts, "truncated": result.truncated},
            ensure_ascii=False,
        )
    )
    return doc_cache.CacheEntry(
        tenant_id=doc_cache.tenant_key(tenant_id),
        sha256=sha256,
        model=doc_cache.normalize_model(model),
        extractor_version=doc_cache.EXTRACTOR_VERSION,
        extracted_at=extracted_at
        or datetime.now(UTC).isoformat(timespec="seconds"),
        extraction_status=result.status,
        doc_kind=result.doc_kind if not failed else doc_cache.KIND_UNKNOWN,
        facts_json=facts_json,
        summary_text="" if failed else result.summary,
        kind_reason=result.kind_reason,
        attempts=max(1, int(attempts)),
        error_code=result.error_code or None,
    )


# ── 模型调用 ────────────────────────────────────────────────────────────────


async def _call_model(messages: list, *, provider: str, model: str, timeout: float) -> str:
    """走 Hermes 辅助 LLM 通道；provider/model 显式给出，thinking 强制 low。"""
    from agent.auxiliary_client import async_call_llm

    response = await async_call_llm(
        provider=provider,
        model=model,
        messages=messages,
        temperature=0.1,
        max_tokens=4000,
        timeout=timeout,
        reasoning_config={"enabled": True, "effort": "low"},
    )
    return _response_text(response)


def _response_text(response: Any) -> str:
    """从 OpenAI 风格响应里取文本（兼容 str / 对象 / dict）。"""
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    try:
        from agent.auxiliary_client import extract_content_or_reasoning

        text = extract_content_or_reasoning(response)
        if text:
            return str(text)
    except Exception:
        pass
    try:
        choices = response.choices
        if choices:
            content = getattr(choices[0].message, "content", None)
            if isinstance(content, str):
                return content
    except Exception:
        pass
    if isinstance(response, dict):
        content = response.get("content")
        if isinstance(content, str):
            return content
    return ""


def _parse_json_object(raw: str) -> dict | None:
    """容忍 ```json 围栏与前后杂音。"""
    if not raw:
        return None
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _coerce_facts(raw: Any) -> list[dict]:
    """模型 facts 只保留 dict，值统一成字符串（JSON 可序列化）。"""
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw[:_MAX_MODEL_FACTS]:
        if not isinstance(item, dict) or not item:
            continue
        out.append({str(k): _jsonable(v) for k, v in item.items()})
    return out


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except (TypeError, ValueError):
        return str(value)


def _merge_facts(parsed: list[dict], model_facts: list[dict]) -> list[dict]:
    """确定性表格事实在前，模型补充在后；按内容去重并限流。"""
    merged: list[dict] = []
    seen: set[str] = set()
    for item in list(parsed) + list(model_facts):
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
        if len(merged) >= _MAX_PARSED_FACTS:
            break
    return merged


def _failed(code: str) -> ExtractionResult:
    return ExtractionResult(status=doc_cache.STATUS_FAILED, error_code=code)


_MONEY_HINTS = re.compile(
    r"(?:USD|CNY|RMB|EUR|GBP|JPY|HKD|\$|￥|¥|报价|价格|单价|金额|总价|合同|"
    r"invoice|\bPI\b|发票|价目)",
    re.IGNORECASE,
)


def _looks_like_money(parsed: ParsedDocument) -> bool:
    """内容级金额特征：只用于把模型误判的 info 改回 money（fail-closed）。"""
    blob = parsed.text[:5000]
    if parsed.facts:
        blob += "\n" + json.dumps(parsed.facts[:50], ensure_ascii=False)
    return bool(_MONEY_HINTS.search(blob))


# ── 确定性解析 ──────────────────────────────────────────────────────────────


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _clip(parsed: ParsedDocument) -> ParsedDocument:
    if len(parsed.text) > _MAX_TEXT_CHARS:
        parsed.text = parsed.text[:_MAX_TEXT_CHARS]
        parsed.truncated = True
    return parsed


def _parse_csv(path: Path) -> ParsedDocument:
    text = _decode(path.read_bytes())
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    return _clip(_table_document(path, rows, sheet=""))


def _parse_xlsx(path: Path) -> ParsedDocument:
    try:
        import openpyxl

        workbook = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    except Exception as exc:  # 损坏/加密/格式不符：交给调用方按 failed 处理
        _log.warning("解析 xlsx 失败（%s）：%s", path.name, exc)
        return ParsedDocument(path, error=f"{type(exc).__name__}: {exc}")

    parts: list[str] = []
    facts: list[dict] = []
    values_by_sheet: list[list[list[Any]]] = []
    truncated = False
    try:
        for sheet in workbook.worksheets[:_MAX_SHEETS]:
            rows: list[list[Any]] = []
            for index, row in enumerate(sheet.iter_rows(values_only=True)):
                if index >= _MAX_TABLE_ROWS:
                    truncated = True
                    break
                if len(row) > _MAX_TABLE_COLS:
                    truncated = True
                rows.append(list(row))
            parts.append(f"## Sheet: {sheet.title}\n" + _rows_to_text(rows))
            sheet_facts, sheet_facts_truncated = _table_facts(rows, sheet=sheet.title)
            if sheet_facts_truncated:
                truncated = True
            facts.extend(sheet_facts)
            if len(facts) > _MAX_PARSED_FACTS:
                truncated = True
                facts = facts[:_MAX_PARSED_FACTS]
            values_by_sheet.append(rows)
            if truncated:
                break
        if len(workbook.worksheets) > _MAX_SHEETS:
            truncated = True
    except Exception as exc:
        _log.warning("读取 xlsx 内容失败（%s）：%s", path.name, exc)
        return ParsedDocument(path, error=f"{type(exc).__name__}: {exc}")
    finally:
        try:
            workbook.close()
        except Exception:
            pass
    # 公式格没有缓存值时 data_only 读到 None，会被当成空单元格 —— 必须在
    # 写入缓存前识别出来，否则计算结果会静默丢失。
    if not truncated and _xlsx_has_uncached_formula(path, values_by_sheet):
        truncated = True
    parsed = ParsedDocument(path, text="\n\n".join(parts), facts=facts[:_MAX_PARSED_FACTS])
    parsed.truncated = truncated
    return _clip(parsed)


def _xlsx_has_uncached_formula(
    path: Path, values_by_sheet: list[list[list[Any]]],
) -> bool:
    """是否存在 data_only 读不到值的公式格；无法确认时按“有”处理。"""
    try:
        import openpyxl

        workbook = openpyxl.load_workbook(str(path), read_only=True, data_only=False)
    except Exception as exc:
        _log.warning("检查 xlsx 公式失败（%s）：%s", path.name, exc)
        return True
    try:
        for sheet_index, sheet in enumerate(workbook.worksheets[:_MAX_SHEETS]):
            if sheet_index >= len(values_by_sheet):
                break
            values_rows = values_by_sheet[sheet_index]
            for row_index, row in enumerate(sheet.iter_rows()):
                if row_index >= _MAX_TABLE_ROWS:
                    break
                values = values_rows[row_index] if row_index < len(values_rows) else []
                for col_index, cell in enumerate(row[:_MAX_TABLE_COLS]):
                    if getattr(cell, "data_type", "") != "f":
                        continue
                    value = values[col_index] if col_index < len(values) else None
                    if value is None:
                        return True
    except Exception as exc:
        _log.warning("检查 xlsx 公式失败（%s）：%s", path.name, exc)
        return True
    finally:
        try:
            workbook.close()
        except Exception:
            pass
    return False


def _parse_docx(path: Path) -> ParsedDocument:
    try:
        import docx

        document = docx.Document(str(path))
    except Exception as exc:
        _log.warning("解析 docx 失败（%s）：%s", path.name, exc)
        return ParsedDocument(path, error=f"{type(exc).__name__}: {exc}")

    parts: list[str] = []
    facts: list[dict] = []
    truncated = False
    try:
        for index, paragraph in enumerate(document.paragraphs):
            text = (paragraph.text or "").strip()
            if text:
                parts.append(f"[段落 {index + 1}] {text}")
        for table_index, table in enumerate(document.tables):
            rows: list[list[Any]] = []
            for row in table.rows:
                if len(rows) >= _MAX_TABLE_ROWS:
                    truncated = True
                    break
                cells = row.cells
                if len(cells) > _MAX_TABLE_COLS:
                    truncated = True
                rows.append([cell.text for cell in cells[:_MAX_TABLE_COLS]])
            parts.append(f"## 表格 {table_index + 1}\n" + _rows_to_text(rows))
            table_facts, table_facts_truncated = _table_facts(
                rows, sheet=f"表格 {table_index + 1}"
            )
            if table_facts_truncated:
                truncated = True
            facts.extend(table_facts)
            if len(facts) > _MAX_PARSED_FACTS:
                truncated = True
                facts = facts[:_MAX_PARSED_FACTS]
    except Exception as exc:
        _log.warning("读取 docx 内容失败（%s）：%s", path.name, exc)
        return ParsedDocument(path, error=f"{type(exc).__name__}: {exc}")
    return _clip(ParsedDocument(
        path, text="\n".join(parts), facts=facts[:_MAX_PARSED_FACTS],
        truncated=truncated,
    ))


def _parse_pdf(path: Path) -> ParsedDocument:
    try:
        import fitz  # PyMuPDF

        document = fitz.open(str(path))
    except Exception as exc:
        _log.warning("解析 PDF 失败（%s）：%s", path.name, exc)
        return ParsedDocument(path, error=f"{type(exc).__name__}: {exc}")

    parts: list[str] = []
    empty_pages = 0
    try:
        for page_index, page in enumerate(document):
            text = page.get_text() or ""
            if text.strip():
                parts.append(f"[第 {page_index + 1} 页]\n{text}")
            else:
                empty_pages += 1
        if document.page_count == 0:
            return ParsedDocument(path, needs_ocr=True)
    except Exception as exc:
        _log.warning("读取 PDF 内容失败（%s）：%s", path.name, exc)
        return ParsedDocument(path, error=f"{type(exc).__name__}: {exc}")
    finally:
        try:
            document.close()
        except Exception:
            pass
    # 任一页没有文字层（扫描页/空白页）都不写缓存：无法确认这一页读过。
    if not parts or empty_pages:
        return ParsedDocument(path, needs_ocr=True)
    return _clip(ParsedDocument(path, text="\n\n".join(parts)))


def _rows_to_text(rows: list[list[Any]]) -> str:
    lines = []
    for row in rows:
        cells = [str(value).strip() for value in row[:_MAX_TABLE_COLS]
                 if value is not None and str(value).strip()]
        if cells:
            lines.append("\t".join(cells))
    return "\n".join(lines)


def _table_document(path: Path, rows: list[list[Any]], *, sheet: str) -> ParsedDocument:
    truncated = (
        len(rows) > _MAX_TABLE_ROWS
        or any(len(row) > _MAX_TABLE_COLS for row in rows)
    )
    rows = [row[:_MAX_TABLE_COLS] for row in rows[:_MAX_TABLE_ROWS]]
    facts, facts_truncated = _table_facts(rows, sheet=sheet)
    return ParsedDocument(
        path, text=_rows_to_text(rows),
        facts=facts[:_MAX_PARSED_FACTS],
        truncated=truncated or facts_truncated,
    )


def _table_facts(
    rows: list[list[Any]], *, sheet: str,
) -> tuple[list[dict], bool]:
    """把表格转成五元组事实；返回 (facts, 是否因上限提前停止)。"""
    if not rows:
        return [], False
    header = [str(cell).strip() if cell is not None else "" for cell in rows[0]]
    facts: list[dict] = []
    for row_index, row in enumerate(rows[1:], start=2):
        row_label = str(row[0]).strip() if row and row[0] is not None else ""
        subtotal = bool(_SUBTOTAL_RE.search(row_label))
        for col_index, cell in enumerate(row[1:_MAX_TABLE_COLS], start=1):
            raw = "" if cell is None else str(cell).strip()
            if not raw:
                continue
            value, unit = _split_value_unit(raw)
            facts.append({
                "sheet": sheet,
                "row": row_label,
                "column": header[col_index] if col_index < len(header) else "",
                "value": value,
                "unit": unit,
                "subtotal": subtotal,
                "location": {"sheet": sheet, "row": row_index, "column": col_index + 1},
            })
            if len(facts) >= _MAX_PARSED_FACTS:
                return facts, True
    return facts, False


def _split_value_unit(raw: str) -> tuple[str, str]:
    """把 "USD 3.50" / "3.50 USD" / "12%" 拆成 (数值, 单位)；拆不出就原样。"""
    match = _NUM_UNIT_RE.match(raw)
    if not match:
        return raw, ""
    prefix, number, suffix = match.groups()
    unit = " ".join(part for part in (prefix, suffix) if part).strip()
    return number, unit
