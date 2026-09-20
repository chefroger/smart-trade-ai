---
name: b2b-linkedin-marketing
description: LinkedIn 营销 — Profile 优化、内容策略、InMail 模板、Account IQ 深度分析
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
  Day2：Headline（产品词+角色+价值，≤150 字符，三种结构（A）产品词+公司角色+核心优势（B）I help... 表达（C）职位+公司+业务范围）+ About（Who we are→What we make→Who we serve→Strengths，≤800 字符，3W+1H 或 Dream+Help 或 Story+Specialties 或 数据+案例 或 Pain Point 五种架构）
  Day3：Experience（至少 2 份，公司 20 条优势→价值展示而非罗列职责→嵌入关键词）+ Skills（10-15 个英文关键词）
  Day4：Featured 富媒体（产品册 PDF、工厂视频、案例链接）+ Media（Title≤60 字符，Description≤500 字符）
  Day5：推荐信（至少 3 封，先给别人写）
  Day6：Contact Info + 证书/专利背书
  Day7：隐私设置检查——联系人名单仅自己可见、动态关闭公开、公开档案给买家看/隐身看同行、重要 Groups 必须隐私、两步验证开启、用无痕浏览器模拟买家视角检查

  **LinkedIn 五维度内容营销**：
  1. Post-视频（产品展示/工厂参观/客户案例）
  2. Post-照片（工程现场/装箱发货/团队活动）
  3. Post-文章（行业深度长文，SEO 权重高，长尾词可排谷歌首页）
  4. 投票（高参与度，轻互动，引导评论）
  5. Document（上传高价值资料如产品目录/选型指南，引导客户下载获取线索，标题带产品关键词）

  **Document 引流打法**：文档名称=产品关键词（如"Guy Grip / Dead End Clamp / Insulator Clamp"），Description 引导目标客户画像素级客户来下载，用客户画像的关键词吸引南美/澳洲/中东等特定市场。

  **LinkedIn 客户开发六步流水线（串行执行——前一步完成才做下一步）**：
  ① **画像（卖给谁）**：先定客户类型，不是先搜产品名——产品适合卖给进口商 / 经销商 / 品牌商 / 批发商 / 终端企业哪几类？按"有持续采购需求 / 与产品匹配 / 采购量更大 / 更值得优先开发"四问筛选，输出 5 类最值得开发的 B2B 客户 + 每类业务模式 + 可能采购的产品 + 推荐职位 + 优先级排序
  ② **买家词（搜什么）**：把"产品词"升级为"买家词"——搜索组合 = **产品 + 买家身份 + 行业 + 国家**；买家词表：Importer / Distributor / Wholesaler / Brand / Private Label / Dealer / Retail Chain / 下游应用行业 / 当地常用行业表达；关键词要注明"适合找哪类客户"并按优先级排序
  ③ **分类（筛优先级）**：搜出的公司混着同行/零售商/服务商/终端——先判断**渠道属性**（属于哪类买家）+ 产品匹配度 + 有无渠道和采购能力 → A/B/C 三级（A 重点开发 / B 继续验证 / C 暂时放后）；无法验证的信息标注「待验证」
  ④ **决策人（找谁）**：别只会搜 "Buyer"——按公司规模/业务模式分析真实采购决策角色：谁筛选供应商 / 谁做技术评估 / 谁参与最终决策；职位词表：Purchasing / Procurement、Sourcing / Supply Chain、Product / Category Manager、Owner / Founder / Managing Director；推荐 3 类优先职位 + 生成 LinkedIn 英文职位搜索词
  ⑤ **背景（为什么值得联系）**：写消息前先研究——公司最近在推什么产品 / 主要做哪些市场 / 有无新品-项目-展会动态 / 我方产品从哪里最容易切入；只根据公开可验证信息判断，**不虚构客户需求**
  ⑥ **触达（怎么写）**：前五步跑完才写消息（此时已知：客户是谁/负责什么/卖什么给他/为什么值得联系）；生成 **3 个版本**、控制 **60-80 词**、开头直接结合对方业务、自然带出产品匹配点、结尾留一个容易回复的问题；核心心法：**第一条消息不是介绍自己，而是让客户看懂"你为什么找到他"**

  **客户开发三步闭环（快速版，六步的浓缩）**：
  1. 画像素级客户画像（仅需主营产品→输出目标市场/行业分类/搜索关键词/客户类型/公司规模/决策人职位 6 大维度）
  2. 精准搜索——[免费] 基础搜索 + 布尔运算符（职位 OR 产品关键词 OR 行业 AND 国家 AND 公司规模 11-200 人；免费版最多 5 组关键词）；[SN] 升级为 40 个搜索维度、10 组关键词
  3. Add Note 300 字符开发（人维度/公司维度两套模板，必须引用买家背景关键词+提产品匹配点，专业真诚不推销）

  **Add Note 铁则**：关注→有 post 就评论→忍不住想开发才用 Add Note。哪怕没 post 也一定关注（关注后 LinkedIn 算法更懂你）。先发 Connection Request（[SN] 也可用 InMail，但额度有限留关键客户）；[SN] 按后台追踪数据（是否看过视频/案例/分享）决定跟进话术，[免费] 则以对方互动（点赞/评论/回复）为信号。

  **[SN] Smart Link 定制要点**：针对单一客户定制（命名带对方公司名、打包 3 个文件：本地气候应对 PDF + 安装视频 + 成功案例）；画像与筛选沿用上方"客户开发三步闭环"，追踪玩法见下方 Smart Link 条目。

  **LinkedIn 安全规则**：一天加好友不超过 100 个、新号先内部互加 50 人再开发、不加国内同行（防举报封号）、界面语言切英文（功能更全）

  **会员能力分级（重要——先确认用户等级，再给方案）**：
  用户可能是免费会员或高级会员（Sales Navigator，简称 SN）。下面标注 [免费] / [SN] 的能力必须区分——**不要给免费会员推荐 SN 专属操作**，每个 SN 功能都要能给出免费替代路径。

  **四大金库**（后台顶部导航，SN 的核心工作流）：公司金库（保存的公司 + 上传展会名录）/ 人的金库（Saved Leads，动向监测）/ 销售素材金库（配合 Smart Link）/ 发信记录。定位：一次工作量、永久复用——"你的时间就是客户就是钱"。

  **群必须先加才能筛（[免费] 环节）**：LinkedIn 群只能在免费版加入（SN 界面加不了群）——这是"群搜索三步法"的第一步，[SN] 能力只体现在筛选环节。

  **[SN] 客户画像**：画像只能保存"职务"；**按市场分组**（例：北方市场老板决策→存总经理；深圳/宁波关务经理决策→存中层）——欧洲/非洲/不同市场各有行为习惯，分开存。

  **[SN] 保存搜索记录 = "买家的侦探"**：保存后新增客户自动追踪（例：保存 PCBA 搜索→一段时间后 159 个新增）；列表积累到几百~1000 条时保存效果最佳（太少意义不大）；公司/人的搜索记录都支持批量保存。

  **[SN] 上传展会名录**：每表 ≤1000 家公司；CSV 固定格式（公司名 + LinkedIn URL 必填，界面可 Download 模板）；上传后自动匹配客户画像职务，精准定位决策者。

  **[SN] Account IQ（账户智能）**：打开目标公司 → K people（与你相关联的人，如"13 万人中 5000 人相关"）、决策者推荐、公司情报（投资/扩张计划、增长数据、招聘信号）；先上传企业画像（服务能力描述）匹配更准。

  **[SN] 决策链图谱**：把所有相关联系人拖入地图可视化——标记支持者 / 反对者 / 保留意见者；谁给谁汇报；可团队共享，锁定背后的决策人。

  **[SN] 意向信号**：员工增长（哪个部门在招人——"研发部增 20% → 新设备需求"）+ 行为信号（员工访问你主页 / 点过广告 = 高购买意愿）。

  **[SN] Smart Link（链接侦查）**：上传资料生成追踪链接——谁看了、看了多久（12 分 30 秒 = 浓兴趣）、**转给了谁**（采购经理转 CEO → 锁定决策人）；发邮件/消息时用（不发公开帖）。

  **[SN] InMail 额度**：每月 50 条，未用可留存、客户回复即返还，**累计上限 150**——额度有限，发之前先做分析。

  **[SN] 其他**：公司维度搜索（独立通道：搜索→Account→三个点→「查看类似公司」= 双胞胎公司，相同痛点+相同预算）；Spy 竞品公司员工列表；TeamLink 突破二度人脉；Lead Builder 保存搜索模板；联系人深挖（公开的联系方式、职业轨迹/原公司/上下级/**谁有现决策权**）。

  **免费会员替代路径（没有 SN 时这样干）**：
  - 无客户画像/保存搜索 → 手动固化搜索词组合，每次复制复用
  - 无 InMail → 用 Connection Request + Add Note（≤300 字符），角度保持低摩擦
  - 无 Smart Link → 常规发送资料 + 主动跟进问反馈（无法追踪就靠对话确认）
  - 无 Account IQ / 决策链图谱 → 公开信息手工梳理：公司页员工列表 + Google 检索「职位+公司名」
  - 无群筛选 → 免费版加群后，手动浏览群成员列表（免费版只能看、不能按条件筛）

  **封号风控（全员适用）**：共享账号 = 永久封号；非正规渠道购买"个人版" = 100% 封号；短时间大量加人 = 警告 3 次以上永久封号。正确做法：控制频率、精准连接；SN 用户优先用"按职位/技能推荐加人"功能。

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

### Section 3: About Section (3,000 characters max)

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
2. **Tagline**: `[X] Years of Excellence in [Industry] | Your Trusted [Product] Partner`
3. **About**: Similar structure to personal profile, company-focused
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

### Connection Request (≤300 characters)

**Formula**: `[提及对方的痛点或共同点] + [你能帮TA解决什么问题] + [CTA]`

核心原则：不推销产品，而是让对方意识到「这个人可能帮我省时间/省钱/降低风险」。

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

## Phase 7: Sales Navigator 高级功能实战（含免费会员替代）

> 2026-09 新增，来源：领英高级会员获客教学（4 集）实战内容。
> **使用前提**：先确认用户是免费会员还是高级会员（SN）——标注 [SN] 的方案只适合高级会员，免费会员走每节的"免费替代"。

### 7.1 账号后台导航：四大金库

| 金库 | 内容 | 用途 |
|------|------|------|
| 公司金库 | 保存的公司（Account List） | 上传展会名录、监测公司动向 |
| 人的金库 | 保存的人（Saved Leads） | 单独关注，任何动向第一时间知道 |
| 销售素材金库 | 上传的资料 | 配合 Smart Link 定向发送 |
| 发信记录 | 所有发过的开发信 / InMail | 回溯沟通历史 |

> 设计哲学：**一次工作量、永久复用**——"别人干十次你干一次，省下的时间就是客户就是钱"。

### 7.2 [SN] 客户画像（Saved Search 的职务维度）

- **画像只能保存"职务"**（这是 LinkedIn 的产品限制），配合地点/行业筛选使用
- **按市场分组**（关键方法论）：
  - 北方市场（河南/河北/山东/天津）：老板决策 → 存总经理类职务
  - 深圳 / 宁波：关务经理等中层决策 → 存中层职务
  - 不同海外市场（欧洲/非洲）各有行为习惯 → 分开存
- 效果：选画像后目标从海量收敛到极精准（示例：选画像后仅 190 人符合）

### 7.3 [SN] 保存搜索记录 = 买家的侦探

- 保存后**新增客户自动追踪**：示例——1 月 16 日保存 PCBA 搜索，之后自动发现 159 个新增；2023 年保存的"袜子"搜索累计 214 个新客户
- **保存时机建议**：列表积累到几百 ~ 1000 条时保存效果最佳（290 条时保存意义不大）
- 客户换职位、有新闻、有新决策者 → 第一时间知道
- 支持批量保存（公司搜索记录同样可存）

### 7.4 [SN] 上传展会名录

1. 位置：金库 → 上传目标企业 / 展会名录
2. 格式：CSV（界面提供 Download 模板）；**必填：公司名称 + LinkedIn URL**；其他字段可选
3. 限制：**每表 ≤1000 家公司**；可多表分批上传
4. 上传后自动匹配客户画像职务 → 从名录中精准锁定决策者
5. 注意：**画像职务要与名录行业配套**（例：工业暖通名单配 sourcing/procurement 画像匹配不出——暖通行业不设这些岗）

### 7.5 [SN] Account IQ（账户智能）

- 打开公司后左侧面板 = Account IQ，核心看三块：
  1. **K people**：与你相关联的人（示例："13 万人中 5000 人与你相关"；按销售层面收敛后可能只有 200 多人——从这里优先切入）
  2. **决策者推荐**：该公司里最该找谁
  3. **公司情报**：投资/扩张计划（如"最近有投资中国计划"）、增长数据（销售增长 6%）、招聘信号
- 提升匹配精度：先上传企业画像（5000 字服务能力描述，"三位一体"式优势）

### 7.6 [SN] 决策链图谱（Map）

- 把所有相关联系人**拖拽进地图**：谁给谁汇报、谁是支持者、谁是反对者、谁持保留意见
- 标记后重点搞定"反对者"和"关键决策者"
- 可团队共享（销售负责人与业务员看到同一张决策链）
- 进阶：叠加"隐藏的盟友"（同事联系过的客户一览）→ 把客户织成一整张关系网

### 7.7 [SN] 意向信号（Signal）

| 信号类型 | 示例 | 解读 |
|---------|------|------|
| 员工增长 | 研发部在招人 +20% | 有新产品研发 → 急需新材料/新设备 |
| 行为信号 | 员工访问过你的领英主页 / 点过你的广告 | 高购买意愿，"马上会来联系你" |
| 公司监测 7 维度 | 账户增长/风险/更新/新决策者/职位变多/新潜客 | 配合"增长动态"找谈判话题 |

> 实操技巧：结合"增长动态"数据直接生成谈判开场话题。

### 7.8 [SN] Smart Link 三步玩法（链接侦查）

> 解决痛点：邮件/消息发出去石沉大海，不知道客户看没看、转没转。

1. **上传资料生成专属链接**：产品图册 / 公司简介 / 针对性报价 PDF
2. **实时信号**：谁点击了、谁开始下载 → 手机和电脑弹出提醒
3. **深度侦查**：后台看谁看过、打开多久（**12 分 30 秒 = 浓兴趣**；10 秒 = 还没戏）、**转给了谁**（采购经理→CEO/CFO = 锁定背后决策人）

- 创建位置：金库 → Smart Link → 添加（文件名 + 上传文档）→ copy 链接
- 使用场景：发邮件 / 发消息（**不发公开帖**——它是你的秘密武器）

### 7.9 [SN] InMail 额度管理

- 每月 **50 条**；未用完可留存（例：3 个月存 5 条 → 本月 55 条）
- **客户回复（哪怕一个字）→ 额度返还**
- **累计上限 150 条**——额度稀缺，发之前先做客户分析

### 7.10 [免费] 免费会员替代路径汇总

| 高级功能 [SN] | 免费替代 |
|--------------|---------|
| 客户画像 / 保存搜索 | 手动固化搜索词组合，每次复制复用 |
| InMail | Connection Request + Add Note（≤300 字符） |
| Smart Link 追踪 | 常规发送资料 + 主动跟进问反馈 |
| Account IQ / 决策链图谱 | 公开信息手工梳理（公司页员工列表 + Google「职位+公司名」检索） |
| 群筛选 | 免费版加群 → 手动浏览成员列表（免费版只能看不能筛） |

### 7.11 封号风控（全员适用）

| 行为 | 后果 |
|------|------|
| 共享账号 | 永久封号 |
| 非正规渠道购买"个人版"（2000-3000 元） | 100% 封号 |
| 短时间大量加人 | 警告 3 次以上 → 永久封号 |

- 正确做法：控制连接频率、精准连接；SN 用户优先用"按职位/技能推荐加人"
- 解封仅限官方渠道提交订单的邮箱和公司；席位管理：离职员工席位可回收重分配
- 官方学习窗口（头像→设置）：全部学完有评分，**评分影响领英给你的客户推荐质量**——不要跳过

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

> 铁律：**只根据公开可验证的信息判断，不要虚构客户需求。**（可结合 Phase 7 的 [SN] 意向信号 + 公司情报增强背景研究）

### 8.6 第⑥步 首次触达：客户资料生成个性化消息

**前置条件**：前五步全部跑完（此时已知：客户是谁 / 负责什么 / 卖什么给他 / 为什么值得联系）。

**四条要求**：
1. 不群发（不使用群发销售口吻）
2. 开头直接结合对方业务（不长篇介绍工厂）
3. 自然带出产品的匹配点
4. 结尾留一个**容易回复的问题**

**输出规格**：生成 **3 个不同版本**（供 A/B 选择）；每条控制 **60-80 词**；素材变量：公司名称 / 对方主营 / 联系人 / 职位 / 你方产品 / 合作切入口（来自第⑤步）。

> 核心心法：**第一条消息不是介绍自己，而是让客户看懂"你为什么找到他"。**（与 Add Note 铁则、"第一句讲客户不讲自己"一致）

## Quality Standards

1. **No placeholders**: All content must be complete and ready to publish. No "XXX", "[insert]", or "[TBD]"
2. **Industry-specific**: Use actual product terminology from user's资料. Adapt examples to their industry
3. **Platform-native**: Content should feel natural for LinkedIn, not repurposed blog content
4. **Visual requirement**: Every post should have an image/video or clear visual description
5. **Character limits**: Respect LinkedIn limits — headline 220 chars, connection note 300 chars, article title 100 chars
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
