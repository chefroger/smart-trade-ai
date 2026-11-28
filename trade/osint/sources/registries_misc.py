"""其他国家的企业登记（工单 P2-2）：法国 / 挪威 / 巴西。

- 法国：recherche-entreprises.api.gouv.fr（官方开放数据，按名称）
- 挪威：data.brreg.no Enhetsregisteret（官方，按名称）
- 巴西：BrasilAPI 聚合官方 CNPJ 数据（只在目标含 CNPJ 号时查）

只取公开登记字段（名称、编号、成立日期、状态、地址），不做信用判断。
"""

from __future__ import annotations

import re

from trade.osint.sources.base import (
    Fetcher,
    SourceResult,
    TargetContext,
    error_result,
    fetch_json,
    quote,
    skipped,
)

NAME = "registries_misc"
LABEL = "其他企业登记（FR/NO/BR）"
FR_URL = "https://recherche-entreprises.api.gouv.fr/search?q={q}&per_page=3"
NO_URL = "https://data.brreg.no/enhetsregisteret/api/enheter?navn={q}&size=3"
BR_URL = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"

_CNPJ_RE = re.compile(r"\b(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})\b")


def _hint(ctx: TargetContext) -> str:
    if ctx.company_name:
        return ctx.company_name
    if ctx.domain:
        return ctx.domain.split(".")[0]
    return ""


def _cnpj(target: str) -> str | None:
    match = _CNPJ_RE.search(target)
    return re.sub(r"\D", "", match.group(1)) if match else None


def _applicable(ctx: TargetContext) -> bool:
    if ctx.target_type == "person":
        return False
    return bool(_hint(ctx).strip() or _cnpj(ctx.target))


def run(ctx: TargetContext, fetch: Fetcher | None = None) -> SourceResult:
    """查 FR/NO（按名称）与 BR（按 CNPJ）。"""
    if not _applicable(ctx):
        return skipped(NAME, "没有可用于企业登记的公司名/CNPJ")

    hint = _hint(ctx).strip()
    cnpj = _cnpj(ctx.target)
    facts: list[dict] = []
    data: dict = {}
    attempted = 0
    errors: list[Exception] = []

    if hint:
        # 法国
        attempted += 1
        try:
            fr = fetch_json(FR_URL.format(q=quote(hint)), fetch=fetch)
        except Exception as exc:  # noqa: BLE001 —— 单国失败不影响其它，全失败时返回 error
            fr = None
            errors.append(exc)
        fr_rows = ((fr or {}).get("results") or [])[:2] if isinstance(fr, dict) else []
        for row in fr_rows:
            name = str(row.get("nom_complet") or row.get("nom_raison_sociale") or "")
            if hint.lower() not in name.lower():
                continue
            parts = [f"法国登记：{name}"]
            if row.get("siren"):
                parts.append(f"SIREN {row['siren']}")
            if row.get("date_creation"):
                parts.append(f"成立 {row['date_creation']}")
            if row.get("etat_administratif"):
                parts.append(f"状态 {row['etat_administratif']}")
            siege = row.get("siege") or {}
            addr = " ".join(str(siege.get(key) or "").strip() for key in (
                "adresse", "code_postal", "libelle_commune",
            )).strip()
            if addr:
                parts.append(f"地址 {addr}")
            facts.append({
                "text": "，".join(parts),
                "url": "https://annuaire-entreprises.data.gouv.fr/",
            })
            data.setdefault("fr", []).append(row)

        # 挪威
        attempted += 1
        try:
            no = fetch_json(NO_URL.format(q=quote(hint)), fetch=fetch)
        except Exception as exc:  # noqa: BLE001
            no = None
            errors.append(exc)
        enheter = ((no or {}).get("_embedded") or {}).get("enheter") if isinstance(no, dict) else None
        for row in (enheter or [])[:2]:
            name = str(row.get("navn") or "")
            if hint.lower() not in name.lower():
                continue
            parts = [f"挪威登记：{name}"]
            if row.get("organisasjonsnummer"):
                parts.append(f"组织号 {row['organisasjonsnummer']}")
            if row.get("registreringsdatoEnhetsregisteret"):
                parts.append(f"注册 {row['registreringsdatoEnhetsregisteret']}")
            addr_obj = row.get("forretningsadresse") or {}
            addr = " ".join(str(addr_obj.get(key) or "").strip() for key in (
                "adresse", "postnummer", "poststed",
            )).strip()
            if addr:
                parts.append(f"地址 {addr}")
            facts.append({
                "text": "，".join(parts),
                "url": f"https://virksomhet.brreg.no/nb/oppslag/enheter/{row.get('organisasjonsnummer', '')}",
            })
            data.setdefault("no", []).append(row)

    if cnpj:
        attempted += 1
        try:
            br = fetch_json(BR_URL.format(cnpj=cnpj), fetch=fetch)
        except Exception as exc:  # noqa: BLE001
            br = None
            errors.append(exc)
        if isinstance(br, dict) and br.get("razao_social"):
            parts = [f"巴西登记：{br['razao_social']}", f"CNPJ {br.get('cnpj') or cnpj}"]
            if br.get("data_inicio_atividade"):
                parts.append(f"成立 {br['data_inicio_atividade']}")
            if br.get("descricao_situacao_cadastral"):
                parts.append(f"状态 {br['descricao_situacao_cadastral']}")
            addr = " ".join(str(br.get(key) or "").strip() for key in (
                "logradouro", "numero", "bairro", "municipio", "uf", "cep",
            )).strip()
            if addr:
                parts.append(f"地址 {addr}")
            facts.append({"text": "，".join(parts), "url": BR_URL.format(cnpj=cnpj)})
            data["br"] = br

    if facts:
        return SourceResult(NAME, "hit", facts=facts, data=data)
    if attempted > 0 and len(errors) >= attempted:
        # 全部拟查登记库均报错：绝不伪装成 miss（P2-6）
        return error_result(NAME, exc=errors[0])
    return SourceResult(NAME, "miss", error="FR/NO/BR 未查到匹配登记")
