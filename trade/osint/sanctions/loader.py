"""
Trade AI Assistant — OSINT 制裁名单下载器 + 持久化缓存。

负责 OFAC SDN / UN 制裁名单的下载、解析、缓存管理。
缓存策略：进程内存 → 文件缓存（24h TTL）→ 网络下载 → 过期缓存 fallback。
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import time
from pathlib import Path

from trade.osint.constants import http_get

logger = logging.getLogger(__name__)

# ── 缓存基础设施 ──────────────────────────────────────────────────────────

# 进程内存缓存（整个进程生命周期有效，避免重复下载）
_sanctions_cache: dict[str, list[dict]] = {
    "OFAC": [],
    "UN": [],
}

# 每份名单的**来源与健康度** —— 与 _sanctions_cache 分开存放（后者是「名字 → 条目列表」
# 的纯数据映射，check_sanctions 会直接遍历它的值）。
#
# 为什么必须记录：加载失败时会落到 2 条硬编码 fallback，而返回结构里原先没有任何
# 字段能区分「比对过上万条 SDN 记录」与「只比对了几条样本」。报告于是输出绿色的
# 「✅ 未在任何制裁名单中发现匹配项」—— 被制裁的公司也会被判「干净」。
_sanctions_meta: dict[str, dict] = {}

# OFAC SDN 实际有上万条实体；低于这个数说明下载/解析出了问题，
# 不能当成「加载成功」。取 100 是保守下限（阈值过低会放过空页面/错误页）。
_MIN_OFAC_ENTRIES = 100

# OFAC 官方下载地址。允许有多个候选：历史上换过地址（旧地址实测已 404），
# 逐个尝试并把命中的那个记进 meta，便于事后判断数据源是否又变了。
_OFAC_URL_CANDIDATES = (
    "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV",
    "https://www.treasury.gov/ofac/downloads/sdn.csv",
)

# 文件缓存 TTL：24 小时后视为过期，触发重新下载
_CACHE_TTL_SECONDS = 86400


def _mark_loaded(list_name: str, entries: list[dict], source: str, note: str = "") -> None:
    """记录一份名单的加载结果（条目数 + 来源 + 是否降级）。

    Args:
        list_name: "OFAC" / "UN"
        entries: 解析出的条目
        source: "network" | "cache" | "fallback"
        note: 附加说明（如命中的 URL、失败原因），随 coverage 一起返回
    """
    _sanctions_cache[list_name] = entries
    _sanctions_meta[list_name] = {
        "entries": len(entries),
        "source": source,
        "degraded": source == "fallback",
        "note": note,
    }


def get_coverage() -> dict:
    """返回制裁数据源的健康度摘要（供 check_sanctions 一并返回给上层）。

    Returns:
        {
            "degraded": bool,        # 任一份名单走了 fallback 即为 True
            "total_entries": int,    # 实际参与比对的条目总数
            "lists": {名单名: {...}}, # 每份名单的 entries/source/degraded/note
        }
    """
    lists = dict(_sanctions_meta)
    degraded = any(m.get("degraded") for m in lists.values()) or not lists
    return {
        "degraded": degraded,
        "total_entries": sum(m.get("entries", 0) for m in lists.values()),
        "lists": lists,
    }


def _resolve_cache_dir() -> Path:
    """解析制裁名单文件缓存的存储目录。

    优先级: TRADE_HOME 环境变量 > 平台默认路径。
    macOS/Linux: ~/.trade/cache/sanctions/
    Windows:     %LOCALAPPDATA%\\trade\\cache\\sanctions\\
    """
    val = os.environ.get("TRADE_HOME", "").strip()
    if val:
        return Path(val) / "cache" / "sanctions"
    if os.name == "nt":
        _local = os.environ.get(
            "LOCALAPPDATA", str(Path.home() / "AppData" / "Local")
        )
        return Path(_local) / "trade" / "cache" / "sanctions"
    return Path.home() / ".trade" / "cache" / "sanctions"


_CACHE_DIR = _resolve_cache_dir()


def _get_cache_path(list_name: str) -> Path:
    """制裁名单的 JSON 文件缓存路径。

    文件名格式: {list_name}.json（如 OFAC.json / UN.json）。
    """
    return _CACHE_DIR / f"{list_name}.json"


def get_cache() -> dict[str, list[dict]]:
    """返回内存缓存的引用。供 checker 模块直接使用。"""
    return _sanctions_cache


# ── 文件缓存读写 ──────────────────────────────────────────────────────────

def _load_from_file_cache(list_name: str) -> list[dict] | None:
    """从 JSON 文件缓存加载制裁名单。TTL 过期返回 None。

    返回格式: [{name, label, type, program, country}, ...]
    """
    cache_file = _get_cache_path(list_name)
    if not cache_file.is_file():
        return None  # 文件不存在 → 需要下载

    try:
        with open(cache_file, encoding="utf-8") as f:
            cached = json.load(f)

        # 检查 TTL：超过 24 小时的缓存视为过期
        age = time.time() - cached.get("_loaded_at", 0)
        if age > _CACHE_TTL_SECONDS:
            logger.debug(
                "制裁名单缓存已过期: %s (%.1f 小时)", list_name, age / 3600
            )
            return None

        entries = cached.get("entries", [])
        logger.info("制裁名单从文件缓存加载: %s (%d 条)", list_name, len(entries))
        return entries
    except Exception as e:
        logger.warning("制裁名单文件缓存读取失败: %s", e)
        return None


def _load_from_file_cache_expired(list_name: str) -> list[dict] | None:
    """强制从文件缓存加载（忽略 TTL，作为网络不可用时的最后 fallback）。"""
    cache_file = _get_cache_path(list_name)
    if not cache_file.is_file():
        return None

    try:
        with open(cache_file, encoding="utf-8") as f:
            cached = json.load(f)
        entries = cached.get("entries", [])
        if entries:
            logger.info("使用过期缓存: %s (%d 条)", list_name, len(entries))
            return entries
    except Exception:
        pass  # 解析失败静默 fallthrough
    return None


def _save_to_file_cache(list_name: str, entries: list[dict]) -> None:
    """将制裁名单条目持久化到 JSON 文件缓存。

    文件格式:
      {
        "entries": [...],
        "_loaded_at": <unix timestamp>,
        "_list": "OFAC",
        "_count": 12345
      }
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)  # 确保缓存目录存在
    cache_file = _get_cache_path(list_name)
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "entries": entries,
                    "_loaded_at": time.time(),
                    "_list": list_name,
                    "_count": len(entries),
                },
                f,
                ensure_ascii=False,
            )
        logger.info("制裁名单已缓存: %s (%d 条)", list_name, len(entries))
    except Exception as e:
        logger.warning("制裁名单文件缓存写入失败: %s", e)


