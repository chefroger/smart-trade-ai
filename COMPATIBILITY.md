# Hermes ↔ Foreign Trade Assistant 兼容性记录

> 每次 Hermes 升级后更新此文件。升级前先跑一次完整兼容性检查（见 `项目需求文档.md` 第二章）。

## 当前策略（2026-10-14 起，取代此前所有 pin / 兼容窗口口径）

> **一句话**：机器上只保留**一份**、且是**最新版**的 Hermes；Trade 跑在 **Python 3.14** 上，
> 通过 `sys.path` 用那份 Hermes；Hermes 过旧时 **Trade 自己在后台升级它**并在界面显示进度。

**为什么放弃「固定 tag + 兼容窗口」**

1. **Python 版本是硬互斥的**：上游 ≤ v0.21.5 声明 `requires-python = ">=3.11,<3.14"`，
   ≥ v0.21.6 声明 `>=3.11,<3.15` 且**只提供 3.14 的依赖集**（`>=3.11` 只是留给旧安装
   跑完升级步骤的过渡桥）。实测：`pip install` 0.19.0 在 3.14 上直接
   `ERROR: Package 'hermes-agent' requires a different Python`。Trade 是**进程内**嵌
   Hermes 的，一个 venv 只能有一个 Python 版本 —— 不可能同时服务两代 Hermes。
2. **固定的那份会和用户自己那份抢同一个 checkout**（都是 `~/.hermes/hermes-agent`）：
   目录里已有检出时 `_clone_or_update` 会原样保留，pin 静默失效，还把用户的 Hermes
   降级（install.sh 旧版 `ref != main → return 0` 分支即此）。而 index.md 的官方教程
   Step 5 是从 **main** 装 Hermes —— 于是「装得上、起不来」对每个新用户必然发生。

**为什么 Trade 能跑在 3.14 上（2026-10-14 隔离实测通过）**

`pm/environments.py:activate_dependencies()` 会在 `import hermes_bootstrap` 时把
`sys.path` 换成 Hermes 的托管环境 site-packages（**按目录名剥掉进程原有的全部
site-packages**，且覆盖 `PYTHONPATH`，不检查任何开关）。Trade 的应对是**事后恢复**：
把自身 site-packages 追加回 `sys.path` 末尾（让 Hermes 的依赖优先胜出冲突）并重设
`PYTHONPATH`。实测结果：`hermes_bootstrap` 导入无重拉、`run_agent.AIAgent` 与
Trade 依赖（pymupdf/openpyxl/python-docx/bs4/fastapi）可在同一进程共存，
`openai` 正确来自 Hermes 的托管代际。

> **架构红利**：Trade 的依赖装在 **Trade 自己的 venv** 里，**不在** pm 代际里 ——
> Hermes 更新重建代际不会清掉它们。

**过旧 Hermes 的处理（不阻断、自动升级）**

- `trade/hermes_compat.hermes_python_compat()` 读 checkout 的 `requires-python` 与
  安装印章版本判定，**全程不导入 Hermes**（旧 Hermes 在 3.14 上崩的是缺依赖的
  `ImportError`，用 import 判只能得到天书，得不到「版本过旧」这个可行动的结论）。
- 判定为过旧时 `setup()` **不再 `sys.exit`**：跳过一切会 import Hermes 的步骤、照常起服务，
  由 `trade/hermes_upgrade.py` 在后台跑用户自己的 `hermes update`，界面显示进度（SSE）
  并可重试；成功后自动重启 Trade。
- **网络前置是硬约束**：升级前先用 `git ls-remote` 探 GitHub 可达性（不用裸 TCP —— 用户
  可能配了代理，裸 TCP 会误判）。不通则**绝不开始**，只提示开代理：半途失败会同时弄坏
  Hermes 与 Trade。
- 安装脚本的收尾自检**忽略「Hermes 版本」这一致命项**（`has_fatal_failure(..., ignore_names=('Hermes 版本',))`），
  否则安装会判失败退出，用户永远见不到那个升级界面。

