"""
Trade AI Assistant — 共享辅助函数。

集中了 Provider 校验和 Agent 构造参数逻辑，避免 /chat 和 /chat/stream
两个端点各自重复约 90 行代码。
"""

import json
import os
import re
from pathlib import Path

from trade import chat_memory as _cm
from trade import company as _company
from trade import customer as _cust
from trade import library as _lib
from trade import prompts as _prompts
from trade import skill_router as _skill_router
from trade.order import search_orders

# ── 一致性温度分流 ────────────────────────────────────────────────────────────
# 创作类 skill 豁免清单：输出需要多样性（A/B 变体、内容创意），保持 provider 默认温度。
# 其余 skill（分析/提取/清单类）与无匹配的通用对话 → 低温，减少数据漂移。
_CREATIVE_SKILLS = frozenset({
    "b2b-cold-outreach", "b2b-email-imitation", "b2b-social-media",
    "b2b-seo-aeo", "b2b-short-video", "b2b-kol-imitation",
    "b2b-linkedin-marketing", "b2b-product-description",
    "b2b-guarantee-proposal", "b2b-sales-playbook",
    "b2b-inquiry-training", "b2b-sales-pipeline",
})

# 支持自定义 temperature 的 provider 白名单（常规 chat-completions 类，传了确实生效）。
# 白名单外有两种情况，都不能传 temperature：
#   1. 会报错型：Kimi/Moonshot（服务端管理温度）与 Anthropic 新模型（拒绝非默认采样参数）
#      在 Hermes 内有 OMIT_TEMPERATURE / fixed_temperature 契约，且主对话路径没有
#      "参数不支持时自动降级重试"（error_classifier 判为不可重试的确定性错误），强传即报错。
#   2. 静默忽略型：deepseek-flash 的 thinking mode 默认开启，而 thinking mode 下
#      temperature / presence_penalty / frequency_penalty 被静默忽略（不报错、也不生效）。
#      传 0.1 只会制造"有低温保障"的假象，实际没被消费，故 deepseek 不在白名单内。
_TEMP_SAFE_PROVIDERS = frozenset({
    "openai", "zai", "zhipu", "qwen", "dashscope",
    "ollama", "lmstudio", "minimax", "openrouter", "nous", "groq",
})

# 分析/提取类任务的默认温度（可用 TRADE_CONSISTENCY_TEMPERATURE 环境变量覆盖）
_DEFAULT_CONSISTENCY_TEMPERATURE = "0.1"


def _consistency_request_overrides(skill_name: str | None, provider: str) -> dict | None:
    """按 skill 类型与 provider 决定是否注入一致性 temperature。

    - 创作类 skill（_CREATIVE_SKILLS）→ None（用 provider 默认温度，保多样性）
    - 白名单外 provider → None（会报错型如 Kimi/Anthropic；静默忽略型如 deepseek）
    - 其余（分析/提取/清单类 + 无匹配通用对话）→ {"temperature": 低温}

    注意：temperature 只是"锦上添花"的一致性辅助，不是主防线。分析/提取类任务的
    确定性主防线在 prompt 层（STOP RULE / 清单协议 / 事实核查）与代码校验层
    （三道防线），它们不依赖 provider 的采样参数契约——尤其是 deepseek 这类
    thinking mode 下 temperature 被静默忽略的 provider。
    """
    if skill_name in _CREATIVE_SKILLS:
        return None
    if (provider or "").strip().lower() not in _TEMP_SAFE_PROVIDERS:
        return None
    try:
        temp = float(os.environ.get(
            "TRADE_CONSISTENCY_TEMPERATURE", _DEFAULT_CONSISTENCY_TEMPERATURE))
    except ValueError:
        temp = 0.1  # 环境变量值非法时回退默认
    return {"temperature": temp}


def _json_loads(raw):
    """安全解析 JSON 字符串，失败时返回空字典。

    对于非字符串非字典的意外输入类型（如 int/list），返回 {} 并记录 warning，
    帮助调用方发现类型错误而非静默吞掉。
    """
    if not raw or not isinstance(raw, str):
        if isinstance(raw, dict):
            return raw
        # 非空非字符串非字典 → 可能上游传错了类型
        if raw is not None and raw != "":
            import logging
            logging.getLogger(__name__).warning(
                "_json_loads received unexpected type %s, returning {}", type(raw).__name__
            )
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


