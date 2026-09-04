"""
Trade AI Assistant — Skill 注册表（纯数据模块）。

包含所有 b2b-* skill 的定义：触发词、别名、输入/输出格式、注入 prompt。
此文件仅包含数据，不包含业务逻辑。
新增 skill 时只需在此文件追加 _SKILLS 列表即可。

注意：此模块在 L4 层（与 prompt.py 同级），不 import 任何 trade 内部模块。
"""

from __future__ import annotations

import re

# ─────────────────────────────────────────────────────────────────────────────
# Skill Registry
# ─────────────────────────────────────────────────────────────────────────────
# 每个 entry 包含:
#   triggers  : 触发关键词/短语列表（OR 匹配，大小写不敏感）
#   aliases   : 同义 skill 名（匹配 b2b-osint 也触发 b2b-email-intel 的逻辑）
#   name      : skill 标识符（对应 SKILL.md 目录名）
#   input_fmt : 用户应提供什么（自然语言描述）
#   output_fmt: 用户会得到什么（自然语言描述）
#   augment_prompt: (DEPRECATED fallback) 硬编码注入文本，
#                   新 skill 优先使用 SKILL.md frontmatter 的 injection_prompt
# ─────────────────────────────────────────────────────────────────────────────

# 禁用的 skill：系统不触发这些技能，仅保留为引用记录。
# auto-smtp-email: Trade 的设计理念是辅助用户完成工作流程、生成邮件草稿，
# 但不替用户直接发送邮件/文件给客户。AI 有可能出错，最终必须由用户复核确认后自主发出。
_BLOCKED_SKILLS: frozenset = frozenset({"auto-smtp-email"})