**干净机器实测暴露的两个坑（2026-10-15，已修，回归测试钉住）**

新策略的第一版在干净机器上**装不上**，两个坑都不是「Hermes 版本」问题，而是本策略
自身的实现缺口 —— 记在这里，因为它们正是「路径准备必须集中且早于一切 Hermes import」
这条规则的理由：

1. **自检绕过路径准备**：安装脚本收尾用裸 `python -c` 调 doctor，不走 `setup()`。而
   Hermes 不再装进 Trade 的 venv，于是报 `No module named 'run_agent'` ——
   **安装永远过不了自检**。修法：自检先调 `bootstrap.prepare_hermes_import_paths()`。
2. **doctor 成了「第一个 import Hermes 的人」**：它自己 `from run_agent import AIAgent`
   会触发 pm 激活，剥离 venv 的 site-packages 且**没人恢复**，导致 doctor 后面几项
   （holehe / sqlite-vec）误报「未安装」。修法：`setup()` 里把
   `prepare_hermes_import_paths()` 提到 `dispatch_subcommands()` **之前**。

另有一个独立的装机体验问题：**「没配大模型」曾被当作致命安装失败**（`create_agent()`
抛错 → 「Agent 构造」fatal）→ 新装机器永远看到「安装不完整，请发给技术支持」。现改为
先查 `check_provider()`，未配置则报 WARN 并指向 `hermes setup`。

**版本口径**

- 下限：**Hermes 0.21.6**（`trade/bootstrap.py::_MIN_HERMES_VERSION`、
  `pre_install_check.py::MIN_COMPATIBLE_VERSION`，两处有测试钉住一致）。
- **上限：无。** 新版 Hermes 一律要跟；`_MAX_HERMES_VERSION` 已删除。
- 每次 Hermes 升级仍需复核：**重点是 `pm/` 的行为**（激活是否仍在 import 时发生、是否
  仍按目录名剥离、是否有新的 opt-out），而不只是符号面 —— 符号面全绿但 import 副作用
  改了的坑已经踩过一次（见下方「上游 main 跟进记录」与「静态核对的盲区」）。

## 兼容性矩阵


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

