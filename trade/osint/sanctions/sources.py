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
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urlparse

from trade.osint.constants import _current_opener

# ── 下载限制 ────────────────────────────────────────────────────────────────
# 只允许这些官方主机（白名单写死，避免配置被改成任意地址）
ALLOWED_HOSTS = frozenset({
    "sanctionslistservice.ofac.treas.gov",
    "data.trade.gov",
    "scsanctions.un.org",
    "webgate.ec.europa.eu",
    "sanctionslist.fcdo.gov.uk",
})

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


def download_official(url: str, *, timeout: int = _DOWNLOAD_TIMEOUT) -> bytes:
    """流式下载官方名单（只允许白名单主机，单文件上限 64 MiB）。

    显式绕过通用 http_get 的 2 MB 上限 —— 但目标主机写死白名单，
    而不是把「任意 URL 可下载 50 MB」的能力开放出去。
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in ALLOWED_HOSTS:
        raise ValueError(f"非官方名单主机，拒绝下载: {url}")

    opener = _current_opener()  # 复用 SSRF 复查 + 系统代理配置
    request = _make_request(url)
    buffer = bytearray()
    with opener.open(request, timeout=timeout) as response:
        # 跟随重定向后复查最终主机：通用 opener 只拦内网，不认名单白名单（审计 P2-8）
        final = urlparse(response.geturl())
        if final.scheme != "https" or final.hostname not in ALLOWED_HOSTS:
            raise ValueError(f"重定向到非官方名单主机，拒绝下载: {response.geturl()}")
        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > MAX_DOWNLOAD_BYTES:
            raise ValueError(f"文件过大（{declared} 字节）: {url}")
        while True:
            chunk = response.read(_CHUNK)
            if not chunk:
                break
            buffer.extend(chunk)
            if len(buffer) > MAX_DOWNLOAD_BYTES:
                raise ValueError(f"下载超过 {MAX_DOWNLOAD_BYTES} 字节上限: {url}")
    return bytes(buffer)


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
    """按 source.kind 分派到具体解析器。"""
    if source.kind in ("ofac_sdn", "ofac_cons"):
        return _parse_ofac(source, payloads)
    text = _decode(payloads[0], source.kind)
    if source.kind == "csl":
        return _parse_csl(source, text)
    if source.kind == "un":
        return _parse_un(source, text)
    if source.kind == "eu":
        return _parse_eu(source, text)
    if source.kind == "uk":
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
    primary = 0
    rows_total = 0
    # PRIM：ent_num, name, type, program, ...
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
        rows.append((name, country_by_entity.get(entity_id, ""), "entity"))
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
        rows.append((alias, country_by_entity.get(entity_id, ""), "alias"))
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
        if name:
            rows.append((name, "", "entity"))
            primary += 1
        for alias in (_clean(record.get("alt_names")) or "").split(";"):
            alias = _clean(alias)
            if alias and alias.casefold() != name.casefold():
                rows.append((alias, "", "alias"))
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
            rows.append((name, country, "entity"))
            primary += 1
        for alias in individual.findall("./INDIVIDUAL_ALIAS"):
            alias_name = (alias.findtext("ALIAS_NAME") or "").strip()
            if alias_name:
                rows.append((alias_name, "", "alias"))
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
        rows.append((name, "", "entity"))
    return ParsedList(
        label=source.label, source_url=source.urls[0],
        primary=len(rows), aliases=0, rows_total=rows_total, rows=rows,
    )


def _parse_uk(source: Source, text: str) -> ParsedList:
    """UK CSV：首行是 Report Date，第二行才是表头；姓名在 Name 1..6。"""
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
        kind = "alias" if "alias" in (_clean(record.get("Name type")) or "").casefold() else "entity"
        if kind == "alias":
            aliases += 1
        rows.append((name, "", kind))
    return ParsedList(
        label=source.label, source_url=source.urls[0],
        primary=len(rows) - aliases, aliases=aliases, rows_total=rows_total, rows=rows,
    )
