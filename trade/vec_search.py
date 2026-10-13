"""
Smart Trade AI — 客户/文档语义检索（优化路线 P0-2）。

用 sqlite-vec（SQLite 向量扩展）在本地做向量检索，零服务器、零运维，
与项目 local-first 架构天然契合。

设计：
- 向量存在 vec0 虚表里（metadata 列：customer_id / company_id），
  元信息（维度、模型、更新时间）存在普通表 vec_meta；
- 维度变化时自动重建（backend 换了就重建索引，不静默错配）；
- sqlite-vec 未安装 / 扩展加载失败 → 所有函数优雅降级为关键词 LIKE
  检索，保证功能永不中断；
- embedding 文本由调用方组装（客户：name+contact+note+extra 摘要；
  文档：标题+摘要），本模块只管存取。

环境变量：
    TRADE_VEC_TOP_K        默认返回条数（默认 10）
    TRADE_VEC_MIN_SCORE    最低分（默认 0.43，score=1/(1+distance)）。
                           **别凭感觉调**：L2 归一化下无关向量的距离恒为 √2，
                           score 有恒定正交基线 0.4142 —— 低于它等于不过滤。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time

logger = logging.getLogger(__name__)

_vec_available: bool | None = None
_vec_lock = threading.Lock()


def vec_available() -> bool:
    """sqlite-vec 是否可用（带缓存的探测）。"""
    global _vec_available
    with _vec_lock:
        if _vec_available is not None:
            return _vec_available
        try:
            import sqlite_vec  # noqa: F401
        except ImportError:
            logger.info("sqlite-vec 未安装，语义检索降级为关键词检索（pip install sqlite-vec 可启用）")
            _vec_available = False
            return False
        # 进一步验证扩展真的能 load（某些精简 sqlite 构建会禁用扩展）
        try:
            conn = sqlite3.connect(":memory:")
            conn.enable_load_extension(True)
            import sqlite_vec

            sqlite_vec.load(conn)
            conn.execute("CREATE VIRTUAL TABLE _vec_probe USING vec0(embedding float[8])")
            conn.close()
        except Exception as e:
            logger.warning("sqlite-vec 扩展加载失败，降级为关键词检索: %s", e)
            _vec_available = False
            return False
        _vec_available = True
        return True


def _load_vec(conn: sqlite3.Connection) -> bool:
    """在给定连接上加载 vec0 扩展。失败返回 False。

    加载完**立刻关掉** extension loading：这是长驻的应用连接，
    留着开关意味着任何一处 SQL 注入都能加载任意扩展。
    """
    if not vec_available():
        return False
    try:
        conn.enable_load_extension(True)
        import sqlite_vec

        sqlite_vec.load(conn)
        return True
    except Exception as e:
        logger.warning("vec0 扩展加载失败: %s", e)
        return False
    finally:
        try:
            conn.enable_load_extension(False)  # 只需打开一瞬间；查询不受影响
        except Exception:
            pass


def _serialize(vec: list[float]) -> bytes:
    import sqlite_vec

    return sqlite_vec.serialize_float32(vec)


# ── Schema ────────────────────────────────────────────────────────────────

META_SQL = """
CREATE TABLE IF NOT EXISTS vec_meta (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    dim           INTEGER NOT NULL,
    model         TEXT    NOT NULL DEFAULT '',
    updated_at    REAL    NOT NULL,
    backend_state TEXT    NOT NULL DEFAULT ''
);
"""


def ensure_vec_schema(
    conn: sqlite3.Connection, dim: int, model: str = "", *, allow_rebuild: bool = True
) -> bool:
    """确保向量表结构存在。维度/模型变化时按 allow_rebuild 决定是否重建。

    **allow_rebuild=False 是给单条 upsert 用的**：重建会 DROP 整张 vec_customers
    （其他租户/客户的向量一起没了），单条写入场景绝不能接受这种"顺手清库"
    —— 维度对不上说明配置变了，正确动作是跳过这次写入、提示做一次全量重建。
    """
    if not _load_vec(conn):
        return False
    conn.execute(META_SQL)
    row = conn.execute("SELECT dim, model FROM vec_meta WHERE id = 1").fetchone()
    if row is None:
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_customers USING vec0("
            f"customer_id INTEGER, company_id INTEGER, embedding float[{dim}])"
        )
        conn.execute(
            "INSERT INTO vec_meta (id, dim, model, updated_at) VALUES (1, ?, ?, ?)",
            (dim, model, time.time()),
        )
        conn.commit()
        return True
    if row[0] != dim or row[1] != model:
        if not allow_rebuild:
            logger.warning(
                "向量维度/模型与索引不一致（%s/%s -> %s/%s），跳过本次单条写入；"
                "请跑一次全量重建（rebuild_all_customers）",
                row[1], row[0], model, dim,
            )
            return False
        logger.info("向量维度/模型变化（%s/%s -> %s/%s），重建 vec_customers", row[1], row[0], model, dim)
        conn.execute("DROP TABLE IF EXISTS vec_customers")
        conn.execute(
            f"CREATE VIRTUAL TABLE vec_customers USING vec0("
            f"customer_id INTEGER, company_id INTEGER, embedding float[{dim}])"
        )
        conn.execute(
            "UPDATE vec_meta SET dim = ?, model = ?, updated_at = ?, backend_state = '' WHERE id = 1",
            (dim, model, time.time()),
        )
        conn.commit()
    return True


# ── 后端状态持久化（跨进程复用同一向量空间）──────────────────────────────
#
# 为什么需要：TF-IDF 的空间由 fit 语料决定，而写入向量（建索引那次进程）与
# 查询向量（以后每次搜索）可能跨进程。不持久化的话，服务一重启就没有同一份
# 词表/IDF —— 查询向量与库里存的向量不可比，只能降级关键词（功能静默消失）。
# 把 fit 结果存进 vec_meta，重启后恢复即可继续用。

def save_backend_state(conn: sqlite3.Connection, backend=None) -> bool:
    """把后端的 fit 状态写入 vec_meta。非 TF-IDF（无需 fit）返回 True 不落盘。"""
    from trade.embeddings import get_backend

    backend = backend or get_backend(scope="vec_search")
    try:
        if not getattr(backend, "needs_fit", False):
            return True  # ST 后端无状态，无需持久化
        state = backend.export_state()
        if not state:
            return False
        conn.execute(
            "UPDATE vec_meta SET backend_state = ? WHERE id = 1",
            (json.dumps(state, ensure_ascii=False),),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.warning("后端状态持久化失败: %s", e)
        return False


def load_backend_state(conn: sqlite3.Connection, backend=None) -> bool:
    """从 vec_meta 恢复后端的 fit 状态。返回是否可用（未 fit）。"""
    from trade.embeddings import get_backend

    backend = backend or get_backend(scope="vec_search")
    if not getattr(backend, "needs_fit", False):
        return True
    if getattr(backend, "_fitted", False):
        return True  # 本进程已 fit 过，无需恢复
    try:
        row = conn.execute("SELECT backend_state FROM vec_meta WHERE id = 1").fetchone()
        if not row or not row[0]:
            return False
        return bool(backend.load_state(json.loads(row[0])))
    except Exception as e:
        logger.warning("后端状态恢复失败: %s", e)
        return False


# ── 索引写入 ──────────────────────────────────────────────────────────────

def upsert_customer_vector(
    conn: sqlite3.Connection,
    customer_id: int,
    company_id: int,
    text: str,
    *,
    backend=None,
) -> bool:
    """新增/更新一条客户向量。返回是否成功（降级时返回 False）。

    单条写入**不重新 fit**：TF-IDF 的词表来自建索引时的那次全量 fit（已持久化），
    单条重 fit 会把词表换成这一条的语料，让库里其他向量全部失效。没有可用状态
    时直接跳过（返回 False）—— 宁可不索引，不可污染。
    """
    from trade.embeddings import get_backend

    backend = backend or get_backend(scope="vec_search")
    try:
        if backend.needs_fit and not load_backend_state(conn, backend):
            logger.debug("客户向量单条写入跳过：索引尚未建立（先跑一次全量重建）")
            return False
        # allow_rebuild=False：单条写入**永远不许**因为维度不符而 DROP 整表
        if not ensure_vec_schema(
            conn, backend.dim or 0, model=getattr(backend, "model_name", "tfidf"), allow_rebuild=False
        ):
            return False
        vec = backend.embed([text])[0]
        if not any(vec):
            return False  # 零向量无意义，跳过
        conn.execute("DELETE FROM vec_customers WHERE customer_id = ?", (customer_id,))
        conn.execute(
            "INSERT INTO vec_customers (customer_id, company_id, embedding) VALUES (?, ?, ?)",
            (customer_id, company_id, _serialize(vec)),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.warning("客户向量写入失败: %s", e)
        return False


def rebuild_customer_index(
    conn: sqlite3.Connection,
    rows: list[tuple[int, int, str]],
    *,
    backend=None,
) -> int:
    """批量重建向量索引。rows: [(customer_id, company_id, text)]。

    对 TfidfBackend 会先在传入的文本上 fit，保证 IDF 有意义，并把 fit 结果
    持久化（见 save_backend_state）供以后跨进程的查询/单条写入复用。
    返回成功写入条数。

    **必须传全量客户**（用 rebuild_all_customers）：TF-IDF 的词表由 fit 语料决定，
    传子集会换词表 → 维度变化 → 整表重建 → **其他客户/公司的向量被清空**。
    多租户项目里这是数据丢失级别的错误，不要传过滤子集。
    """
    from trade.embeddings import get_backend

    backend = backend or get_backend(scope="vec_search")
    if not rows:
        return 0
    try:
        texts = [t for _, _, t in rows]
        if backend.needs_fit:
            backend.fit(texts)
        dim = backend.dim
        if dim <= 0 or not ensure_vec_schema(conn, dim, model=getattr(backend, "model_name", "tfidf")):
            return 0
        save_backend_state(conn, backend)
        vecs = backend.embed(texts)
        n = 0
        for (cid, comp_id, _), vec in zip(rows, vecs, strict=True):
            if not any(vec):
                continue
            conn.execute(
                "DELETE FROM vec_customers WHERE customer_id = ?", (cid,)
            )
            conn.execute(
                "INSERT INTO vec_customers (customer_id, company_id, embedding) VALUES (?, ?, ?)",
                (cid, comp_id, _serialize(vec)),
            )
            n += 1
        conn.commit()
        logger.info("客户向量索引重建完成: %d 条", n)
        return n
    except Exception as e:
        logger.warning("批量建索引失败: %s", e)
        return 0


# ── 客户行 → 索引文本（供增删改钩子与全量重建共用）────────────────────────

def customer_index_text(cust: dict) -> str:
    """把一条客户记录拍平成索引文本（名称/联系人/备注/国家/邮箱 等）。"""
    parts = [
        cust.get("name") or "",
        cust.get("contact") or "",
        cust.get("note") or "",
        cust.get("title") or "",
        cust.get("country") or "",
        cust.get("email") or "",
        cust.get("company_website") or "",
        cust.get("main_category") or "",
        cust.get("buyer_type") or "",
        cust.get("source") or "",
    ]
    return " ".join(p for p in parts if p).strip()


def index_customer(conn: sqlite3.Connection, cust: dict) -> bool:
    """按客户 dict 写向量索引（增/改后调用）。best-effort，绝不抛错。

    首次写入时若索引尚未建立（从未全量重建），借这次机会做一次**自举全量重建**
    —— 否则单条 upsert 没有可用词表（TF-IDF 需要按语料 fit），
    索引会一直建不起来，语义检索永远降级。
    """
    try:
        cid, company_id = cust.get("id"), cust.get("company_id")
        if not cid or not company_id:
            return False
        if not vec_available():
            return False  # 没装 sqlite-vec：整套语义能力静默降级
        from trade.embeddings import get_backend

        backend = get_backend(scope="vec_search")
        if getattr(backend, "needs_fit", False) and not load_backend_state(conn, backend):
            return rebuild_all_customers(conn) > 0  # 自举：按全量语料 fit 一次
        return upsert_customer_vector(conn, int(cid), int(company_id), customer_index_text(cust))
    except Exception as e:
        logger.debug("客户索引写入跳过: %s", e)
        return False


def rebuild_all_customers(conn: sqlite3.Connection) -> int:
    """全量重建（首次自举 / 维护用）：一次 SELECT 取全部客户后建索引。

    成本：N 条客户生成 N 份向量（纯 Python 的 n-gram + IDF 计算）。
    正常规模（几十到几百条）是毫秒级；上千条会明显变慢 ——
    所以只在首次自举或显式维护时调用（见 index_customer 的自举分支）。
    """
    try:
        cur = conn.execute("SELECT * FROM customers")
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    except Exception as e:
        logger.warning("读取客户列表失败: %s", e)
        return 0
    texts = []
    for row in rows:
        cust = _row_dict(cols, row)
        # 缺 id/company_id 的行无法建索引（脏数据），跳过
        if cust.get("id") and cust.get("company_id"):
            texts.append((int(cust["id"]), int(cust["company_id"]), customer_index_text(cust)))
    return rebuild_customer_index(conn, texts)


def _row_dict(cols: list[str], row) -> dict:
    """数据库行 → dict，并把 extra1/extra2/extra3 里的 JSON 字段展开到顶层。"""
    cust = dict(zip(cols, row, strict=True))
    for key in ("extra1", "extra2", "extra3"):
        raw = cust.get(key)
        if raw:
            try:
                merged = json.loads(raw)
                if isinstance(merged, dict):
                    cust.update({k: v for k, v in merged.items() if v not in (None, "")})
            except Exception:
                pass  # 脏 JSON 不该让整次重建失败
    return cust


def delete_customer_vector(conn: sqlite3.Connection, customer_id: int) -> None:
    try:
        if _load_vec(conn):
            conn.execute("DELETE FROM vec_customers WHERE customer_id = ?", (customer_id,))
            conn.commit()
    except Exception:
        pass


# ── 检索 ──────────────────────────────────────────────────────────────────

def _default_top_k() -> int:
    import os

    try:
        return int(os.environ.get("TRADE_VEC_TOP_K", "10"))
    except (ValueError, TypeError):
        return 10


def _default_min_score() -> float:
    """默认最低分。**不要凭感觉调** —— 这个尺度有个恒定基线。

    score = 1/(1+distance)，而 vec0 默认 L2 距离作用在 L2 归一化向量上：
    两个**完全无关**（正交）向量的距离恒为 √2，即 score 恒为 1/(1+√2) ≈ **0.4142**。
    出厂默认 0.35 低于这个基线 → 任何查询都会把**全部客户**当命中返回，
    关键词降级分支永远不会触发（实测：5 个客户、无关查询也全数返回）。

    实测（5 条真实客户文本）：相关命中 0.44~0.48（对应 cos 0.18~0.41），
    无关命中恒为 0.4142（cos 0）。默认取 0.43（≈ cos 0.08）：滤掉正交噪声，
    又保住弱重叠的相关命中。**上线前应随评测集重校准**（TRADE_VEC_MIN_SCORE 可覆盖）。
    """
    import os

    try:
        return float(os.environ.get("TRADE_VEC_MIN_SCORE", "0.43"))
    except (ValueError, TypeError):
        return 0.43


def semantic_search_customers(
    conn: sqlite3.Connection,
    query: str,
    company_id: int,
    *,
    top_k: int | None = None,
    min_score: float | None = None,
    backend=None,
) -> list[dict]:
    """向量检索客户。返回 [{"customer_id","score"}]，score=1/(1+distance)。

    vec 不可用 → 返回 []（调用方 search_customers 会自动走关键词降级）。
    """
    from trade.embeddings import get_backend

    query = (query or "").strip()
    if not query:
        return []
    top_k = top_k or _default_top_k()
    min_score = min_score if min_score is not None else _default_min_score()
    backend = backend or get_backend(scope="vec_search")
    try:
        if not _load_vec(conn):
            return []
        row = conn.execute("SELECT dim FROM vec_meta WHERE id = 1").fetchone()
        if row is None:
            return []  # 尚未建索引
        if backend.needs_fit and not load_backend_state(conn, backend):
            return []  # TF-IDF 无可用词表（未建索引），不能查
        qvec = backend.embed([query])[0]
        if not any(qvec):
            return []
        # vec0 查询：MATCH + k；company 过滤在 Python 侧做（兼容性最好，
        # 避免不同 sqlite-vec 版本对 metadata 过滤支持不一致）
        cur = conn.execute(
            "SELECT customer_id, company_id, distance FROM vec_customers "
            "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (_serialize(qvec), top_k * 3),
        )
        out = []
        for cid, comp, dist in cur.fetchall():
            if comp != company_id:  # 多租户隔离：只返回本公司的
                continue
            d = float(dist)
            score = 1.0 / (1.0 + d)
            if score >= min_score:
                # 同时给出 cosine，便于按可解释的尺度调阈值：
                # L2 距离 d 与 cosine 的关系：d² = 2 - 2·cos
                cos = max(-1.0, min(1.0, 1.0 - (d * d) / 2.0))
                out.append({"customer_id": cid, "score": round(score, 4), "cosine": round(cos, 4)})
            if len(out) >= top_k:
                break
        return out
    except Exception as e:
        logger.warning("向量检索失败: %s", e)
        return []


def keyword_search_customers(
    conn: sqlite3.Connection, query: str, company_id: int, *, top_k: int | None = None
) -> list[dict]:
    """降级路径：LIKE 关键词检索（复用现有 customers 表，无需向量表）。"""
    query = (query or "").strip()
    if not query:
        return []
    top_k = top_k or _default_top_k()
    like = f"%{query}%"
    try:
        cur = conn.execute(
            """SELECT id FROM customers
               WHERE company_id = ?
                 AND (name LIKE ? OR contact LIKE ? OR note LIKE ?
                      OR json_extract(extra1, '$.country') LIKE ?
                      OR json_extract(extra2, '$.email') LIKE ?)
               ORDER BY id DESC LIMIT ?""",
            (company_id, like, like, like, like, like, top_k),
        )
        return [{"customer_id": r[0], "score": 1.0} for r in cur.fetchall()]
    except Exception as e:
        logger.warning("关键词检索失败: %s", e)
        return []


def search_customers(
    conn: sqlite3.Connection,
    query: str,
    company_id: int,
    *,
    top_k: int | None = None,
    min_score: float | None = None,
    backend=None,
) -> list[dict]:
    """统一入口：优先向量检索，不可用/无结果时自动降级关键词检索。"""
    hits = semantic_search_customers(
        conn, query, company_id, top_k=top_k, min_score=min_score, backend=backend
    )
    if hits:
        return hits
    return keyword_search_customers(conn, query, company_id, top_k=top_k)