# ── Config.model compat ───────────────────────────────────────────────────────

def _parse_model_config_str(raw: str) -> tuple[str, str, str]:
    """解析 v0.14 平铺模型配置字符串，返回 (provider, model, base_url)。

    支持两种格式：
      - "provider:model"     (冒号分隔，语义明确)
      - "provider/model/..." (斜杠分隔，例如 openrouter/anthropic/claude-sonnet-4)

    base_url 在该平铺格式中始终返回空字符串。
    """
    if not raw or not raw.strip():
        # 传入空字符串或 None 时返回全部空值
        return "", "", ""
    raw = raw.strip()
    # colon 优先，语义更精确
    if ":" in raw:
        provider, _, model = raw.partition(":")
        return provider.strip(), model.strip(), ""
    elif "/" in raw:
        parts = raw.split("/", 1)
        provider = parts[0].strip()
        model = parts[1].strip() if len(parts) > 1 else ""
        return provider, model, ""
    else:
        # 既无冒号也无斜杠，整个字符串作为 model 名
        return "", raw, ""


def check_provider() -> str | None:
    """检查 LLM provider 和 API key 是否已配置。

    如果缺少配置则返回错误信息字符串，配置正常则返回 None。
    必须在 ``import run_agent``（该操作会触发 .env 加载）之后调用。
    """
    from hermes_cli.config import load_config

    cfg = load_config()
    model_cfg = cfg.get("model", "")
    # 兼容 v0.13 (dict) 和 v0.14+ (str) 两种 config.model 格式
    if isinstance(model_cfg, dict):
        # v0.13 字典格式：检查 default model 和 provider 是否都已配置
        if not model_cfg.get("default") and not model_cfg.get("provider"):
            return "未配置 AI 模型。请先运行 trade setup 选择模型。"
    elif isinstance(model_cfg, str):
        # v0.14+ 字符串格式：检查是否为空字符串
        if not model_cfg.strip():
            return "未配置 AI 模型。请先运行 trade setup 选择模型。"

    has_key = any(
        os.getenv(k)
        for k in (
            "OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY",
            "MINIMAX_API_KEY", "MINIMAX_CN_API_KEY", "DEEPSEEK_API_KEY",
            "GLM_API_KEY", "KIMI_API_KEY", "DASHSCOPE_API_KEY",
            "LLM_API_KEY", "HF_TOKEN",
        )
    )
    if not has_key:
        # 所有已知的 API Key 环境变量均未设置，无法调用 LLM
        return "未检测到 API Key。请在 ~/.hermes/.env 中设置，或运行 trade setup 重新配置。"

    # 检查 openai SDK 是否可导入 — Hermes 用此 SDK 作为所有 provider 的通用 HTTP 客户端
    try:
        import openai  # noqa: F401
    except ImportError:
        return (
            "OpenAI Python SDK 未安装。所有 LLM Provider 的 HTTP 通信都依赖此包。\n"
            "请运行: pip install openai==2.24.0"
        )

    # 检查 anthropic SDK 是否可导入 — 仅在使用原生 Anthropic provider 时需要
    # 不作为硬错误阻断，因为大多数用户走 OpenAI/OpenRouter/DeepSeek 等 openai 兼容协议
    try:
        import anthropic  # noqa: F401
    except ImportError:
        import logging
        logging.getLogger(__name__).warning(
            "Anthropic SDK not installed. Native Anthropic provider will not work. "
            "Install with: pip install anthropic==0.87.0"
        )

    return None


