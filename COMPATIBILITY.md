# Hermes ↔ Foreign Trade Assistant 兼容性记录

> 每次 Hermes 升级后更新此文件。升级前先跑一次完整兼容性检查（见 `项目需求文档.md` 第二章）。

## 兼容性矩阵

> **当前声明范围**：`0.13.0 <= version < 0.22.0`（定义在 `trade/bootstrap.py` 的 `_MIN_HERMES_VERSION` / `_MAX_HERMES_VERSION`）

| Hermes 版本 | 兼容状态 | 测试日期 | 测试人 | 备注 |
|------------|---------|---------|--------|------|
| 0.12.0 | ⚠️ 不再支持 | 2026-05-11 | — | 低于最低兼容版本 0.13.0，启动时拒绝 |
| 0.13.0 | ✅ 兼容 | 2026-05-11 | AI | API 检查通过：AIAgent/MemoryProvider/load_config 均无 breaking change |
| 0.14.0 | ✅ 兼容 | 2026-05-18 | AI | config.model 从嵌套 dict 变为扁平字符串；name_to_models 移除。已适配。 |
| 0.15.0 | ✅ 兼容 | 2026-05-29 | AI | run_agent.py 拆分到 agent/ 但 AIAgent re-export 正常；config.model / _PROVIDER_MODELS 未变。 |
| 0.16.0 | ✅ 兼容 | 2026-06-11 | AI | 扫描了 origin/main 领先 387 commits：AIAgent 新增可选参数（tool_progress_mode/read_terminal_callback）向后兼容；config.model 格式不变；_PROVIDER_MODELS 结构不变；hermes_constants 无变更。无需 Trade 修改。 |
| 0.17.0 | ✅ 兼容 | 2026-06-24 | AI | v2026.6.19 版本。AIAgent 重构为 `agent.agent_init.init_agent` 转发器；load_config/PROVIDER_REGISTRY/_PROVIDER_MODELS/get_hermes_home/load_hermes_dotenv 均无 breaking change。 |
| 0.18.0 | ✅ 兼容 | 2026-07-06 | AI | v2026.7.1 版本。扫描 release notes 无 breaking change 涉及 Trade 耦合点（AIAgent/load_config/_PROVIDER_MODELS/get_hermes_home/gateway）。packaging/psutil/pyyaml/pydantic 版本未变。仅需更新 `_MAX_HERMES_VERSION` 到 0.19.0。 |
| 0.19.0 | ✅ 兼容 | 2026-07-22 | AI | v2026.7.20 "Quicksilver" 版本。扫描 release notes 无 breaking change 涉及 Trade 耦合点（AIAgent/load_config/_PROVIDER_MODELS/get_hermes_home/gateway）。新增 Fireworks AI / DeepInfra provider、GPT-5.6 等模型、订阅管理、SecretSource 接口。仅需更新 `_MAX_HERMES_VERSION` 到 0.20.0。 |
| 0.20.0 | ✅ 兼容 | 2026-08-03 | AI | v2026.8.3 "The Herald" 版本。扫描 release notes 无 breaking change 涉及 Trade 耦合点。注意：brew+pip/PyPI wheel 渠道退役（安装方式变化）、Node 26 要求、默认 tool-calling iteration limit 90→500（Trade 显式设置 max_iterations 不受影响）。仅需更新 `_MAX_HERMES_VERSION` 到 0.21.0。 |
| 0.20.3 | ✅ 兼容 | 2026-08-18 | AI | v2026.8.16.2 版本（0.20.1~0.20.3 三个 patch rollup）。`compare/v2026.8.3...v2026.8.16.2` 确认 Trade 7 个耦合点入口（run_agent.py 的 AIAgent / hermes_cli.config/auth/models/env_loader / hermes_constants）零变更；agent/ 内部实现有更新但 Trade 不直接 import。无 breaking change，仍在 `<0.21.0` 范围内，`_MAX_HERMES_VERSION` 无需改动。仅更新 pyproject.toml git pin。 |
| 0.20.5 | ✅ 兼容 | 2026-08-24 | AI | v2026.8.19 版本（0.20.4~0.20.5 两个 patch rollup，共 963 commits）。`compare/v2026.8.16.2...v2026.8.19` 确认 Trade 7 个耦合点入口零变更；新增 keyless 免费 tier、cron 持久记忆等均不涉及 Trade 耦合点。无 breaking change，仍在 `<0.21.0` 范围内，`_MAX_HERMES_VERSION` 无需改动。仅更新 pyproject.toml git pin。 |
| 0.20.6 | ✅ 兼容 | 2026-08-31 | AI | v2026.8.27 版本（0.20.5→0.20.6 单个 patch rollup，共 1376 commits）。`compare/v2026.8.19...v2026.8.27` 确认 Trade 7 个耦合点入口零变更；web_search TTL 缓存、updater 经 control socket 暂停 gateway、新模型（GLM-5.3-Flash/MiniMax M3 free）等均不涉及 Trade 耦合点。无 breaking change，仍在 `<0.21.0` 范围内，`_MAX_HERMES_VERSION` 无需改动。仅更新 pyproject.toml git pin。 |
| 0.21.0 | ✅ 兼容 | 2026-09-03 | AI | v2026.8.31 "The Pantheon" 版本（自 0.20.0 共 ~5800 commits / ~2475 PRs，含 Bot Mode、gateway 消息平台、CLI 大改）。`compare/v2026.8.27...v2026.8.31` 确认 Trade 7 个耦合点入口零变更（run_agent.py / hermes_cli.config/auth/models/env_loader / hermes_constants 全未动）；agent/ 内部 54 文件变更不涉及 Trade；skills/memory 写保护属 Hermes 工具层，不影响 Trade 外部文件复制式 skills 安装。需更新 `_MAX_HERMES_VERSION` 到 0.22.0 + pyproject.toml git pin。 |
| 0.21.1 | ✅ 兼容 | 2026-09-08 | AI | v2026.9.7 版本（0.21.0→0.21.1 patch rollup，共 5995 commits / ~632 PRs：代码模块化、性能优化、provider/模型更新、cron 与 delegation 修复）。`compare/v2026.8.31...v2026.9.7` 确认 Trade 7 个耦合点入口零变更。无 breaking change，仍在 `<0.22.0` 范围内，`_MAX_HERMES_VERSION` 无需改动。仅更新 pyproject.toml git pin。 |
| 0.21.2 | ✅ 兼容 | 2026-09-14 | AI | v2026.9.11 "state.db Patch Release" 版本（0.21.1→0.21.2，共 986 commits / 312 PRs）。核心为 state.db 可靠性战役（修 0.21.0 引入的 session store 连接处理问题：多写入者锁冲突、损坏误报、坏行崩溃、打开抢锁卡顿），对已跟随 0.21.0 的用户有实际修复价值。`compare/v2026.9.7...v2026.9.11` 确认 Trade 7 个耦合点入口零变更。无 breaking change，仍在 `<0.22.0` 范围内，`_MAX_HERMES_VERSION` 无需改动。仅更新 pyproject.toml git pin。 |
| 0.21.3 | ✅ 兼容 | 2026-09-15 | AI | v2026.9.14 版本（0.21.2→0.21.3，共 1039 commits / ~338 PRs）。重点：长驻进程 state.db writer handle 泄漏修复（直接相关——Trade 会 spawn `hermes gateway run` 长驻子进程）、远程 Desktop/Cloud 登录修复、模型目录更新。`compare/v2026.9.11...v2026.9.14` 确认 Trade 7 个耦合点入口零变更。无 breaking change，仍在 `<0.22.0` 范围内，`_MAX_HERMES_VERSION` 无需改动。仅更新 pyproject.toml git pin。 |
| 0.21.4 | ✅ 兼容 | 2026-09-22 | AI | v2026.9.21 版本（0.21.3→0.21.4，共 5173 commits / 5169 文件 / 1812 PRs；完整说明留待 v0.22.0）。逐文件比对确认 Trade 7 个耦合点签名全部保留：AIAgent 的 11 个已用参数均在（新增 `connection_callback`/`cwd` 为可选）、`ProviderConfig` 字段零变更、`_PROVIDER_MODELS`/`get_hermes_home`/`load_hermes_dotenv(hermes_home=)` 均未破坏；`load_config` 新增 `_normalize_root_model_keys` 会把 model 归一化为 dict，Trade 已同时兼容 dict/str。两个新变化不构成破坏：① `hermes gateway run` 新增 host 级单例锁与 attach（已有 gateway 时新进程 attach 后 exit 0），Trade 的 `_is_gateway_running()` 预检已覆盖；② 新增 `skills.auto_load` 配置默认 `[]`（opt-in），Trade 不设置。**真机验证**（本机 hermes 0.20.4→0.21.4 后）：`/api/status`、`/api/trade/models/providers`（78 providers）、`/api/trade/companies`、`/api/trade/chat`（同步）、`/api/trade/chat/stream`（SSE：thinking→response→done）全部通过。注意上游行为变化：MoA preset 的 `reference_max_tokens`/`max_tokens` 已从规范化中移除（配置里设置将不再生效），改由 `auxiliary.moa_reference` 控制。无 breaking change，仍在 `<0.22.0` 范围内，`_MAX_HERMES_VERSION` 无需改动。仅更新 pyproject.toml git pin。 |
| 0.21.5 | ✅ 兼容 | 2026-09-28 | AI | v2026.9.24 版本（0.21.4→0.21.5，共 1148 commits）。逐符号核对 Trade 7 个耦合点：`run_agent.AIAgent` 仍在（组合式实现，`run_conversation(task_id=)` / `chat()` 由 `TurnFacadeMixin` 提供，签名未变）、`hermes_cli.config.load_config`、`auth.PROVIDER_REGISTRY` / `get_auth_status`、`models._PROVIDER_MODELS` / `provider_model_ids`、`env_loader.load_hermes_dotenv`、`hermes_constants.get_hermes_home` 全部保留；`hermes_cli/provider_catalog.py` 文件未变；`tool_complete_callback` / `ephemeral_system_prompt` 构造参数健在。另核对**上游 main**（比本地基线多 5045 commits）：`hermes_cli.__version__` 已改为惰性读安装印章 `install-stamp.json`，**无印章时返回 "0.0.0"**，并新增 `hermes_cli.version_info.get_version_info()`（安装印章 → live git → unknown，明确选择降级不崩）。这会让 Trade 的启动门禁把 0.0.0 误判成「版本过旧」而拒绝启动 —— 已修：`trade/hermes_compat.hermes_version()` 改为多源识别（version_info → `__version__` → checkout pyproject），占位值与不可解析值一律按「未知」处理、警告后继续启动；`pre_install_check.py` 同原则同步（`0.0.0` 与带 `+git` 后缀的派生版本不再判「过旧」）。无 breaking change，仍在 `<0.22.0` 范围内，`_MAX_HERMES_VERSION` 无需改动。 |