| 0.21.6 | ✅ 兼容 | 2026-10-10 | AI | **v0.21.6**（2026-10-08 发布）。注意上游从此改用**语义化 tag**（`v0.21.6`），不再是 `v2026.9.24` 那种日期式命名。本 release 内 **8 个耦合文件全部被动过**，逐个拉 tag 上的实际内容核符号，全部健在且签名未变：`run_agent.AIAgent` 在且 Trade 实际传的 **14 个构造参数一个不少**、`config.load_config() -> Dict[str, Any]`、`auth.PROVIDER_REGISTRY` / `get_auth_status(provider_id=None)`、`models.provider_model_ids(provider, *, force_refresh=False)` / `_PROVIDER_MODELS`、`env_loader.load_hermes_dotenv(*, hermes_home=, …)`、`hermes_constants.get_hermes_home() -> Path`、`version_info.get_version_info() -> VersionInfo`、`provider_catalog.provider_catalog() -> list[ProviderDescriptor]`。Release 说明里无 BREAKING/removed/rename/deprecated 字样。**单独核过一条行为风险**：10-08 的 `refactor(approval): one session /yolo contract` 把三份会话级 YOLO 持久化实现收进 `tools/approval_yolo.py` —— 它只**新增**会话级开关，Trade 依赖的**进程级环境变量**未受影响：`tools/approval.py:46` 仍是 `_YOLO_MODE_FROZEN = is_truthy_value(os.getenv("HERMES_YOLO_MODE", ""))`，并在 :326/:487 的放行判定中使用。无 breaking change，仍在 `<0.22.0` 范围内，`_MAX_HERMES_VERSION` 无需改动；Trade 无需改代码。**⚠️ 2026-10-14 真机会诊推翻本行结论**：该 tag 已含 `pm/` 托管运行时，import 时激活会劫持 Trade 进程依赖集（见顶部「进程内嵌硬不兼容」警告）。 |
| 0.21.7 | ❌ 不兼容（2026-10-14 真机实测推翻静态结论） | 2026-10-12 / 10-14 | AI | **v0.21.7**（2026-10-12 发布；v0.21.6→v0.21.7 共 **777 commits**，主力是 release/CI/测试，功能面含 terminal `persistent_shell` 修复、Codex 请求体 zstd 压缩）。本 release 内 7 个耦合文件有改动（auth ±201 / config ±202 / run_agent ±106 / env_loader ±27 / hermes_constants ±7 / models ±4 / version_info ±4；`provider_catalog` 未动），但 **v0.21.7 上这些文件的最终内容与上游 main tip 完全一致** —— 与当日 main 复核是同一批内容，逐符号核对结论直接成立：`AIAgent.__init__` 共 86 形参、Trade 传的 **14 个全部保留**（无 `**kwargs` 兜底）；`load_config()` / `get_auth_status(provider_id)` / `provider_model_ids(provider, *, force_refresh)` / `provider_catalog()` / `load_hermes_dotenv(*, hermes_home=…)` / `get_hermes_home()` / `get_version_info()` 签名未变；`PROVIDER_REGISTRY` 的 `base_url_env_var`/`auth_type`/`api_key_env_vars` 仍在；`agent.tools` 仍由 `agent/agent_init.py` 赋值；`HERMES_DISABLE_LAZY_INSTALLS` 与 `gateway` 子命令仍在。**新增 toolset 逐个核对，结论均不应启用**：`connections`/`catalog`（`tools/connectors/`）受 portal 门控（`connectors_available()`，本地无 portal 时不出现），`setup`/`start_chat` 是 CLI 向导便利工具，`example` 是 AGENTS.md 示例；`homeassistant` 被移除（Trade 未用）。版本面：v0.21.7 的 pyproject 是占位 `0.0.0`、`__version__` 改为惰性读安装印章，源码检出由 `version_info` 经语义化 tag 解出 **0.21.7** —— 仍在 `<0.22.0` 窗口内，`_MAX_HERMES_VERSION` 无需改动；Trade 的多源版本识别已覆盖该情形。区间内无 BREAKING/CVE 关键词命中。**结论：Trade 无需改代码。但 ⚠️ 2026-10-13 发现 v0.21.7 的依赖被标成 Python 3.14+，在 3.11–3.13 上装不出依赖（见文件顶部「安装 pin 硬约束」）——所以它**不能**作为安装 pin；安装 pin 定为 `v2026.9.24`（0.21.5）。本机（0.21.4 基线）暂不升级。** 附带观察：上游发布节奏约 3–4 天一个 release（0.21.5 09-28 → 0.21.6 10-08 → 0.21.7 10-12），单 release 千级提交，现有「跟随」模式的维护成本由此可量化。**❌ 2026-10-14 真机升级实测（main@d97007c32d = v0.21.7+758）推翻了上段静态结论**：静态核对只覆盖了 7 个耦合文件的符号面，漏掉了 `hermes_bootstrap.py` 新增的 pm 重拉/依赖激活机制 —— 它在 import 时把进程 sys.path 换成 3.14 托管环境，Trade 进程依赖集被劫持（实测：doctor 里 holehe/sqlite-vec/fitz 全「未安装」、openai 因 `pydantic_core` ABI 不符崩、`trade doctor` 被 runpy 重拉后 2 秒崩）。已回滚本机，详见下方跟进记录。 |

