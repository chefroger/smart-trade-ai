"""制裁名单官方源：下载（白名单 + 流式上限）与解析（工单 P0-1）。

只用官方公开渠道。解析逐个源单独实现 —— 每份名单的坑都不一样：

  - OFAC SDN / 非 SDN：无表头，按列位置；ALT（别名）与 ADD（地址/国家）分开下载
  - 美国 CSL：有表头；alt_names 用分号分隔多个别名
  - UN：XML；个人名拆在 FIRST/SECOND/THIRD/FOURTH_NAME，别名在 INDIVIDUAL_ALIAS
  - EU：分号分隔 + UTF-8 BOM；一行一个姓名（含别名），名为 WholeName 或
    First/Middle/Last 组合
  - UK：第一行是 "Report Date: ..."，第二行才是表头；姓名拆在 Name 1..6
"""

from __future__ import annotations

import csv
import io
import sys
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import urlparse

from trade.osint.constants import _current_opener


@contextmanager
def _large_csv_fields():
    """解析名单期间临时放宽 csv 单字段上限（CSL 有超长字段）。

    **不能进程级全局放宽**：`trade/doc_extract.py` 依赖默认的 131072
    上限拒绝超大单元格（防止内存膨胀），全局提高会静默拆掉那道闸
    （测试 `test_huge_csv_field_returns_error` 钉住）。
    """
    previous = csv.field_size_limit()
    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
    try:
        yield
    finally:
        csv.field_size_limit(previous)

# ── 下载限制 ────────────────────────────────────────────────────────────────
# 只允许这些官方主机（白名单写死，避免配置被改成任意地址）
ALLOWED_HOSTS = frozenset({
    "sanctionslistservice.ofac.treas.gov",
    "data.trade.gov",
    "scsanctions.un.org",
    "webgate.ec.europa.eu",
    "sanctionslist.fcdo.gov.uk",
})

# 官方站点的已知跨主机跳转：入口主机 → ((目标**确切主机**, 路径前缀), ...)。
# 2026-11-23 审计 P0-A：只认入口主机会把 OFAC/UN 的官方 CDN 跳转当成攻击，
# 新装用户的这三份名单永远下载不下来。跳转必须成对出现：入口 A 不允许跳到
# 入口 B 的 CDN；https 仍然强制。
# W4：目标主机必须**完全相等**，不能只校验后缀 —— 否则攻击者只要建一个
# `attacker-bucket.s3.us-gov-west-1.amazonaws.com/Published/...` 就能通过。
# 实测官方桶：wc2h-sls-prod-public-published.s3.us-gov-west-1.amazonaws.com。
ALLOWED_REDIRECT_HOSTS: dict[str, tuple[tuple[str, str], ...]] = {
    "sanctionslistservice.ofac.treas.gov": (
        ("wc2h-sls-prod-public-published.s3.us-gov-west-1.amazonaws.com", "/Published/"),
    ),
    "scsanctions.un.org": (
        ("unsolprodfiles.blob.core.windows.net", ""),
    ),
}

# 冒烟探测只读前 1 MB：足够走完重定向链并校验最终主机
PROBE_BYTES = 1 << 20

# 单个文件上限。工单写 50 MB，但 UK 官方文件 2026-11 实测已达 50.5 MB
# （十进制），按 50*1024*1024=52.4 MB 仍会误杀 —— 取 64 MiB 留余量。
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
_DOWNLOAD_TIMEOUT = 180
_CHUNK = 1 << 20


@dataclass(frozen=True)
class Source:
    name: str        # 存库代号（OFAC / OFAC_NS / CSL / UN / EU / UK）
    label: str
    kind: str        # ofac_sdn / ofac_cons / csl / un / eu / uk
    urls: tuple[str, ...]  # 主文件在前；OFAC 三件套为 (PRIM, ALT, ADD)