def get_agent_kwargs() -> dict:
    """从配置文件构建 ``AIAgent.__init__`` 所需的参数。

    解析 provider、model、base_url 和 api_key —— 包括环境变量对 base_url
    的覆盖，以及通过 auth 注册表按 provider 查找对应 API key。

    Returns:
        包含 provider、model、base_url、api_key 的字典，所有值均为字符串（可能为空）。
    """
    from hermes_cli.config import load_config

    cfg = load_config()
    model_cfg = cfg.get("model", {})

    # 兼容 v0.13 (dict: {"provider":"...", "default":"...", "base_url":"..."})
    #     和 v0.14+ (str: "provider:model" 或 "provider/model")
    if isinstance(model_cfg, dict):
        provider = model_cfg.get("provider", "")
        model = model_cfg.get("default", "")
        base_url = model_cfg.get("base_url", "")
    elif isinstance(model_cfg, str) and model_cfg.strip():
        provider, model, base_url = _parse_model_config_str(model_cfg)
    else:
        provider = model = base_url = ""

    # ── base_url: from PROVIDER_REGISTRY, env var overrides config.yaml ──
    env_url = ""
    if provider:
        # 从 PROVIDER_REGISTRY 获取该 provider 的 base_url 环境变量名，覆盖 config.yaml 中的值
        try:
            from hermes_cli.auth import PROVIDER_REGISTRY
            pconfig = PROVIDER_REGISTRY.get(provider)
            if pconfig:
                brv = getattr(pconfig, 'base_url_env_var', '')
                if brv:
                    env_url = os.getenv(brv, "").strip()
        except Exception:
            # PROVIDER_REGISTRY 可能不存在或导入失败，忽略异常
            pass
    if env_url:
        # 环境变量中找到了 base_url，用它覆盖 config.yaml 中的值
        base_url = env_url

    # ── api_key: per-provider via PROVIDER_REGISTRY，严格不跨 provider 兜底 ──
    api_key = ""
    if provider:
        # 从 PROVIDER_REGISTRY 查找该 provider 对应的 API Key 环境变量
        try:
            from hermes_cli.auth import PROVIDER_REGISTRY
            pconfig = PROVIDER_REGISTRY.get(provider)
            if pconfig and pconfig.auth_type == "api_key":
                for env_name in pconfig.api_key_env_vars:
                    api_key = os.getenv(env_name, "").strip()
                    if api_key:
                        # 找到第一个不为空的 key 即停止
                        break
        except Exception:
            # PROVIDER_REGISTRY 可能不存在或导入失败，忽略异常
            pass
        # provider 已知时绝不回退到 LLM_API_KEY，避免错配
    else:
        # 仅在 provider 完全未配置时才用通用 LLM_API_KEY 兜底
        api_key = os.getenv("LLM_API_KEY", "").strip()

    return {"provider": provider, "model": model,
            "base_url": base_url, "api_key": api_key}


# ── Agent factory ─────────────────────────────────────────────────────────────

def create_agent(
    tool_start_callback=None,
    tool_complete_callback=None,
    *,
    ephemeral_system_prompt: str | None = None,
    skill_name: str | None = None,
):
    """创建 Hermes AIAgent 实例的统一入口。

    Trade 中所有对 Hermes Agent 的调用都通过此函数，不直接 import AIAgent。
    当 Hermes 升级改变模块路径或构造签名时，只需修改此一处。

    Args:
        tool_start_callback: Hermes 工具开始回调（用于 SSE 流式进度）
        tool_complete_callback: Hermes 工具完成回调
        ephemeral_system_prompt: 临时 system prompt（OSINT 等 skill 的指令，
                                 通过 Hermes 原生 system 层传入，不混入 user message）
        skill_name: 本次匹配到的 skill 名 —— 用于一致性温度分流（分析/提取类低温
                    保数据稳定，创作类保持默认温度）。见 _consistency_request_overrides。

    Returns:
        AIAgent 实例，已配置好 quiet_mode / max_iterations / provider 等参数。

    Raises:
        ImportError: hermes-agent 未安装
        RuntimeError: provider 未配置或 API key 缺失
    """
    from run_agent import AIAgent

    kwargs = get_agent_kwargs()
    err = check_provider()
    if err:
        raise RuntimeError(err)

    # 一致性温度：按 skill 类型 + provider 白名单决定是否注入（None = 不传，用 provider 默认）
    request_overrides = _consistency_request_overrides(skill_name, kwargs["provider"])

    # toolsets 可通过 TRADE_ENABLED_TOOLSETS 环境变量覆盖（逗号分隔）
    _toolsets = os.environ.get("TRADE_ENABLED_TOOLSETS", "").strip()
    if _toolsets:
        # 环境变量存在时，解析逗号分隔的 toolset 列表
        enabled_toolsets = [t.strip() for t in _toolsets.split(",") if t.strip()]
    else:
        # 未设置环境变量时使用默认 toolset 组合
        enabled_toolsets = ["web", "search", "file", "terminal", "code_execution",
                            "browser", "skills", "memory", "cronjob", "todo"]

    return AIAgent(
        quiet_mode=True,
        max_iterations=int(os.environ.get("TRADE_MAX_ITERATIONS", "90")),
        provider=kwargs["provider"] or None,
        base_url=kwargs["base_url"] or None,
        model=kwargs["model"] or None,
        api_key=kwargs["api_key"] or None,
        tool_start_callback=tool_start_callback,
        tool_complete_callback=tool_complete_callback,
        enabled_toolsets=enabled_toolsets,
        ephemeral_system_prompt=ephemeral_system_prompt,
        request_overrides=request_overrides,
    )


