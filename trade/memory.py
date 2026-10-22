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
from typing import Any

logger = logging.getLogger(__name__)

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


# ── 客户端（懒初始化，复用单例）────────────────────────────────────────────

_client: Any = None


def _get_client():
    """返回缓存的 Hindsight 客户端，如果不可用则返回 None。"""
    global _client
    # 如果 Hindsight 整体不可用，直接返回 None
    if not is_available():
        return None
    # 如果客户端已经初始化过，直接返回缓存的实例
    if _client is not None:
        return _client

    try:
        from hermes_constants import get_hermes_home
        from hindsight_client import Hindsight

        api_key = os.environ.get("HINDSIGHT_API_KEY", "")
        api_url = os.environ.get("HINDSIGHT_API_URL", "https://api.hindsight.vectorize.io")
        timeout = int(os.environ.get("HINDSIGHT_TIMEOUT", "120"))

        # 尝试从 Hermes profile 作用域的配置文件中读取覆盖值
        config_path = get_hermes_home() / "hindsight" / "config.json"
        # 如果配置文件存在，用其中的值覆盖环境变量（环境变量优先）
        if config_path.exists():
            try:
                cfg = json.loads(config_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                # 配置文件损坏或不可读时降级为空配置，避免阻断客户端初始化
                logger.warning("Hindsight config 解析失败: %s", exc)
                cfg = {}
            api_key = api_key or cfg.get("apiKey", "") or cfg.get("api_key", "")
            api_url = cfg.get("api_url", api_url)
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


def retain_to_hermes_memory(
    query: str,
    response: str,
    *,
    company_name: str = "",
    library_name: str = "",
    customer_name: str = "",
    limit: int = 200,
) -> bool:
    """将对话摘要追加到 ~/.hermes/memories/MEMORY.md。

    这样可以让 Hermes Agent 的原生记忆系统学习到 B2B 贸易对话，
    而无需任何 API 密钥。
    """
    import datetime as _dt
    from pathlib import Path as _Path

    _hermes_root = _Path(os.environ.get("HERMES_HOME", ""))
    if not _hermes_root.is_absolute() or not str(_hermes_root).strip():
        # 跨平台解析 Hermes 根目录
        if os.name == "nt":
            _local = os.environ.get("LOCALAPPDATA", str(_Path.home() / "AppData" / "Local"))
            _hermes_root = _Path(_local) / "hermes"
        else:
            _hermes_root = _Path.home() / ".hermes"
    MEMORY_FILE = _hermes_root / "memories" / "MEMORY.md"
    LOCK_FILE = _hermes_root / "memories" / "MEMORY.md.lock"

    # 如果查询内容为空或只有空白字符，不执行写入操作
    if not query or not query.strip():
        return False

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

        _hermes_env = os.environ.get("HERMES_HOME", "")
        if _hermes_env:
            _hermes_root = _Path(_hermes_env)
        elif os.name == "nt":
            _local = os.environ.get("LOCALAPPDATA", str(_Path.home() / "AppData" / "Local"))
            _hermes_root = _Path(_local) / "hermes"
        else:
            _hermes_root = _Path.home() / ".hermes"
        lock_dir = _hermes_root / "memories"
        lock_dir.mkdir(parents=True, exist_ok=True)
        # 防御符号链接攻击：如果锁文件已是 symlink，拒绝跟随
        if LOCK_FILE.is_symlink():
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
                existing = MEMORY_FILE.read_text(encoding="utf-8")
            SECTION = "## Foreign Trade Assistant — B2B Trade Memory\n"
            # 如果文件中还没有 B2B 记忆段落，则在文件开头创建
            if SECTION not in existing:
                content_str = SECTION + entry + "\n\n" + existing if existing else SECTION + entry
            else:
                # 如果已有段落，将新条目插入到段落标题之后（最新在最前）
                idx_s = existing.find(SECTION) + len(SECTION)
                content_str = existing[:idx_s] + entry + "\n\n" + existing[idx_s:]
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


def retain_fact_to_hermes_memory(
    fact: str,
    *,
    company_id: int | None = None,
    company_name: str = "",
) -> bool:
    """把一条**事实**（模型主动要记住的东西）写入 Hermes MEMORY.md。

    与 `retain_to_hermes_memory`（存对话摘要）的区别：
      - 摘要存的是「Q/A 对话片段」；事实存的是「值得长期记住的结论」；
      - 事实**必须带公司标签**，由本函数从 company_id 查出公司名后**代码写入** ——
        模型不参与标签，标签也就不会漏（漏标签 = 跨公司串户）。

    为什么不直接用 Hermes 的 `memory` 工具：它写进同一个 MEMORY.md，但**不带任何
    公司标签**，而 Hermes 把整个文件原样注入 system prompt（零过滤）——
    模型写的无标签条目会在别家公司的对话里浮现。这里用 Trade 侧的写入器，
    company_id 由调用方（插件）从 thread-local 取，模型无法传错。

    Args:
        fact: 事实正文（自包含的完整句子，含具体数值）。
        company_id: 公司 ID；给了就自动查名并打标签（推荐）。
        company_name: 公司名（company_id 查不到时的兜底）。

    Returns:
        True=写入成功；False=失败或参数不合法（调用方应如实告知模型）。
    """
    import datetime as _dt

    if not fact or not fact.strip():
        return False

    # 公司名优先从 company_id 查（权威），查不到才用传入的名字
    name = company_name
    if company_id:
        try:
            from trade import company as _company

            co = _company.get(company_id)
            if co:
                name = co.get("name", "") or name
        except Exception:
            pass
    if not name:
        # 没有公司名就无法打标签 → 宁可不写（无标签条目必然串户）
        return False

    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = (
        f"[{now}] [公司: {name}]\n"
        f"  FACT: {fact.strip()}\n"
        "\n"
    )

    try:
        from pathlib import Path as _Path

        _hermes_env = os.environ.get("HERMES_HOME", "")
        if _hermes_env:
            _hermes_root = _Path(_hermes_env)
        elif os.name == "nt":
            _local = os.environ.get("LOCALAPPDATA", str(_Path.home() / "AppData" / "Local"))
            _hermes_root = _Path(_local) / "hermes"
        else:
            _hermes_root = _Path.home() / ".hermes"
        memory_file = _hermes_root / "memories" / "MEMORY.md"
        lock_file = _hermes_root / "memories" / "MEMORY.md.lock"
        lock_dir = _hermes_root / "memories"
        lock_dir.mkdir(parents=True, exist_ok=True)
        if lock_file.is_symlink():
            return False

        import time as _time

        if os.name != "nt":
            import fcntl as _fcntl_module

        lock_fd = open(str(lock_file), "w")
        for _attempt in range(5):
            try:
                if os.name == "nt":
                    import msvcrt as _msvcrt

                    _msvcrt.locking(lock_fd.fileno(), _msvcrt.LK_NBLCK, 1)
                else:
                    _fcntl_module.flock(lock_fd.fileno(), _fcntl_module.LOCK_EX | _fcntl_module.LOCK_NB)
                break
            except OSError:
                _time.sleep(0.1)
        else:
            lock_fd.close()
            return False

        try:
            existing = memory_file.read_text(encoding="utf-8") if memory_file.is_file() else ""
            if "## Foreign Trade Assistant" in existing:
                # 插到 Trade 段的开头（新事实比旧摘要更该被看到）
                marker = "## Foreign Trade Assistant"
                idx = existing.index(marker)
                rest = existing[idx:]
                # 跳过标题行与其后第一个空行，插在标题块之后
                lines = rest.split("\n")
                insert_at = 1
                while insert_at < len(lines) and not lines[insert_at].strip():
                    insert_at += 1
                head = "\n".join(lines[:insert_at])
                tail = "\n".join(lines[insert_at:])
                content = f"{head}\n{entry}\n{tail}"
            else:
                content = existing.rstrip("\n") + "\n\n" + entry
            memory_file.write_text(content, encoding="utf-8")
        finally:
            if os.name == "nt":
                import msvcrt as _msvcrt

                lock_fd.seek(0)
                _msvcrt.locking(lock_fd.fileno(), _msvcrt.LK_UNLCK, 1)
            else:
                _fcntl_module.flock(lock_fd.fileno(), _fcntl_module.LOCK_UN)
            lock_fd.close()
            try:
                lock_file.unlink(missing_ok=True)
            except OSError:
                pass
        return True
    except Exception:
        return False