@dataclass
class ParsedList:
    label: str
    source_url: str
    primary: int              # 主名称条数
    aliases: int              # 别名条数
    rows_total: int           # 源文件数据行数（含重复）
    rows: list[tuple[str, str, str]] = field(default_factory=list)  # (name, country, kind)


_OFAC_BASE = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/"

SOURCES: tuple[Source, ...] = (
    Source(
        "OFAC", "美国 OFAC SDN 名单", "ofac_sdn",
        (_OFAC_BASE + "SDN.CSV", _OFAC_BASE + "ALT.CSV", _OFAC_BASE + "ADD.CSV"),
    ),
    Source(
        "OFAC_NS", "美国 OFAC 非 SDN 名单", "ofac_cons",
        (_OFAC_BASE + "CONS_PRIM.CSV", _OFAC_BASE + "CONS_ALT.CSV", _OFAC_BASE + "CONS_ADD.CSV"),
    ),
    Source(
        "CSL", "美国综合筛查名单 (CSL)", "csl",
        ("https://data.trade.gov/downloadable_consolidated_screening_list/v1/consolidated.csv",),
    ),
    Source(
        "UN", "联合国安理会制裁名单", "un",
        ("https://scsanctions.un.org/resources/xml/en/consolidated.xml",),
    ),
    Source(
        "EU", "欧盟制裁名单", "eu",
        ("https://webgate.ec.europa.eu/fsd/fsf/public/files/"
         "csvFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw",),
    ),
    Source(
        "UK", "英国制裁名单", "uk",
        ("https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv",),
    ),
)

SOURCE_LABELS = {source.name: source.label for source in SOURCES}


# ── 下载 ────────────────────────────────────────────────────────────────────


def _check_entry(url: str) -> str:
    """校验入口 URL，返回入口主机（官方白名单内、https）。"""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in ALLOWED_HOSTS:
        raise ValueError(f"非官方名单主机，拒绝下载: {url}")
    return host


def redirect_allowed(entry_host: str, final_url: str) -> bool:
    """重定向终点是否允许：同主机放行；跨主机只认成对配置的**确切**主机。

    成对规则（审计 P0-A / W4）：OFAC 入口只能跳官方桶
    `wc2h-sls-prod-public-published.s3.us-gov-west-1.amazonaws.com`
    且路径以 `/Published/` 开头；UN 入口只能跳 Azure blob 主机。
    不做后缀匹配（攻击者自建同后缀桶即可绕过）；反向、交叉（OFAC 跳到
    UN 的 CDN）以及 http 一律拒绝。
    """
    parsed = urlparse(final_url)
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    # 同主机跳转（同站 301/302）仍属官方源
    if host == entry_host:
        return True
    for allowed_host, path_prefix in ALLOWED_REDIRECT_HOSTS.get(entry_host, ()):
        if host != allowed_host:
            continue
        return (not path_prefix) or (parsed.path or "").startswith(path_prefix)
    return False


@contextmanager
def _open_checked(url: str, timeout: int, *, on_final=None):
    """打开官方源并校验重定向终点；yield (response, entry_host, final_url)。

    on_final(final_url) 在**校验之前**调用：冒烟需要在校验失败时也能报告
    最终跳到了哪个主机。
    """
    entry_host = _check_entry(url)
    opener = _current_opener()  # 复用 SSRF 复查 + 系统代理配置
    with opener.open(_make_request(url), timeout=timeout) as response:
        final_url = response.geturl()
        if on_final is not None:
            on_final(final_url)
        if not redirect_allowed(entry_host, final_url):
            raise ValueError(f"重定向到非允许的名单主机，拒绝下载: {final_url}")
        yield response, entry_host, final_url