# ── Token estimation helpers ──────────────────────────────────────────────────

def _estimate_tokens(text: str) -> int:
    """估算文本的 token 数（用于上下文窗口预算）。

    CJK/日韩/全角：约 1.5 字/token → 系数 0.67
    其他（英文/数字）：约 4 字符/token → 系数 0.25
    优先使用 tiktoken 以获得准确估算（缺包时回退到启发式）。
    """
    if not text:
        return 0

    # 优先用 tiktoken
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        pass

    # fallback 启发式：扩展 CJK 范围（含标点、全角、日韩）
    cjk_ranges = (
        (0x3000, 0x303F),   # CJK 标点
        (0x3040, 0x30FF),   # 日语假名
        (0x3400, 0x4DBF),   # CJK 扩展 A
        (0x4E00, 0x9FFF),   # CJK 基本块
        (0xAC00, 0xD7AF),   # 韩语音节
        (0xFF00, 0xFFEF),   # 全角符号
    )

    def _is_cjk(code: int) -> bool:
        for lo, hi in cjk_ranges:
            if lo <= code <= hi:
                return True
        return False

    cjk_chars = sum(1 for c in text if _is_cjk(ord(c)))
    other_chars = len(text) - cjk_chars
    return int(cjk_chars / 1.5 + other_chars / 4.0)


def _get_history_block(company_id: int | None, total_prompt_chars: int) -> tuple[str, int]:
    """根据 prompt 总大小构造历史对话注入块。

    上下文越长，注入的历史条数越少，防止超出 token 预算。
    返回 (history_block, history_token_count)。
    当 company_id 为 None 或 0 时 history_block 为空字符串。
    """
    if not company_id:  # None, 0, 空 — company_id 从 1 开始自增，0 不可能有效
        return "", 0

    # Token thresholds (hard-coded, not user-visible)
    if total_prompt_chars < 80_000:      # ~< 20k tokens — 上下文充足，注入最近 20 条
        limit = 20
        hint = None
    elif total_prompt_chars < 200_000:   # ~< 50k tokens — 中等上下文，注入 10 条并提示用户
        limit = 10
        hint = "如需更早的对话历史，请使用 chat_memory_list 工具。"
    else:                                # >= 50k tokens — 上下文紧张，仅注入 5 条
        limit = 5
        hint = "当前上下文较长，历史对话已精简。如需查询更早内容，请使用 chat_memory_list 工具。"

    rows = _cm.get_recent(company_id, limit=limit)
    if not rows:
        # 数据库中无历史记录
        return "", 0

    lines = ["## 最近对话历史"]
    for row in rows:
        ts = row.get("created_at", "")[:16]  # YYYY-MM-DD HH:MM — 截断到分钟精度
        lines.append(f"[{ts}] user: {row['query'][:200]}")
        if row.get("response"):
            # 仅在有 response 时注入，避免空内容占用 token
            lines.append(f"[{ts}] assistant: {row['response'][:200]}")
    block = "\n".join(lines) + "\n"

    if hint:
        # 在历史块末尾附上引导提示，告知用户如何查询更早的内容
        block += f"\n{hint}\n"

    return block, _estimate_tokens(block)

# OSINT 类 skill 名称列表（使用精简 system prompt）
_OSINT_SKILL_NAMES = frozenset({"b2b-osint", "b2b-email-intel"})


# ── 用户问题中显式文件/目录路径提取 ──────────────────────────────────────