# ── OFAC SDN 名单加载（三级 fallback） ────────────────────────────────────

def load_ofac_sanctions() -> None:
    """加载 OFAC SDN 制裁名单。

    三级加载策略：
      1. 文件缓存（24h TTL）→ 命中直接返回
      2. 网络下载 → 从 ofac.treasury.gov 拉取最新 CSV → 缓存到本地
      3. 过期缓存 fallback → 网络失败时用过期数据
      4. 内存内置数据 → 所有途径都失败时的最终兜底

    结果写入 _sanctions_cache["OFAC"]。
    """
    # 1. 优先读文件缓存（网络未变化时直接命中，零网络开销）
    cached = _load_from_file_cache("OFAC")
    if cached is not None:
        _mark_loaded("OFAC", cached, "cache")
        return

    # 2. 网络下载最新 OFAC SDN CSV —— 逐个尝试候选地址（官方换过地址）
    entries: list[dict] = []
    used_url = ""
    errors: list[str] = []

    for url in _OFAC_URL_CANDIDATES:
        try:
            response = http_get(url, timeout=30)
            if not response:
                errors.append(f"{url}: 无响应")
                continue

            parsed: list[dict] = []
            # 用 csv.DictReader 解析 CSV，自动处理标题行
            reader = csv.DictReader(io.StringIO(response))
            for row in reader:
                # 优先使用 SDN_Name 列（全名），为空时回退到 Last Name
                name = row.get("SDN_Name", "").strip()
                if not name:
                    name = row.get("Last Name", "").strip()
                if name:
                    parsed.append(
                        {
                            "name": name,
                            "label": "OFAC SDN",
                            "type": row.get("SDN_Type", ""),
                            "program": row.get("Program", ""),
                            "country": row.get("Country", ""),
                        }
                    )

            # 条目数下限校验：地址失效时往往返回错误页/空页，解析出 0~几条，
            # 若只看"有没有解析出东西"就会把错误页当成加载成功。
            if len(parsed) < _MIN_OFAC_ENTRIES:
                errors.append(f"{url}: 仅解析出 {len(parsed)} 条（低于下限 {_MIN_OFAC_ENTRIES}）")
                continue

            entries = parsed
            used_url = url
            break
        except Exception as e:  # noqa: PERF203 — 逐个候选尝试，逐个记录原因
            errors.append(f"{url}: {e}")

    if entries:
        logger.info("OFAC 制裁名单下载完成: %d 条记录（来源 %s）", len(entries), used_url)
        _save_to_file_cache("OFAC", entries)
        _mark_loaded("OFAC", entries, "network", note=used_url)
        return

    # 3. Fallback：读过期缓存（网络不可用但有旧数据）
    logger.warning("OFAC 下载失败（候选地址均未取到足量数据）: %s", "; ".join(errors))
    stale = _load_from_file_cache_expired("OFAC")
    if stale is not None:
        _mark_loaded("OFAC", stale, "cache", note="过期缓存：" + "; ".join(errors))
        return

    # 4. 连过期缓存也没有：使用内存内置的 fallback 示例数据
    #    注意这里必须标 degraded —— 上层据此拒绝给出「未发现匹配」的结论。
    _mark_loaded(
        "OFAC",
        _get_fallback_ofac_entries(),
        "fallback",
        note="; ".join(errors),
    )