def download_official(
    url: str, *, timeout: int = _DOWNLOAD_TIMEOUT, max_bytes: int | None = None,
) -> bytes:
    """流式下载官方名单（只允许白名单主机，单文件上限 64 MiB）。

    max_bytes 仅供冒烟探测使用：读到该长度就断开，返回已读部分，
    不因文件本身更大而报错。
    """
    buffer = bytearray()
    with _open_checked(url, timeout) as (response, _entry, _final):
        declared = response.headers.get("Content-Length")
        if max_bytes is None and declared and declared.isdigit() and int(declared) > MAX_DOWNLOAD_BYTES:
            raise ValueError(f"文件过大（{declared} 字节）: {url}")
        while True:
            chunk = response.read(_CHUNK)
            if not chunk:
                break
            buffer.extend(chunk)
            if max_bytes is not None:
                if len(buffer) >= max_bytes:
                    del buffer[max_bytes:]
                    break
            elif len(buffer) > MAX_DOWNLOAD_BYTES:
                raise ValueError(f"下载超过 {MAX_DOWNLOAD_BYTES} 字节上限: {url}")
    return bytes(buffer)


def probe_official(
    url: str, *, timeout: int = _DOWNLOAD_TIMEOUT, max_bytes: int = PROBE_BYTES,
) -> dict:
    """真实下载冒烟：只读前 max_bytes，返回入口/最终主机与是否通过校验。

    返回的 ok=False 不抛异常，由调用方（CI 冒烟）汇总失败。
    """
    result = {
        "url": url,
        "entry_host": "",
        "final_host": "",
        "final_url": "",
        "bytes_read": 0,
        "ok": False,
        "error": "",
    }
    try:
        entry_host = _check_entry(url)
        result["entry_host"] = entry_host
        buffer = bytearray()

        def _record(final_url: str) -> None:
            result["final_url"] = final_url
            result["final_host"] = (urlparse(final_url).hostname or "").lower()

        with _open_checked(url, timeout, on_final=_record) as (response, _entry, _final):
            while len(buffer) < max_bytes:
                chunk = response.read(_CHUNK)
                if not chunk:
                    break
                buffer.extend(chunk)
        result["bytes_read"] = min(len(buffer), max_bytes)
        result["ok"] = True
    except Exception as exc:  # noqa: BLE001 —— 冒烟要把原因完整带回
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _make_request(url: str):
    import urllib.request

    return urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; Trade-AI/1.0; +https://github.com)",
            "Accept": "*/*",
        },
    )


def fetch_source(source: Source) -> ParsedList:
    """下载并解析一份名单（可能包含多个文件）。"""
    payloads = [download_official(url) for url in source.urls]
    return parse_source(source, payloads)


# ── 解析 ────────────────────────────────────────────────────────────────────


def _clean(cell: str | None) -> str:
    """去空白；OFAC 用 `-0-` 表示空值。"""
    value = (cell or "").strip()
    return "" if value in ("", "-0-") else value


def parse_source(source: Source, payloads: list[bytes]) -> ParsedList:
    """按 source.kind 分派到具体解析器（CSV 系临时放宽单字段上限）。"""
    if source.kind in ("ofac_sdn", "ofac_cons"):
        with _large_csv_fields():
            return _parse_ofac(source, payloads)
    text = _decode(payloads[0], source.kind)
    if source.kind == "csl":
        with _large_csv_fields():
            return _parse_csl(source, text)
    if source.kind == "un":
        return _parse_un(source, text)
    if source.kind == "eu":
        with _large_csv_fields():
            return _parse_eu(source, text)
    if source.kind == "uk":
        with _large_csv_fields():
            return _parse_uk(source, text)
    raise ValueError(f"未知名单类型: {source.kind}")


def _decode(raw: bytes, kind: str) -> str:
    """EU 文件带 UTF-8 BOM；其余按 UTF-8 解（坏字节替换，不中断）。

    同时去掉 DOS EOF 字符（\\x1a）：OFAC 的 CSV 末尾带一行只有该字符的
    "终止行"，不清掉会被算成一条没有名称的数据行（实测 SDN/CONS 各多 1）。
    """
    encoding = "utf-8-sig" if kind == "eu" else "utf-8"
    return raw.decode(encoding, errors="replace").replace("\x1a", "")