# 匹配常见文件路径模式：绝对路径、带扩展名的文件名、中文文件名
_EXPLICIT_PATH_RE = re.compile(
    r'(?:(?:文件|目录|路径|path|file|dir)\s*[：:]\s*)?'  # 可选前缀 "文件："
    r'(/(?:[^\s,，。；;、]+/)*[^\s,，。；;、]+'            # Unix 绝对路径
    r'|\b[A-Za-z]:\\(?:[^\s,，。；;、]+\\)*[^\s,，。；;、]+'  # Windows 绝对路径
    r'|[^\s,，。；;、]+\.(?:xlsx?|csv|pdf|docx?|pptx?|txt|md|json|xml|html?|png|jpg|jpeg)'
    r')',
    re.IGNORECASE,
)


def _extract_explicit_paths(query: str) -> list[str]:
    """从用户问题中提取明确提到的文件路径或目录路径。

    提取后验证路径是否真实存在，只返回磁盘上确实存在的路径。
    去重并排序：目录优先、绝对路径优先。
    """
    candidates = _EXPLICIT_PATH_RE.findall(query)
    if not candidates:
        return []

    verified: list[str] = []
    seen = set()
    for raw in candidates:
        raw = raw.strip().rstrip(',，。；;、')
        if not raw or raw in seen:
            continue
        # 去除前缀标记
        cleaned = re.sub(r'^(?:文件|目录|路径|path|file|dir)\s*[：:]\s*', '', raw, flags=re.IGNORECASE)
        try:
            p = Path(cleaned).expanduser().resolve()
            if p.exists() and str(p) not in seen:
                verified.append(str(p))
                seen.add(str(p))
        except (OSError, ValueError):
            # 路径无效（含非法字符等），跳过
            pass

    # 排序：目录在前，文件在后；各自按字母序
    verified.sort(key=lambda x: (not Path(x).is_dir(), x.lower()))
    return verified