## 上游 main 跟进记录

Hermes 的安装路径跟的是 **main 分支**（`scripts/install.sh` 用 `git clone --depth 1 --branch main`），
所以「上游有没有变化」不能只看 release —— main 在两次 release 之间会持续前进。这里记录**未伴随
新 release 的 main 复核**；伴随 release 的复核记在上方矩阵的对应行里。

复核方法：用 GitHub API（`/commits?path=<文件>&sha=main&per_page=1`）逐个查 Trade 耦合点文件的
最后改动时间，与本地检出基线比较；有改动的再拉当前内容核对具体符号与签名 —— 上游仓库体量大、
本机装不起 main，故用静态符号核对而非运行验证。

| 复核日期 | 上游 main | 本地基线 | 期内有改动的耦合文件 | 结论 |
|---------|-----------|---------|------------------|------|
| 2026-09-30 | `f42f579c` | `d275e422` (2026-09-23) | 7 个耦合点文件被改：run_agent.py / config.py / auth.py / env_loader.py / models.py / hermes_constants.py / version_info.py（另 `auxiliary_client.py`、`vision_tools.py` 亦有改动，非 Trade 耦合点；`agent/image_routing.py` 未动） | ✅ 无破坏。`AIAgent` 仍在且 Trade 实际传的 **14 个构造参数全部保留**；`load_config()` / `PROVIDER_REGISTRY` / `get_auth_status()` / `provider_model_ids()` / `_PROVIDER_MODELS` / `load_hermes_dotenv(hermes_home=)` / `get_hermes_home()` / `provider_catalog()` / `get_version_info()` 签名均未变。无需改动 Trade。 |
| 2026-10-03 | `1cb26bf2` | `d275e422` (2026-09-23) | 4 个：run_agent.py（reasoning blob 容错修复）、config.py + env_loader.py（原子写入临时文件的内部重构）、models.py（StepFun 模型列表合并） | ✅ 无破坏。与上一行同一批符号逐个复核仍未变；`provider_model_ids(provider, *, force_refresh=False)` 与 `_PROVIDER_MODELS` 均保留。无需改动 Trade，`_MAX_HERMES_VERSION` 无需改动。 |