| 0.22.0 | ✅ 兼容（新策略下） | 2026-10-14 | AI | **v0.22.0**（tag `e06df9c2`，2026-10-13 发布；`v0.21.7→v0.22.0` 756 commits，`v2026.9.24→v0.22.0` 10,713 commits）。8 个耦合点逐个核对：`AIAgent.__init__` 86 形参、Trade 实传的 **14 个全部保留**（无 `**kwargs` 兜底）；`load_config()` / `get_auth_status(provider_id=None)` / `provider_model_ids(provider, force_refresh)` / `load_hermes_dotenv(hermes_home, project_env, load_external_secrets)` / `get_hermes_home()` / `provider_catalog()` / `get_version_info()` 签名均未变；`PROVIDER_REGISTRY`（`auth.py:246`）、`_PROVIDER_MODELS`（由 `models_catalog_static.py` 转出）仍在。**`pm/` 行为未变**：`hermes_bootstrap.py:613` 仍无条件 `activate_dependencies(_root)`，`pm/environments.py:449` 仍按目录名剥离 site-packages，**仍无 opt-out** —— 新策略（3.14 + 事后恢复）正对此而设计。注意：`d97007c`（10-14 真机升级目标，即"v0.21.7+758"）**只比 v0.22.0 多 2 个提交**（均为 Docker release CI 修复），且 `hermes_bootstrap.py` / `pm/environments.py` / `run_agent.py` 三点间零差异 ⇒ 10-14 那次真机失败**就是 v0.22.0**，无需再上机复现。另：`requires-python` 仍 `>=3.11,<3.15`（3.14 才可运行），`rc.1-v0.22.1` 已在 RC。 |

## 上游 main 跟进记录

Hermes 的安装走**固定 tag**（`scripts/install.sh` 的 `HERMES_REF`，当前 `v2026.9.24`）——
2026-10-13 起因上游依赖 marker 问题不再跟 main（见文件顶部「安装 pin 硬约束」）。
但**复核上游 main 仍然必要**：它是「下一个 release 里会发生什么」的预警（历史多次靠它提前发现
签名变化），也是将来换 pin 的候选来源。这里记录**未伴随新 release 的 main 复核**；伴随 release
的复核记在上方矩阵的对应行里。

复核方法：用 GitHub API（`/commits?path=<文件>&sha=main&per_page=1`）逐个查 Trade 耦合点文件的
最后改动时间，与本地检出基线比较；有改动的再拉当前内容核对具体符号与签名 —— 上游仓库体量大、
本机装不起 main，故用静态符号核对而非运行验证。

> 2026-10-12 起改用更省事的办法：在本地检出上 `git fetch --shallow-since=<基线日期> origin main`，
> 然后直接 `git diff HEAD origin/main -- <耦合文件>` 看全量差异、`git show origin/main:<文件>`
> 取上游当前实现做符号/签名核对（AST 解析取形参，别用手写正则 —— `dict[str, Any] | None`
> 这类注解里的逗号会让正则漏报）。fetch 只更新 `.git` 里的对象与 refs，**工作树不动**，
> 生产代码不受影响（核对前后 `git status` 应保持干净）。该方法比 API 更全、无速率限制。