def build_query(
    company_id: int,
    library_id: int | None,
    query: str,
    customer_id: int | None = None,
    *,
    last_skill_name: str | None = None,
    language: str = "zh",
) -> tuple[str, str | None]:
    """组装完整的用户 prompt：公司身份 + 文档库上下文 + Skill 注入。

    返回 (user_message, skill_system_hint)，其中 skill_system_hint 是给 OSINT 等
    场景的辅助系统指令（非 OSINT skill 时为 None），由 chat.py 通过
    agent.run_conversation(system_message=...) 传入，与 user message 分层处理。

    company_id 决定注入哪家公司身份到 system prompt。
    library_id 可选地添加文档库上下文。
    customer_id 可选地添加客户上下文（客户名称、关联文档库）。
    last_skill_name 上次使用的 skill 名称，连续同 skill 时跳过重复注入。
    """

    # 0. Skill auto-detection — 评分排序后取最高置信度 skill
    matched_skills = _skill_router.match_skills(query)
    matched_name = matched_skills[0]["skill_name"] if matched_skills else None
    matched_skill = _skill_router.get_skill_by_name(matched_name) if matched_name else None

    # 连续同 skill 时跳过完整注入，大幅节约 token（injection_prompt 通常 1000-2000 tokens）
    same_skill_repeat = bool(last_skill_name and matched_name == last_skill_name)

    if same_skill_repeat and matched_name and matched_name not in _OSINT_SKILL_NAMES:
        # 非 OSINT 且连续同 skill → augmented_query 仅含简短提示，不重复注入完整规则
        augmented_query = (
            f"[SKILL AUGMENTATION]\n"
            f"继续使用 {matched_name} 技能，规则同上一次。\n\n"
            f"## 用户原始问题\n{query}\n"
            f"[SKILL AUGMENTATION]"
        )
    else:
        augmented_query = _skill_router.augment_query(
            query, company_id=company_id
        )

    # 1. Company identity — 根据场景选择不同深度的 system prompt
    company_slug = _company.slug_from_id(company_id) if company_id else None
    db_identity = _company.get_agent_identity(company_id) if company_id else None

    # 检查是否有历史对话记录，用于判断是否首轮
    has_history = bool(company_id and _cm.get_recent(company_id, limit=1))

    if matched_name in _OSINT_SKILL_NAMES:
        # OSINT 背调场景使用精简 system prompt，去掉销售相关的指令以减少 token 浪费
        from trade.prompt import TRADE_SYSTEM_PROMPT_OSINT
        code_fallback = TRADE_SYSTEM_PROMPT_OSINT
    elif has_history:
        # 非首轮对话 — 首轮已发送过完整版，后续注入精简版节约 token
        from trade.prompt import TRADE_SYSTEM_PROMPT_MINIMAL
        code_fallback = TRADE_SYSTEM_PROMPT_MINIMAL
    else:
        # 首轮非 OSINT 对话 — 使用完整版 system prompt（含文档生成指南、Cognee 等）
        code_fallback = None
    system_prompt = _prompts.resolve_system_prompt(
        company_slug=company_slug,
        db_identity=db_identity,
        code_fallback=code_fallback,
    )

    # 1.4 语言策略：用户选择英文时替换语言策略块
    if language == "en":
        from trade.prompt import LANGUAGE_POLICY_BLOCK, LANGUAGE_POLICY_BLOCK_EN
        system_prompt = system_prompt.replace(LANGUAGE_POLICY_BLOCK, LANGUAGE_POLICY_BLOCK_EN)

    # 1.5 注入当前公司信息 — Agent 需要明确知道自己为哪家公司工作
    if company_id:
        co = _company.get(company_id)
        if co:
            # 用户输入字段清理：去除换行、控制字符、prompt 注入标记，限制长度
            def _sanitize_identity(s: str, max_len: int = 200) -> str:
                import re as _re
                s = s.replace('\n', ' ').replace('\r', '')
                # 去除 ASCII 控制字符（0x00-0x1F, 0x7F），保留空格
                s = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', s)
                # 防止 prompt 注入 — 转义 [ 字符，避免被解析为 markdown 指令
                s = s.replace('[', '〔').replace(']', '〕')
                return s[:max_len]
            name = _sanitize_identity(co['name'])
            slug = _sanitize_identity(co.get('slug', ''))
            system_prompt += (
                f"\n\n## 当前工作公司\n"
                f"- 公司名称：「{name}」\n"
                f"- 公司 ID：{co['id']}\n"
                f"- Slug：「{slug}」\n\n"
                "**所有数据操作（记忆读取、客户查询、文档搜索）必须限定在上述公司范围内。**"
            )

    # 1.6 品牌安全护栏 — 所有对外内容生成都需遵守
    if company_slug:
        brand_safety = _prompts.get_brand_safety(company_slug)
        if brand_safety:
            system_prompt += f"\n\n{brand_safety}"

    # 2. Customer context — AI 客户简报（身份 + 联系方式 + 历史 + 订单 + 数据完整度）
    customer_context = ""
    if customer_id:
        briefing = _cust.build_briefing(customer_id, company_id=company_id)
        if briefing:
            customer_context = briefing
        # 追加关联文档库信息
        linked_libs = _cust.get_libraries(customer_id, company_id=company_id)
        if linked_libs:
            lib_names = "、".join(l["name"] for l in linked_libs)
            customer_context += f"\n关联文档库：{lib_names}。"

    # 3. Order context — 按 3 层优先级搜索订单并注入
    order_context = ""
    if company_id:
        order_text = search_orders(company_id, query)
        if order_text:
            order_context = order_text

    # 4. Library document context — 所有栏目均告知可用文档库，Agent 自行判断是否读取
    #    读取时必须遵守完整扫描规则：逐个文件、不跳过、不截断
    doc_context = ""

    # 4.0 用户问题中明确提到了文件路径或目录 → 强制读取
    explicit_paths = _extract_explicit_paths(query)
    if explicit_paths:
        path_lines = "\n".join(
            f"  - {p}" + (" (目录)" if Path(p).is_dir() else " (文件)")
            for p in explicit_paths
        )
        doc_context += (
            f"\n## 用户指定文件（强制读取 — 最高优先级）\n"
            f"用户在问题中明确提到了以下文件/目录，**你必须先全部读取完毕才能回答**：\n"
            f"{path_lines}\n\n"
            f"**强制规则：**\n"
            f"1. 对每个目录使用 list_files 列出所有文件，对每个文件使用 read_file 完整读取\n"
            f"2. 每个文件必须读到末尾，截断则用 offset 继续，多 sheet Excel 读全部 sheet\n"
            f"3. **禁止跳过任何一个**——用户明确指定了就说明需要\n"
            f"4. 全部读取完成后，综合所有文件内容回答用户问题\n\n"
        )

    if library_id:
        # 用户明确选择了文档库 → 强制完整读取
        lib = _lib.get(library_id, company_id=company_id)
        if lib:
            doc_context = (
                f"\n## 文档库上下文（强制扫描）\n"
                f"用户正在文档库「{lib['name']}」({lib['root_path']}) 中提问。\n"
                f"**你必须先扫描此目录中的所有文件：**\n"
                f"1. 使用 list_files 列出 {lib['root_path']} 下的所有文件\n"
                f"2. 逐个使用 read_file 完整读取每个文件，不允许跳过任何文件\n"
                f"3. 每个文件必须读到末尾，如果被截断则用 offset 继续读取\n"
                f"4. 全部读完后才能开始回答用户问题\n"
            )
    elif company_id:
        # 收集工作目录 + 所有文档库，告知 Agent 可用目录，Agent 自行判断是否需要读取
        dirs_to_scan: list[str] = []
        tc = _company.get_trade_company(company_id)
        if tc:
            data_dir = tc.get("data_dir", "")
            if data_dir and Path(data_dir).is_dir():
                dirs_to_scan.append(data_dir)
            if tc.get("extra1"):
                extra = _json_loads(tc["extra1"])
                wd = extra.get("work_dir", "")
                if wd and Path(wd).is_dir() and wd not in dirs_to_scan:
                    dirs_to_scan.append(wd)
        company_libs = _lib.list_by_company(company_id)
        for l in company_libs:
            rp = l.get("root_path", "")
            if rp and Path(rp).is_dir() and rp not in dirs_to_scan:
                dirs_to_scan.append(rp)

        if dirs_to_scan:
            dir_lines = "\n".join(f"  - {d}" for d in dirs_to_scan)
            doc_context = (
                f"\n## 可用文档目录\n"
                f"当前公司有以下数据目录，你**可以根据用户问题自行判断**是否需要读取：\n"
                f"{dir_lines}\n\n"
                f"**如果决定读取文件，必须遵守以下规则：**\n"
                f"1. 使用 list_files 列出目录中的所有文件，**不跳过任何文件**\n"
                f"2. 逐个使用 read_file **完整读取每个文件**，文件名不等于内容\n"
                f"3. 每个文件必须读到末尾，如果被截断则用 offset 继续读取\n"
                f"4. 多 sheet 的 Excel 必须读每个 sheet，多页 PDF 必须读每一页\n"
                f"5. **禁止跳过文件或中途截断**——一个被跳过的文件可能就是答案所在\n"
            )

    # 6. Skill system hint — OSINT 类 skill 的注入指令作为 system 层独立传入
    skill_system_hint: str | None = None
    if matched_name in _OSINT_SKILL_NAMES and matched_skill:
        if same_skill_repeat:
            # 同一 skill 连续使用 → 简短提示，不重复发送完整规则
            skill_system_hint = (
                f"## 当前技能：{matched_name}\n"
                f"继续使用 {matched_name} 技能，规则同上一次。"
            )
        else:
            # 首轮或切换 skill → 完整注入
            augment = _skill_router.load_injection_prompt(matched_name)
            if augment is None:
                augment = matched_skill.get("augment_prompt", "")
            if augment:
                skill_system_hint = (
                    f"## 当前技能：{matched_name}\n\n{augment}"
                )
        # OSINT skill 的 system hint 已单独抽出，augmented_query 中无需
        # 再拼 [SKILL AUGMENTATION] 块。用原始 query 替代。
        augmented_query = query

    # 7. History block — OSINT 类 skill 不注入历史，每次背调目标是独立的
    #    非 OSINT 场景注入最近对话历史，帮助 AI 保持上下文连续
    history_block = ""
    if matched_name not in _OSINT_SKILL_NAMES:
        # 估算已有 prompt 长度，动态决定注入多少条历史
        pre_history_chars = (
            len(system_prompt) + len(customer_context) + len(doc_context) +
            len(augmented_query) + 200
        )
        history_block, _ = _get_history_block(company_id, pre_history_chars)

    # 8. Assemble final user message：system → 客户 → 订单 → 文档库 → 历史 → 查询
    final_prompt = system_prompt + customer_context + order_context + doc_context
    if history_block:
        # 有历史时才注入，避免多余空行
        final_prompt = f"{final_prompt}\n\n{history_block}"

    return f"{final_prompt}\n\n{augmented_query}", skill_system_hint