def _parse_ofac(source: Source, payloads: list[bytes]) -> ParsedList:
    """OFAC SDN / 非 SDN：PRIM 无表头 + ALT 别名 + ADD 国家。"""
    if len(payloads) < 3:
        raise ValueError(f"{source.name} 需要 PRIM/ALT/ADD 三个文件")
    prim_text = _decode(payloads[0], "ofac")
    alt_text = _decode(payloads[1], "ofac")
    add_text = _decode(payloads[2], "ofac")

    # 国家：同一 entity 取第一条非空地址的国家
    country_by_entity: dict[str, str] = {}
    for row in csv.reader(io.StringIO(add_text)):
        if len(row) >= 5:
            entity_id = row[0].strip()
            country = _clean(row[4])
            if entity_id and country and entity_id not in country_by_entity:
                country_by_entity[entity_id] = country

    rows: list[tuple[str, str, str]] = []
    entity_kind: dict[str, str] = {}
    primary = 0
    rows_total = 0
    # PRIM：ent_num, name, type（individual/entity/vessel）, program, ...
    for row in csv.reader(io.StringIO(prim_text)):
        if not any(cell.strip() for cell in row):
            continue
        rows_total += 1
        if len(row) < 2:
            continue
        name = _clean(row[1])
        if not name:
            continue
        entity_id = row[0].strip()
        # W1：个人与实体分开标，制裁命中分级要用
        raw_type = _clean(row[2]).casefold() if len(row) > 2 else ""
        kind = "person" if "individual" in raw_type or "person" in raw_type else "entity"
        entity_kind[entity_id] = kind
        rows.append((name, country_by_entity.get(entity_id, ""), kind))
        primary += 1

    # ALT：ent_num, alt_num, alt_type, alt_name, ...
    aliases = 0
    for row in csv.reader(io.StringIO(alt_text)):
        if len(row) < 4:
            continue
        alias = _clean(row[3])
        if not alias:
            continue
        entity_id = row[0].strip()
        rows.append((
            alias,
            country_by_entity.get(entity_id, ""),
            entity_kind.get(entity_id, "entity"),
        ))
        aliases += 1

    return ParsedList(
        label=source.label,
        source_url=source.urls[0],
        primary=primary,
        aliases=aliases,
        rows_total=rows_total,
        rows=rows,
    )


def _parse_csl(source: Source, text: str) -> ParsedList:
    """美国 CSL：有表头；name 为主名，alt_names 用分号分隔别名。"""
    reader = csv.DictReader(io.StringIO(text))
    rows: list[tuple[str, str, str]] = []
    primary = 0
    aliases = 0
    rows_total = 0
    for record in reader:
        rows_total += 1
        name = _clean(record.get("name"))
        raw_type = _clean(record.get("type")).casefold()
        kind = "person" if "individual" in raw_type else "entity"
        if name:
            rows.append((name, "", kind))
            primary += 1
        for alias in (_clean(record.get("alt_names")) or "").split(";"):
            alias = _clean(alias)
            if alias and alias.casefold() != name.casefold():
                rows.append((alias, "", kind))
                aliases += 1
    return ParsedList(
        label=source.label, source_url=source.urls[0],
        primary=primary, aliases=aliases, rows_total=rows_total, rows=rows,
    )


