# Hermes ↔ Foreign Trade Assistant 兼容性记录

> 每次 Hermes 升级后更新此文件。升级前先跑一次完整兼容性检查（见 `项目需求文档.md` 第二章）。

## 兼容性矩阵

> **当前声明范围**：`0.13.0 <= version < 0.21.0`（定义在 `trade/bootstrap.py` 的 `_MIN_HERMES_VERSION` / `_MAX_HERMES_VERSION`）

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
4. 全部通过 → 更新上方矩阵 + 更新 pyproject.toml 版本 pin + 更新 Dockerfile
```

## 断裂记录

> 记录历史上 Hermes 哪些升级导致了兼容性问题，以及修复方式。

| Hermes 版本 | 断裂点 | 影响 | 修复方式 |
|------------|--------|------|---------|
| 0.14.0 | `config["model"]` 从 dict 变为 str | `helpers.py` 和 `memory.py` 中 `model_cfg.get("provider")` 报 AttributeError | `_parse_model_config_str()` 兼容两种格式 |
| 0.14.0 | `hermes_cli.models.name_to_models` 移除 | `memory.py` import 失败 | 改用 `_PROVIDER_MODELS` |
| 0.14.0 | `run_agent.py` 从 `chefroger/hermes-agent` fork 迁移到上游 `NousResearch/hermes-agent` | pyproject.toml git 依赖指向旧 fork | 更新 git URL 指向 `NousResearch/hermes-agent` |