**静态核对的盲区**（两次复核都受此限制，记录以免误以为「查过了就没事」）：
① 无法发现**签名不变但行为变了**的符号 —— 这类只能靠真机跑端点暴露；
② 无法发现上游新增了 Trade **应该启用却没启用**的 toolset —— 默认 toolset 组合缺 `vision`
就是靠真机跑 `create_agent()` 打印工具表才发现的（导致 agent 一直没有 `vision_analyze`，
自写 OCR 兜底）。所以每次跟随 release 时，仍应做一次真机端点验证。

## 升级检查流程

当 Hermes 发布新版本时，按以下步骤验证：

```
1. pip install hermes-agent@新版本（或更新 pyproject.toml 中的 git tag）
2. python server.py --no-browser
3. 如果启动检查通过，手动执行以下验证：
   a. /api/trade/chat 端点正常
   b. /api/trade/chat/stream 端点正常
   c. /api/trade/models/providers 端点正常（验证 config.model 解析）
   d. 文档提取功能正常
4. 全部通过 → 更新上方矩阵 + 更新 pyproject.toml 的 tested 版本注释
```

> 另：Hermes 的耦合点在 `trade/` 内的完整清单见 `CLAUDE.md` 的「Hermes Coupling Points」一节；
> 代码里对 Hermes 的**真实 import 点**（权威来源）可用
> `grep -rn "import run_agent\|from hermes_cli\|import hermes_constants" trade/ pre_install_check.py` 列出。

## 断裂记录

> 记录历史上 Hermes 哪些升级导致了兼容性问题，以及修复方式。

| Hermes 版本 | 断裂点 | 影响 | 修复方式 |
|------------|--------|------|---------|
| 0.14.0 | `config["model"]` 从 dict 变为 str | `helpers.py` 和 `memory.py` 中 `model_cfg.get("provider")` 报 AttributeError | `_parse_model_config_str()` 兼容两种格式 |
| 0.14.0 | `hermes_cli.models.name_to_models` 移除 | `memory.py` import 失败 | 改用 `_PROVIDER_MODELS` |
| 0.14.0 | `run_agent.py` 从 `chefroger/hermes-agent` fork 迁移到上游 `NousResearch/hermes-agent` | pyproject.toml git 依赖指向旧 fork | 更新 git URL 指向 `NousResearch/hermes-agent` |
