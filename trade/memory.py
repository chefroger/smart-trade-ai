"""
Trade AI Assistant — 记忆桥接层（Hindsight 集成）。

提供 trade/chat_memory 与 Hindsight 长期记忆后端之间的轻量桥接。
独立于 Hermes Agent 运行时工作（不需要 MemoryManager）。

当 hindsight-client 已安装并配置时，对话轮次将被自动保留到知识图谱中，
以实现跨会话召回。否则，本模块优雅降级，所有操作变为空操作。
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 公司专属 MEMORY.md 段落标题与滚动容量上限（防止长期运行无限膨胀 Prompt）
_MEMORY_SECTION_HEADER = "## Foreign Trade Assistant — B2B Trade Memory\n"
_MAX_COMPANY_MEMORY_BLOCKS = 30
_MEMORY_ENTRY_TS_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\](?P<ctx>.*)$")
_MEMORY_CUSTOMER_TAG_RE = re.compile(r"(?:^|\[|,\s*)客户:\s*([^,\]]+)")

# ── Hindsight 可用性检测 ─────────────────────────────────────────────────────

_hindsight_available: bool | None = None  # 三态：None=尚未检查


def is_available() -> bool:
    """检查 Hindsight 是否已安装并配置。"""
    global _hindsight_available
    # 如果已经检查过，直接返回缓存结果，避免重复导入
    if _hindsight_available is not None:
        return _hindsight_available

    try:
        import importlib
        importlib.import_module("hindsight_client")
        # 检查环境变量中是否有 API 密钥
        has_key = bool(
            os.environ.get("HINDSIGHT_API_KEY", "")
            or os.environ.get("HINDSIGHT_LLM_API_KEY", "")
        )
        # 如果环境变量中没有 API 密钥，则尝试从配置文件中读取
        if not has_key:
            from pathlib import Path
            _hermes_env = os.environ.get("HERMES_HOME", "")
            if _hermes_env:
                _hermes_root = Path(_hermes_env)
            elif os.name == "nt":
                _local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
                _hermes_root = Path(_local) / "hermes"
            else:
                _hermes_root = Path.home() / ".hermes"
            config_paths = [
                _hermes_root / "hindsight" / "config.json",
                Path.home() / ".hindsight" / "config.json",
            ]
            # 遍历所有可能的配置文件路径
            for p in config_paths:
                # 如果配置文件存在，尝试读取其中的 API 密钥
                if p.exists():
                    try:
                        # 显式 utf-8：配置文件可能含非 ASCII（Windows 默认 cp1252 会读失败）
                        cfg = json.loads(p.read_text(encoding="utf-8"))
                        # 支持多种配置字段名，兼容不同版本
                        if cfg.get("apiKey") or cfg.get("api_key") or cfg.get("mode") == "local_embedded":
                            has_key = True
                            break
                    except Exception:
                        pass
        _hindsight_available = has_key
    except ImportError:
        # 未安装 hindsight_client 包，标记为不可用
        _hindsight_available = False

    return _hindsight_available


def reset_cache() -> None:
    """清空 Hindsight 可用性与客户端缓存。仅供测试或重新配置时使用。"""
    global _hindsight_available, _client
    _hindsight_available = None
    _client = None


# 用户开关的存储键；默认开启（"1"）
_ENABLED_SETTING_KEY = "hindsight_enabled"


def is_enabled() -> bool:
    """长期记忆是否被用户开启（默认开）。

    读不到设置时按开启处理 —— 设置表缺失不能把记忆功能关掉。
    """
    try:
        from trade.database import get_setting

        return get_setting(_ENABLED_SETTING_KEY, "1") != "0"
    except Exception:
        return True


def set_enabled(enabled: bool) -> None:
    """持久化用户开关；关闭后立即丢弃已缓存的客户端。"""
    from trade.database import set_setting

    set_setting(_ENABLED_SETTING_KEY, "1" if enabled else "0")
    # 关掉时立刻释放缓存的客户端，避免开关"看起来关了但还在用旧实例"
    global _client
    if not enabled:
        _client = None


def _load_hindsight_config() -> dict:
    """读 Hermes 作用域的 Hindsight 配置；缺失或损坏时返回空 dict。

    客户端初始化与连通性探测共用这一份解析，避免两边指向不同地址
    （2026-11-20 审计 C6：探测走默认地址、实际连自定义地址会误判不可达）。
    """
    try:
        from hermes_constants import get_hermes_home

        config_path = get_hermes_home() / "hindsight" / "config.json"
        # 配置文件不存在：没有覆盖值，交给调用方用环境变量/默认值
        if not config_path.exists():
            return {}
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        # 非 dict 的畸形配置按空处理
        return cfg if isinstance(cfg, dict) else {}
    except Exception as exc:
        # 损坏或不可读时降级为空配置，不阻断任何功能
        logger.warning("Hindsight config 解析失败: %s", exc)
        return {}


def _resolve_api_url(cfg: dict | None = None) -> str:
    """解析 Hindsight 服务地址：配置文件优先，其次环境变量，最后默认。"""
    cfg = _load_hindsight_config() if cfg is None else cfg
    default = "https://api.hindsight.vectorize.io"
    # 配置文件里的自定义地址优先（与客户端初始化保持一致）
    return str(cfg.get("api_url") or os.environ.get("HINDSIGHT_API_URL", default))


def health_check(timeout: float = 2.0) -> bool:
    """真实探测 Hindsight 服务是否可达（2026-11-20 审计 C6）。

    is_available() 只能证明「装了包、配了 key」；配置写错或服务端挂了，
    要等到 retain 时才失败。这里做一次 TCP 连接探测，带硬超时，不抛异常。
    """
    # 包都没装/没配 key 就不用探了
    if not is_available():
        return False
    try:
        import socket
        from urllib.parse import urlparse

        # 与客户端初始化共用同一份地址解析，避免探测打到另一个地址
        api_url = _resolve_api_url()
        parsed = urlparse(api_url)
        host = parsed.hostname
        # 非法 URL：视为不可达，不抛
        if not host:
            return False
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        # 连接成功即视为可达（不发送任何请求体）
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


# ── 客户端（懒初始化，复用单例）────────────────────────────────────────────

_client: Any = None


def _get_client():
    """返回缓存的 Hindsight 客户端，如果不可用则返回 None。"""
    global _client
    # 用户手动关闭时立即停用（优先于缓存，否则关掉后仍在用旧实例）
    if not is_enabled():
        return None
    # 如果 Hindsight 整体不可用，直接返回 None
    if not is_available():
        return None
    # 如果客户端已经初始化过，直接返回缓存的实例
    if _client is not None:
        return _client

    try:
        from hindsight_client import Hindsight

        api_key = os.environ.get("HINDSIGHT_API_KEY", "")
        timeout = int(os.environ.get("HINDSIGHT_TIMEOUT", "120"))

        # 配置文件的密钥/地址/超时与 health_check 共用同一份解析，
        # 避免「探测用默认地址、实际连自定义地址」的不一致
        cfg = _load_hindsight_config()
        api_key = api_key or cfg.get("apiKey", "") or cfg.get("api_key", "")
        api_url = _resolve_api_url(cfg)
        timeout = int(cfg.get("timeout", timeout))

        # 如果最终仍没有 API 密钥，则不创建客户端
        if not api_key:
            logger.debug("Hindsight: 未配置 API 密钥，不创建客户端")
            return None

        _client = Hindsight(
            base_url=api_url,
            api_key=api_key,
            timeout=float(timeout),
        )
        logger.info("Hindsight 客户端已连接: %s", api_url)
    except Exception as exc:
        logger.warning("Hindsight 客户端初始化失败: %s", exc)
        _client = None

    return _client


# ── 公开 API ─────────────────────────────────────────────────────────────────

def retain(
    content: str,
    context: str = "",
    *,
    bank_id: str = "trade",
    document_id: str | None = None,
    tags: list[str] | None = None,
) -> bool:
    """将信息存储到 Hindsight 长期记忆。

    成功返回 True，如果 Hindsight 不可用则返回 False。
    """
    client = _get_client()
    # 如果 Hindsight 客户端不可用，静默返回 False 表示操作未执行
    if client is None:
        return False

    try:
        metadata = {"source": "trade-ai-assistant"}
        kwargs: dict[str, Any] = {
            "bank_id": bank_id,
            "content": content,
            "metadata": metadata,
        }
        # 仅当 context 非空时才添加，避免发送不必要的空字段
        if context:
            kwargs["context"] = context
        # 仅当 document_id 提供时才添加，用于关联特定文档
        if document_id:
            kwargs["document_id"] = document_id
        # 仅当 tags 提供时才添加，便于后续按标签检索
        if tags:
            kwargs["tags"] = tags

        client.retain(**kwargs)
        logger.debug("Hindsight 保留: bank=%s, content_len=%d, context=%s",
                      bank_id, len(content), context or "(无)")
        return True
    except Exception as exc:
        logger.warning("Hindsight 保留失败: %s", exc)
        return False


def recall(
    query: str,
    *,
    bank_id: str = "trade",
    budget: str = "mid",
    max_tokens: int = 4096,
) -> str | None:
    """搜索 Hindsight 长期记忆。

    返回格式化后的记忆文本，如果不可用则返回 None。
    """
    client = _get_client()
    # 如果 Hindsight 客户端不可用，返回 None 表示无法搜索
    if client is None:
        return None

    try:
        resp = client.recall(
            bank_id=bank_id,
            query=query,
            budget=budget,
            max_tokens=max_tokens,
        )
        # 防御：resp 可能为 None 或缺少 results 属性
        results = getattr(resp, "results", None) if resp is not None else None
        if not results:
            return None
        lines = [f"- {r.text}" for r in results if getattr(r, "text", "")]
        return "\n".join(lines) if lines else None
    except Exception as exc:
        logger.warning("Hindsight 召回失败: %s", exc)
        return None


def reflect(
    query: str,
    *,
    bank_id: str = "trade",
    budget: str = "mid",
) -> str | None:
    """从 Hindsight 长期记忆中综合生成答案。

    返回综合后的文本，如果不可用则返回 None。
    """
    client = _get_client()
    # 如果 Hindsight 客户端不可用，返回 None
    if client is None:
        return None

    try:
        resp = client.reflect(bank_id=bank_id, query=query, budget=budget)
        return resp.text or None
    except Exception as exc:
        logger.warning("Hindsight 综合失败: %s", exc)
        return None


def _bank_id(company_id: int | None) -> str:
    """构造按公司隔离的 bank_id。"""
    if company_id:
        return f"trade-company-{company_id}"
    return "trade-default"


def retain_conversation(
    query: str,
    response: str,
    *,
    library_name: str = "",
    customer_name: str = "",
    company_id: int | None = None,
    bank_id: str = "trade-default",
) -> bool:
    """将完整的对话轮次推送到 Hindsight 记忆。

    格式化问答对并用资料库/客户上下文进行标注。
    """
    content_parts = [f"Q: {query}", f"A: {response}"]
    context = "B2B trade conversation"
    if company_id:
        context += f" — company: {company_id}"
    if library_name:
        context += f" — library: {library_name}"
    if customer_name:
        context += f" — customer: {customer_name}"
    content = "\n".join(content_parts)
    bid = _bank_id(company_id) if company_id else bank_id
    return retain(content, context=context, bank_id=bid)


def _is_safe_slug(slug: str) -> bool:
    """校验 company_slug 是否可安全拼入本地目录名，防止路径穿越。"""
    s = (slug or "").strip()
    # 空串、当前/上级目录或包含路径分隔符均视为不安全
    if not s or s in {".", ".."} or "/" in s or "\\" in s:
        return False
    return True


def _resolve_trade_home() -> Path:
    """解析 Trade 数据根目录（优先 TRADE_HOME 环境变量）。"""
    trade_home = os.environ.get("TRADE_HOME", "").strip()
    if not trade_home:
        # Windows 与 POSIX 默认路径保持与 database._get_db_path 一致
        if os.name == "nt":
            local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
            trade_home = str(Path(local) / "trade")
        else:
            trade_home = str(Path.home() / ".trade")
    return Path(trade_home)


def _resolve_hermes_memory_paths(company_slug: str = "") -> tuple[Path, Path] | None:
    """解析 Hermes 原生记忆文件与锁文件路径（优先按公司物理隔离）。

    - 传入合法 `company_slug` 时，落盘到 `TRADE_HOME/{slug}/memories/MEMORY.md`，
      彻底杜绝多公司共享 `~/.hermes/memories/MEMORY.md` 导致的上下文串味。
    - 未传 `company_slug` 时，仅当数据库确认活跃公司数 <= 1 才回退全局 `~/.hermes/memories/MEMORY.md`；
      多公司场景或数据库查询异常时一律返回 None（fail-closed，修复 O-新33）。
    """
    # 有合法公司标识：写入该公司专属目录
    if _is_safe_slug(company_slug):
        slug_dir = _resolve_trade_home() / company_slug.strip()
        # 拒绝跟随公司目录或 memories 目录层级的符号链接
        if slug_dir.is_symlink():
            return None
        mem_dir = slug_dir / "memories"
        if mem_dir.is_symlink():
            return None
        return mem_dir / "MEMORY.md", mem_dir / "MEMORY.md.lock"

    # 未传入合法公司 slug 时，若入参非空说明是不安全路径（如 ../），直接拒绝
    if company_slug and company_slug.strip():
        return None

    # 未传入公司 slug 时检查当前实例是否为多公司环境
    try:
        from trade.database import get_connection

        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM companies WHERE is_active = 1"
            ).fetchone()
            active_count = int(row["c"] or 0) if row else 0
        finally:
            conn.close()
    except Exception:
        # O-新33：数据库故障窗口下无法排除多公司并存，按 fail-closed 拒绝写全局共享文件
        return None

    # 多公司并存但缺少归属公司标识：拒绝写入全局共享记忆文件
    if active_count > 1:
        return None

    hermes_env = os.environ.get("HERMES_HOME", "").strip()
    if hermes_env and Path(hermes_env).is_absolute():
        # 显式配置了绝对路径 HERMES_HOME 时优先采用
        hermes_root = Path(hermes_env)
    elif os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        hermes_root = Path(local) / "hermes"
    else:
        hermes_root = Path.home() / ".hermes"
    mem_dir = hermes_root / "memories"
    return mem_dir / "MEMORY.md", mem_dir / "MEMORY.md.lock"


def _split_section_entries(body: str) -> list[str]:
    """按空行切分 B2B 记忆段落内的条目块。"""
    blocks: list[str] = []
    cur: list[str] = []
    for line in (body or "").splitlines():
        if not line.strip():
            if cur:
                blocks.append("\n".join(cur).strip())
                cur = []
        else:
            cur.append(line)
    if cur:
        blocks.append("\n".join(cur).strip())
    return blocks


def retain_to_hermes_memory(
    query: str,
    response: str,
    *,
    company_name: str = "",
    company_slug: str = "",
    library_name: str = "",
    customer_name: str = "",
    limit: int = 200,
) -> bool:
    """将对话摘要追加到本地 MEMORY.md（支持按 company_slug 物理隔离）。

    这样可以让本地记忆系统学习到 B2B 贸易对话，同时避免跨公司上下文泄漏。
    """
    import datetime as _dt

    # 如果查询内容为空或只有空白字符，不执行写入操作
    if not query or not query.strip():
        return False

    resolved_paths = _resolve_hermes_memory_paths(company_slug)
    # 多公司环境下若无法确定归属路径，安全跳过写入
    if resolved_paths is None:
        return False
    MEMORY_FILE, LOCK_FILE = resolved_paths

    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    q_preview = query.strip()[:limit]
    r_preview = (response or "").strip()[:limit]

    context_parts = []
    # 如果提供了公司名称，添加到上下文片段中
    if company_name:
        context_parts.append("公司: " + company_name)
    # 如果提供了资料库名称，添加到上下文片段中
    if library_name:
        context_parts.append("资料库: " + library_name)
    # 如果提供了客户名称，添加到上下文片段中
    if customer_name:
        context_parts.append("客户: " + customer_name)

    # 根据是否有上下文片段，构造上下文字符串
    if context_parts:
        context_str = " [" + ", ".join(context_parts) + "]"
    else:
        context_str = ""

    entry_lines = [
        "[" + now + "]" + context_str,
        "  Q: " + q_preview,
        "  A: " + r_preview,
        "",
    ]
    entry = "\n".join(entry_lines)

    try:
        # 跨平台文件锁：fcntl.flock (Unix) / msvcrt.locking (Windows)
        # 替代之前的 TOCTOU 竞态（LOCK_FILE.exists() + write_text）
        import time as _time

        # fcntl 是 Unix 专有模块，必须在 os.name 分支内延迟导入
        if os.name != "nt":
            import fcntl as _fcntl_module

        lock_dir = MEMORY_FILE.parent
        lock_dir.mkdir(parents=True, exist_ok=True)
        # 防御符号链接攻击：如果锁文件或目标文件已是 symlink，拒绝跟随
        if LOCK_FILE.is_symlink() or MEMORY_FILE.is_symlink():
            return False
        lock_fd = open(str(LOCK_FILE), "w")
        # 最多重试 5 次获取文件锁，避免死锁
        for _attempt in range(5):
            try:
                # Windows 平台使用 msvcrt.locking
                if os.name == "nt":
                    import msvcrt as _msvcrt
                    _msvcrt.locking(lock_fd.fileno(), _msvcrt.LK_NBLCK, 1)
                else:
                    _fcntl_module.flock(lock_fd.fileno(), _fcntl_module.LOCK_EX | _fcntl_module.LOCK_NB)
                break
            except (BlockingIOError, OSError):
                _time.sleep(0.05)
        else:
            # 所有重试均失败，无法获取锁
            lock_fd.close()
            return False

        try:
            existing = ""
            # 如果记忆文件已存在，读取其现有内容
            if MEMORY_FILE.exists():
                existing = MEMORY_FILE.read_text(encoding="utf-8-sig")
            SECTION = _MEMORY_SECTION_HEADER
            # 如果文件中还没有 B2B 记忆段落，则在文件开头创建
            if SECTION not in existing:
                content_str = SECTION + entry + "\n\n" + existing if existing else SECTION + entry
            else:
                # 已有段落时：把新条目置顶并对历史条目按上限滚动裁剪，防止文件无限膨胀
                idx_s = existing.find(SECTION) + len(SECTION)
                prefix = existing[:idx_s]
                rest = existing[idx_s:]
                # 若后面还有其它二级标题段落，保留后续段落不误裁
                next_sec_idx = rest.find("\n## ")
                if next_sec_idx >= 0:
                    b2b_body = rest[:next_sec_idx]
                    tail_sections = rest[next_sec_idx:]
                else:
                    b2b_body = rest
                    tail_sections = ""
                old_blocks = _split_section_entries(b2b_body)
                kept_blocks = [entry.strip(), *old_blocks][:_MAX_COMPANY_MEMORY_BLOCKS]
                content_str = prefix + "\n\n".join(kept_blocks) + "\n" + tail_sections
            MEMORY_FILE.write_text(content_str, encoding="utf-8")
        finally:
            # 释放文件锁，确保即使写入失败也会解锁
            if os.name == "nt":
                import msvcrt as _msvcrt
                lock_fd.seek(0)
                _msvcrt.locking(lock_fd.fileno(), _msvcrt.LK_UNLCK, 1)
            else:
                _fcntl_module.flock(lock_fd.fileno(), _fcntl_module.LOCK_UN)
            lock_fd.close()
            # 尝试删除锁文件，如果失败则静默忽略
            try:
                LOCK_FILE.unlink(missing_ok=True)
            except OSError:
                pass
        return True
    except Exception:
        return False


def read_company_hermes_memory(
    company_slug: str,
    *,
    customer_name: str = "",
    exclude_queries: set[str] | None = None,
    max_chars: int = 2400,
) -> str:
    """读取当前公司物理隔离的 MEMORY.md，返回可注入 Prompt 的记忆摘要块。

    - 仅读取 `TRADE_HOME/{slug}/memories/MEMORY.md`（不读全局共享文件）；
    - 用户关闭长期记忆开关时返回空串；
    - 传入 `customer_name` 时过滤掉明确归属其它客户的条目，防跨客户泄漏报价；
    - 传入 `exclude_queries` 时跳过已在「最近对话历史」中注入的同轮问答，省 Token。
    """
    # 开关关闭或缺少合法公司 slug 时不注入任何记忆
    if not is_enabled() or not _is_safe_slug(company_slug):
        return ""

    resolved = _resolve_hermes_memory_paths(company_slug)
    if resolved is None:
        return ""
    memory_file, _ = resolved
    # 拒绝符号链接或不存在的文件
    if memory_file.is_symlink() or not memory_file.is_file():
        return ""

    try:
        raw = memory_file.read_text(encoding="utf-8-sig")
    except Exception:
        return ""
    if not raw.strip():
        return ""

    # 剥离段落头，提取全部条目块
    body = raw
    if _MEMORY_SECTION_HEADER.strip() in body:
        idx = body.find(_MEMORY_SECTION_HEADER.strip()) + len(_MEMORY_SECTION_HEADER.strip())
        body = body[idx:]
    blocks = _split_section_entries(body)
    if not blocks:
        return ""

    norm_customer = customer_name.strip().casefold() if customer_name else ""
    seen_queries = exclude_queries or set()
    selected: list[str] = []
    used_chars = 0

    for block in blocks:
        lines = block.splitlines()
        if not lines:
            continue
        first_line = lines[0].strip()
        m_ts = _MEMORY_ENTRY_TS_RE.match(first_line)

        # 指定了当前客户时，剔除带有其它客户标签的条目（无客户标签的公司级条目保留）
        if norm_customer and m_ts:
            m_cust = _MEMORY_CUSTOMER_TAG_RE.search(m_ts.group("ctx") or "")
            if m_cust and m_cust.group(1).strip().casefold() != norm_customer:
                continue

        # 跳过已由 SQLite 最近历史块注入过的同一条提问，避免同轮重复消耗 Token
        if seen_queries:
            q_line = next(
                (ln.strip()[3:].strip() for ln in lines[1:] if ln.strip().startswith("Q: ")),
                "",
            )
            if q_line and q_line[:120] in seen_queries:
                continue

        # 预算裁剪：至少保证不超出 max_chars
        addition = len(block) + 2
        if used_chars + addition > max_chars:
            break
        selected.append(block)
        used_chars += addition

    if not selected:
        return ""
    return "## 公司对话记忆（MEMORY.md）\n" + "\n\n".join(selected) + "\n"