def _parse_un(source: Source, text: str) -> ParsedList:
    """UN XML：个人名由 FIRST/SECOND/THIRD/FOURTH_NAME 拼成；别名各有 ALIAS_NAME。"""
    root = ET.fromstring(text)
    rows: list[tuple[str, str, str]] = []
    primary = 0
    aliases = 0

    for individual in root.findall("./INDIVIDUALS/INDIVIDUAL"):
        parts = [
            (individual.findtext(tag) or "").strip()
            for tag in ("FIRST_NAME", "SECOND_NAME", "THIRD_NAME", "FOURTH_NAME")
        ]
        name = " ".join(part for part in parts if part)
        if name:
            country = ""
            for value in individual.findall("./NATIONALITY/VALUE"):
                if (value.text or "").strip():
                    country = value.text.strip()
                    break
            rows.append((name, country, "person"))
            primary += 1
        for alias in individual.findall("./INDIVIDUAL_ALIAS"):
            alias_name = (alias.findtext("ALIAS_NAME") or "").strip()
            if alias_name:
                rows.append((alias_name, "", "person"))
                aliases += 1

    for entity in root.findall("./ENTITIES/ENTITY"):
        name = (entity.findtext("FIRST_NAME") or "").strip()
        if name:
            rows.append((name, "", "entity"))
            primary += 1
        for alias in entity.findall("./ENTITY_ALIAS"):
            alias_name = (alias.findtext("ALIAS_NAME") or "").strip()
            if alias_name:
                rows.append((alias_name, "", "alias"))
                aliases += 1

    return ParsedList(
        label=source.label, source_url=source.urls[0],
        primary=primary, aliases=aliases, rows_total=primary + aliases, rows=rows,
    )


def _parse_eu(source: Source, text: str) -> ParsedList:
    """EU CSV：分号分隔；WholeName 优先，否则 First/Middle/Last 组合。"""
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    rows: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    rows_total = 0
    for record in reader:
        rows_total += 1
        whole = _clean(record.get("NameAlias_WholeName"))
        if whole:
            name = whole
        else:
            parts = [
                _clean(record.get(key))
                for key in ("NameAlias_FirstName", "NameAlias_MiddleName", "NameAlias_LastName")
            ]
            name = " ".join(part for part in parts if part)
        if not name:
            continue
        logical_id = _clean(record.get("Entity_LogicalId"))
        key = (logical_id, name.casefold())
        if key in seen:
            continue
        seen.add(key)
        subject_type = _clean(record.get("Entity_SubjectType")).upper()
        kind = "person" if subject_type == "P" else "entity"
        rows.append((name, "", kind))
    return ParsedList(
        label=source.label, source_url=source.urls[0],
        primary=len(rows), aliases=0, rows_total=rows_total, rows=rows,
    )


def _parse_uk(source: Source, text: str) -> ParsedList:
    """UK CSV：首行是 Report Date，第二行才是表头；姓名在 Name 1..6。

    W1：`Designation Type` 明确区分 Individual / Entity（2026-11 实测
    6629 条个人、2562 条实体），个人行必须标 person，否则同名个人会被
    当成实体判 confirmed。
    """
    first_newline = text.find("\n")
    body = text[first_newline + 1:] if first_newline >= 0 else text
    reader = csv.DictReader(io.StringIO(body))
    rows: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    rows_total = 0
    aliases = 0
    for record in reader:
        rows_total += 1
        parts = [(_clean(record.get(f"Name {i}")) or "") for i in range(1, 7)]
        name = " ".join(part for part in parts if part)
        if not name:
            continue
        unique_id = _clean(record.get("Unique ID"))
        dedupe_key = (unique_id, name.casefold())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        designation = (_clean(record.get("Designation Type")) or "").casefold()
        is_alias = "alias" in (_clean(record.get("Name type")) or "").casefold()
        # 个人：Designation Type = Individual；其余按实体处理。
        # 个人的别名同样标 person（姓名字段没有生日/证件号，撞名必须降级）。
        if "individual" in designation:
            kind = "person"
        elif is_alias:
            kind = "alias"
        else:
            kind = "entity"
        if is_alias:
            aliases += 1
        rows.append((name, "", kind))
    return ParsedList(
        label=source.label, source_url=source.urls[0],
        primary=len(rows) - aliases, aliases=aliases, rows_total=rows_total, rows=rows,
    )
