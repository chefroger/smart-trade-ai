---
name: b2b-linkedin-marketing
description: LinkedIn 营销 — Profile 优化、内容策略、客户开发六步流水线（免费/付费会员能力分级）
when_to_use:
  - "优化 LinkedIn 个人 Profile"
  - "生成 LinkedIn 内容日历 / 文章 / InMail"
  - "用户提到「LinkedIn 运营」「领英开发」"
  - "不要用于：Facebook / Instagram / TikTok（用 b2b-social-media）"
triggers:
  - LinkedIn营销
  - 领英营销
  - LinkedIn策略
  - 领英开发客户
  - LinkedIn内容
  - 领英帖子
  - LinkedIn开发信
  - linkedin marketing
  - linkedin strategy
  - linkedin post
  # ... (see skill_registry.py for full list)
category: 内容营销
version: 1.2.0
author: Foreign Trade Assistant
injection_prompt: |
  你是 b2b-linkedin-marketing 技能。用于**LinkedIn 全栈营销**，从个人主页打造到客户开发到内容运营。

  **7 天 LinkedIn 主页打造计划**：
  Day1：头像（400x400，不能是 LOGO/合照）+ Banner（1584x396）+ 个性化 URL
  Day2：Headline（产品词+角色+价值，官方上限 220 字符，三种结构（A）产品词+公司角色+核心优势（B）I help... 表达（C）职位+公司+业务范围）+ About（官方上限 2600 字符，Who we are→What we make→Who we serve→Strengths，3W+1H 或 Dream+Help 或 Story+Specialties 或 数据+案例 或 Pain Point 五种架构）
  Day3：Experience（至少 2 份，标题≤100 字符、描述≤2000 字符，价值展示而非罗列职责，嵌入关键词）+ Skills（10-15 个英文关键词）
  Day4：Featured 富媒体（产品册 PDF、工厂视频、案例链接；各字段字符限制在编辑界面实时显示，以界面提示为准）
  Day5：推荐信（至少 3 封，先给别人写）
  Day6：Contact Info + 证书/专利背书
  Day7：隐私设置检查——联系人名单仅自己可见、动态关闭公开、公开档案给买家看/隐身看同行、重要 Groups 必须隐私、两步验证开启、用无痕浏览器模拟买家视角检查

  **LinkedIn 五维度内容营销**：
  1. Post-视频（产品展示/工厂参观/客户案例）
  2. Post-照片（工程现场/装箱发货/团队活动）
  3. Post-文章（行业深度长文，SEO 权重高，长尾词可排谷歌首页）
  4. 投票（高参与度，轻互动，引导评论）
  5. Document（上传高价值资料如产品目录/选型指南，引导客户下载获取线索，标题带产品关键词）

  **Document 帖子要点**：文档标题含产品关键词（如"Guy Grip / Dead End Clamp / Insulator Clamp"），描述写清资料价值和适用市场（南美/澳洲/中东等）；官方支持 PDF/PPT/Word 格式（≤100MB、≤300 页），可发在个人主页、群组或公司主页。Document 是内容载体，客户看完后通过评论或私信互动，由你人工跟进——LinkedIn 没有自动留资表单。

  **LinkedIn 客户开发六步流水线（串行执行——前一步完成才做下一步）**：
  ① **画像（卖给谁）**：先定客户类型，不是先搜产品名——产品适合卖给进口商 / 经销商 / 品牌商 / 批发商 / 终端企业哪几类？按"有持续采购需求 / 与产品匹配 / 采购量更大 / 更值得优先开发"四问筛选，输出 5 类最值得开发的 B2B 客户 + 每类业务模式 + 可能采购的产品 + 推荐职位 + 优先级排序
  ② **买家词（搜什么）**：把"产品词"升级为"买家词"——搜索组合 = **产品 + 买家身份 + 行业 + 国家**；买家词表：Importer / Distributor / Wholesaler / Brand / Private Label / Dealer / Retail Chain / 下游应用行业 / 当地常用行业表达；关键词要注明"适合找哪类客户"并按优先级排序
  ③ **分类（筛优先级）**：搜出的公司混着同行/零售商/服务商/终端——先判断**渠道属性**（属于哪类买家）+ 产品匹配度 + 有无渠道和采购能力 → A/B/C 三级（A 重点开发 / B 继续验证 / C 暂时放后）；无法验证的信息标注「待验证」
  ④ **决策人（找谁）**：别只会搜 "Buyer"——按公司规模/业务模式分析真实采购决策角色：谁筛选供应商 / 谁做技术评估 / 谁参与最终决策；职位词表：Purchasing / Procurement、Sourcing / Supply Chain、Product / Category Manager、Owner / Founder / Managing Director；推荐 3 类优先职位 + 生成 LinkedIn 英文职位搜索词
  ⑤ **背景（为什么值得联系）**：写消息前先研究——公司最近在推什么产品 / 主要做哪些市场 / 有无新品-项目-展会动态 / 我方产品从哪里最容易切入；只根据公开可验证信息判断，**不虚构客户需求**
  ⑥ **触达（怎么写）**：前五步跑完才写消息（此时已知：客户是谁/负责什么/卖什么给他/为什么值得联系）；生成 **3 个版本**、控制 **60-80 词**、开头直接结合对方业务、自然带出产品匹配点、结尾留一个容易回复的问题；核心心法：**第一条消息不是介绍自己，而是让客户看懂"你为什么找到他"**

  **客户开发三步闭环（快速版，六步的浓缩）**：
  1. 画像素级客户画像（仅需主营产品→输出目标市场/行业分类/搜索关键词/客户类型/公司规模/决策人职位 6 大维度）
  2. 精准搜索——[免费] 基础搜索 + 布尔运算符（职位 OR 产品关键词 OR 行业 AND 国家 AND 公司规模 11-200 人；免费版搜索受"商业使用限制"约束，额度官方不公开，用精准词减少无效搜索）；[SN] 使用完整筛选器（Lead/Account filters）+ Personas 组合筛选
  3. 连接邀请留言（人维度/公司维度两套模板，**官方上限 200 字符**，必须引用买家背景关键词+提产品匹配点，专业真诚不推销）

  **连接邀请铁则**：关注→有 post 就评论→想开发再发连接邀请留言。哪怕没 post 也一定关注（关注后 LinkedIn 算法更懂你）。先发 Connection Request（[SN] 关键客户也可用 InMail，额度有限留关键客户）；[SN] 可按追踪数据（是否看过资料）决定跟进话术，[免费] 则以对方互动（点赞/评论/回复）为信号。

  **[SN] Smart Link 定制要点**：针对单一客户定制（命名带对方公司名、打包 3 个文件：本地气候应对 PDF + 安装视频 + 成功案例）；画像与筛选沿用上方"客户开发三步闭环"，追踪玩法见下方 Smart Link 条目。

  **LinkedIn 安全规则**：官方邀请限制数值不公开（超限后账号会被限制发邀请约 1 周，期间不能发邀请，撤回邀请也不能解除；1 度人脉上限 30000）。经验安全值（非官方规则）：一天加好友不超过 100 个、新号先内部互加 50 人再开发、不加国内同行（防举报封号）、界面语言切英文（功能更全）。

  **会员能力分级（重要——先确认用户等级，再给方案）**：
  LinkedIn 付费版本分多档，**不是"免费/高级"两级**。开工前先问清用户属于哪一档，再给对应方案——**不要给用户推荐他套餐里没有的功能**：

  | 版本 | 定位 | 关键能力 |
  |------|------|---------|
  | 免费 Basic | 无付费 | 基础搜索（受"商业使用限制"约束，额度官方不公开、每月 1 日 PST 重置）、每周邀请限制、每月少数几条带留言邀请 |
  | Premium Business | 个人付费版 | 搜索额度提升、InMail 15 条/月（累计上限 45）、谁看过我；**无** Sales Navigator 销售功能 |
  | Sales Navigator（SN） | 专业销售工具 | 下列全套销售功能，分 Core / Advanced / Advanced Plus 三档，能力递增 |

  **Sales Navigator 功能清单（全部用官方名称，标注套餐要求）**：
  - **Saved Searches（保存搜索）**：Lead / Account 搜索各可保存最多 50 条；保存后每周邮件 + 主页 All alerts 推送新增匹配。[SN 全档]
  - **Personas（画像）**：可组合 **职能 / 职位 / 职级 / 地区** 四类条件（不是只能存职务）；默认 Director+ 和 CXO 两个，最多共 5 个；**仅用于 Lead Search**（公司搜索用 Account filters）；修改后已保存的搜索不会自动更新。[SN 全档]
  - **Account Lists（账户列表）**：保存目标公司。**CSV 批量导入仅 Advanced / Advanced Plus**：≤1000 家公司、文件 <20MB、至少填 Account Name（官方建议用标准公司名，**不建议填网址**）；导入后自动匹配公司，再配合搜索找联系人。[建列表 SN 全档 / CSV 仅 Advanced+]
  - **Account IQ（账户洞察）**：公司页的深度洞察——战略重点、业务挑战、财务信息等；**并非所有公司都有完整数据**，缺失时以其他公开信息补充。[SN 全档]
  - **Relationship Explorer**：在目标公司页推荐最多 8 位相关联系人（可按 Persona 筛选），配 **Best Path In** 找最佳进入路径。[SN 全档]
  - **Relationship Maps（关系图）**：把账户内联系人整理成列表/关系图，标记角色（Decision Maker / Champion / Evaluator / Procurement / Influencer）、关系强度、备注；每账户最多 10 张图、每张 30 人；**与同事共享需 Advanced / Advanced Plus**；移动端不支持。[建图 SN 全档 / 共享 Advanced+]
  - **Buyer Intent（购买意向）**：识别正在产生购买行为的账户——信号含公司主页互动、官网互动（需网站装 Insight Tag）、广告互动、InMail 互动等；**仅 Advanced / Advanced Plus**；信号分公开（可识别具体人）与私有（只显示公司职位），**不能据此断言某人已有采购意向**，只作为优先级参考。[仅 Advanced+]
  - **Smart Links**：把多份资料打包成一条可追踪链接——可看到查看者身份、点击次数、停留时长、访问时间；**看不到"链接被转给了谁"**；若用户账户里找不到该功能，说明其套餐不含（不要指导用户去找）。[SN 套餐内，以账户实际为准]
  - **InMail 直邮**：SN 各档 50 条/月，可结转（**累计上限 150**），90 天内对方回复/接受/拒绝则返还；每月 1 日补充；不能购买额外额度。[SN 全档]
  - **Alerts（提醒）**：主页 Alerts feed 汇总账户增长、新决策者、职位变动、线索动态等；部分提醒（Buyer Intent、Smart Link 查看等）有套餐要求。[基础提醒 SN 全档]

  **免费会员替代路径（没有付费版时这样干）**：
  - 无保存搜索 → 把搜索条件固化成文档反复复用（Trade 帮你生成搜索词清单）
  - 无 Persona → 每次搜索手动套用"职能+职级+地区"三步筛选
  - 无 InMail → 用连接邀请 + 200 字符留言（关注→互动→邀请），接受连接后再继续沟通
  - 无 Smart Link → 发送资料后主动跟进问反馈（无法追踪就靠对话确认）
  - 无 Account IQ / Relationship Maps → 公开信息手工梳理：公司页员工列表 + Google「职位+公司名」+ 官网团队页
  - 搜索受商业使用限制 → 用精准搜索词减少无效搜索、错开使用时段、记录已查看对象避免重复

  **账号风控（全员适用）**：共享账号 = 永久封号；非正规渠道购买"个人版" = 100% 封号（经验，来源存疑渠道风险极高）；短时间大量加人 → 账号被限制发邀请（官方限制通常持续 1 周，累计多次可能永久封号）。正确做法：控制频率、精准连接；先互动后邀请。

  **全年内容规划**：三支柱（技术 40%/项目 30%/动态 30%）+ 季度市场重点 + 月主题线 + 周二/四/六发布。Post 结构：吸睛开头(emoji+节奏感)→实操内容→行业关键词→CTA→精选标签。

  **领英公司主页**：About us 含产品关键词和工厂优势、公司规模/成立年份/认证/主要市场全部填写。用 Google Site Search 搜索：`site:linkedin.com "职位" "行业" "国家"` 扩展搜索。