| 复核日期 | 上游 main | 本地基线 | 期内有改动的耦合文件 | 结论 |
|---------|-----------|---------|------------------|------|
| 2026-09-30 | `f42f579c` | `d275e422` (2026-09-23) | 7 个耦合点文件被改：run_agent.py / config.py / auth.py / env_loader.py / models.py / hermes_constants.py / version_info.py（另 `auxiliary_client.py`、`vision_tools.py` 亦有改动，非 Trade 耦合点；`agent/image_routing.py` 未动） | ✅ 无破坏。`AIAgent` 仍在且 Trade 实际传的 **14 个构造参数全部保留**；`load_config()` / `PROVIDER_REGISTRY` / `get_auth_status()` / `provider_model_ids()` / `_PROVIDER_MODELS` / `load_hermes_dotenv(hermes_home=)` / `get_hermes_home()` / `provider_catalog()` / `get_version_info()` 签名均未变。无需改动 Trade。 |
| 2026-10-03 | `1cb26bf2` | `d275e422` (2026-09-23) | 4 个：run_agent.py（reasoning blob 容错修复）、config.py + env_loader.py（原子写入临时文件的内部重构）、models.py（StepFun 模型列表合并） | ✅ 无破坏。与上一行同一批符号逐个复核仍未变；`provider_model_ids(provider, *, force_refresh=False)` 与 `_PROVIDER_MODELS` 均保留。无需改动 Trade，`_MAX_HERMES_VERSION` 无需改动。 |
| 2026-10-07 | `9b38eb14` | `d275e422` (2026-09-23) | 6 个（均 10-06）：run_agent.py（free tier 限流处理）、config.py（**移除内置 tirith 扫描器**）、auth.py（free-tier 重构）、models.py + provider_catalog.py（pre-release profile 不进发现列表）、hermes_constants.py（scratch 清理记账） | ✅ 无破坏。同一批符号逐个复核未变：`AIAgent` 的 14 个参数、`load_config()`、`PROVIDER_REGISTRY` / `get_auth_status()`、`provider_model_ids()` / `_PROVIDER_MODELS`、`get_hermes_home()`、`provider_catalog()` 全部保留。唯一「移除」是内置 **tirith** 预执行扫描器，**对 Trade 零影响**：Trade 代码完全不引用它，`~/.hermes/config.yaml` 里相关键也只出现在注释行。无需改动 Trade。 |
| 2026-10-12 | `835c3dd0` | `d275e422` (2026-09-23) | **8 个耦合点文件全部有改动**（区间共 **10,105 个提交**，最新日期 tag `v2026.9.24`）：run_agent.py(±284) / config.py(±1118) / auth.py(±478) / env_loader.py(±216) / models.py(±546) / provider_catalog.py(±8) / **version_info.py（+332，新增模块）** / hermes_constants.py(±560) | ✅ 无破坏，建议**不跟随**（与「冻结 + vendor」路线一致）。逐符号复核：`AIAgent` 仍在、`__init__` 共 86 个形参且 Trade 传的 **14 个全部保留**（无 `**kwargs` 兜底，故「保留」有意义）；`load_config()` / `get_auth_status(provider_id)` / `provider_model_ids(provider, *, force_refresh)` / `provider_catalog()` / `load_hermes_dotenv(*, hermes_home=…)` / `get_hermes_home()` / `get_version_info()` 签名均未变；`PROVIDER_REGISTRY` 的 `base_url_env_var` / `auth_type` / `api_key_env_vars` 属性仍在；`agent.tools`（`doctor._agent_tool_names` 读的工具表）仍由 `agent/agent_init.py` 赋值；`HERMES_DISABLE_LAZY_INSTALLS` 开关与 `gateway` 子命令均保留。区间内安全类提交集中在 **Trade 不使用的消息适配器**（line / webhook / whatsapp_cloud / memory-provider hand-off），无影响 Trade 的面。版本仍落窗口内（最新语义化 tag `v0.21.6` < `0.22.0`；上游 main 的 pyproject 现为占位 `0.0.0`，Trade 的 `_is_real_version()` 已按「识别不到」处理，不会误判不兼容 —— 该预判被现实验证）。 |
| 2026-10-14 | `d97007c3` | `d275e422` (2026-09-23) | **本机真机升级实测**（非静态核对，10,854 commits）：`hermes_bootstrap.py` 新增 pm 重拉/激活机制（`prepare_launch` → `os.execv`；`pm/environments.py:activate_dependencies`） | ❌ **发现进程内嵌硬不兼容，已回滚**。现场时间线：升级后首次 Hermes import 触发「更新收尾」（技能同步 / config **v46→v50 迁移**（误删 `auxiliary.vision`，已恢复）/ 建 **370MB** Python 3.14 托管环境 / 改写 `~/.local/bin/hermes` 启动器（已恢复）/ `pip install -e` 刷新印章）。随后 `trade doctor` 每次 **~2 秒崩**（runpy 重拉 `server.py` → 无 trade 包）；加 `HERMES_DISABLE_LAZY_INSTALLS=1` 后不崩，但**依赖仍被劫持**（doctor 里 holehe/sqlite-vec/fitz 全「未安装」；`import openai` 因 `pydantic_core` 是 cp314 在本进程 3.13 上崩）—— 根因是 `activate_dependencies()` **不检查任何开关**，把 sys.path 换成托管环境 3.14 site-packages。处理：回滚 checkout 至 `d275e422`、清理 `~/.hermes/installs/`（370MB）、恢复启动器与配置、重装 editable 元数据，doctor 全绿（仅剩 Hindsight / sentence-transformers 两个既有可选降级项）。**本机基线保持 `d275e422`，不跟随 main，直到上游提供 opt-out 或 Trade 改子进程架构。** Trade 侧加固：`setup()` 第 0 步先设 `HERMES_DISABLE_LAZY_INSTALLS`（覆盖子命令分发与版本检查两个早于 `load_env_and_set_yolo()` 的窗口；含回归测试 + mutation 验证）。 |

