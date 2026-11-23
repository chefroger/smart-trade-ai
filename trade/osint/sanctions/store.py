"""制裁名单的本地 SQLite 存储与查询（工单 P0-1）。

`check_sanctions()` 只查本地库，**不在请求路径上下载任何东西**；名单由
后台每日刷新写入（见 loader.start_background_refresh）。

表结构：
  lists     每份名单的健康度（条目数、来源、抓取时间、最后错误）
  entities  归一化后的姓名（主名 + 别名），tkey 为 token 集合键
  entities_fts  FTS5 外部内容索引（不可用时退回 LIKE 候选集）
"""

from __future__ import annotations

import difflib
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from trade.osint.sanctions.normalize import (
    FUZZY_THRESHOLD,
    HIT_THRESHOLD,
    SHORT_NAME_CHARS,
    STOPWORDS,
    core_tokens,
    normalize_name,
    token_key,
    tokens_of,
)
from trade.osint.sanctions.sources import SOURCE_LABELS, SOURCES

DB_FILENAME = "sanctions.db"
# 过期上限（2026-11-23 审计 P0-A）：
#   >72h 未成功刷新 → coverage 标 stale，报告写「名单已过期 N 小时」，仍可用；
#   >7d  → 按 degraded 处理（不发「未发现匹配」的绿色结论）。
STALE_WARN_HOURS = 72
STALE_DEGRADED_HOURS = 24 * 7


def _resolve_cache_dir() -> Path:
    """解析名单缓存目录（与旧版 JSON 缓存同位置）。

    优先级: TRADE_HOME > Windows LOCALAPPDATA > ~/.trade
    """
    value = os.environ.get("TRADE_HOME", "").strip()
    if value:
        return Path(value) / "cache" / "sanctions"
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        return Path(local) / "trade" / "cache" / "sanctions"
    return Path.home() / ".trade" / "cache" / "sanctions"


def db_path() -> Path:
    """当前进程使用的制裁库路径。"""
    return _resolve_cache_dir() / DB_FILENAME


# ── 连接与建表 ──────────────────────────────────────────────────────────────