---


Industry: [Target industry — e.g., manufacturing, retail, construction]
Company Size: [1-10 / 11-50 / 51-200 / 200+ employees]
Roles: [Purchasing Manager, CEO, Operations Director, etc.]
Region: [Specific countries or regions]
Pain Points: [Top 3 challenges they face]
Goals: [What they're trying to achieve]
Buying Behavior: [Price-sensitive / quality-focused / relationship-driven]
```

### Example (Generic B2B Manufacturing)

```
Industry: Industrial equipment manufacturing
Company Size: 50-200 employees
Roles: Purchasing Manager, Plant Manager, CEO
Region: North America, Europe, Southeast Asia
Pain Points: Quality consistency, lead time, communication barriers
Goals: Find reliable suppliers, reduce costs, scale production
Buying Behavior: Quality-focused, requires certifications, longer sales cycle
```

## Phase 2: Personal Profile Optimization (5 Sections)

### Section 1: Profile Photo & Banner

- **Photo**: Professional headshot with clear face visible, smiling, neutral background
- **Banner**: Company product/factory image OR brand statement image (1584 x 396 px)

### Section 2: Headline (220 characters max)

**Formula**: `[Job Title] | [Core Value Proposition] | [Industry/Product]`

**Examples**:
- `Export Sales Manager | Helping Global Partners Source Quality [Product] at Competitive Prices | 10+ Years Experience`
- `B2B Sourcing Expert | Connecting Worldwide Buyers with Top-Tier Manufacturers | Certified Supply Chain Partner`
- `[Product] Supplier | Your Reliable China Sourcing Partner | ISO Certified Factory`

### Section 3: About Section (2,600 characters max)

**Structure**:

```
[HOOK — 1-2 sentences addressing their pain point]
I've helped [X]+ companies in [industry] solve [specific problem].

[YOUR BACKGROUND — Credibility]
With [X] years in [industry], I understand the challenges you face.

[WHAT YOU OFFER — Clear value proposition]
I specialize in:
• [Service/Product 1] — [Benefit]
• [Service/Product 2] — [Benefit]
• [Service/Product 3] — [Benefit]

[CTA — Next step]
📩 Connect with me to discuss your sourcing needs.
🌐 [Website]
🔗 [Product catalog link]
```

### Section 4: Experience

**Format**: `[Job Title] at [Company Name]`
- Use keywords in job titles (Export Manager, B2B Sales, Sourcing Specialist)
- Write 40-50 words per position describing achievements

### Section 5: Skills & Endorsements

- Add 50 skills relevant to your industry
- Prioritize: Product Sourcing, B2B Sales, Negotiation, Supply Chain Management, Quality Control, International Trade
- Ask colleagues to endorse your top skills

## Phase 3: Company Page Setup

### Company Page Sections

1. **Name**: `[Your Brand] — Professional [Product] Manufacturer`
2. **Tagline**（官方上限 120 字符）: `[X] Years of Excellence in [Industry] | Your Trusted [Product] Partner`
3. **About**（官方上限 2000 字符）: Similar structure to personal profile, company-focused
4. **Products**: Add all product categories with descriptions and images
5. **Media**: Factory photos, certifications, team, trade show presence

### Content Strategy for Company Page

- Post company updates 3-5x per week
- Share behind-the-scenes content
- Post certifications and quality compliance
- Share client testimonials (with permission)

## Phase 4: Annual LinkedIn Marketing Plan

### Monthly Content Calendar Template

| Week | Content Type | Topic Focus | Goal |
|------|-------------|------------|------|
| Week 1 | Video/Photos + Article | Product showcase + Industry insight | Awareness |
| Week 2 | Poll + Text Post | Engagement boost + Industry question | Engagement |
| Week 3 | Document + Article | Lead magnet + How-to guide | Lead generation |
| Week 4 | Video + Text Post | Factory/culture + Quick tip | Trust building |

### Sample Annual Content Plan

```
Q1 (Jan-Mar): Brand awareness & foundation
- Month 1: Profile optimization, 5 foundational posts
- Month 2: First article series (industry trends)
- Month 3: Document post (product guide v1)

Q2 (Apr-Jun): Lead generation focus
- Month 4: First poll series, engagement campaign
- Month 5: Case study article, client testimonial
- Month 6: Product catalog document, company milestone

Q3 (Jul-Sep): Authority building
- Month 7: Thought leadership articles
- Month 8: Trade show coverage, industry event
- Month 9: Expert interview series

Q4 (Oct-Dec): Year-end review & planning
- Month 10: Annual industry report
- Month 11: Client success stories
- Month 12: Year in review, next year preview
```

## Phase 5: Outreach Message Templates

### Connection Request (≤200 characters)

**Formula**: `[提及对方的痛点或共同点] + [你能帮TA解决什么问题] + [CTA]`

核心原则：不推销产品，而是让对方意识到「这个人可能帮我省时间/省钱/降低风险」。注意：LinkedIn 连接邀请留言官方上限 **200 字符**（含空格），生成的模板必须在此限制内。

**Examples**:
- `Hi [Name], saw your post about supplier quality issues. I help [industry] buyers eliminate inconsistent product quality with a 3-step process. Open to connecting?`
- `Hi [Name], many purchasing managers in [industry] tell me their lead times are killing their margins. We built a system that cuts it by 30%. Worth a coffee chat?`
- `Hi [Name], I noticed your company is expanding in [market]. Getting CE/FDA certification right from the start saves months of rework — happy to share what we've learned.`

### Follow-Up After Connection (Day 3-5)

```
Hi [Name],

Enjoyed connecting with you!

I know that for [product] buyers in [industry], keeping quality consistent across multiple containers is a constant headache. One of our clients in [similar company/region] was seeing 8% defect rates from their previous supplier, which ate up their margins on every order.

We built [specific process/capability] that brought it down to under 2% and saved them about $[X] on their last three shipments.

Would you be open to a 15-minute call? I'd love to understand what frustrates you most about your current sourcing setup.

Best,
[Your Name]
```

### InMail for Prospects

```
Subject: [Their company] + supply chain idea

Hi [Name],

I know that for [industry] companies expanding in [region], finding a supplier who actually understands [local certification/regulation requirements] can make or break a product launch.

We recently worked with [a company similar to prospect] who were stuck because their existing suppliers couldn't meet [specific requirement]. We stepped in with [specific solution] and got their product to market [X weeks/months faster].

Is supply chain reliability something you're focused on right now? Happy to share what we've learned — no pitch, just insight.

Best,
[Your Name]
```

## Phase 6: Content Templates by Type

### Video/Photo Post Template

```
[Visual: 客户使用场景 / 定制化服务过程 / 检测实验室 / 客户反馈截图]

[用客户痛点开头 — 1-2句]
Most [industry] buyers don't realize that [a hidden problem] costs them [X]% on every order...

[你的独到解决方案 — 3-4句]
At [company], we [specific thing you do differently], which means:
→ [Benefit for customer — money/time/risk]
→ [Benefit for customer — money/time/risk]
→ [Benefit for customer — money/time/risk]

[CTA — 让读者参与]
Is [problem] something your team faces? Comment below or DM me.

#industry #sourcing #supplychain #qualitycontrol
```

### Article Template

```
Title: [Number] Things You Must Know About Sourcing [Product] from [Country]

Introduction: [Hook — address their pain point]

Section 1: [Topic]
[2-3 paragraphs]

Section 2: [Topic]
[2-3 paragraphs]

Section 3: [Topic]
[2-3 paragraphs]

Conclusion: [Summary + CTA]
[Author bio with photo]

#industry #sourcing #[product] #[country]
```

### Document Post Template

```
🎁 FREE GUIDE: [Title]

This [X]-page guide covers:
📌 [Key point 1]
📌 [Key point 2]
📌 [Key point 3]
📌 [Key point 4]

Comment "GUIDE" below and I'll send you the link!

#industry #[product] #sourcing #[country]
```

### Text Post Template

```
[用客户的视角切入 — 痛点、误区、踩坑经历]

[你遇到过的真实案例或行业现象]

[你或你的团队是如何解决这个问题的 — 重点讲流程、工具、服务,不讲产品参数]

[以一个问题结尾，邀请讨论]

#industry #supplychain #foreigntrade #[topic-not-product]
```

## Phase 7: Sales Navigator 功能实战（官方功能名 + 套餐分级）

> 2026-09 按 LinkedIn 官方帮助中心重写。**使用前提**：先确认用户套餐——免费 Basic / Premium Business / Sales Navigator Core / Advanced / Advanced Plus。
> 标注 [SN] 的功能免费用户不可用，需给出免费替代；标注 [Advanced+] 的功能仅 Advanced / Advanced Plus 可用；拿不准的入口写"在账户中查找，以实际为准"，不猜菜单路径。

### 7.1 功能地图：搜索 → 保存 → 画像 → 提醒

Sales Navigator 的核心工作流围绕四类对象：

| 对象 | 官方名称 | 说明 |
|------|---------|------|
| 保存的搜索 | Saved Searches | Lead / Account 搜索各最多存 50 条，新增匹配自动推送 |
| 保存的对象 | Saved Leads / Account Lists | 保存的人和公司，单独监测动向 |
| 画像 | Personas | 组合职能/职位/职级/地区的潜客筛选模板（仅 Lead Search） |
| 提醒 | Alerts | 主页 Alerts feed 汇总账户与线索动态 |

> 设计哲学：**一次工作量、永久复用**——保存搜索和画像设好后，新客户会自动出现在提醒里。

### 7.2 [SN] Personas（画像）

- Persona 可组合 **职能 / 职位 / 职级 / 地区** 四类条件（不是只能存职务）；职位必须用标准职位名，不支持关键词模糊搜索
- 默认提供 Director+ 和 CXO 两个，可再建 3 个（**合计上限 5 个**）
- **仅用于 Lead Search**（公司搜索用 Account filters）；修改 Persona 后，已保存的搜索不会自动更新（需重新套用）
- **按市场分组**（实战方法论）：不同市场决策角色不同——如国内北方市场老板拍板（存总裁/总经理类职位）、沿海关务型公司中层主导（存经理类职位）；欧洲/非洲等海外市场也各有习惯，分开建 Persona

### 7.3 [SN] Saved Searches = "买家的侦探"

- 保存后新增客户自动追踪：新匹配通过**每周邮件 + 主页 All alerts** 推送（不是即时消息）
- **保存时机建议**：搜索结果积累到一定量再保存（样本太少时意义不大）
- 客户换职位、有新闻、有新决策者 → 通过 Alerts 第一时间知道
- Lead / Account 搜索都支持保存（各上限 50 条）

### 7.4 [SN][Advanced+] CSV 批量导入 Account Lists（展会名录）

1. 套餐要求：**仅 Advanced / Advanced Plus 可导入 CSV**；CSV **仅用于 Account Lists，不支持 Lead Lists**
2. 格式要求：用官方 CSV 模板；**必填 Account Name**（用标准公司名，官方建议不要填网址）；建议从界面下载模板再填写
3. 限制：**每表 ≤1000 家公司**、文件 <20MB；可多表分批上传
4. 上传后系统自动匹配公司（名称拼写差异会影响匹配），可下载匹配报告核对
5. 导入的是**公司**，不是联系人——之后仍需通过公司页、Relationship Explorer、Lead 搜索找到具体联系人
6. 注意：**搜索职位词要与名录行业配套**（例：工业暖通行业不设 sourcing/procurement 岗，硬套这些词匹配不出人）

### 7.5 [SN] Account IQ（账户洞察）

- 公司账户页中的深度洞察，核心内容：
  1. **战略重点与业务挑战**：公司公开的战略方向、可能痛点
  2. **财务信息**：公开财务数据（如适用）
  3. **增长与招聘信号**：员工数量变化、职位空缺、新入职人员——"研发部在招人"可解读为可能有新项目/新设备需求（合理推测，非官方结论）
- **注意：并非所有公司都有完整数据**——缺失时用公司官网、新闻、招聘网站等公开信息补充
- 洞察内容来自 LinkedIn 自有数据与公开信息，是分析辅助，不是内幕情报

### 7.6 [SN] Relationship Explorer + Relationship Maps（找对人 → 理关系）

**Relationship Explorer（找对人）**：
- 在目标公司账户页推荐**最多 8 位**相关联系人，可按 Persona 筛选
- **Best Path In**：根据你与对方的关系强度（1 度/2 度/群组等）找最佳进入路径
- 推荐结果随保存动作刷新（保存线索后重新加载/切换筛选可看到更新）

**Relationship Maps（理关系）**：
- 把账户内联系人整理成列表或关系图，可标记：**角色**（Decision Maker / Champion / Evaluator / Procurement / Influencer）、关系强度、负责人、备注
- 上限：每账户最多 10 张图、每张 30 人；可添加"占位卡"记录还没有 LinkedIn 档案的联系人
- **与同事共享需 Advanced / Advanced Plus**；移动端不支持查看
- 用法建议：先标出 Champion（支持者）和 Decision Maker（决策者），按角色设计接触顺序

### 7.7 [SN][Advanced+] Buyer Intent（购买意向）

- **套餐要求：仅 Advanced / Advanced Plus**
- 信号类型（官方区分公开/私有）：
  - **公开信号**（可识别具体人）：关注公司主页、查看你的个人资料、与你/同事建立新联系、提交表单、接受合同内 InMail
  - **私有信号**（只显示公司+职位，不显示具体人）：访问公司主页、访问员工个人资料、查看/点击广告、访问装了 Insight Tag 的公司官网
- 正确解读：意向信号 = **优先级排序参考**，不等于购买承诺
  - "员工访问过主页" → 该公司内有人关注你们，值得优先接触（不能断言"高购买意愿马上来联系"）
  - "研发部在扩招" → 可能的新项目信号，可在开场中作为话题（不能断言"急需新设备"）
- 网站访问类信号需要对方公司网站安装 LinkedIn Insight Tag（通常是大公司才装）

### 7.8 [SN] Smart Links（资料追踪链接）

> 解决痛点：邮件/消息发出去石沉大海，不知道客户看没看。

1. **创建**：上传资料（产品图册 / 公司简介 / 针对性报价 PDF）生成一条专属链接
2. **可追踪数据**：查看者身份（登录 LinkedIn 者显示姓名/职位/公司；未登录者需自行登记）、点击次数、停留时长、访问时间
3. **看不到的**：链接被转发给了谁（官方不提供转发链）——重要判断请通过后续对话确认
4. **使用场景**：发邮件 / 发消息时附上；官方支持设置访问者需先登记身份才能查看
5. **解读建议**：停留时间长的访问者优先跟进；同一人多日多次访问 = 高关注度

### 7.9 [SN] InMail 额度管理

- 每月 **50 条**（SN 各档一致）；可结转（**累计上限 150 条**）
- **90 天内对方回复/接受/拒绝 → 返还额度**；每月 1 日（UTC）补充当月额度
- 不能购买额外额度；取消订阅/换套餐时现有额度不转移
- 额度稀缺，发之前先跑完客户分析（Phase 8 前五步）再发

### 7.10 [免费] 免费会员替代路径汇总

| 付费功能 | 免费替代 |
|--------------|---------|
| Saved Searches / Personas | 把搜索词固化成文档反复复用；手动套用"职能+职级+地区"筛选 |
| InMail | 连接邀请 + 200 字符留言（关注→互动→邀请） |
| Smart Link 追踪 | 发送资料后主动跟进问反馈 |
| Account IQ / Relationship Maps | 公开信息手工梳理（公司页员工列表 + Google「职位+公司名」+ 官网团队页） |
| Buyer Intent | 关注对方公司主页动态、招聘信息、行业新闻，人工判断优先级 |

### 7.11 账号风控（全员适用）

| 行为 | 后果 |
|------|------|
| 共享账号 | 永久封号 |
| 非正规渠道购买"个人版" | 高风险（渠道不受官方保护，封号申诉无门） |
| 短时间大量加人 / 邀请被频繁忽略 | 账号被限制发邀请（官方：通常持续 1 周，期间不能发邀请、撤回也不解除） |

- 正确做法：控制连接频率、精准连接、先互动后邀请
- 官方信息：1 度人脉上限 30000；限制类型与时长由 LinkedIn 判定（官方不支持人工解封或缩短）
- Sales Navigator 有官方学习/上手内容，建议新用户走一遍

## Phase 8: 六步开发流水线

> 2026-09 新增。来源：大宗师网络「LinkedIn 外贸客户开发」实战内容。
> 与 Phase 7 的关系：**Phase 7 是"平台怎么操作"，本 Phase 是"需要做哪些分析"**——两者配合，先跑流水线定位目标，再用 SN 功能执行触达。

**总原则**：
- 六步**串行**——前一步的输出是后一步的输入，前一步跑完再进下一步
- 第 ⑥ 步（触达）必须等前五步完成：此时你才真正知道"客户是谁、负责什么、卖什么给他、为什么值得联系"
- 每一步的分析都要输出结构化结果（表格/清单），不泛泛而谈

### 8.1 第①步 客户画像：先确定"卖给谁"

**核心认知**：LinkedIn 开发客户第一步不是搜产品名，而是确定"我的产品到底应该卖给谁"。

**客户类型 5 分类**：进口商（Importer）/ 经销商（Distributor）/ 品牌商（Brand）/ 批发商（Wholesaler）/ 终端企业（End User）。

**筛选四问**（对每类客户评估）：
1. 谁有持续采购需求？
2. 谁与你的产品更匹配？
3. 谁采购量更大？
4. 谁更值得优先开发？

**输出五要素**：
1. 最值得开发的 5 类 B2B 客户
2. 每类客户的典型业务模式
3. 可能采购我们的哪些产品
4. 推荐联系的职位
5. 按开发优先级排序

> 铁律：**不要泛泛推荐所有相关企业**，优先寻找真正存在进口、分销、采购或配套需求的客户。

### 8.2 第②步 搜索关键词：把"产品词"变成"买家词"

**核心认知**：只搜 "Furniture" / "Pet Products" / "Machinery" 范围太大——**不要只搜"产品"，要开始搜"谁在买这个产品"**。

**搜索组合公式**：`产品 + 买家身份 + 行业 + 国家`

**买家词表**（重点加入）：
| 类别 | 词 |
|------|---|
| 流通环节 | Importer / Distributor / Wholesaler |
| 品牌端 | Brand / Private Label |
| 零售端 | Dealer / Retail Chain |
| 特定行业表达 | 下游应用行业词 + **当地常用行业表达**（本地化） |

**生成要求**：生成 30 组搜索关键词；覆盖上述全部类别；**每组注明"适合寻找哪类客户"**；按推荐优先级排序。

### 8.3 第③步 客户分类：把一批公司筛出优先级

**核心认知**：LinkedIn 搜出 50 家公司 ≠ 50 家都值得开发——里面可能混着：**同行、零售商、服务商、终端客户和真正的进口商**。

**评估四维度**：
1. **渠道属性**：判断属于进口商、经销商、品牌商、批发商还是其他类型（这是最容易漏判的一步）
2. 产品匹配度
3. 有没有渠道和采购能力
4. 是否值得继续跟进

**A/B/C 分级定义**：
- **A 类 = 重点开发**（说明为什么值得重点开发）
- **B 类 = 继续验证**
- **C 类 = 暂时放后**

> 铁律：无法验证的信息标注「待验证」（与全局置信度标注体系一致）。**客户名单不是越长越好，真正有价值的是先把重点客户挑出来。**

### 8.4 第④步 采购负责人：别只会搜 "Buyer"

**核心认知**：公司找准后，要找**真正能推进采购的人**——不同公司规模/业务模式，对应的关键职位不同。

**采购决策角色三问**（针对目标公司分析）：
1. 谁负责**寻找和筛选供应商**？
2. 谁负责**产品或技术评估**？
3. 谁可能**参与最终采购决策**？

**职位词表**（重点找）：
| 职能 | 职位 |
|------|------|
| 采购 | Purchasing / Procurement |
| 寻源供应链 | Sourcing / Supply Chain |
| 产品线 | Product / Category Manager |
| 高层（小公司决策者） | Owner / Founder / Managing Director |

**分析输出**：推荐优先联系的 **3 类职位** + **生成对应的 LinkedIn 英文职位搜索词** + 按联系优先级排序。

> 铁律：公司找对只是第一步，**找到真正负责采购的人**，开发才开始变精准。

### 8.5 第⑤步 客户背景：找到"为什么值得联系他"

**核心认知**：找到采购负责人以后**不要马上发消息**——先研究出一个具体的"开发理由"，再决定第一句话怎么说。

**研究清单**：
- 公司最近在推什么产品？
- 对方主要做哪些市场？
- 有没有新品、项目或展会动态？
- 我们的产品从哪里最容易切进去？

**输出五要素**：
1. 对方目前主营产品和业务重点
2. 双方最匹配的产品
3. 最自然的合作切入口
4. 最适合第一次沟通的话题
5. 哪些公开信息值得在开发中利用

> 铁律：**只根据公开可验证的信息判断，不要虚构客户需求。**（可结合 Phase 7 的 [SN][Advanced+] Buyer Intent + Account IQ 增强背景研究）

### 8.6 第⑥步 首次触达：客户资料生成个性化消息

**前置条件**：前五步全部跑完（此时已知：客户是谁 / 负责什么 / 卖什么给他 / 为什么值得联系）。

**四条要求**：
1. 不群发（不使用群发销售口吻）
2. 开头直接结合对方业务（不长篇介绍工厂）
3. 自然带出产品的匹配点
4. 结尾留一个**容易回复的问题**

**输出规格**：生成 **3 个不同版本**（供 A/B 选择）；每条控制 **60-80 词**；素材变量：公司名称 / 对方主营 / 联系人 / 职位 / 你方产品 / 合作切入口（来自第⑤步）。

> 核心心法：**第一条消息不是介绍自己，而是让客户看懂"你为什么找到他"。**（与连接邀请铁则、"第一句讲客户不讲自己"一致）

## Quality Standards

1. **No placeholders**: All content must be complete and ready to publish. No "XXX", "[insert]", or "[TBD]"
2. **Industry-specific**: Use actual product terminology from user's资料. Adapt examples to their industry
3. **Platform-native**: Content should feel natural for LinkedIn, not repurposed blog content
4. **Visual requirement**: Every post should have an image/video or clear visual description
5. **Character limits**: Respect LinkedIn limits — headline 220 chars, About 2,600 chars, connection note 200 chars, article title 100 chars
6. **Hashtag strategy**: Use 3-5 relevant hashtags per post, mix broad (#B2B #Sourcing) with specific (#Machinery #Electronics)
7. **客户价值优先**: 每篇内容先想「读这篇文章的人最关心什么」——不是你的产品有多好，而是你能让TA的工作更容易、更挣钱、更少风险。产品参数是支撑证据，不是主角。

## Common Pitfalls

1. **Generic content**: Don't create one-size-fits-all posts. Always adapt to user's specific industry and products
2. **Product-first mentality** 🔴 **最严重的错误**: 帖子开头就讲产品参数、规格、价格优势。正确做法：先谈客户痛点 → 解决方案 → 工厂硬实力展示 → 产品作为支撑证据出现
3. **过度推销**: 没人关注只会贴产品目录的账号。产品/工厂内容占 25% 左右，且须裹在客户价值叙事里
4. **空洞话术**: 不要说「质量好」「价格优」「服务好」——每个供应商都这么说。具体讲「我们的出货检验包含 X 项测试」「48 小时打样承诺」「拉美市场 CE 认证我们有专门文件团队」
5. **Ignoring engagement**: Respond to comments within 24 hours. Engagement drives algorithmic reach
6. **Inconsistent posting**: Better to post 3x/week consistently than 10x one week and none the next
7. **Cold outreach without personalization**: Always reference something specific about the prospect before pitching
8. **No CTA**: Every post should have a clear call-to-action (comment, share, click link, DM)

## LinkedIn SEO Optimization

To appear in search results when prospects search for suppliers:

1. **Keywords in profile**: Put industry/product keywords in headline, About section, and Experience titles
2. **Consistent posting**: LinkedIn rewards active accounts with better search visibility
3. **Engagement**: Comment on industry posts to increase visibility
4. **Connections**: Grow your network — aim for 500+ connections in your target industry
5. **Recommendations**: Ask clients for recommendations — they appear in search results
