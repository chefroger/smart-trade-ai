# Skills 标准化规范

> 本规范参考 [Anthropic Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills) 与 [agentskills.io/specification](https://agentskills.io/specification) 的目录结构，同时保留 smart-trade-ai 的项目惯例。

**适用范围**：smart-trade-ai 仓库下 `skills/` 目录的 38 个 skill。

---

## 1. 目录结构（Anthropic Agent Skills 兼容）

每个 skill 是一个**目录**，至少含 `SKILL.md`。推荐结构：

```
<skill-name>/
├── SKILL.md              # 必需：元数据 + 指令
├── scripts/              # 可选：可执行代码（Python / Shell）
│   ├── README.md         # 脚本使用说明
│   └── *.py
├── references/           # 可选：长文档 / 背景资料 / 模板
│   ├── README.md
│   └── *.md
├── assets/               # 可选：模板、图标、配置样例
│   ├── README.md
│   └── *
└── examples/             # 可选：调用样例（输入输出示例）
    ├── README.md
    └── *
```

**当前项目约定**（与 Anthropic 标准的差异）：
- 项目已用 `scripts/`、`references/`、`assets/`、`examples/` 四目录约定（与 Anthropic 一致）
- `SKILL.md` 是 agent 加载的唯一入口；其他目录内容由 SKILL.md 中的 `injection_prompt` 显式指引

---

## 2. SKILL.md frontmatter 规范

### 必需字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | skill 标识符。**必须与目录名完全一致**（Anthropic 硬约束） |
| `description` | string（**单行**） | 一句话说明 skill 做什么 + 何时用。**必须是单行 YAML 值**，多行会破坏 frontmatter 解析（Anthropic 规范警告） |
| `when_to_use` | YAML list | 结构化触发场景清单，**比 description 更细**。Anthropic 推荐字段 |
| `triggers` | YAML list | **项目扩展**：自然语言触发词，匹配用户 query 自动路由 |
| `category` | string | **项目扩展**：业务分类（客户开发 / 文档管理 / 数据分析 等） |
| `version` | string | semver（如 `1.0.0`），每次内容变更需递增 |
| `author` | string | 作者或维护者标识 |

### 可选字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `injection_prompt` | YAML block scalar (`\|`) | 注入到 system prompt 的长指令。**可以省略**（内容直接写在 body 里也行） |
| `license` | string | 子许可证（项目级 LICENSE 已覆盖，通常省略） |

### 完整示例

```yaml
---
name: b2b-osint
description: 客户背景调查 — 6 层验证：WHOIS/邮箱/制裁名单/技术栈/LinkedIn/风险评分
when_to_use:
  - 用户提到"背景调查""背调""查公司""查域名"
  - 用户粘贴公司名 / 邮箱 / 域名要求做尽职调查
  - 用户询问"这家公司是真的吗""客户是不是骗子"
  - 准备签合同 / 大额订单前要求风险评估
  - 用户提到 OFAC / 制裁名单 / 风险评估
  - 不要用于：邮箱营销列表批量验证（用 b2b-email-intel）
triggers:
  - 背景调查
  - 背调
  - 尽职调查
  - # ... (完整列表见 skill_registry.py)
category: 客户开发
version: 1.0.0
author: Foreign Trade Assistant
injection_prompt: |
  你是 b2b-osint ...
---
```

---

## 3. description vs when_to_use vs triggers 三者关系

| 字段 | 谁读 | 用途 | 详细度 |
|------|------|------|--------|
| `description` | Agent **自动加载判断** | "这个 skill 是干嘛的 + 我该不该用它" | 一句话（50-150 字符） |
| `when_to_use` | Agent **二次校验** | 结构化场景清单（when to use / when NOT to use） | 5-10 条 bullet |
| `triggers` | **`skill_router` 程序匹配** | 用户自然语言 query → skill 路由 | 5-30 个关键词/短语 |

**三者协同**：
1. 用户 query → `triggers` 程序匹配 → 候选 skill 列表
2. 对每个候选 skill → 读 `description` → 判断是否相关
3. 确认相关 → 读 `when_to_use` → 最终确认匹配

---

## 4. 何时省略 injection_prompt

- ✅ **有**（推荐）：当 skill 需要注入"我是谁 / 怎么做"的长指令到 system prompt 时
- ✅ **省略**：当 skill 只需在 README 末尾的 body 提供文档 / 输出格式（Agent 自行遵循）即可

> 项目当前状态（2026-09-14 统计）：6 个 skill 省略了 injection_prompt（body 直接是文档，依赖 `skill_registry.py` 的 `augment_prompt` 作运行时注入），32 个有 injection_prompt。两种形态都允许。
>
> ⚠️ 注意：SKILL.md 的 injection_prompt 一旦存在，运行时会**优先于** registry 的 `augment_prompt`（见 `skill_router.load_injection_prompt`）。修改 prompt 规则时必须同步两处，或确认只改生效的那处。

---

## 5. 目录内容规范

### `scripts/`
- **可执行的 Python / Shell 脚本**
- 每个文件必须有 `if __name__ == "__main__":` 入口
- 配套 `scripts/README.md` 说明调用方式 + 参数
- **不依赖** GUI / 网络（除非明确声明）

### `references/`
- **长文档**（>200 行）或**模板**
- 形式：Markdown / JSON Schema / YAML 配置
- SKILL.md 中通过相对路径引用：`references/checklist.md`

### `assets/`
- **静态资源**：图片、Logo、HTML 模板、Excel 模板、CSV 样例
- 命名规范：`<purpose>.<ext>`（如 `cold-email-template.eml`）

### `examples/`
- **调用样例**（input → output）
- 文件名：`<NN>-<scenario>.<ext>`（如 `01-simple-osquery.md`）
- 用于自动回归测试 / Agent 自学

---

## 6. 验证清单（提交前自查）

每个 skill 提交时确保：

- [ ] `name` 与目录名一致
- [ ] `description` 是**单行**
- [ ] `when_to_use` 含 3-10 条触发场景 + 至少 1 条 "不要用于"
- [ ] `triggers` 至少 5 个关键词
- [ ] `category` 命中以下枚举之一：`客户开发` / `客户管理` / `文档管理` / `数据分析` / `平台运营` / `内容营销` / `销售转化` / `履约运营` / `合规风控` / `自动化` / `系统工具`
- [ ] `version` 递增（修改时）
- [ ] `scripts/README.md` + `references/README.md` + `assets/README.md` 至少存在 3 个目录占位（即使内容为空）
- [ ] 没有 broken 相对路径（`./references/` 或 `references/`）

---

## 7. 当前覆盖率（2026-09-14 统计）

| 项 | 状态 |
|----|------|
| 38 个 skill 目录，全部注册于 `skill_registry.py` | ✅ |
| 38 个 `SKILL.md` frontmatter 完整 + YAML 可解析 | ✅（2026-09-14 修复 3 个损坏文件：b2b-customs-data / b2b-doc-generation / b2b-osint） |
| 38 个 `description` 均为单行 | ✅ |
| 38 个含 `when_to_use`（Anthropic 推荐） | ✅ |
| 32 个含 `injection_prompt` / 6 个用 registry `augment_prompt` | ✅ |
| 38 个 skill 至少有一处可注入内容（SKILL.md 或 registry） | ✅ |
| 38 个含 `scripts/` + `references/` + `assets/` 骨架目录 | ✅（2026-09-14 补齐 4 个：b2b-guarantee-proposal / b2b-inquiry-meeting / b2b-sales-playbook / b2b-tech-drawing） |
| `category` 值统一到枚举内 | ✅（2026-09-14 修正 9 个零散值；枚举更新为：客户开发 / 客户管理 / 文档管理 / 数据分析 / 平台运营 / 内容营销 / 销售转化 / 履约运营 / 合规风控 / 自动化 / 系统工具） |

---

**修订历史**
- 2026-07-27: 首次发布（v0.6.8）
- 2026-09-14: 全量体检后更新统计；修复 3 个结构损坏的 SKILL.md；补充 injection_prompt 与 augment_prompt 的优先级说明
