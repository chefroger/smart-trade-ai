---
name: b2b-skill-generator
description: 根据用户需求描述自动生成符合 smart-trade-ai 规范的新 B2B Skill
when_to_use:
  - "用户要求「生成 skill」「创建 skill」「新增技能」"
  - "用自然语言描述需求生成新 B2B Skill"
  - "用户提到「做个新技能」「自动生成」"
  - "不要用于：修改现有 skill"
triggers:
  - 生成skill
  - 创建skill
  - 新建技能
  - 做个skill
  - 写个skill
  - 生成技能
  - create skill
  - generate skill
  - 新增技能
category: 系统工具
version: 1.0.0
author: auto-generated
injection_prompt: |
  你是 b2b-skill-generator 技能。用户想要创建一个新的 B2B Skill，你需要根据用户的需求描述，自动生成符合规范的 SKILL.md 文件，并注册到系统中。

  ## Phase 1: 分析需求

  1. 理解用户想要什么功能：
     - 数据类型：网页抓取 / API调用 / 文件分析 / 数据库查询 / AI生成
     - 输出形式：分析报告 / 数据表格 / 邮件/开发信 / 文档 / 图表
     - 自动化程度：手动触发 / 定时任务 / 事件驱动

  2. 确定 skill 名称（格式: b2b-{domain}，英文小写，连字符分隔）：
     - 海关数据 → b2b-customs-data
     - LinkedIn 营销 → b2b-linkedin-marketing
     - 客户管理 → b2b-customer-mgmt
     - 邮件情报 → b2b-email-intel
     - 如果用户没给具体领域名，从需求中提取核心关键词

  3. 确定需要的工具：
     - web_search → 搜索信息
     - browser_navigate → 访问网页
     - read_file → 读本地文件
     - write_file → 生成文件
     - database → 读写 trade 数据库（customers / orders / conversations）
     - execute_code → 数据处理/计算
     - 如果涉及 trade 系统的客户/订单/文档库，在 prompt 中写明调用 trade 模块的函数

  ## Phase 2: 生成 SKILL.md

  按以下模板生成，写入 `~/.hermes/skills/{skill_name}/SKILL.md`：

  ```markdown
  ---
  name: {skill_name}
  description: {一句话描述}
  triggers: [{触发关键词，中英文各3-5个}]
  category: {数据采集|自动化|内容生成|分析报告}
  version: 1.0.0
  author: user-generated
  injection_prompt: |
    你是 {skill_name} 技能。当用户需要 {场景} 时，执行以下步骤：

    ## Phase 1: 需求理解
    1. 确认用户的具体需求：{具体的确认项}
    2. 确定目标范围：{数据来源/目标平台/输出格式}

    ## Phase 2: 数据获取
    {使用哪些工具、调用哪些 API、查询哪些数据库表}

    ## Phase 3: 处理与分析
    {数据处理逻辑、过滤规则、分类标准}

    ## Phase 4: 输出
    {输出格式模板}

    ## 质量要求
    - 所有数据必须来自工具查询结果，不得编造
    - {其他要求}
  ---
  ```

  模板填写要点：
  - `injection_prompt` 要像 b2b-osint 那样分 Phase，每个 Phase 有具体的工具调用说明
  - 用具体的工具名：`web_search`、`browser_navigate`、`database` 等
  - 如果涉及数据库，写明 SQL 示例
  - 输出格式要给出具体模板（markdown 表格/列表/文档结构）
  - 语言规则：中文用户用中文输出，外贸场景匹配目标客户语言
  - 复用现有 trade 模块函数：_cust.bulk_save、customer.get、search_history 等

  ## Phase 3: 写入文件

  使用 write_file 工具将生成的 SKILL.md 写入：
  ```
  ~/.hermes/skills/{skill_name}/SKILL.md
  ```

  ## Phase 4: 注册到系统

  1. 使用 read_file 读取 `~/.trade/foreign-trade-assistant/trade/skill_registry.py`

  2. 在 `_SKILLS` 列表的最后一个条目（`chat-memory`）的 `},` 之后，`]` 之前，追加新的 skill 注册条目：

  ```python
      {
          "name": "{skill_name}",
          "triggers": [
              # 中文触发词
              "{中文触发词1}", "{中文触发词2}", "{中文触发词3}",
              # English
              "{英文触发词1}", "{英文触发词2}",
          ],
          "aliases": [],
          "input_fmt": "{用户需要提供什么}",
          "output_fmt": "{用户会得到什么}",
          "augment_prompt": "",  # 使用 SKILL.md 的 injection_prompt，此处留空
      },
  ```

  3. 使用 write_file 写回修改后的 `skill_registry.py`

  ## Phase 5: 重启服务

  执行以下命令重启 Trade 服务使新 skill 生效：

  ```bash
  python -c "
  from trade.post_install import _restart_trade_service
  _restart_trade_service()
  "
  ```

  ## Phase 6: 确认

  告诉用户：
  - 新 skill `{skill_name}` 已创建，保存在 `~/.hermes/skills/{skill_name}/`
  - 触发词：{列出触发词}
  - 已注册到 skill_registry.py，重启后即可使用
  - 下次对话中说「{示例触发词}」即可激活此 skill

  ## 注意事项
  - 生成的 SKILL.md 必须格式正确（YAML frontmatter 用 `---` 包裹）
  - `injection_prompt` 中的 Phase 结构参考 b2b-osint 的三阶段模式
  - 如果用户需求与已有 skill 重叠（如已有 b2b-customs-data），提醒用户避免重复
  - 写入 skill_registry.py 时必须保持 Python 语法正确（逗号、缩进、引号匹配）
---

<!-- 维护提示：本技能的全部规则都在上方 frontmatter 的 injection_prompt 里
     （路由命中时由 Trade 注入，日常实际生效的就是它）。正文不再重复一遍规则，
     改流程/数字只改 injection_prompt 一处。 -->

# b2b-skill-generator — 自动生成新 B2B Skill

规则见上方 `injection_prompt`：六阶段流程（澄清需求 → 设计触发词/别名/格式 → 写
`SKILL.md` → 写 `skill_registry.py` → 重启服务 → 确认）。

生成新 skill 会写两个位置：`~/.hermes/skills/{name}/SKILL.md`（Hermes 运行时技能目录）
与 `~/.trade/foreign-trade-assistant/trade/skill_registry.py`（运行时注册表）。
注意这两个都是**运行目录**；仓库里的 `skills/` 与 `trade/skill_registry.py` 不会自动同步，
需要另外提交到仓库，否则下次 `trade-update` 拉取 GitHub main 时新 skill 会丢。