# ── UN 制裁名单加载 ──────────────────────────────────────────────────────

def load_un_sanctions() -> None:
    """加载联合国安理会制裁名单。

    UN 制裁名单目前不提供机器可读 CSV 端点（仅 HTML 表格页面），
    因此目前使用本地维护的 fallback 数据 —— **这份名单永远是降级状态**，
    必须如实标记，上层不得据此给出「未发现匹配」的结论。

    未来改进方向：
      1. 定期抓取 https://www.un.org/securitycouncil/content/un-sc-consolidated-list
      2. 使用第三方 sanctions 数据集
      3. 与 OFAC SDN 交叉引用来验证数据完整性

    注意：OFAC SDN 已覆盖大部分国际贸易制裁实体，
    UN / EU 制裁名单与 OFAC 高度重叠。
    """
    _mark_loaded(
        "UN",
        _get_fallback_un_entries(),
        "fallback",
        note="UN 无机器可读端点，仅比对内置样本",
    )


# ── Fallback 数据（所有途径失败时的内存兜底） ────────────────────────────

def _get_fallback_ofac_entries() -> list[dict]:
    """OFAC 内存备份（最常见的制裁主体示例）。

    当网络不可用、文件缓存不存在、且过期缓存也为空时使用。
    覆盖俄罗斯国防部和委内瑞拉国营企业两大常见制裁类别。
    """
    return [
        {
            "name": "RUSSIAN DEFENSE MINISTRY",
            "label": "OFAC SDN",
            "type": "Entity",
            "program": "RUSSIAN-DEFENSE",
            "country": "RU",
        },
        {
            "name": "GAS ROM",
            "label": "OFAC SDN",
            "type": "Entity",
            "program": "VENEZUELA",
            "country": "VE",
        },
    ]


def _get_fallback_un_entries() -> list[dict]:
    """UN 制裁名单内存备份。

    覆盖索马里青年党和阿富汗塔利班两类常见安理会制裁实体。
    """
    return [
        {"name": "AL-SHABAAB", "label": "UN 1267", "country": "SO"},
        {"name": "TALIBAN", "label": "UN 1267", "country": "AF"},
    ]
