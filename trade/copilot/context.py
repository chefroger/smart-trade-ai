"""context —— 客户匹配 + 上下文组装（平台无关）。

## 铁律 4：客户匹配宁缺毋滥

对方名称与客户库的模糊匹配**低于阈值就按新客户处理**，禁止把任何既有客户的
历史上下文带进草稿。理由：把 A 客户的价格/需求说给 B 客户，是真实的业务事故
（不只是"串味"）—— 报价、MOQ、认证要求都可能对不上。

阈值取 0.62（`MATCH_THRESHOLD`）：向量/关键词检索的分数是 1/(1+distance)，
**无关向量的恒定正交基线是 0.4142** —— 阈值必须显著高于它，否则任何名字都能
"匹配"到某个客户。

## 检索用哪条路

- 客户：沿用 `trade.vec_search.search_customers`（按 company_id 过滤，向量优先、
  无向量时自动降级关键词）
- 客户历史：沿用 `trade.chat_memory.search_history`（同一公司归属口径）
- 产品库：沿用 `trade.library` 的既有读取路径
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from trade.copilot.numbers import NUMBER_RE, number_key
from trade.copilot.types import CustomerContext, SourceRef

_log = logging.getLogger(__name__)

# 客户匹配阈值（高于向量检索的正交基线 0.4142，低于它等于不过滤）
MATCH_THRESHOLD = 0.62

# 低于这个分数即便有候选也按新客户处理（多候选时的保守侧）
AMBIGUOUS_MARGIN = 0.05

# ── 产品库扫描预算（15s 触发式读取，不能把所有库整份扫一遍）──────────────
_TEXT_SUFFIXES = frozenset({
    ".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".html", ".htm", ".log",
})
_PDF_SUFFIXES = frozenset({".pdf"})
_DOCX_SUFFIXES = frozenset({".docx"})
_XLSX_SUFFIXES = frozenset({".xlsx"})
_MAX_FILES = 80                 # 单次触发最多看多少个文件
_MAX_FILE_BYTES = 2 * 1024 * 1024
_MAX_TOTAL_BYTES = 8 * 1024 * 1024
_MAX_EXCERPT_CHARS = 300
_MAX_FACTS_PER_FILE = 20
_MAX_FACTS = 100
_MAX_PDF_PAGES = 3
_MAX_EXCEL_ROWS = 200
_MAX_EXCEL_SHEETS = 3


def _normalize_name(name: str) -> str:
    """名字归一：去空白与常见分隔符，小写。

    聊天软件里的称呼常常带空格/点/破折号（"John Smith" / "john.smith" /
    "John-Smith"），归一后再比能显著提高命中率。
    """
    if not name:
        return ""
    text = name.strip().lower()
    for ch in (" ", "\t", ".", "_", "-", "·", "，", ","):
        text = text.replace(ch, "")
    return text


def _exact_name_hits(contact: str, customers: list[dict]) -> list[dict]:
    """归一后完全相同的所有客户（不依赖向量分数，最可靠）。"""
    target = _normalize_name(contact)
    if not target:
        return []
    return [
        cust for cust in customers
        if _normalize_name(str(cust.get("name") or "")) == target
    ]


def _names_overlap(contact: str, candidate: str) -> bool:
    """两边的归一名字是否有实质重叠。

    只用于**关键词降级命中**的二次校验：LIKE 会扫 note/email，别家客户备注里
    写了个名字也会命中（复审 P1-3）。名字本身对不上就不许算匹配。

    短查询（归一后 ≤3 字符）只认完全相等 —— 否则 `Li → Lily`、`Al → also`
    这类包含关系会把对方认成另一个人（2026-10-25 审计 P1-5）。
    """
    left = _normalize_name(contact)
    right = _normalize_name(candidate)
    if not left or not right:
        return False
    if left == right:
        return True
    if len(left) <= 3 or len(right) <= 3:
        return False
    return left in right or right in left


def match_customer(
    contact: str,
    *,
    company_id: int,
    threshold: float = MATCH_THRESHOLD,
) -> CustomerContext:
    """在**当前公司**的客户库里匹配对方名称。

    Args:
        contact: 抽取到的对方名称/昵称。
        company_id: 当前公司（严格作用域，跨公司绝不查）。
        threshold: 匹配阈值。

    Returns:
        CustomerContext。未命中时 `matched=False` + `new_contact=True`，
        **不带任何历史**。
    """
    if not company_id or company_id <= 0:
        return CustomerContext(new_contact=True)

    name = (contact or "").strip()
    if not name:
        return CustomerContext(new_contact=True)

    customers = _list_company_customers(company_id)
    if not customers:
        return CustomerContext(new_contact=True)

    # ① 归一后完全相同 → 命中；同名多条 → 宁缺毋滥，按新客户（铁律 4）
    exact_matches = _exact_name_hits(name, customers)
    if len(exact_matches) == 1:
        exact = exact_matches[0]
        return CustomerContext(
            customer_id=int(exact.get("id") or 0),
            customer_name=str(exact.get("name") or name),
            matched=True,
            new_contact=False,
            match_score=1.0,
        )
    if len(exact_matches) > 1:
        _log.info("副驾客户同名多候选（%d 条），按新客户处理", len(exact_matches))
        return CustomerContext(customer_name=name, new_contact=True)

    # ② 模糊检索（向量优先，无向量时降级关键词）
    hits = _fuzzy_search(name, company_id)
    if not hits:
        return CustomerContext(new_contact=True)

    best = hits[0]
    score = float(best.get("score") or 0.0)
    if score < threshold:
        return CustomerContext(
            customer_name=name,
            new_contact=True,
            match_score=score,
        )

    # ③ 多候选且分数接近 → 宁缺毋滥，按新客户处理
    if len(hits) > 1:
        second = float(hits[1].get("score") or 0.0)
        if second >= score - AMBIGUOUS_MARGIN:
            return CustomerContext(
                customer_name=name,
                new_contact=True,
                match_score=score,
            )

    cust = _get_customer(best["customer_id"], company_id)
    if not cust:
        return CustomerContext(customer_name=name, new_contact=True, match_score=score)

    # ④ 关键词降级命中的二次校验：LIKE 返回的 score 恒为 1.0，会直接越过
    #    0.62 阈值；而 LIKE 也会扫 note/email —— 别家客户备注里出现这个名字
    #    同样会命中。名字本身没有实质重叠 → 按新客户（铁律 4）。
    keyword_hit = best.get("match_type") == "keyword" or score >= 0.9999
    if keyword_hit and not _names_overlap(name, str(cust.get("name") or "")):
        _log.info(
            "副驾关键词命中但名字无重叠（%r vs %r），按新客户处理",
            name, cust.get("name"),
        )
        return CustomerContext(customer_name=name, new_contact=True, match_score=score)

    return CustomerContext(
        customer_id=int(cust.get("id") or 0),
        customer_name=str(cust.get("name") or name),
        matched=True,
        new_contact=False,
        match_score=score,
    )


def _list_company_customers(company_id: int) -> list[dict]:
    try:
        from trade import customer as customer_module

        return customer_module.list_by_company(company_id) or []
    except Exception as exc:
        _log.warning("副驾读取客户库失败：%s", exc)
        return []


def _fuzzy_search(query: str, company_id: int) -> list[dict]:
    try:
        from trade.database import get_connection
        from trade.vec_search import search_customers

        conn = get_connection()
        try:
            return search_customers(conn, query, company_id=company_id, top_k=5) or []
        finally:
            conn.close()
    except Exception as exc:
        _log.warning("副驾客户模糊检索失败：%s", exc)
        return []


def _get_customer(customer_id: int, company_id: int) -> dict | None:
    try:
        from trade import customer as customer_module

        return customer_module.get(int(customer_id), company_id=company_id)
    except Exception as exc:
        _log.warning("副驾读取客户档案失败：%s", exc)
        return None


def load_history(ctx: CustomerContext, *, company_id: int, limit: int = 10) -> list[str]:
    """取该客户近期对话要点（**仅命中客户**才有）。

    未命中 → 返回空列表（铁律 4：绝不把别家客户的历史带进来）。
    """
    if not ctx.matched or not ctx.customer_id:
        return []

    # 只按**归一后的客户名**归属历史。绝不能拿 customer_id 做子串判断：
    # id=1 会命中任何含 "1" 的文本（"1 号方案"、"10% 折扣"），把别家客户的
    # 对话带进来（复审 P1-2）。
    name_key = _normalize_name(ctx.customer_name)
    if len(name_key) < 2:
        # 名字太短（如 "A"）无法安全归属 —— 宁可没有历史，也不给错的历史。
        return []

    try:
        from trade import chat_memory

        # 按 customer_id 过滤（新数据）；老数据没有 customer_id，
        # 下面仍保留客户名粗筛作为第二道防线。
        rows = chat_memory.search_history(
            company_id=company_id,
            customer_id=ctx.customer_id,
            time_range="all",
            limit=limit,
        )
    except Exception as exc:
        _log.warning("副驾读取客户历史失败：%s", exc)
        return []

    out: list[str] = []
    for row in rows or []:
        query = str(row.get("query") or "").strip()
        if not query:
            continue
        # search_history 不按客户过滤（conversations 表没有 customer_id 列），
        # 所以这里只做粗筛：归一后的客户名出现在这段对话里才算数。
        blob_key = _normalize_name(f"{query} {row.get('response') or ''}")
        if name_key in blob_key:
            out.append(query[:200])
    return out


def load_product_entries(
    keywords: str, *, company_id: int, limit: int = 8
) -> tuple[list[dict[str, Any]], list[SourceRef]]:
    """按关键词在**本公司的文档库**里检索产品资料，并抽出可引用的数字出处。

    之前这里只列库的元数据（库名/路径），关键词根本没参与检索、facts 永远是空
    列表 —— 等于铁律 3 的单据来源是空的（复审 P1-1）。现在真的进文件里找：

        - 文本类（md/txt/csv/json/yaml/html）直接读；
        - PDF（PyMuPDF，前 3 页）、DOCX（python-docx）、XLSX（openpyxl，
          前 3 个 sheet × 200 行）走仓库已声明的依赖，缺失/损坏就跳过；
        - 全程有文件数 / 单文件大小 / 总字节预算，避免一次触发扫爆大目录。

    Returns:
        (条目列表, 出处列表)。`facts` 里的每个 value 是文件里**原文**的一处数字，
        草稿组装时会用同一套 numbers 规则做比对 —— 数字只能来自这里（铁律 3）。
    """
    entries: list[dict[str, Any]] = []
    facts: list[SourceRef] = []
    terms = _search_terms(keywords)
    if not terms:
        return entries, []

    try:
        from trade import library as library_module

        libs = library_module.list_by_company(company_id) or []
    except Exception as exc:
        _log.warning("副驾读取文档库失败：%s", exc)
        return entries, []

    # 先批量读文件、按关键词命中次数排序，再取前 limit 个文件做条目。
    scored: list[tuple[int, dict, Path, str]] = []
    total_bytes = 0
    files_left = _MAX_FILES

    for lib in libs:
        root = Path(str(lib.get("root_path") or ""))
        if not str(root) or not root.is_dir():
            continue
        for path in _iter_library_files(root, files_left):
            files_left -= 1
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size <= 0 or size > _MAX_FILE_BYTES:
                continue
            if total_bytes + size > _MAX_TOTAL_BYTES:
                break
            total_bytes += size
            text = _read_for_search(path)
            if not text:
                continue
            # 文件名也参与打分：价格表常以产品名命名，正文里未必重复写一遍。
            haystack = f"{path.name}\n{text}".lower()
            score = sum(haystack.count(term) for term in terms)
            if score > 0:
                scored.append((score, lib, path, text))
            if files_left <= 0:
                break
        if files_left <= 0:
            break

    scored.sort(key=lambda item: item[0], reverse=True)

    for _score, lib, path, text in scored[:limit]:
        library_name = str(lib.get("name") or path.parent.name)
        label = f"{library_name}/{path.name}"
        entries.append({
            "label": label,
            "source_file": path.name,
            "excerpt": _excerpt(text, terms),
            "matched_terms": [t for t in terms if t in text.lower()][:5],
        })
        for ref in _facts_from_text(text, label, terms):
            if len(facts) >= _MAX_FACTS:
                break
            facts.append(ref)
        if len(facts) >= _MAX_FACTS:
            break

    return entries, facts


def _search_terms(keywords: str) -> list[str]:
    """把关键词拆成去重的小写词（中文按常见分隔符切）。"""
    raw = (keywords or "").strip().lower()
    if not raw:
        return []
    terms: list[str] = []
    # 中文用户常用顿号/全角逗号分隔（"LED，灯带"）—— 只按空白切会把整串
    # 当成一个词，导致明明有货也查不到（复审 P2）。
    for part in re.split(r"[\s,，、;；/|]+", raw):
        part = part.strip()
        if len(part) < 2 or part in terms:
            continue
        terms.append(part)
        if len(terms) >= 8:
            break
    return terms


def _iter_library_files(root: Path, limit: int):
    """递归遍历库目录（跳过隐藏项与符号链接），最多 yield limit 个文件。

    跳过符号链接是数据隔离要求：库目录里指向外部的链接不该让副驾读出库外内容。
    """
    yielded = 0
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for filename in filenames:
                if filename.startswith("."):
                    continue
                path = Path(dirpath) / filename
                try:
                    if path.is_symlink() or not path.is_file():
                        continue
                except OSError:
                    continue
                yield path
                yielded += 1
                if yielded >= limit:
                    return
    except OSError:
        return


def _read_for_search(path: Path) -> str:
    """把文件读成纯文本；不支持的格式/读取失败返回空串（跳过，不报错）。"""
    suffix = path.suffix.lower()
    try:
        if suffix in _TEXT_SUFFIXES:
            raw = path.read_bytes()
            # 中文 CSV/TXT 可能是 GBK，先 UTF-8 再 GB18030，全失败才忽略错误
            for encoding in ("utf-8-sig", "gb18030"):
                try:
                    return raw.decode(encoding)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", errors="ignore")
        if suffix in _PDF_SUFFIXES:
            return _read_pdf(path)
        if suffix in _DOCX_SUFFIXES:
            return _read_docx(path)
        if suffix in _XLSX_SUFFIXES:
            return _read_xlsx(path)
    except Exception as exc:  # 单个文件损坏不影响整次检索
        _log.warning("副驾读取产品文件失败（%s）：%s", path.name, exc)
    return ""


def _read_pdf(path: Path) -> str:
    """读 PDF 文字层的前几页（扫描件没有文字层 → 返回空）。"""
    try:
        import fitz  # PyMuPDF（requirements.txt 已声明）
    except Exception:
        return ""
    document = None
    try:
        document = fitz.open(str(path))
        parts: list[str] = []
        for index, page in enumerate(document):
            if index >= _MAX_PDF_PAGES:
                break
            parts.append(page.get_text() or "")
        return "\n".join(parts)
    except Exception:
        return ""
    finally:
        if document is not None:
            try:
                document.close()
            except Exception:
                pass


def _read_docx(path: Path) -> str:
    try:
        import docx  # python-docx（requirements.txt 已声明）
    except Exception:
        return ""
    try:
        document = docx.Document(str(path))
        parts = [p.text for p in document.paragraphs if p.text]
        for table in document.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        return "\n".join(parts)
    except Exception:
        return ""


def _read_xlsx(path: Path) -> str:
    try:
        import openpyxl  # openpyxl（requirements.txt 已声明）
    except Exception:
        return ""
    workbook = None
    try:
        workbook = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        parts: list[str] = []
        for sheet in workbook.worksheets[:_MAX_EXCEL_SHEETS]:
            for index, row in enumerate(sheet.iter_rows(values_only=True)):
                if index >= _MAX_EXCEL_ROWS:
                    break
                cells = [
                    str(value).strip() for value in row
                    if value is not None and str(value).strip()
                ]
                if cells:
                    parts.append(" ".join(cells))
        return "\n".join(parts)
    except Exception:
        return ""
    finally:
        if workbook is not None:
            try:
                workbook.close()
            except Exception:
                pass


def _excerpt(text: str, terms: list[str]) -> str:
    """截取包含第一个关键词命中的一小段（供提示词展示）。"""
    lowered = text.lower()
    positions = [lowered.find(term) for term in terms]
    positions = [pos for pos in positions if pos >= 0]
    if not positions:
        return text[:_MAX_EXCERPT_CHARS].strip()
    start = max(0, min(positions) - _MAX_EXCERPT_CHARS // 3)
    return text[start:start + _MAX_EXCERPT_CHARS].strip()


def _facts_from_text(text: str, label: str, terms: list[str]) -> list[SourceRef]:
    """抽出一段文本里的数字及出处（优先靠近关键词的，同值去重）。"""
    lowered = text.lower()
    anchors = [lowered.find(term) for term in terms]
    anchors = [pos for pos in anchors if pos >= 0]
    anchor = min(anchors) if anchors else 0

    ranked: list[tuple[int, SourceRef]] = []
    seen: set[str] = set()
    for match in NUMBER_RE.finditer(text):
        key = number_key(match.group(0))
        if key is None or key in seen:
            continue
        seen.add(key)
        ranked.append((
            abs(match.start() - anchor),
            SourceRef(label=label, value=match.group(0).strip()),
        ))
    ranked.sort(key=lambda item: item[0])
    return [ref for _, ref in ranked[:_MAX_FACTS_PER_FILE]]


def build_context(
    contact: str,
    *,
    company_id: int,
    product_keywords: str = "",
    threshold: float = MATCH_THRESHOLD,
    with_history: bool = True,
) -> CustomerContext:
    """完整组装上下文：匹配客户 → 取历史 → 检索产品库。

    命中既有客户时带历史；未命中时 `new_contact=True` 且**不带任何既有上下文**。
    """
    ctx = match_customer(contact, company_id=company_id, threshold=threshold)
    if with_history and ctx.matched:
        ctx.history = load_history(ctx, company_id=company_id)
    ctx.product_entries, ctx.facts = load_product_entries(
        product_keywords, company_id=company_id
    )
    return ctx