def _connect(write: bool = False) -> sqlite3.Connection | None:
    """打开数据库；只读场景下库不存在返回 None（未下载过任何名单）。"""
    path = db_path()
    if not write and not path.is_file():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    if write:
        # WAL：后台刷新写入时查询端不会拿到 "database is locked"
        conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> bool:
    """建表；返回 FTS5 是否可用。"""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS lists (
            name            TEXT PRIMARY KEY,
            label           TEXT NOT NULL DEFAULT '',
            entries         INTEGER NOT NULL DEFAULT 0,
            aliases         INTEGER NOT NULL DEFAULT 0,
            rows_total      INTEGER NOT NULL DEFAULT 0,
            source_url      TEXT NOT NULL DEFAULT '',
            fetched_at      TEXT,
            last_attempt_at TEXT,
            last_error      TEXT
        );
        CREATE TABLE IF NOT EXISTS entities (
            id      INTEGER PRIMARY KEY,
            list    TEXT NOT NULL,
            name    TEXT NOT NULL,
            norm    TEXT NOT NULL,
            tkey    TEXT NOT NULL,
            country TEXT NOT NULL DEFAULT '',
            kind    TEXT NOT NULL DEFAULT 'entity'
        );
        CREATE INDEX IF NOT EXISTS idx_entities_tkey ON entities(tkey);
        CREATE INDEX IF NOT EXISTS idx_entities_list ON entities(list);
        """
    )
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5("
            "name, norm, content='entities', content_rowid='id', "
            "tokenize=\"unicode61 remove_diacritics 2\")"
        )
        return True
    except sqlite3.OperationalError:
        # 精简版 SQLite 没编译 FTS5：退回 LIKE 候选集（慢一些但可用）
        return False


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")




# ── 写入（后台刷新调用）────────────────────────────────────────────────────


def save_list(conn: sqlite3.Connection, source, parsed, *, fetched_at: str | None = None) -> None:
    """用一份解析结果替换该名单的全部条目。

    同一事务内先删后插：查询端（WAL）看到的是刷新前的完整快照，
    不会出现「删完了还没插」的半空状态。

    **空结果拒绝写入**（2026-11-22 审计 P1-1）：官方格式变更/空文件/截断下载
    都可能让解析器“成功返回 0 行”。先删后插会把整份名单清空，随后 coverage
    仍标健康、评分给满分干净——合规假阴性。这里在 DELETE 之前拒绝空 payload，
    本次刷新按失败处理（loader 会 mark_failure，旧数据保留）。
    """
    payload = []
    for name, country, kind in parsed.rows:
        norm = normalize_name(name)
        if not norm:
            continue
        toks = tokens_of(norm)
        payload.append(
            (source.name, name, norm, token_key(toks), country or "", kind or "entity")
        )
    if not payload or int(parsed.primary or 0) <= 0:
        raise ValueError(
            f"解析结果为空，拒绝覆盖旧名单（主名 {parsed.primary}，源行 {parsed.rows_total}）"
        )
    conn.execute("DELETE FROM entities WHERE list = ?", (source.name,))
    conn.executemany(
        "INSERT INTO entities(list, name, norm, tkey, country, kind) VALUES (?,?,?,?,?,?)",
        payload,
    )
    conn.execute(
        """
        INSERT INTO lists(name, label, entries, aliases, rows_total, source_url,
                          fetched_at, last_attempt_at, last_error)
        VALUES (?,?,?,?,?,?,?,?,NULL)
        ON CONFLICT(name) DO UPDATE SET
            label=excluded.label, entries=excluded.entries, aliases=excluded.aliases,
            rows_total=excluded.rows_total, source_url=excluded.source_url,
            fetched_at=excluded.fetched_at, last_attempt_at=excluded.last_attempt_at,
            last_error=NULL
        """,
        (
            source.name, parsed.label, parsed.primary, parsed.aliases,
            parsed.rows_total, parsed.source_url, fetched_at or _now_iso(),
            _now_iso(),
        ),
    )


def mark_failure(conn: sqlite3.Connection, source, error: str) -> None:
    """下载/解析失败：保留上一次成功的数据，只记录失败时间与原因。"""
    conn.execute(
        """
        INSERT INTO lists(name, label, source_url, last_attempt_at, last_error)
        VALUES (?,?,?,?,?)
        ON CONFLICT(name) DO UPDATE SET
            label=excluded.label, source_url=excluded.source_url,
            last_attempt_at=excluded.last_attempt_at, last_error=excluded.last_error
        """,
        (source.name, source.label, source.urls[0], _now_iso(), error[:500]),
    )


def rebuild_fts(conn: sqlite3.Connection) -> None:
    """重建 FTS 索引（批量替换后一次完成，避免逐行触发器拖慢刷新）。"""
    try:
        conn.execute("INSERT INTO entities_fts(entities_fts) VALUES('rebuild')")
    except sqlite3.OperationalError:
        pass  # FTS5 不可用：查询端会退回 LIKE


def ensure_writable_db(conn: sqlite3.Connection) -> bool:
    """写入前建表，返回 FTS 可用性。"""
    return _ensure_schema(conn)


# ── 读取：健康度 ────────────────────────────────────────────────────────────


def get_coverage() -> dict:
    """返回每份名单的覆盖情况（fetched_at / entries / degraded / 过期小时）。

    degraded 的口径（工单 P0-1 + 2026-11-23 审计 P0-A）：
      - 从来没成功下载过 → degraded；
      - 有历史数据但本次下载失败 → 沿用旧数据，degraded=False，附 last_error；
      - 数据超过 72 小时 → stale=True + stale_hours，报告写「名单已过期 N 小时」；
      - 数据超过 7 天 → degraded（不发绿色结论）。
    """
    conn = _connect()
    rows: dict[str, sqlite3.Row] = {}
    if conn is not None:
        try:
            rows = {r["name"]: r for r in conn.execute("SELECT * FROM lists")}
        finally:
            conn.close()

    now = datetime.now(UTC)
    lists: dict[str, dict] = {}
    degraded = False
    any_stale = False
    total_entries = 0

    for source in SOURCES:
        row = rows.get(source.name)
        if row is None or not row["fetched_at"]:
            lists[source.name] = {
                "label": source.label,
                "entries": 0,
                "aliases": 0,
                "source_url": source.urls[0],
                "fetched_at": None,
                "degraded": True,
                "note": (row["last_error"] if row is not None and row["last_error"] else "尚未成功下载"),
            }
            degraded = True
            continue

        entry = {
            "label": source.label,
            "entries": int(row["entries"] or 0),
            "aliases": int(row["aliases"] or 0),
            # 源文件数据行数（含重复/别名行）：用于和官方文件交叉核对解析完整性
            "rows_total": int(row["rows_total"] or 0),
            "source_url": row["source_url"] or source.urls[0],
            "fetched_at": row["fetched_at"],
            "degraded": False,
        }
        total_entries += entry["entries"]
        try:
            fetched = datetime.fromisoformat(row["fetched_at"])
            age_hours = max(0.0, (now - fetched).total_seconds() / 3600)
        except (ValueError, TypeError):
            # 无时区/损坏的 fetched_at 不能让整个制裁层瘫痪（审计 P2-7）
            age_hours = 0.0
        stale = age_hours > STALE_WARN_HOURS
        if stale:
            any_stale = True
            entry["stale"] = True
            entry["stale_hours"] = round(age_hours, 1)
            entry["note"] = f"名单已过期 {age_hours:.0f} 小时（超过 {STALE_WARN_HOURS} 小时）"
        if row["last_error"]:
            # 本次刷新失败但沿用了旧数据：如实标注，但不是 degraded
            refresh_note = f"本次刷新失败，沿用 {age_hours:.0f} 小时前的数据：{row['last_error']}"
            entry["note"] = f"{entry['note']}；{refresh_note}" if stale else refresh_note
        if age_hours > STALE_DEGRADED_HOURS:
            # 过期一周以上：旧数据不再当「可用结论」
            entry["degraded"] = True
            degraded = True
            too_old = (
                f"名单已过期 {age_hours:.0f} 小时（超过 "
                f"{STALE_DEGRADED_HOURS // 24} 天），按降级处理"
            )
            entry["note"] = f"{entry['note']}；{too_old}" if entry.get("note") else too_old
        if entry["entries"] <= 0:
            # “下载成功但 0 条”绝不是健康名单（2026-11-22 审计 P1-1）：
            # 可能来自格式变更/空文件/解析回归。必须降级，评分才会 fail-closed。
            entry["degraded"] = True
            entry["note"] = "名单解析结果为 0 条，按降级处理"
            degraded = True
        lists[source.name] = entry

    return {
        "degraded": degraded,
        "stale": any_stale,
        "total_entries": total_entries,
        "lists": lists,
    }


# ── 读取：名称匹配 ──────────────────────────────────────────────────────────


def _has_fts(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='entities_fts'"
    ).fetchone()
    return row is not None


def _candidates(conn: sqlite3.Connection, q_tokens: frozenset[str]) -> list[sqlite3.Row]:
    """取可能匹配的候选行（token 至少共享一个）。

    FTS5 可用时用全文索引；不可用时用 LIKE（慢一些，但结果集一致）。
    """
    if not q_tokens:
        return []
    if _has_fts(conn):
        expression = " OR ".join(f'"{token}"' for token in sorted(q_tokens))
        try:
            return conn.execute(
                "SELECT e.id, e.name, e.list, e.country, e.kind, e.tkey "
                "FROM entities e WHERE e.id IN "
                "(SELECT rowid FROM entities_fts WHERE entities_fts MATCH ?) LIMIT 20000",
                (expression,),
            ).fetchall()
        except sqlite3.OperationalError:
            pass  # FTS 索引尚未建立（首次刷新中断）：走 LIKE 兜底
    clauses = " OR ".join("norm LIKE ?" for _ in q_tokens)
    params = [f"%{token}%" for token in sorted(q_tokens)]
    return conn.execute(
        f"SELECT id, name, list, country, kind, tkey FROM entities "
        f"WHERE {clauses} LIMIT 20000",
        params,
    ).fetchall()


def _person_spelling_variant(q_core, entry_core) -> bool:
    """姓名拼写变体（Victor ↔ Viktor）：只对个人条目放宽一个 token（W1）。"""
    if len(q_core) < 2:
        return False
    q_only = q_core - entry_core
    e_only = entry_core - q_core
    if len(q_only) != 1 or not (1 <= len(e_only) <= 2):
        return False
    missing = next(iter(q_only))
    return any(
        difflib.SequenceMatcher(None, missing, candidate).ratio() >= 0.8
        for candidate in e_only
    )


_PERSON_ORG_TOKENS = frozenset({
    "bank", "airlines", "airways", "shipping", "line", "lines", "ministry",
    "agency", "committee", "council", "fund", "foundation", "university",
    "hospital", "institute", "association", "authority", "bureau",
    "laboratories", "laboratory", "labs", "electronics", "companies",
})

# 常见中文姓氏（拼音）。CSL 的 BIS 等来源没有 type 字段，只能靠
# 「两段式 姓+名」识别 "Wang Wei" 这类个人；首词是姓氏才启用，
# 避免把 "Samsung Electronics" 这类公司名误判成个人。
_CN_SURNAMES = frozenset({
    "wang", "zhang", "li", "liu", "chen", "yang", "huang", "zhao", "wu",
    "zhou", "xu", "sun", "ma", "zhu", "hu", "guo", "he", "gao", "lin",
    "luo", "zheng", "liang", "xie", "song", "tang", "han", "feng", "deng",
    "cao", "peng", "zeng", "xiao", "tian", "dong", "pan", "yuan", "cai",
    "jiang", "yu", "du", "ye", "cheng", "su", "wei", "lv", "ding", "ren",
    "shen", "yao", "lu", "cui", "zhong", "tan", "qiu", "qin", "fan", "jin",
    "shi", "hou", "shao", "meng", "long", "wan", "duan", "lei", "qian",
    "yin", "gu", "lai", "gong", "wen", "pang",
})


def _is_person_row(row: sqlite3.Row, tokens: list[str]) -> bool:
    """该条目是否按个人处理（W1）。

    优先用解析层标的 kind；老库没有 person 标记时退到结构判断：
      - 一次逗号分成两段、无数字、无公司后缀、总 token ≤3（"WANG, Wei"）
      - 无逗号的两段式中文姓名（"Wang Wei"；CSL 的 BIS 行没有 type 字段）
    """
    if row["kind"] == "person":
        return True
    # 老库的别名行 kind='alias'，同样允许结构判断
    if row["kind"] not in ("entity", "alias"):
        return False
    raw = str(row["name"] or "")
    if any(ch.isdigit() for ch in raw):
        return False
    if any(token in STOPWORDS or token in _PERSON_ORG_TOKENS for token in tokens):
        return False
    if raw.count(",") == 1:
        left, right = (part.strip() for part in raw.split(",", 1))
        if not left or not right:
            return False
        # "BOUT, Viktor Anatolijevitch" 这类含父名的三段也算个人
        return len(tokens) <= 3 and len(left.split()) <= 3 and len(right.split()) <= 3
    words = raw.split()
    if len(words) == 2 and all(word.isalpha() for word in words):
        # 姓在前（"Wang Wei"）或名在前（"Jack Wang"）都算
        return any(word.casefold() in _CN_SURNAMES for word in words)
    return False


def search(name: str, country: str | None = None, limit: int = 20) -> list[dict]:
    """在本地库中匹配名称，返回按置信度降序的命中列表。

    2026-11-23 工单 P1-G（11-22 P1-A）：
      - 法定后缀/泛词（co/ltd/technology/group…）不参与匹配，避免凑出大量
        疑似命中；中文「有限公司/科技/贸易」等归一化时直接剥掉。
      - 完整 token 或**核心 token** 集合一致 → confirmed（score 1.0）；
        子集/拼写差异 → possible（≤0.95）。
      - 短名（<8 字符）只接受完整/核心 token 精确匹配（如 HUAWEI → 名单里的
        HUAWEI TECHNOLOGIES CO LTD 的核心集都是 {huawei}）。
    """
    q_norm = normalize_name(name)
    if not q_norm:
        return []
    q_tokens_tuple = tokens_of(q_norm)
    q_tokens = frozenset(q_tokens_tuple)
    q_core = core_tokens(q_tokens_tuple)
    is_short = len(q_norm) < SHORT_NAME_CHARS
    q_key = token_key(q_tokens_tuple)

    conn = _connect()
    if conn is None:
        return []
    try:
        exact_rows = conn.execute(
            "SELECT id, name, list, country, kind, tkey FROM entities "
            "WHERE tkey = ? LIMIT 500",
            (q_key,),
        ).fetchall()
        # 短名也要拿候选：核心 token 精确匹配同样适用于品牌短名
        candidates = _candidates(conn, q_tokens) if q_tokens else []
    finally:
        conn.close()

    best: dict[int, dict] = {}

    def consider(
        row: sqlite3.Row, score: float, field: str, confirmation: str, *,
        person: bool = False,
    ) -> None:
        if score < (1.0 if is_short else HIT_THRESHOLD):
            return
        # 个人只有姓名一致（没有出生日期/证件号佐证）→ 不能当 confirmed
        if person:
            confirmation = "possible"
        current = best.get(row["id"])
        if current is None or score > current["score"]:
            best[row["id"]] = {
                "list": row["list"],
                "list_label": SOURCE_LABELS.get(row["list"], row["list"]),
                "matched_field": field,
                "matched_value": row["name"],
                "score": round(score, 3),
                "confirmation": confirmation,
                "person": person,
                "country": row["country"] or "",
            }

    for row in exact_rows:
        consider(
            row, 1.0, "exact_name", "confirmed",
            # 结构判断用条目自身的 token（老库没有 person 标记时靠它）
            person=_is_person_row(row, (row["tkey"] or "").split()),
        )

    if q_core:
        for row in candidates:
            tkey = row["tkey"] or ""
            if not tkey:
                continue
            entry_tokens = tkey.split()
            entry_core = core_tokens(entry_tokens)
            if not entry_core:
                continue
            if entry_core == q_core:
                # 泛词剥掉后核心一致。单 token 核心只有在短名/品牌查询里才算
                # confirmed；非短名查询不再产出「SHENZHEN」这类单 token 疑似命中
                # （W1 验收）。
                if len(q_core) >= 2 or is_short:
                    consider(
                        row, 1.0, "core_exact", "confirmed",
                        person=_is_person_row(row, entry_tokens),
                    )
                continue
            if is_short:
                # 短品牌名（Rosneft / Huawei）允许核心 token 是条目核心的子集，
                # 但要求 token 足够长且条目核心 ≤2，避免 "ABC" 这类泛短名；
                # 仅在短名分支启用，不影响 W1 的 Shenzhen 长问题验收。
                if (len(q_core) == 1 and len(entry_core) <= 2
                        and q_core < entry_core
                        and len(next(iter(q_core))) >= 6):
                    consider(
                        row, 1.0, "core_exact", "confirmed",
                        person=_is_person_row(row, entry_tokens),
                    )
                continue
            if q_core <= entry_core or entry_core <= q_core:
                smaller = len(q_core) if q_core <= entry_core else len(entry_core)
                larger = len(entry_core) if q_core <= entry_core else len(q_core)
                field = "name_contains" if q_core <= entry_core else "name_contained_in_query"
                consider(
                    row, min(smaller / larger * 1.2, 0.95), field, "possible",
                    person=_is_person_row(row, entry_tokens),
                )
            else:
                union = len(q_core | entry_core)
                if union:
                    similarity = len(q_core & entry_core) / union
                    if similarity >= FUZZY_THRESHOLD:
                        consider(
                            row, min(similarity * 0.9, 0.9), "name_similar",
                            "possible", person=_is_person_row(row, entry_tokens),
                        )
                    elif (
                        (row["kind"] == "person" or "," in str(row["name"] or ""))
                        and _is_person_row(row, entry_tokens)
                        and _person_spelling_variant(q_core, entry_core)
                    ):
                        # 拼写变体只给 possible，不能当确认命中
                        consider(row, 0.8, "name_similar", "possible", person=True)

    hits = list(best.values())

    # 国家过滤：同名但不同国家 → 置信度减半（沿用旧行为）
    if country and hits:
        country_lower = country.casefold()
        for hit in hits:
            hit_country = (hit.get("country") or "").casefold()
            if hit_country and country_lower not in hit_country and hit_country not in country_lower:
                hit["score"] = round(hit["score"] * 0.5, 3)

    hits.sort(key=lambda item: item["score"], reverse=True)
    return hits[:limit]


def list_entries(list_name: str) -> list[dict]:
    """读取某份名单的全部条目（兼容 get_cache 的旧接口，按需调用）。"""
    conn = _connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT name, country, kind FROM entities WHERE list = ?", (list_name,)
        ).fetchall()
    finally:
        conn.close()
    return [
        {"name": row["name"], "label": SOURCE_LABELS.get(list_name, list_name),
         "country": row["country"], "kind": row["kind"]}
        for row in rows
    ]