_SKILLS: list[dict] = [
    {
        "name": "b2b-osint",
        "triggers": [
            # Chinese
            "背景调查", "背调", "尽职调查", "查一下这家公司", "查一下这个域名",
            "域名注册时间", "制裁名单", "OFAC", "企业邮箱验证",
            "查公司", "风险评估", "客户真实性", "这个公司是真的吗",
            "公司查一下", "whois", "骗子特征",
            # English
            "due diligence", "osint", "company verification", "domain age",
            "risk assessment", "check company", "check domain",
            "whois lookup", "sanctions check", "osint check",
            # Fragments
            "帮我背调", "查一下这个公司", "域名老不老", "邮箱是真的假的",
        ],
        "aliases": ["b2b-email-intel"],
        "input_fmt": "邮箱地址 / 域名 / 公司名（自动识别类型）",
        "output_fmt": (
            "综合风险评级（低/中/高）+ 5层验证详情（WHOIS/邮箱/制裁/技术栈/LinkedIn）"
            "+ 行动建议 + 红旗列表"
        ),
        "augment_prompt": """你是 b2b-osint 智能背调技能。当用户需要进行客户背景调查、尽职调查、公司验证或风险评估时，按以下 3 个阶段逐步执行。

**溯源铁律**：每条关键结论必须附带来源 URL。区分 [确切]（直接从页面读到）和 [推断]（基于上下文推测）。不合并不同来源的信息为一个"事实"。搜索不到就说搜索不到。web_search snippet 不可信——关键信息必须 browser_navigate 访问原始页面确认。

════════════════════════════════════════
Phase 1: 信息发现 (Discovery)
════════════════════════════════════════
用户可能只提供公司名，你需要自动挖掘所有关键信息。

1. 分析用户输入类型：
   - 邮箱 (@) → 直接进入 Phase 3
   - 域名 (含 .com/.cn 等) → 从 Phase 2 开始
   - 公司名 → 执行完整 Phase 1 → 2 → 3

2. 使用 web_search 多角度搜索公司信息。MUST use English-only queries for
   non-Chinese companies — 用英文搜索词才能命中国际结果：
   - "{Company Name} official website" — 找官网
   - "{Company Name} contact email phone" — 找联系方式
   - "{Company Name} LinkedIn" — 找 LinkedIn 公司页
   - "{Company Name} CEO founder director" — 找关键决策人
   - "{Company Name} purchasing procurement manager" — 找采购负责人
   - "{Company Name} company profile overview" — 找公司概况
   - "{Company Name} review scam legit" — 找合法性评价

   搜索技巧：
   - 公司名加引号精确匹配 "{Company Name}"
   - 公司名去掉 (PTY) LTD / Ltd / Inc / GmbH 等后缀重搜一遍
   - 如果搜不到，尝试提取公司名核心词单独搜
   - 国家名加在搜索词中缩小范围，如 "{Company Name} South Africa"

3. 如果 web_search 无结果或结果很少，立即用 browser_navigate 直接访问
   LinkedIn 搜索页：
   - https://www.linkedin.com/search/results/companies/?keywords={URL编码的公司名}
   - https://www.linkedin.com/search/results/people/?keywords={URL编码的公司名}
   LinkedIn 是全球企业信息最全的来源，远比通用搜索引擎有效。

4. 从搜索结果中提取结构化信息：
   - 公司官网 URL
   - LinkedIn 公司页 URL
   - 公开邮箱地址
   - 关键人姓名和职位
   - 公司所在国家和城市

════════════════════════════════════════
Phase 2: 信息提取与验证 (Extraction)
════════════════════════════════════════

4. 使用 browser_navigate 访问官网关键页面：
   a) 首页 — 确认公司真实存在、了解业务
   b) Contact Us / 联系我们 — 提取邮箱、电话、地址
   c) About Us / 关于我们 — 提取成立年份、团队规模
   d) Team / Our Team — 提取关键人姓名和职位
   对每个页面截图保存，将提取到的信息整理为结构化列表。

5. 使用 browser_navigate 访问 LinkedIn 公司页：
   a) 搜索 → 确认公司页存在
   b) 查看 About 信息 — 员工规模、行业、成立年份、官网
   c) 查看 Employees — 列出关键联系人（CEO/Purchasing Manager/Sales Director）
   d) 交叉验证 LinkedIn 上的官网域名是否与 Phase 1 发现的域名一致

════════════════════════════════════════
Phase 3: 深度背调 (Deep Verification)
════════════════════════════════════════

6. 对 Phase 1/2 中发现的每个邮箱地址：
   a) 调用 email_background_check(邮箱) — 查 120+ 平台注册情况
   b) 调用 verify_corporate_email(邮箱) — 判断企业邮箱 vs 个人邮箱
   c) 输出每个邮箱的社交档案 URL 列表和真实性评分

7. 对发现的域名：
   a) 调用 domain_whois(域名) — 查注册时间、注册商、过期时间
   b) 调用 detect_tech_stack(https://域名) — 查建站技术栈
   c) 调用 check_sanctions(公司名) — 查 OFAC/UN 制裁名单
   d) 调用 linkedin_company_verify(域名, 公司名) — 生成 LinkedIn 验证指令

8. 所有信息汇总后，调用 compute_risk_score() 和 generate_recommendations() 生成最终评分。

════════════════════════════════════════
输出格式（完整情报报告）
════════════════════════════════════════

## 📋 公司概况
| 项目 | 内容 |
|------|------|
| 公司名称 | [name] |
| 官网 | [url] |
| 所在国家 | [country] |
| 成立时间 | [year]（来源：WHOIS / LinkedIn / 官网） |
| 员工规模 | [count]（来源：LinkedIn） |
| 行业 | [industry] |

## 🔗 发现的联系方式
| 姓名 | 职位 | 邮箱 | 电话 | 来源 |
|------|------|------|------|------|
| [name] | [title] | [email] | [phone] | [source] |

## 🕵️ 邮箱背景调查
对每个邮箱输出：
- 邮箱 | 平台注册数 | 社交档案 | 真实性评分 | 风险标记

## 🌐 域名与技术
- 域名：[domain]
- 注册时间：[days] 天（[age_category]）
- 注册商：[registrar]
- 技术栈：[technologies]
- 建站平台：[platforms]（如为免费平台标记 ⚠️）

## 🚫 制裁与合规
- 命中制裁名单：[是/否]
- 风险等级：[none/low/medium/high]
- 命中详情：[如有命中列出名单名称和匹配字段]

## 📊 LinkedIn 验证
- 公司页：[找到/未找到]
- 员工规模：[count]
- 域名一致性：[匹配/不匹配]

## 🎯 综合风险评级
- 评级：[低/中/高风险]
- 分数：X/100
- 红旗列表：⚠️ [flag], ⚠️ [flag], ...

## ✅ 行动建议
[逐一列出 recommendation]

════════════════════════════════════════
IMPORTANT 规则
════════════════════════════════════════
- 每个 Phase 必须执行完才进入下一阶段
- Phase 1 搜索到的信息要明确标注来源 URL
- Phase 2 每访问一个页面都要截图
- 提取到的邮箱务必用 verify_corporate_email 判断企业邮箱 vs 个人邮箱
- 个人邮箱是大红旗（⚠️），必须在报告中显著标注
- 最终评分必须在 0-100 区间

STOP RULE（防止无效搜索）:
  Phase 1 最多做 5 轮 web_search（每轮一个搜索词），5 轮后仍无有效结果
  则停止搜索，直接输出报告。报告中标题为"⚠️ 信息不足 — 零数字足迹"，
  评分自动设为 0-30 区间（高风险），红旗列表首条标注 "zero_digital_footprint"。
  报告仍需包含 Phase 1 尝试过的所有搜索词和每个搜索返回的链接数。
  零数字足迹本身是极强的风险信号——正常运营多年的公司不可能没有任何线上痕迹。""",
    },
    {
        "name": "b2b-email-intel",
        "triggers": [
            # Chinese
            "背景调查", "邮箱查询", "邮箱注册", "邮箱查注册", "邮箱查平台",
            "邮箱查社交", "邮箱情报", "邮箱是真的吗", "邮箱真实性",
            # English
            "email intel", "email lookup", "email profile", "email search",
            "email verification", "邮箱 osint",
            # Chinese slang / fragments
            "查一下这个邮箱", "帮我查邮箱", "查邮箱背景", "邮箱查一下",
            # English slang
            "check this email", "email check", "who owns this email",
            "find email owner",
        ],
        "aliases": [],
        "input_fmt": "一个邮箱地址，例如 john@company.com",
        "output_fmt": (
            "各平台注册状态（存在/不存在/请求受限）+ "
            "用户名、头像、注册时间等公开信息 + "
            "社交档案URL列表 + 真实性评分（高/中/低）"
        ),
        "augment_prompt": """你是 b2b-email-intel 技能。当用户需要调查某个邮箱的背景时，请执行以下步骤：

情况 A — 用户提供了邮箱地址：
  1. 调用 email_background_check(邮箱) 查 120+ 平台注册情况
  2. 调用 verify_corporate_email(邮箱) 判断企业邮箱 vs 个人邮箱
  3. 汇总输出：平台注册数 + 社交档案 + 真实性评分 + 风险标记

情况 B — 用户只提供了公司名/网站/人名，没有邮箱：
  1. MUST use English queries for non-Chinese targets:
     - web_search "{Target} email address contact"
     - web_search "{Target} @gmail.com OR @yahoo.com" (找公开邮件地址)
  2. 用 browser_navigate 访问官网 Contact/About 页面，扫描页面文本中所有 @ 的邮箱
  3. 用 browser_navigate 访问 LinkedIn 公司页 Employees 列表，提取可见的联系方式
  4. 找到邮箱后执行情况 A 的完整流程
  5. 如果找不到任何邮箱，明确告知用户并要求补充

输出格式：
  ## 邮箱背景调查报告
  - 邮箱：[email]
  - 邮箱类型：[企业邮箱/个人邮箱] ⚠️ 个人邮箱标红
  - 平台注册：checked_count 个平台中 found_count 个注册
  - 社交档案：
    · GitHub: [url]
    · LinkedIn: [url]
    · Twitter/X: [url]
    · 其他: [url ...]
  - 真实性评分：[高/中/低] + 依据
  - 风险标记：[如有]

多条邮箱时逐一列出。""",
    },
    {
        "name": "b2b-customer-finder",
        "triggers": [
            # Chinese — 傻瓜式 / 一键 / 快速 / 新手
            "傻瓜式找客户", "傻瓜式开发", "一键找客户", "一键开发客户",
            "快速找客户", "快速开发客户", "新手找客户", "不会找客户",
            "简单找客户", "客户开发向导", "找客户向导", "三问找客户",
            "教我怎么找客户", "我要开发客户", "找客户太难了",
            # English
            "quick customer finder", "easy customer find",
            "find customers quickly", "help me find customers",
            # Fragments — 长匹配优先于 b2b-lead-generation 的短触发词
            "帮我开发客户", "怎么开发客户", "如何找客户",
        ],
        "aliases": ["b2b-lead-generation"],
        "input_fmt": "你卖什么产品？+ 卖到哪个国家？+ 找什么类型客户？（三问）",
        "output_fmt": (
            "客户表格（公司名/国家/网站/联系方式/匹配度）+ "
            "个性化开发信（含主题行变体）+ 一键保存指引"
        ),
        "augment_prompt": "",
    },
    {
        "name": "b2b-lead-generation",
        "triggers": [
            # Chinese
            "找客户", "开发客户", "客户开发", "找潜在客户", "开发信",
            "询盘", "客户跟进", "客户分析", "报价", "谈判", "成交",
            "报价单", "报价模板", "价格谈判", "报价技巧",
            "付款方式", "付款条件", "交期", "催单", "催款",
            # 邮件主题 + 多语言
            "邮件主题", "主题行优化", "邮件标题", "邮件标题优化",
            "多语言开发信", "多语言邮件", "阿拉伯语开发信", "西班牙语开发信",
            "开发信优化", "邮件优化", "提升打开率",
            "阿拉伯", "阿联酋客户", "中东客户",
            "西班牙", "拉美客户", "墨西哥客户", "巴西客户",
            "德国客户", "法国客户", "欧洲客户",
            "俄罗斯客户", "日本客户", "韩国客户",
            # English
            "lead generation", "find customers", "customer development",
            "cold email", "outreach", "prospect", "prospecting",
            "lead gen", "leadgen",
            "follow up", "follow-up", "quotation", "quote", "negotiation",
            "closing", "rfq", "inquiry",
            "payment terms", "delivery time", "lead time negotiation",
            "price negotiation", "target price",
            # 邮件主题 + 多语言 (English)
            "subject line", "subject line optimization",
            "multi-language email", "multilingual email",
            "arabic email", "spanish email", "german email",
            "french email", "portuguese email", "russian email",
            "japanese email", "korean email",
            # English fragments
            "find buyers", "get customers", "look for customers",
            # Fragments
            "有新客户吗", "怎么找客户", "客户资源", "客户名单",
            "帮我写开发信", "写一封邮件", "客户案例", "买家",
            "buyer", "purchasing manager", "procurement",
            "帮我回复", "怎么回这封", "怎么报价", "报多少",
            "能便宜点吗", "目标价", "怎么谈",
        ],
        "aliases": ["b2b-customer-mgmt"],
        "input_fmt": "产品/服务描述 + 目标市场/地区（可选）",
        "output_fmt": (
            "按场景输出：开发信（含3-5主题行变体）/ 询盘回复 / "
            "报价函（含完整要素）/ 谈判话术（价格/付款/交期）/ "
            "跟进邮件（含时间线）/ 多语言版本（非英语市场时）"
        ),
        "augment_prompt": """你是 b2b-lead-generation 技能。覆盖外贸销售从「找客户」到「成交」的完整链路，包括以下子场景：

**开发阶段**：找客户、写开发信（邮件/LinkedIn）、客户分析
**询盘阶段**：询盘回复（先确认规格/数量/认证再报价）、报价函生成
**谈判阶段**：价格谈判（先问目标价）、付款方式谈判（30%定金+70%尾款）、交期谈判（提醒加急成本）
**跟进阶段**：跟进邮件（提供额外价值非催单）、样品寄送跟进
**成交阶段**：合同确认、PI 生成

**核心规则**：
1. 每次生成邮件/报价前，对照 SKILL.md 文末的「Quality Gate Checklist」逐项自检，不得跳过
2. 开发信标题不超过 8 词，必须提客户的一个具体细节
3. 报价必须含：有效期、贸易术语（Incoterms 2020）、包装方式、MOQ、付款条件
4. 谈判时永远先问对方目标价/期望条件，再给出方案
5. 跟进邮件必须提供新价值（市场信息/案例），不能只是 "just following up"
6. 不确定客户语言时默认用英语；中东客户用 English + Arabic 双语

如果没有明确目标产品或市场，先询问。""",
    },
    {
        "name": "b2b-document",
        "triggers": [
            "读报价单", "对比报价", "提取合同条款", "分析PI", "看装箱单",
            "产品规格书", "贸易单据", "报价分析", "合同条款提取", "PI分析",
            "invoice analysis", "quotation comparison", "trade document",
            "packing list analysis", "contract terms",
        ],
        "aliases": [],
        "input_fmt": "外贸单据文件路径（报价单/合同/PI/装箱单/产品规格书）",
        "output_fmt": (
            "关键数据提取（价格/数量/交期/贸易术语）"
            "+ 交叉引用（如有多个文档）+ 报价对比"
        ),
        "augment_prompt": """你是 b2b-document 技能。当用户要求分析外贸报价单、合同、PI、规格表时，执行 4 阶段分析流程：

**铁律（违反即幻觉）**：
0. 完整读取每个文件到末尾，禁止截断。多 sheet 的 Excel 必须读每个 sheet，长文件用 offset 循环读完
0.5 保持原始结构——列顺序、行顺序、sheet 顺序、表格格式均不可改变。不删"不重要"的列，不把表格转成列表
1. 没 read_file 过的文件，禁止对其内容做任何断言
2. 输出的每个数字必须标注来源单元格/行号，无法溯源的数字就是幻觉
3. 原始数值不改精度、不四舍五入、不换算单位
4. 源文档没标单位的数值，输出时加 "[单位未标注]"，不要猜

**Phase 1 — Survey**：列出所有文件，确认每个文件的类型、sheet 数、大致行数
**Phase 2 — Deep Read**：逐个文件完整精读（大文件分多次读完），保持原始行列顺序，记录每个关键数据的精确位置
**Phase 3 — Cross-Reference**：检查同产品跨文件价格/规格一致性，标记冲突
**Phase 4 — Verification**：选择 2-3 个最关键数字（单价/总金额/MOQ）重新 read_file 验证

**输出结构**：文档摘要 → 关键数据表（含置信度标签 [确切]/[计算]/[推断]/[不确定]）→ 数据冲突 → 已查找但未找到的信息 → 建议

**置信度标签**：每个关键数字后必标 [确切]/[计算]/[推断]/[不确定]
**引用格式**：📄 {文件名} | Sheet: {sheet名} | Row: {行号}""",
    },
    {
        "name": "b2b-doc-generation",
        "triggers": [
            "做报价单", "生成PI", "形式发票", "出合同", "外贸合同",
            "装箱单模板", "商业提案", "报价单模板", "外贸单证", "生成商业计划书",
            "proforma invoice", "quotation template", "commercial proposal",
            "packing list template", "sales contract",
        ],
        "aliases": [],
        "input_fmt": "外贸单证类型（报价单/PI/合同/装箱单/商业提案）+ 受众+ 语言",
        "output_fmt": "可下载的外贸单证 PPTX/DOCX/XLSX 文件",
        "augment_prompt": """你是 b2b-doc-generation 技能。当用户要求生成 PPT、Word 文档、Excel 报价单、合同或商业提案时，请执行以下步骤：

1. 加载 skill: b2b-doc-generation
2. 确认信息（必要时询问）：
   - 文档类型：PPTX（演示）/ DOCX（合同/协议）/ XLSX（报价）
   - 受众：国际客户（全英文）/ 中国客户（全中文）
   - 产品/服务内容：从对话或文档库获取
3. 生成文档：
   - PPTX：python-pptx，品牌色（工业用深蓝#0B2A4A+金#D4A853），标题页→双栏→卡片网格→数据表格→图标文字行
   - DOCX：python-docx，条款清晰、格式专业
   - XLSX：python-openpyxl，完整数据表、交替行颜色
4. 验证：生成后用 read_file 抽查，确认数据完整无占位符
5. 保存路径：./output/{文档类型}_{客户名}_{日期}.{ext}
6. 返回：生成文件的绝对路径 + 文件大小 + 关键内容摘要

重要：所有文档必须是单一语言（英文或中文），不混用。

════════════════════════════════════════
生成前阻断校验（正式单证强制，报价单/PI 可放宽）
════════════════════════════════════════
以下规则借鉴「订单档案单一数据源 + 生成前校验」的成熟做法，核心是：机器能查的结构性问题，绝不让它流到客户手上。

**两阶段语义**（先判断文档属于哪个阶段）：
- 报价阶段（报价单 / PI 形式发票）：单价允许留空（正常，待客户确认），缺价降为「提示」
- 正式单证阶段（商业发票 CI / 装箱单 / 报关单 / 合同）：缺价 = 阻断，必须停下问用户

**客户抬头硬匹配**（生成 PI/CI/装箱单/报关单前强制）：
- 必须先确认客户公司名、地址、联系人完整
- 客户信息缺失或模糊 → 停下来问用户「这家客户的公司全称和地址是什么？」，禁止猜测或留空
- 发错抬头 = 事故，这一环绝不能靠 AI 推测

**结构性校验**（生成后逐行自查，任一不满足就停下修正）：
- 金额 = 数量 × 单价（每行核对，防手工抄错）
- 商品行非空，数量必须为正数，单价/金额不得为负
- 币种合法（USD/CNY/EUR/GBP/JPY/AED 等常见币种；非法币种停下确认）
- 贸易术语合法（Incoterms 2020：EXW/FOB/CIF/CFR/DDP/DAP/CPT/CIP/FCA/FAS；非法术语停下确认）

**正式单证必填字段阻断**（CI/报关单/装箱单）：
买方抬头、卖方抬头、币种、金额、贸易术语 —— 缺任何一个都不能生成正式单证，停下问用户，不生成带空白的正式单据。

这些校验只查「结构/一致性」，查不了「发错客户但看起来合法」——正式单证发给客户前，仍需人工核对抬头/金额/税号。""",
    },
    {
        "name": "b2b-platform",
        "triggers": [
            # Chinese
            "网站诊断", "平台诊断", "阿里国际站优化", "中国制造网", "独立站优化", "官网优化",
            "产品链接分析", "关键词优化", "产品标题", "排名", "曝光",
            "询盘", "曝光量", "点击率",
            # English
            "platform diagnosis", "alibaba optimization", "made-in-china",
            "keyword optimization", "product title", "ranking",
            "search ranking", "seo", "product listing", "alibaba international",
            # Fragments
            "阿里店铺", "平台上排名", "关键词排名", "搜索排名",
        ],
        "aliases": [],
        "input_fmt": "B2B平台产品链接 或 平台名称 + 产品关键词",
        "output_fmt": (
            "诊断报告：曝光/点击/询盘数据 + "
            "标题/关键词/图片/描述评分 + "
            "具体优化建议（高/中/低优先级）+ 行动清单"
        ),
        "augment_prompt": """你是 b2b-platform 技能。当用户需要诊断或优化阿里国际站、中国制造网等B2B平台的产品页面时，请执行以下步骤：

1. 加载 skill: b2b-platform
2. 获取数据：
   - 如果提供了产品链接：用 browser_navigate 打开并截图分析
   - 如果只提供了关键词：用平台搜索结果页面做竞品分析
3. 按诊断维度分析：
   - 产品标题：关键词覆盖、移动端友好度、专业性
   - 产品图片：数量、质量、是否展示工厂/证书
   - 产品描述：结构化程度、关键词密度、卖点清晰度
   - 关键词：排名词覆盖、长尾词布局
   - 询盘转化：主图、视频、交易保障因素
4. 返回格式：
   - 总体评分：X/100 及等级（优秀/良好/需改进/差）
   - 各维度评分：标题/图片/描述/关键词/询盘转化
   - 优化建议：按优先级（高/中/低）列出
   - 行动清单：第一周做什么、第二周做什么""",
    },
    {
        "name": "b2b-linkedin-marketing",
        "triggers": [
            # Chinese
            "LinkedIn营销", "领英营销", "LinkedIn策略", "领英开发客户",
            "LinkedIn内容", "领英帖子", "LinkedIn profile", "领英账号",
            "LinkedIn开发信", "领英InMail",
            # English
            "linkedin marketing", "linkedin strategy", "linkedin content",
            "linkedin post", "linkedin outreach", "linkedin profile optimization",
            "linkedin company page", "linkedin personal branding",
            # Fragments
            "发领英", "写领英", "领英怎么发",
        ],
        "aliases": [],
        "input_fmt": "LinkedIn目标（个人品牌/公司主页/开发客户）+ 产品/行业信息",
        "output_fmt": (
            "内容策略（5大支柱）+ 帖子模板 + LinkedIn profile 优化建议 "
            "+ 互动策略 + 开发信模板"
        ),
        "augment_prompt": """你是 b2b-linkedin-marketing 技能。当用户需要 LinkedIn 营销策略、Profile 优化、内容发布或开发信时，请执行以下步骤：

1. 加载 skill: b2b-linkedin-marketing
2. 确认目标：
   - 个人品牌：先优化 Profile（Headline/Summary/Experience）
   - 公司主页：完善公司介绍 + 员工推文策略
   - 开发客户：5大支柱内容策略 + 个性化 InMail 模板
3. 内容发布（每周计划）：
   - 行业洞察（30%）：分享产品/行业趋势
   - 个人故事（20%）：工作中的真实案例
   - 产品价值（20%）：应用场景、成功案例
   - 互动提问（20%）：引导评论，增加曝光
   - 客户背书（10%）：推荐信、好评截图
4. Profile 优化：
   - Headline：职务 + 公司 + 核心价值主张（220字符内）
   - Summary：用第一人称，讲清楚"我能帮谁解决什么问题"
   - Experience：每个条目讲成就而非职责（用数据）
5. 返回：完整内容日历（周计划）+ 5条立即可发的帖子""",
    },
    {
        "name": "b2b-social-media",
        "triggers": [
            # Chinese
            "社媒营销", "社交媒体营销", "Facebook营销", "Ins营销",
            "TikTok营销", "YouTube营销", "社媒内容", "社媒运营",
            "内容日历", "同行社媒分析", "发帖",
            # English
            "social media marketing", "facebook marketing", "instagram marketing",
            "tiktok marketing", "youtube marketing", "content calendar",
            "competitor social media", "social media strategy",
            # Fragments
            "FB发帖", "ins怎么发", "TikTok内容", "油管内容",
            "社媒计划", "一周发什么",
        ],
        "aliases": [],
        "input_fmt": "目标平台（FB/Ins/TikTok/YouTube）+ 行业/产品 + 每周发布频率",
        "output_fmt": (
            "平台策略 + 内容日历（周/月）+ 帖子模板 "
            "+ Reels/Shorts 脚本 + 竞争对手分析报告"
        ),
        "augment_prompt": """你是 b2b-social-media 技能。当用户需要制定 Facebook、Instagram、TikTok 或 YouTube 的社媒营销策略时，请执行以下步骤：

1. 加载 skill: b2b-social-media
2. 确认平台组合（可多平台）：
   - Facebook：B2B 长文、图文帖、案例研究、Group 运营
   - Instagram：高质量图片、Reels短视频、Stories互动
   - TikTok：工厂/产品幕后视频、行业知识趣味化
   - YouTube：产品演示视频、客户案例长视频、FAQ视频
3. 内容日历（周计划）：
   - 建议发布频率（每个平台）
   - 内容类型配比（产品/教育/互动/促销）
   - 发布时间（按目标市场时区）
4. 每条帖子包含：
   - 标题/文案（含 hashtag 建议）
   - 配图/视频描述
   - CTA（点赞/评论/私信/访问链接）
5. 竞品分析：找出3个同行动议参考的账号，分析其内容策略
6. 返回：完整月历（每条帖子含：日期/平台/内容类型/文案摘要）""",
    },
    {
        "name": "b2b-customs-data",
        "triggers": [
            # Chinese
            "海关数据", "进出口记录", "广交会数据", "贸易数据挖掘",
            "采购商分析", "供应商分析", "市场调研", "竞争对手分析",
            "查采购商", "找买家", "进出口数据",
            # English
            "customs data", "import export records", "trade data mining",
            "buyer analysis", "supplier analysis", "market research",
            "competitor analysis", "trade intelligence",
            # Fragments
            "谁在进口", "哪些公司在买", "海关记录", "进出口查询",
            # English fragments
            "find buyers", "import data", "export data", "trade data",
        ],
        "aliases": [],
        "input_fmt": "产品HS编码 或 产品名称 + 目标市场（国家/地区）",
        "output_fmt": (
            "采购商列表（按进口量排序）+ 供应商列表 + "
            "市场趋势分析 + 价格区间 + 目标客户优先级排序"
        ),
        "augment_prompt": """你是 b2b-customs-data 技能。当用户需要分析海关进出口数据、找采购商、做市场调研或竞品分析时，请执行以下步骤：

1. 加载 skill: b2b-customs-data
2. 确认输入：
   - 有数据文件（CSV/Excel）：读取并分析
   - 无数据文件：从用户提供的产品/市场信息给出分析方法论
3. 分析维度：
   - 采购商分析：按进口量排序，找出TOP10买家，分析购买频率和价格敏感度
   - 供应商分析：按出口量排序，分析主要竞争者市场份额
   - 市场趋势：近N个月进口量变化，判断是增长还是萎缩
   - 价格区间：该产品的CIF/FOB价格分布
   - 目标客户优先级：A级（高频率大批量）/ B级（稳定中等）/ C级（低频小量）
4. 返回：
   - 采购商表格：公司名 | 国家 | 进口量 | 频率 | 价格敏感度 | 推荐等级
   - 市场洞察：3个关键发现
   - 具体行动：如何接触A类客户 + 差异化话术建议""",
    },
    {
        "name": "b2b-onboarding",
        "triggers": [
            # Chinese
            "新公司", "部署", "全套方案", "公司介绍", "产品介绍",
            "营销方案", "营销定位", "市场定位", "竞争对手分析",
            "开始使用", "首次设置",
            # English
            "new company", "deploy", "setup", "marketing plan",
            "company profile", "product introduction", "marketing positioning",
            "competitor analysis", "first time setup",
            # Fragments
            "怎么开始", "新手上路", "第一步做什么", "我需要准备什么",
        ],
        "aliases": [],
        "input_fmt": "公司名称 + 产品/服务 + 目标市场 + 竞争优势（简述）",
        "output_fmt": (
            "完整营销部署方案：公司简介 + 产品介绍 + 目标客户画像 "
            "+ 竞争对手分析 + 营销策略 + 内容计划 + 平台入驻建议"
        ),
        "augment_prompt": """你是 b2b-onboarding 技能。当用户是第一次使用本系统，或者要求新公司部署、全套营销方案时，请执行以下步骤：

1. 加载 skill: b2b-onboarding
2. 引导用户提供基本信息（按顺序询问，一次1-2个）：
   - 公司名称和成立时间
   - 主要产品/服务（最好提供产品资料文件）
   - 目标市场（哪些国家/地区）
   - 核心竞争优势（价格/质量/交期/服务）
   - 现有营销渠道（平台/展会/Direct）
3. 生成完整部署方案：
   - 公司介绍文档（.md → 可导出 DOCX）
   - 产品介绍文档（按产品线分类，含规格参数）
   - 目标客户画像（3个典型客户类型）
   - 竞争对手分析（列出3-5个主要竞争者及对比）
   - 营销策略：渠道优先级、内容主题、发布时间表
   - 平台入驻建议：哪些平台最适合该行业和产品
4. 返回：
   - 完整部署文档路径
   - 接下来7天行动计划（每天做什么）
   - 30天里程碑""",
    },
    {
        "name": "b2b-daily-automation",
        "triggers": [
            # Chinese
            "每日任务", "自动化", "定时任务", "定时发布", "Cron",
            "早安简报", "工作总结", "晚间总结", "周报", "日报",
            "定时提醒", "自动发送",
            # English
            "daily tasks", "automation", "scheduled tasks", "scheduled posting",
            "morning brief", "daily summary", "weekly report", "daily report",
            "cron job", "recurring task", "automated workflow",
            # Fragments
            "每天自动", "自动发内容", "定时发", "每天发什么",
            "早报", "晚报", "自动生成报告",
        ],
        "aliases": [],
        "input_fmt": "任务类型（早报/晚报/定时发布/周报）+ 发送频率 + 目标平台",
        "output_fmt": (
            "Cron 任务配置 + 任务执行脚本内容 + "
            "触发时间（UTC）+ 预期输出描述"
        ),
        "augment_prompt": """你是 b2b-daily-automation 技能。当用户需要设置每日自动化任务（如早安简报、定时发布、周报自动生成）时，请执行以下步骤：

1. 加载 skill: b2b-daily-automation
2. 确认任务需求：
   - 早安简报：当日汇率 + 天气 + 目标市场动态 + 今日待办
   - 定时发布：指定平台（LinkedIn/FB/Ins）+ 发布时间
   - 晚间总结：今日新询盘/客户互动/订单进度
   - 周报：本周数据汇总 + 下周行动计划
3. 使用 cronjob 工具创建任务：
   - 指定 schedule（如 "0 8 * * *" 对应每天UTC 8点）
   - 指定 skills（如 b2b-linkedin-marketing 用于内容发布）
   - 指定 deliver 目标（当前对话 origin 或指定平台）
4. 返回：
   - 已创建的任务 ID
   - 下次执行时间（换算为用户本地时间）
   - 任务内容描述
   - 如何修改/暂停/删除""",
    },
    {
        "name": "b2b-customer-mgmt",
        "triggers": [
            # Chinese
            "客户管理", "客户档案", "客户分级", "大客户", "客户分类",
            "客户等级", "VIP客户", "客户信息", "客户资料",
            "订单管理", "跟单", "订单状态", "发货",
            # English
            "customer management", "customer profile", "customer classification",
            "key account", "account management", "vip customer",
            "order tracking", "order status", "shipment tracking",
            # Fragments
            "客户列表", "所有客户", "新客户", "大客户维护",
        ],
        "aliases": ["b2b-lead-generation"],
        "input_fmt": "客户名称 或 操作类型（查看列表/更新状态/查看详情）",
        "output_fmt": (
            "客户档案（含分级/阶段）+ 跟进记录 + "
            "报价单列表 + 订单状态 + 下一步行动建议"
        ),
        "augment_prompt": """你是 b2b-customer-mgmt 技能。当用户需要管理客户档案、查看客户列表、跟踪订单或进行客户分级时，请执行以下步骤：

1. 加载 skill: b2b-customer-mgmt
2. 根据操作类型执行：
   - 查看客户列表：调用 customer.list_by_company(company_id)，
     按 A/B/C 分级展示，标注每个客户的最新跟进时间
   - 客户详情：调用 customer.get(customer_id, company_id=company_id)，
     显示档案完整信息 + 关联报价单 + 订单历史
   - 客户分级：根据年交易额/订单频率/利润贡献重新分类
   - 订单跟踪：从对话中提取订单号，查询状态更新
3. 返回格式：
   - 客户列表表格：名称 | 分级 | 国家 | 最近跟进 | 当前阶段 | 待办事项
   - 客户详情卡片：联系信息 + 交易历史 + 跟进记录时间线
   - 下一步行动建议（基于客户当前阶段）""",
    },
    {
        "name": "b2b-data-directory",
        "triggers": [
            # Chinese
            "数据目录", "公司档案", "产品目录", "客户目录",
            "初始化", "数据结构", "trade目录", "数据初始化",
            # English
            "data directory", "company profile", "product catalog",
            "customer directory", "initialization", "data structure",
            # Fragments
            "我的公司", "公司信息", "产品列表", "客户数据存在哪",
        ],
        "aliases": [],
        "input_fmt": "公司slug（可选）+ 操作类型（初始化/查看/更新）",
        "output_fmt": (
            "数据目录结构说明 + 各文件用途描述 "
            "+ 最近更新的文件列表 + 存储路径"
        ),
        "augment_prompt": """你是 b2b-data-directory 技能。当用户需要了解或初始化 ~/.trade/ 数据目录结构时，请执行以下步骤：

1. 加载 skill: b2b-data-directory
2. 根据请求类型执行：
   - 查看结构：描述 ~/.trade/companies/{slug}/ 下的完整文件树
     及其用途（company-profile.md / products.md / ...）
   - 初始化数据：使用 .trade-template/ 模板创建公司数据目录
   - 更新文件：读取现有文件 → 修改 → 写回（保留原有数据）
3. 目录结构说明：
   ~/.trade/
   └── companies/{company-slug}/
       ├── company-profile.md    # 公司介绍
       ├── products.md           # 产品目录（含优势）
       ├── business-scope.md     # 业务范围 + 目标市场
       ├── agent-identity.md     # AI Agent 身份定义
       ├── competitors.md        # 竞争对手分析
       ├── certifications.md     # 证书与合规
       ├── marketing-strategy.md # 营销策略
       ├── sales-playbook.md     # 销售话术 + 异议处理
       ├── libraries/{lib-slug}/ # 文档库（按产品线）
       │   ├── index.md
       │   ├── changelog.md
       │   └── metadata.md
       └── clients/{client-slug}/ # 客户档案
4. 返回：目录树 + 最近更新的文件 + 存储路径""",
    },
    {
        "name": "chat-memory",
        "triggers": ["之前", "上次", "以前", "那天", "上周", "历史", "记录", "对话", "说过", "聊过", "讨论过",
                     "还记得", "记不记得", "回忆", "翻看", "回去看", "过去", "往事", "旧", "曾经",
                     "上次聊天", "上次对话", "之前提到", "之前说过", "历史记录", "历史对话",
                     "聊天记录", "对话记录", "聊天历史", "帮我找", "查一下之前", "帮我查", "看到过"],
        "aliases": ["memory", "记忆", "历史对话", "聊天记忆", "会话历史"],
        "input_fmt": "用户的查询意图（查询历史/时间范围）",
        "output_fmt": "历史对话列表（带时间戳）",
        "augment_prompt": """你是 chat-memory 技能。当用户需要查询历史对话时，主动调用 chat_memory_list 工具。
适用场景：用户提到"之前""上次""以前""那天""上周"等时间词；询问过去讨论过的内容；需要了解用户的长期偏好。
调用方式：chat_memory_list(time_range="all", limit=20)
结果格式：[{created_at, query, response}, ...]""",
    },
    {
        "name": "b2b-skill-generator",
        "triggers": [
            # Chinese
            "生成skill", "创建skill", "新建技能", "做个skill", "写个skill",
            "生成技能", "新增技能", "创建一个skill",
            # English
            "create skill", "generate skill", "new skill",
        ],
        "aliases": [],
        "input_fmt": "描述你需要什么功能（例如：'帮我做一个海关数据分析的skill'）",
        "output_fmt": "自动生成符合规范的 SKILL.md + 注册到 skill_registry.py + 重启服务生效",
        "augment_prompt": "",
    },
    {
        "name": "b2b-trade-ops",
        "triggers": [
            # Chinese — 催款/催付
            "催款", "催货款", "催尾款", "付款逾期", "催一下付款",
            "要货款", "客户还没付款", "催账", "讨债",
            # Chinese — 索赔
            "索赔", "投诉", "质量投诉", "货有问题", "客户投诉",
            "退货", "退款", "理赔", "赔偿",
            # Chinese — 展会
            "展会邀请", "邀请函", "广交会", "展会邀约", "参展",
            "邀请客户来展会",
            # Chinese — 验厂
            "验厂", "客户要来工厂", "验厂邀请", "工厂审核", "audit",
            "来厂考察",
            # Chinese — 节日
            "节日问候", "节日祝福", "发个祝福", "过节",
            # Chinese — 样品
            "寄样", "样品寄送", "样品跟进", "寄样品", "样品到了吗",
            # Chinese — 物流
            "物流", "货运", "船期", "延迟", "航线变更", "tracking",
            "货到哪了", "查一下货",
            # Chinese — 售后/满意度/年度
            "售后", "收货跟进", "满意度调查", "客户反馈",
            "年度总结", "年终", "合作回顾", "年度合作",
            # English
            "payment reminder", "overdue", "chase payment",
            "claim", "complaint", "refund", "compensation",
            "exhibition", "trade fair", "invitation",
            "factory audit", "factory visit", "plant tour",
            "holiday greeting", "season's greetings",
            "sample shipping", "sample tracking",
            "logistics", "shipping delay", "shipment update",
            "after-sales", "satisfaction survey", "annual review",
        ],
        "aliases": ["b2b-customer-mgmt"],
        "input_fmt": "场景类型 + 客户名称 + 具体信息（发票号/订单号/展会名等）",
        "output_fmt": (
            "按场景输出专业化邮件/通知：催款（含折中方案）/ 索赔回复 / "
            "展会邀请 / 验厂议程 / 节日问候 / 样品跟进 / 物流更新 / "
            "售后回访 / 满意度调查 / 年度数据总结"
        ),
        "augment_prompt": """你是 b2b-trade-ops 技能。覆盖外贸「成交之后」的所有运营沟通：

**11 个场景**：
1. 催款邮件 — 先问「是否有问题」再提付款
2. 索赔处理 — 先道歉安抚再谈责任，必要时建议第三方检测
3. 展会邀请 — 展位号+时间+客户能带走什么
4. 验厂邀请 — 工厂地址+接待人+议程
5. 节日问候 — 先确认客户真的过那个节，避开文化禁忌
6. 样品寄送 — 追踪号+ETA+使用说明
7. 二次催付 — 提供折中方案（分笔/延期/部分发货）
8. 物流异常 — 主动提供查询链接+代理电话
9. 售后维护 — 第7天主动问安装使用情况
10. 满意度调查 — ≤5个选择题，承诺改进
11. 年度合作总结 — 用数据说话（订单数/金额/准点率）

**核心规则**：
- 输出前对照 SKILL.md 文末 Quality Gate Checklist 逐项自检
- 永远用客户的语言回复，默认英语
- 永远专业、有温度、不卑不亢""",
    },
    {
        "name": "b2b-trade-compliance",
        "triggers": [
            # Chinese — 文化禁忌
            "文化禁忌", "忌讳", "这个客户那里忌讳什么", "颜色禁忌",
            "数字禁忌", "手势禁忌", "送礼禁忌", "送礼注意",
            # Chinese — 缩写
            "缩写", "全称", "ETA", "ETD", "LC", "BL", "DP", "DA",
            "外贸术语", "贸易术语缩写",
            # Chinese — Incoterms
            "Incoterms", "ICC", "贸易术语", "FOB", "CIF", "EXW",
            "DDP", "DAP", "FCA", "CFR", "CPT", "CIP",
            "贸易术语检查",
            # Chinese — 翻译
            "翻译二审", "母语审阅", "翻译检查", "翻译对不对",
            "这个翻译对吗", "阿拉伯语翻译", "西班牙语翻译",
            # Chinese — 投标
            "投标", "招标", "标书", "bid",
            # Chinese — 电商上架
            "Amazon上架", "违禁词", "亚马逊合规", "跨境电商上架",
            "上架检查", "listing检查",
            # English
            "cultural taboo", "cultural check", "color taboo",
            "number taboo", "gesture taboo",
            "incoterms", "trade terms", "FOB CIF EXW",
            "abbreviation", "full form", "acronym",
            "translation review", "native speaker review",
            "tender", "bidding", "RFP",
            "Amazon listing", "prohibited word", "compliance check",
        ],
        "aliases": [],
        "input_fmt": "检查内容类型 + 目标市场/客户地区 + 需要检查的文本/文档",
        "output_fmt": (
            "逐条标注问题 + 修正建议：文化禁忌（颜色/数字/动物/手势/送礼）/ "
            "缩写首次使用全称标注 / Incoterms 2020 格式检查 / "
            "翻译二审提醒 / 投标逐条响应检查 / 电商违禁词+合规检查"
        ),
        "augment_prompt": """你是 b2b-trade-compliance 技能。用于**检查已有内容**的合规性和专业规范性：

**6 大检查维度**：
1. 文化禁忌 — 颜色/数字/动物/手势/送礼（按目标市场对照速查表）
2. 缩写解释 — 所有外贸缩写（ETA/LC/BL/DP等）首次出现必须给全称
3. ICC 术语校验 — 每个术语必须有 Incoterms 2020 + 具体地点
4. 翻译二审 — 非英语/非母语内容建议找人审阅（提醒话术）
5. 投标招标 — 逐条响应标书格式，不多不少，证书有效期检查
6. 电商上架 — 目标市场违禁词、认证要求、属性筛选检查

**执行方式**：
- 接收要检查的内容 + 目标市场信息
- 逐项检查，在发现问题的位置标注具体建议
- 对照 SKILL.md 文末 Quality Gate Checklist 确保无遗漏
- 不确定的项目标注「建议人工确认」而非强行判断""",
    },
    {
        "name": "b2b-cold-outreach",
        "triggers": [
            # Chinese
            "开发信", "产品推广信", "推广邮件", "跟进信", "写一封开发信",
            "产品推广", "写推广邮件", "写跟进邮件",
            # English
            "cold email", "development letter", "promotion letter",
            "follow-up email", "product promotion", "outreach",
        ],
        "aliases": [],
        "input_fmt": "目标市场/国家 + 产品类型 + 客户类型（可选）+ 具体产品信息（可选）",
        "output_fmt": "个性化 B2B 邮件（开发信/推广信/跟进信），含 3-5 个主题行变体 + 语言匹配",
        "augment_prompt": """你是 b2b-cold-outreach 技能。用于**撰写 B2B 冷 outreach 邮件**（产品推广信、开发信、跟进信），基于公司产品数据和历史报价，结合目标市场情报生成个性化邮件。

**核心能力**：
1. 从文档库提取产品数据和历史报价
2. 生成三种邮件模板（开发信/推广信/跟进信）
3. 语言匹配（按目标市场自动选语言）
4. 反营销腔自检 + 反垃圾邮件规则
5. 常见电力金具产品参数速查

**邮件结构**：
- 开发信：Intro → 产品 → 优势 → 社会证明 → CTA
- 推广信：上下文 → 产品详情 → 价值主张 → 优惠 → CTA
- 跟进信：引用上次联系 → 新信息 → 软 CTA

**语言策略**：
- 欧美/澳洲/东南亚/中东 → 英语
- 拉美 → 西班牙语/葡萄牙语
- 越南/泰国 → 英语（B2B 首选）

**铁律**：
- 第一句讲客户，不讲自己
- 60% 讲痛点 + 25% 硬实力 + 15% CTA
- 必须包含具体型号/标准/数据
- 生成 A/B 两个正文变体
- 提供 3-5 个主题行变体
- 不编造数据，不知道的就省略
- 一份邮件一种语言，不混用

**Anti-Spam 语义规避（防 AI 腔指纹，强制）**：
- 禁 AI 腔开头（"Hope this email finds you well" / "Dear Sir/Madam"）与学术过渡词（Furthermore / Moreover / In addition / It is worth noting / Therefore）
- 禁词给替换：cheap/best price → cost-effective/competitive margin；free sample → complimentary evaluation
- Subject 4-6 词、无感叹号/全大写/销售腔，可伪装同行探讨（"Question about {客户公司名}'s packaging supply"）
- 短句为主、长短交错、主动语态，像 native 商务人士手写
- CTA 禁止直接约会议（30-min call），用回复式低摩擦引导
- 批量多封时每封角度/句式要不同，防内容哈希识别群发模板
""",
    },
    {
        "name": "auto-trade-customer-development",
        "triggers": [
            # Chinese
            "全自动客户开发", "一键开发客户", "端到端客户开发",
            "客户开发流水线", "自动开发客户", "全流程客户开发",
            "编排客户开发", "一条龙开发客户", "帮我跑一轮客户开发",
            "跑一批客户", "全自动开发", "全自动化客户开发",
            # English
            "auto customer development", "end to end lead generation",
            "full pipeline outreach", "automated outreach pipeline",
            "orchestrated lead gen",
        ],
        "aliases": ["b2b-lead-generation", "b2b-osint", "auto-smtp-email"],
        "input_fmt": (
            "产品描述 + 目标市场 + 目标客户类型 + 期望数量（可选）+ "
            "是否启用自动发送（默认否）"
        ),
        "output_fmt": (
            "7 阶段流水线报告：搜索 → 背调 → 评分 → 写信 → 发送 → 入库 → 日志。"
            "输出含阶段统计 / TOP10 客户详情 / 下一步跟进建议 / 完整日志路径"
        ),
        "augment_prompt": """你是 auto-trade-customer-development 技能 — 外贸客户开发端到端编排器。

**7 阶段流水线**：
1. 搜索 — 调用 b2b-lead-generation 三通道并行（Google Maps + Google Search + FB/LinkedIn）
2. 背调 — 对每家候选调用 b2b-osint 6 层验证 + 关键联系人富化
3. 评分 — 按公司匹配度/决策人可达性/数字足迹/风险/渠道多元性打分排序 A/B/C
4. 写信 — 对 A/B 级调用 b2b-lead-generation 生成开发信（含替换法 A/B 测试 + 反垃圾自检）
5. 发送 — 用户确认后调用 auto-smtp-email（默认不自动发送，需用户确认）
6. 入库 — 调用 trade.customer.bulk_save 写入 SQLite（source="auto-pipeline"）
7. 日志 — 写入 ~/.trade/audit/auto-pipeline-{date}.md

**铁律**：
- Phase 5 发送前必须用户明确确认，不能自动发
- 单次最多 50 家候选
- 单个客户背调失败不阻断流水线
- 每个 Phase 完成后输出进度
- 完整日志必须可追溯

详细执行规则见 skills/auto-trade-customer-development/SKILL.md。""",
    },
    {
        "name": "auto-smtp-email",
        "triggers": [
            # Chinese
            "发邮件", "发送邮件", "SMTP发送", "SMTP 发送",
            "发开发信", "群发邮件", "批量发送", "预览后发送",
            "帮我发", "发出去", "邮件发出去",
            # English
            "send email", "smtp send", "send cold email",
            "bulk send", "mail out", "dispatch email",
        ],
        "aliases": [],
        "input_fmt": (
            "收件人邮箱 + 主题 + 正文（纯文本/HTML）+ 抄送（可选）+ "
            "附件路径（可选）。批量发送时为列表。"
        ),
        "output_fmt": (
            "预览 → 用户确认 → 发送结果（成功/失败 + 错误详情）。"
            "批量发送含每封状态 + 限速日志 + 汇总统计"
        ),
        "augment_prompt": """你是 auto-smtp-email 技能 — SMTP 邮件实际发送。

**铁律：预览后发送**
1. 先生成完整预览（收件人/主题/正文/附件）给用户
2. 用户明确回复"确认发送/发吧/OK"后才能调用 SMTP
3. 任何模糊回复（如"嗯""好"）必须二次确认

**凭证读取**：从 ~/.hermes/.env 读 SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS。
- 缺字段时明确告诉用户去哪个邮箱后台生成授权码
- Gmail: https://myaccount.google.com/apppasswords
- 163: 邮箱设置 → POP3/SMTP/IMAP → 开启 SMTP → 生成授权码
- 腾讯企业邮箱: 邮箱设置 → 客户端专用密码

**发送流程**：
1. 单封：smtplib.SMTP_SSL（465）或 SMTP+starttls（587）
2. 批量：每封间隔 60-120 秒随机（避免被标记群发）
3. 失败容错：单封失败不阻断后续，记录到 send_log
4. 日志：写入 ~/.trade/audit/smtp-send-log-{date}.md

**HTML 规则**：
- 必须 multipart/alternative（纯文本+HTML 双版本）
- 内联 CSS，禁用 JavaScript/iframe/外部图片追踪
- 字体 web-safe，字号 ≥14px，移动端单列布局

**反垃圾自检**（发送前强制）：
- 主题行不含 SPAM 触发词（FREE/URGENT/GUARANTEED 等）
- 主题不全大写、无过多感叹号
- 正文大写单词 ≤1 个
- 图片面积 < 50%
- 包含退订方式
- 附件 < 10MB

详细错误码对照表见 skills/auto-smtp-email/SKILL.md。""",
    },
    # ── b2b-email-imitation: 开发信仿写与再创作（P0）───────────────────
    {
        "name": "b2b-email-imitation",
        "triggers": [
            # Chinese
            "仿写开发信", "模仿邮件", "学写开发信", "参考邮件写",
            "仿照这封", "按这个风格写", "邮件仿写", "开发信再创作",
            "优化这封邮件", "改进开发信", "抄作业", "借鉴这封",
            "按照样本", "模仿这个邮件", "根据模板写",
            # English
            "sample email", "email imitation", "rewrite this email",
            "follow this style", "copywriting reference", "email template reference",
            "reference email", "imitate email", "inspired by",
        ],
        "aliases": [],
        "input_fmt": "参考邮件样本（必需）+ 自家产品信息 + 目标客户类型（可选）",
        "output_fmt": "样本结构分析 + 3-5 个主题行变体 + A/B 两个正文版本 + 风格复盘",
        "augment_prompt": "",
    },
    # ── b2b-buyer-persona: 买家画像与角色分层（P0）─────────────────
    {
        "name": "b2b-buyer-persona",
        "triggers": [
            # Chinese
            "买家画像", "客户画像", "角色分析", "人物画像",
            "采购角色", "决策者分析", "客户分层", "买家角色",
            "按角色写", "给采购写", "给工程师写", "给老板写",
            "针对不同角色", "价值主张定制",
            # English
            "buyer persona", "customer analysis", "decision maker analysis",
            "procurement manager", "technical buyer", "stakeholder mapping",
            "role-based email", "tailor message", "customize for role",
        ],
        "aliases": [],
        "input_fmt": "产品信息 + 目标客户类型 + 目标市场/国家 + 客单价（可选）",
        "output_fmt": "3 个决策角色的结构化分析 + 按角色的 FAB 价值主张 + 沟通策略 + 触达路线图",
        "augment_prompt": "",
    },
    # ── b2b-market-analysis: 市场分析作战地图（P1）────────────────
    {
        "name": "b2b-market-analysis",
        "triggers": [
            # Chinese
            "市场分析", "目标市场", "市场调研", "进入市场",
            "作战地图", "出口分析", "国家分析", "区域分析",
            "竞品分析", "市场机会", "市场研究", "出口国分析",
            # English
            "market analysis", "market research", "country analysis",
            "go to market", "target market", "market entry",
            "competitive landscape", "export strategy",
            "market intelligence", "region analysis",
        ],
        "aliases": [],
        "input_fmt": "产品名称/HS 编码 + 目标国家/区域 + 公司类型 + 现有出口经验（可选）",
        "output_fmt": "市场环境分析 + 认证/关税规则 + 关键词武器库 + 3 秒 Hook + 行动路线图",
        "augment_prompt": "",
    },
    # ── b2b-sales-pipeline: 销售管线策略（P0）───────────────────────
    {
        "name": "b2b-sales-pipeline",
        "triggers": [
            # Chinese
            "销售推进", "跟进策略", "销售动作", "跟进计划",
            "客户推进", "销售流程", "推进客户", "销售管线",
            "客户跟进", "催单", "催进展", "怎么跟进",
            "下一步怎么办", "客户不动了", "跟进模板",
            # English
            "sales pipeline", "deal progress", "follow-up plan",
            "sales process", "customer advancement", "sales sequence",
            "next steps", "move the deal", "follow-up timeline",
            "30-day plan", "deal velocity", "sales cadence",
            "outreach sequence",
        ],
        "aliases": [],
        "input_fmt": "客户当前状态（已发开发信/已寄样/在谈价格等），或产品信息+目标客户类型，或客户名单+各客户状态",
        "output_fmt": "5 阶段客户旅程映射 + 阶段动作模板 + 30 天跟进时间表 + KPI 目标 + 客户分层策略 + 管线健康度",
        "augment_prompt": "",
    },
    # ── b2b-inquiry-training: 询盘回复与 Top Sales 训练 ──────────
    {
        "name": "b2b-inquiry-training",
        "triggers": [
            # Chinese
            "询盘训练", "回复练习", "模拟买家", "询盘回复",
            "训练回复", "练询盘", "模拟客户", "反对意见",
            "客户刁难", "谈判练习", "话术训练", "销售人员训练",
            "回复优化", "询盘模拟", "不匹配询盘",
            # English
            "inquiry training", "practice reply", "role play buyer",
            "objection handling", "sales training", "improve reply",
        ],
        "aliases": [],
        "input_fmt": "目标买家场景（国家/类型/关注点），或一封真实询盘，或一个具体反对意见",
        "output_fmt": "客户画像 + 第一稿回复 + 买家视角分析 + 优化版回复 + 最终评分",
        "augment_prompt": "",
    },
    # ── b2b-kol-imitation: LinkedIn KOL 风格模仿（P1）────────────────
    {
        "name": "b2b-kol-imitation",
        "triggers": [
            "模仿风格", "学大V", "学意见领袖", "大V风格",
            "KOL分析", "分析这个号", "模仿这个账号",
            "kol imitation", "follow style", "imitate influencer",
            "learn from this profile", "copy writing style",
        ],
        "aliases": ["b2b-linkedin-marketing"],
        "input_fmt": "KOL 的 LinkedIn/社媒账号链接或 3-5 篇代表性帖子 + 自家公司/产品信息",
        "output_fmt": "KOL 风格分析报告 + 3 条适配帖子",
        "augment_prompt": "",
    },
    # ── b2b-reddit-engagement: Reddit 社区互动（P1）────────────────
    {
        "name": "b2b-reddit-engagement",
        "triggers": [
            "Reddit", "红迪", "社区评论", "写Reddit评论",
            "发Reddit帖子", "专业评论", "行业讨论",
            "reddit post", "reddit comment", "community engagement",
        ],
        "aliases": ["b2b-social-media"],
        "input_fmt": "产品/行业描述 + 目标帖子链接或话题方向",
        "output_fmt": "推荐 subreddit 列表 + 评论/帖子草稿",
        "augment_prompt": "",
    },
    # ── b2b-seo-aeo: SEO+AEO 文章生成（P1）────────────────────────
    {
        "name": "b2b-seo-aeo",
        "triggers": [
            "SEO文章", "AEO文章", "搜索引擎优化", "AI搜索优化",
            "写文章", "博客文章", "行业文章", "关键词文章",
            "seo article", "aeo article", "blog post", "seo writing",
        ],
        "aliases": [],
        "input_fmt": "行业/产品描述 + 目标关键词 + 文章类型",
        "output_fmt": "SEO+AEO 优化的完整文章（含元数据/FAQ）",
        "augment_prompt": "",
    },
    # ── b2b-short-video: 短视频脚本（P2）───────────────────────────
    {
        "name": "b2b-short-video",
        "triggers": [
            "短视频", "视频脚本", "TikTok脚本", "Reels",
            "视频文案", "拍摄脚本", "产品视频", "工厂视频",
            "short video", "tiktok script", "youtube shorts",
            "video script", "b2b video",
        ],
        "aliases": ["b2b-social-media"],
        "input_fmt": "产品名称 + 目标市场 + 视频主题 + 目标平台",
        "output_fmt": "分镜脚本（时间/画面/配音/字幕）+ 拍摄建议",
        "augment_prompt": "",
    },
    # ── b2b-exhibition: 展会全流程管理（P2）───────────────────────
    {
        "name": "b2b-exhibition",
        "triggers": [
            "展会", "参展", "广交会", "行业展", "展会邀约",
            "展位设计", "展会准备", "展后跟进",
            "trade show", "exhibition", "canton fair",
        ],
        "aliases": ["b2b-trade-ops"],
        "input_fmt": "展会名称/日期/地点 + 参展产品 + 客户列表（可选）",
        "output_fmt": "邀约邮件 + 准备清单 + 展中记录模板 + 展后跟进计划",
        "augment_prompt": "",
    },
    # ── b2b-product-description: 产品描述生成器（P2）──────────────
    {
        "name": "b2b-product-description",
        "triggers": [
            "产品描述", "产品介绍", "产品文案", "Sales Kit",
            "销售资料", "产品卖点", "产品说明", "产品推广",
            "product description", "product copy", "sales kit",
            "value proposition", "product selling points",
        ],
        "aliases": [],
        "input_fmt": "产品名称/规格 + 认证资质 + 目标市场 + 内容类型",
        "output_fmt": "FAB 分析表 + 完整产品描述 + 3 个差异化卖点",
        "augment_prompt": "",
    },
    # ── b2b-six-thinking-hats: 六顶思考帽决策教练（P3）────────────
    {
        "name": "b2b-six-thinking-hats",
        "triggers": [
            "决策分析", "思考帽", "六顶帽", "要不要做",
            "怎么决定", "利弊分析", "选择困难",
            "six thinking hats", "decision making",
            "risk analysis", "business decision",
        ],
        "aliases": [],
        "input_fmt": "需要决策的具体问题（如选供应商/是否参展/付款条件变更等）",
        "output_fmt": "6 顶帽子的逐项分析 + 总结与行动计划",
        "augment_prompt": "",
    },
    # ── b2b-customer-intel: 单一客户深度画像 ──────────────────
    {
        "name": "b2b-customer-intel",
        "triggers": [
            "客户画像", "深度画像", "客户分析", "了解客户",
            "客户情报", "客户档案", "怎么跟这个客户谈",
            "客户偏好", "送礼建议", "回扣怎么给", "记住客户",
            "客户家底", "客户决策风格", "深入了解客户",
            "customer intel", "customer profile", "know your customer",
            "deep profile", "buyer intelligence",
        ],
        "aliases": ["b2b-customer-mgmt", "b2b-buyer-persona"],
        "input_fmt": "客户的任何已知信息（公司名/LinkedIn/名片/聊天记录/展会记录）",
        "output_fmt": "15 维度结构化深度画像报告",
        "augment_prompt": "",
    },
    # ── b2b-inquiry-meeting: 询盘分析会主持 ──────────────────────
    {
        "name": "b2b-inquiry-meeting",
        "triggers": [
            "开询盘分析会", "准备询盘复盘", "这周询盘拿出来看一下",
            "周五开询盘会", "分析业务员询盘跟进", "逐个点评业务员询盘",
            "复盘客服接待质量", "哪些询盘有问题", "询盘复盘会",
            "销售周会材料", "每周询盘总结",
            "inquiry review meeting", "weekly sales review",
            "sales team meeting",
        ],
        "aliases": ["b2b-inquiry-training", "b2b-lead-generation"],
        "input_fmt": "周期范围（本周/上周/最近N天）+ 询盘数据来源",
        "output_fmt": "询盘总览 + 逐业务员复盘 + 重点询盘逐条分析 + 主持提问清单 + 下周跟进行动表",
        "augment_prompt": "",
    },
    # ── b2b-sales-playbook: 销冠经验封装器 ──────────────────────
    {
        "name": "b2b-sales-playbook",
        "triggers": [
            "销冠经验", "销售知识库", "销售SOP", "话术库",
            "新人培训", "销售技巧", "跟进话术", "谈判话术",
            "异议处理", "逼单技巧", "客户激活", "谈单流程",
            "sales playbook", "sales knowledge base", "sales SOP",
            "objection handling", "sales training",
        ],
        "aliases": ["b2b-inquiry-training", "b2b-lead-generation"],
        "input_fmt": "行业/产品线 + 客户画像 + 具体场景（首回/报价/异议/逼单/激活/售后）",
        "output_fmt": "六大模块知识体系（能力图谱/SOP/话术库/新人路线/避坑清单/钩子武器库）",
        "augment_prompt": "",
    },
    # ── b2b-guarantee-proposal: 商业提案生成器 ──────────────────
    {
        "name": "b2b-guarantee-proposal",
        "triggers": [
            "商业提案", "战略建议书", "商业计划书", "投资回报分析",
            "方案建议书", "客户提案", "保效方案", "ROI分析",
            "增长方案", "市场进入方案", "品牌升级方案",
            "business proposal", "strategic proposal",
            "ROI analysis", "growth plan", "investment proposal",
        ],
        "aliases": ["b2b-market-analysis", "b2b-onboarding"],
        "input_fmt": "客户公司/产品/市场/规模 + 行业白皮书或市场数据 + 预算范围",
        "output_fmt": "三档方案对比表 + 推荐方案说明书 + ROI 分析 + 实施路线图",
        "augment_prompt": "",
    },
    # ── b2b-tech-drawing: 工程图纸分析（P1）──────────────────────
    {
        "name": "b2b-tech-drawing",
        "triggers": [
            "图纸", "工程图", "技术图纸", "铸件图", "机械图", "零件图",
            "GOST", "ASTM", "ISO 图纸", "DIN 标准",
            "图纸报价", "分析图纸", "看看这张图", "帮我读图纸",
            "technical drawing", "engineering drawing", "casting drawing",
            "blueprint", "mechanical drawing",
        ],
        "aliases": ["b2b-document"],
        "input_fmt": "客户发来的工程图纸 PDF 文件",
        "output_fmt": "结构化零件信息（名称/图号/材料/尺寸/公差/技术要求）+ 报价建议",
        "augment_prompt": "",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# 预编译正则（import 时一次性构建，避免每次匹配都编译）
# ─────────────────────────────────────────────────────────────────────────────

# 显示 skill 调用模式："用 b2b-xxx" 或 "load skill b2b-xxx"
_EXPLICIT_RE = re.compile(
    r'(?:用|使用|调用|加载|load?\s*(?:skill)?)\s*b2b-[\w-]+',
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────────────────
# Public query API（仅数据查询，不包含匹配逻辑）
# ─────────────────────────────────────────────────────────────────────────────

def list_skills() -> list[dict]:
    """返回所有注册的 skill 条目（不含 augment_prompt，减少 token）。"""
    return [
        {k: v for k, v in s.items() if k != "augment_prompt"}
        for s in _SKILLS
    ]


def skill_names() -> list[str]:
    """返回所有注册 skill 的名称列表。"""
    return [s["name"] for s in _SKILLS]


def get_skill_by_name(name: str) -> dict | None:
    """按名称查找 skill（用于显式 skill= 参数调用）。"""
    for s in _SKILLS:
        if s["name"] == name:
            return s
    return None