**静态核对的盲区**（历次复核都受此限制，记录以免误以为「查过了就没事」）：
① 无法发现**签名不变但行为变了**的符号 —— 这类只能靠真机跑端点暴露；
② 无法发现上游新增了 Trade **应该启用却没启用**的 toolset —— 默认 toolset 组合缺 `vision`
就是靠真机跑 `create_agent()` 打印工具表才发现的（导致 agent 一直没有 `vision_analyze`，
自写 OCR 兜底）。所以每次跟随 release 时，仍应做一次真机端点验证；
③ 无法发现 **import 时执行副作用**的模块 —— 2026-10-14 的 pm 事故（`hermes_bootstrap`
在 import 时重拉进程 / 激活托管环境依赖）就是这一类：符号面全绿、静态看不错，
真机一导就炸。**结论：v0.21.6 起的任何跟随，必须真机升级验证，静态核对只作初筛。**

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
| 上游 main（安装印章 0.21.5+9141，领先 tag 9141 commits） | `hermes_bootstrap.py` 引入「借用启动」：判定「当前解释器 ≠ Hermes store 解释器」后，把 `server.py` **重新 exec 到 Hermes 自带的 Python**（`%LOCALAPPDATA%\hermes\tools\python-3.14.7+...\python.exe`） | 那个解释器里没有 trade 包 → 子进程死在 `server.py:11 from trade.app import main`（`ModuleNotFoundError: No module named 'trade'`，退出码 1）→ 父进程 `raise RelaunchExit(1)`。**`RelaunchExit` 继承 `SystemExit`**，而 `chat.py` 的重试循环只捕 `Exception` → agent 线程静默死亡（`Future exception was never retrieved`）→ 前端既收不到 `response` 也收不到 `error` → 只显示「⚠️ Agent 未返回有效回复」。**注意：单纯 `import run_agent` 不报错**（relaunch 到 store python 后能成功，只是白跑一遍），只有重新执行 server.py 才炸 —— 所以安装验证（`/api/status`、providers、面板）全部通过，一聊天就废。 | ① `trade/bootstrap.py:load_env_and_set_yolo()` 设 `HERMES_DISABLE_LAZY_INSTALLS=1`（上游正式的 sealed-venv 开关，见 Hermes `tools/lazy_deps.py`；作用域仅限 Trade 进程树，不影响用户自己的 `hermes` CLI）；② `install.sh` / `install.ps1` 生成的启动器里再设一次（**必须写进生成器** —— `trade.cmd` 是 install.ps1 的产物，手改会被重装抹掉）；③ `trade/api/chat.py` 补捕 `BaseException` 并取出 `agent_task.exception()` 上报，让这类失败不再变哑。 |
