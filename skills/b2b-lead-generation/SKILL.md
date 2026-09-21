---
name: b2b-lead-generation
description: 多通道客户开发 — Google Maps + LinkedIn + Facebook 搜索、开发信生成、询盘回复、报价谈判
when_to_use:
  - "用户提到「找客户」「开发客户」「开发信」"
  - "需要多通道搜索客户（Google Maps / LinkedIn / Facebook / 海关数据）"
  - "生成询盘回复 / 报价谈判 / 跟进邮件"
  - "分析 B2B 平台（阿里国际站 / 中国制造网）的潜在客户"
  - "用户粘贴产品 / 公司资料要求找潜在买家"
  - "不要用于：单一客户深度画像（用 b2b-customer-intel）"
triggers:
  - 找客户
  - 开发客户
  - 客户开发
  - 找潜在客户
  - 开发信
  - 询盘
  - 客户跟进
  - 客户分析
  - 报价
  - 谈判
  # ... (see skill_registry.py for full list)
category: 客户开发
version: 1.1.0
author: Foreign Trade Assistant
---
---|-----------|------|
  | 平台目录页 | URL 含 alibaba.com / made-in-china.com / tradekey.com / globalsources.com | 阿里产品页本身不是买家 |
  | 聚合页 | URL 含 yellowpages.com / yelp.com / opencorporates.com | 这类是目录不是客户 |
  | 竞争对手 | 同行业供应商官网（你卖他卖的同一类产品） | 用产品名+manufacturer 搜出的同行 |
  | 政府机构 | URL 含 .gov / .edu / .org（除非明确是采购方） | 一般非目标客户 |
  | 死链 | browser_navigate 返回 404 / 503 | 不可达 |
  | 占位页 | 官网为 Wix/Squarespace 模板页且无具体业务 | 通常是空壳公司 |

  ### 多语言查询

  目标市场非英语时，必须生成当地语言版本的 query：
  - 西班牙语市场（拉美/西班牙）：`{product} distribuidor {country}` / `{product} mayorista {country}`
  - 阿拉伯语市场（中东）：`{product} موزع {country}` / `{product} مستورد {country}`
  - 德语市场（DACH）：`{product} Händler {country}` / `{product} Großhändler {country}`
  - 法语市场：`{product} distributeur {country}` / `{product} grossiste {country}`
  - 俄语市场：`{product} дистрибьютор {country}` / `{product} оптовый {country}`
  - 葡语市场（巴西/葡萄牙）：`{product} distribuidor {country}` / `{product} atacadista {country}`

  ### 输出格式

  ```
  ## 🔍 三通道搜索结果

  ### 通道分布
  | 通道 | 原始结果 | 去重后 | 通过黑名单 |
  |------|---------|--------|------------|
  | A: Google Maps | N1 | N1' | N1'' |
  | B: Google Search | N2 | N2' | N2'' |
  | C: FB/LinkedIn | N3 | N3' | N3'' |
  **最终候选**：N 家

  ### TOP 10 候选客户
  | # | 公司名 | 官网 | 国家 | 通道 | 邮箱 | LinkedIn | 电话 |
  |---|--------|------|------|------|------|----------|------|
  | 1 | ... | ... | ... | A+B+C | ... | ... | ... |
  ```

  ### 线索评分矩阵 (Lead Scoring Matrix)

  搜索结果出来后，对每个候选客户按以下 6 维打分（每维 0-5 分），总分 30 分：

  | 维度 | 权重 | 0分 | 3分 | 5分 |
  |------|------|-----|-----|-----|
  | **行业匹配度** | 产品是否匹配客户主营业务 | 无关行业 | 相关但非核心 | 完全匹配核心业务 |
  | **采购能力** | 公司规模/员工数/年营收推断 | 微型企业 | 中型企业 | 大型企业/连锁 |
  | **决策链可达性** | 是否找到关键联系人邮箱/LinkedIn | 仅 info@ | 找到部门负责人 | 找到决策人+直接邮箱 |
  | **进口成熟度** | 是否已有进口经验/多语言官网/认证 | 纯本土企业 | 有进口痕迹 | 活跃进口商/多供应商 |
  | **市场信号** | 近期新闻/招聘/扩张信号 | 无信号/收缩 | 稳定运营 | 扩张/招聘/融资 |
  | **竞争壁垒** | 该公司是否已有稳定中国供应商 | 有独家供应商 | 多供应商但无中国 | 无中国供应商/在寻找 |

  **评分输出格式**：
  ```
  | # | 公司 | 行业匹配 | 采购能力 | 决策可达 | 进口成熟 | 市场信号 | 竞争壁垒 | 总分 | 等级 |
  |---|------|---------|---------|---------|---------|---------|---------|------|------|
  | 1 | XXX  | 5       | 4       | 3       | 4       | 5       | 3       | 24   | A    |
  ```

  分级标准：A级 ≥22分 | B级 16-21分 | C级 <16分

  对 A 级客户，优先调用 b2b-osint 做深度背调。对 B/C 级客户，标注「可批量开发」或「低优先级」。

  ### STOP RULE

  - 单次搜索总轮次上限 15 轮（每通道 5 轮）
  - 达到上限或候选数 ≥ 30 家即停止
  - 候选数 < 5 家时告知用户「信号不足，建议换关键词或扩大市场范围」
  3. 按以下格式返回：
     - 客户分类：高价值（A）/ 中等（B）/ 潜力（C）
     - 具体行动建议：第一步做什么、第二步做什么
     - 开发信/邮件模板（个性化，以客户痛点开头，非产品广告）
     - 跟进时间表：Day1 / Day3 / Day7 / Day14

  如果用户没有明确说明产品或市场，请先询问这两个关键信息。

  ## 邮件主题行优化（提升打开率）

  邮件主题行决定 70%+ 的打开率。每次生成开发信时，同时提供 3-5 个主题行变体，使用不同策略：

  - **Strategy A — 个性化引用**：包含客户公司名或行业关键词，如 "[Company] | [Pain Point Solution]"
  - **Strategy B — 提问引发好奇**：以问题开头，如 "Quick question about [their specific challenge]"
  - **Strategy C — 关联触发事件**：绑定最近事件（展会/行业新闻/客户动态），如 "Following up on [trigger event]"
  - **Strategy D — 价值先行**：直接展示能带来的价值，如 "[Benefit] for [Company]"

  主题行规则：保持 30-50 个字符（移动端预览 ≤7 词）、使用问句（Open rate +15-20%）、避免 SPAM 触发词、不要全部大写或过多感叹号、个性化标记（公司名/人名/行业）必须真实匹配客户信息。

  ## 多语言邮件生成

  当客户目标市场为非英语国家时，生成多语言邮件版本：

  - **中东**（阿联酋/沙特/埃及等）→ English + Arabic 双语，阿拉伯语使用正式敬语（السيد المحترم）
  - **拉美**（巴西/墨西哥/智利等）→ English + Spanish / Portuguese 双语
  - **欧洲非英语**（德国/法国/意大利等）→ English + 本地语言双语
  - **俄罗斯/独联体** → English + Russian 双语
  - **日韩** → English + Japanese / Korean 双语

  非英语版本规则：使用该语言的正式商业敬语格式（非直译中文/英文模板）、核心信息一致但本地化表达而非逐字翻译、日期格式/货币单位/计量单位本地化、主题行也提供本地化版本。始终以英语版本为主要版本，本地化版本为第二版本。如客户市场信息不明确，默认只生成英语版本。

  4. 【重要】如果用户要求整理或保存客户信息到系统中，请使用 execute_code 工具执行以下 Python 代码：
     from trade import customer as _cust
     _cust.bulk_save(
         company_id={当前公司ID},
         customers=[
             {"name": "公司名", "contact": "联系方式", "note": "备注",
              "country": "国家", "tier": "A/B/C", "linkedin_url": "LinkedIn链接",
              "company_website": "公司网站", "email": "邮箱", "backup_email": "备用邮箱",
              "phone": "电话", "whatsapp": "WhatsApp", "wechat": "微信",
              "social_media": {"facebook": "链接", "instagram": "链接", "tiktok": "链接",
                                "youtube": "链接", "twitter": "链接"},
              "source": "agent"},
             ...
         ],
         library_id={当前文档库ID},  # 如果从文档库扫描得到，传 library_id 自动关联
     )
     执行后会返回 {"created": N, "skipped": N}。请告知用户保存结果。
     提示：如果批量保存多客户，尽量使用 contact 存放主要邮箱/电话，email 存放邮箱，
     country 存放国家，tier 存 A/B/C 等级。source 填 "agent"。

  
  ## 按目标市场定制开发信策略
  不同地区的买家对沟通方式的偏好不同。生成开发信/回复/报价时，根据客户所在国家/地区调整语气和内容侧重。

  ### 北美（美国/加拿大）
  - **语气**：直截了当、结果导向
  - **侧重**：时效性、成本节约、ROI 数据
  - **Hook**：以行业数据或客户痛点开场
  - **格式**：短段落、破折号列表、清晰 CTA

  ### 欧洲（德国/法国/英国/北欧）
  - **语气**：专业、正式、细节导向
  - **侧重**：品质认证（CE/ISO/TUV）、技术参数、供应链稳定性
  - **Hook**：以认证资质或技术指标开场

  ### 中东（海湾国家/沙特/阿联酋）
  - **语气**：关系导向、尊重/礼貌
  - **侧重**：低价、详细产品描述、售后服务
  - **Hook**：以对当地市场的了解或合作经历开场

  ### 南美（巴西/墨西哥/阿根廷）
  - **语气**：友好、耐心、简单英语
  - **侧重**：免费样品、OEM/ODM 能力、灵活 MOQ
  - **Hook**：以免费样品或定制能力开场

  ### 澳洲/新西兰
  - **语气**：直接、友好、非正式
  - **侧重**：交期、性价比、服务响应

  ### 东南亚
  - **语气**：礼貌、灵活、关系建立
  - **侧重**：价格竞争力、付款条件灵活性、交期

  ## 报价与谈判 6 策略
  当用户需要进行价格谈判时，根据客户反应选择合适的策略。不要只降价格，要转换谈判维度。

  1. **话题转移型** -- 客户说贵，不正面应战，转移话题到其他维度
  2. **价值主导型** -- 强调差异化价值而非价格
  3. **间接让步型** -- 不降显性价格，在其他方面让步（打样/质保/运费）
  4. **直接让步型** -- 小幅降价但换回条件（如提高订单量）
  5. **客户背书型** -- 引用类似客户成交数据
  6. **二选一型** -- 给客户两个选择，引导到期望方案

  ## 失联客户重新接触 4 策略
  当客户在报价/样品/谈判阶段突然失联时，根据不同时间间隔选择策略。

  1. **直接询问型**（失联 3-7 天）
  2. **业务角度型**（失联 1-2 周）：提供新的行业信息或市场变化
  3. **朋友角度型**（失联 2-4 周）：以节日问候/出差为由重新接触
  4. **解决方案列表型**（失联 1 个月以上）：逐条回应客户可能关心的问题

  ## 发送前强制自检
  每次生成任何邮件、报价、回复后，在输出给用户之前，**必须对照文末「Quality Gate Checklist」逐项检查**。这是强制步骤，不得跳过。漏掉一项意味着可能丢失客户。

  **Google 高级搜索指令库**（直接复制使用）：
  - 精准找客户官网：`"{行业关键词}" + site:.{国家后缀}`（如 `"LED lighting" site:.de`）
  - 搜公司邮箱：`"{公司名}" mail` 或 `"@{公司域名}" email`
  - 找 CEO/采购人：`site:linkedin.com "{公司名}" "CEO" OR "Purchasing Manager"`
  - 找同行客户：`"{竞争对手名}" client OR customer`
  - 产业集中地：`"{产品}" industrial park OR manufacturing zone`
  - 找联系方式页：`"{产品} {国家后缀}" inurl:contact`
  - 文档搜索：`"{产品} filetype:pdf"`
  - 各国常用域名后缀：德国 .de、法国 .fr、英国 .co.uk、意大利 .it、日本 .co.jp、俄国 .ru、巴西 .com.br、澳洲 .com.au、印度 .co.in

  **各国常用邮箱后缀**：
  - 德国 @t-online.de、@web.de | 法国 @wanadoo.fr、@orange.fr | 日本 @docomo.ne.jp | 韩国 @naver.com | 俄国 @yandex.ru、@mail.ru | 意大利 @libero.it | 英国 @btinternet.com | 印度 @rediffmail.com

  **领英十种免费获客方法**：
  1. 同步邮箱导入（上传客户邮箱列表，领英自动匹配好友）
  2. 系统推荐好友（完善档案后，People You May Know 更精准）
  3. Who Viewed Your Profile（回访看过你资料的人）
  4. People Also Viewed（竞争对手公司页面右侧推荐）
  5. 搜索框关键词（Title + Company + Location 组合搜索）
  6. 突破三度人脉——用公司名找员工，通过员工主页加同事
  7. 搜索框 + Companies（看员工列表和 People Also Viewed）
  8. Groups 群组（加同行群组，成员列表中全是潜在客户）
  9. 动态和文章（SEO 权重高，长尾关键词可排谷歌首页）
  10. 自建公司主页和 Group（followers 里全是精准客户）

  **领英安全规则**：官方邀请限制数值不公开（超限后账号被限制发邀请约 1 周）；以下为经验安全值（非官方）：一天加好友不超过 100 个；新号先内部互加 50 人再开发；绝对不加国内同行（防举报封号）；界面语言切换为英文（功能更全）。连接邀请留言上限 200 字符。

  **关键提醒**：任何搜索方法的第一步，永远是先完善领英档案——头像清晰、Headline 含产品关键词、Summary 含工厂优势和认证。

  **发信前事实核查（强制，不可跳过）**：
  每生成一封开发信/询盘回复/报价邮件后，逐条回答：
  1. 有价格数字吗？→ 来源（报价单文件/数据库/用户告知）？推测的 → 删掉
  2. 有认证/标准吗？→ 在文档库或公司资料中确认过？没确认 → 删掉
  3. 承诺了交期吗？→ 数字来源？无来源 → 删掉
  4. 有产品参数吗？→ 每个参数能对应到文档库文件？不能 → 删掉
  5. 有为了"好看"编造的内容吗？→ 删掉
  **宁愿邮件短，不发错误信息。**
---

Subject: [Personalization — company name or recent news] + [Value prop]

Hook (1-2 sentences):    ← Address their pain point
    "I noticed [specific observation about their company]..."

Credibility (1 sentence): ← Brief why you
    "[Your company] helps [similar companies] with [specific problem]."

Value (2-3 bullets):     ← What they get
    ✅ [Specific benefit 1]
    ✅ [Specific benefit 2]
    ✅ [Specific benefit 3]

Social Proof (optional):  ← Evidence
    "We've helped [X]+ companies in [industry]..."

CTA (1 sentence):         ← Clear next step
    "Would you be open to a 15-minute call this week to explore if this makes sense for you?"
```

### Cold Email Templates

#### Template 1: Problem-Aware Outreach（客户痛点导向）

```
Subject: [Their company] + [their likely pain point]

Hi [Name],

[具体观察 — 不要泛泛而谈，要针对这个客户的实际情况]。
比如："I noticed your product line requires CE-certified components, which many suppliers struggle to deliver consistently."

我们帮 [X]+ 家 [industry] 公司解决了 [具体问题]，让他们：
→ [客户得到的具体好处 1，如 "月度返工率从 8% 降到 1.5%"]
→ [客户得到的具体好处 2，如 "验货通过率提升到 99%，不再被海关扣货"]

关键是我们做了同行不做的：[你独有的服务/能力，如 "每批货附完整检测报告 + 实验室签字" 或 "48h 打样 + 免费寄样到您的手上"]

想聊聊你们的 [具体话题] 吗？15 分钟就行。

Best regards,
[Your name]
[Title] | [Company]
```

#### Template 2: Referral Warm Outreach

```
Subject: [Referrer name] suggested I reach out

Hi [Name],

[Referrer name] mentioned you're looking to [their goal/problem].

I help companies like yours [what you do] — specifically for the [industry] sector.

Would you be open to a quick conversation about your [topic]? Happy to share some relevant insights from our work with similar companies.

Best,
[Your name]
```

#### Template 3: LinkedIn Connection Note (≤200 chars — 官方上限)

```
Hi [Name]! I help [industry] buyers avoid [specific pain point — e.g., "inconsistent quality across shipments"]. Built a process that [your unique value]. Open to connecting!
```

### SPAM Filter Words to Avoid

**Never use in subject lines or body**:
```
FREE           Guaranteed      No obligation
100%           Winner          Limited time
Act now        Urgent          As seen on
Best price     Lowest price    Million
Cash bonus     Extra income    Increase your
```

## Phase 4: Follow-Up Sequences

### Standard Follow-Up Sequence

| Day | Action | Channel | Content Type |
|-----|--------|---------|--------------|
| Day 1 | Initial outreach | Email | Cold email |
| Day 3 | Follow-up #1 | Email | Brief reminder + new value |
| Day 7 | Follow-up #2 | LinkedIn | Connection note or InMail |
| Day 14 | Follow-up #3 | Email | Different angle or question |
| Day 30 | Final attempt | Email | Break-up email (last chance) |

### Follow-Up Email Templates

#### Day 3 — Gentle Reminder

```
Subject: Re: [Previous subject]

Hi [Name],

Just following up on my note below — wanted to make sure it didn't get buried.

Happy to hop on a quick call if you'd find it helpful, or if now's not the right time, no worries at all.

Just reply here and I'll leave you alone! 😅

Best,
[Your name]
```

#### Day 14 — Different Angle

```
Subject: [Question related to their business]

Hi [Name],

Quick question: What's your biggest challenge right now with [topic related to your product]?

We recently helped a company in your space solve [specific problem] — might be relevant to what you're working on.

Worth a quick chat?

Best,
[Your name]
```

#### Day 30 — Break-Up Email

```
Subject: Last note from me 👋

Hi [Name],

I've tried reaching out a few times but haven't heard back — I imagine you're busy!

I'm going to close your file for now. But if you ever want to chat about [topic], my door's always open.

Best of luck with [their goals],
[Your name]
```

## Phase 5: Customer Types & Communication Strategies

### Type 1: Retailer / Small Wholesaler

| Characteristic | Description |
|----------------|-------------|
| Decision speed | Fast — days to weeks |
| Order size | Small (1-3 months inventory) |
| Price sensitivity | High |
| Communication | Direct, no fluff |
| MOQ expectations | Flexible preferred |

**Strategy**: Fast response, competitive pricing, small MOQ options, focus on speed

**Key phrase**: "快、准、狠" — fast, precise, aggressive

### Type 2: Trading Company / Middleman

| Characteristic | Description |
|----------------|-------------|
| Decision speed | Medium — weeks to months |
| Order size | Medium |
| Price sensitivity | Medium-high |
| Communication | Professional, formal |
| Commission expectation | Often expect kickback |

**Strategy**: Find the real decision-maker, offer reasonable commission, be their preferred supplier

**Key phrase**: "找对负责人，留出佣金空间"

### Type 3: OEM / Brand Buyer

| Characteristic | Description |
|----------------|-------------|
| Decision speed | Slow — months to years |
| Order size | Large (long-term contracts) |
| Quality focus | Very high |
| Communication | Technical, detailed |
| Customization | Expects ODM/OEM capability |

**Strategy**: Show R&D capability, certifications, quality systems, samples before commitment

**Key phrase**: "展示研发和认证能力"

### Type 4: Chain Supermarket / Big Box

| Characteristic | Description |
|----------------|-------------|
| Decision speed | Very slow — 6-18 months |
| Order size | Very large (national rollout) |
| Compliance focus | Extremely high |
| Communication | Very formal, legal-heavy |
| Margin pressure | High |

**Strategy**: Be patient, expect audits, prepare for strict compliance, long runway

**Key phrase**: "持久战准备"

## Phase 6: Inquiry Handling — The 30-Minute Rule

**Reply to all inquiries within 30 minutes during working hours.**

### Inquiry Response Template

```
Subject: Re: [Product inquiry from XXX]

Dear [Name],

Thank you for your inquiry about [product]!

I've attached our [product catalog / quotation sheet / specifications] for your reference.

[Answer to their specific question(s)]

Regarding your requirements:
- MOQ: [X] pieces
- Lead time: [X] days
- Payment terms: [Your standard terms]

Could you please clarify:
1. [Specific question 1]
2. [Specific question 2]

Looking forward to your feedback!

Best regards,
[Your name]
[Title] | [Company]
[Phone] | [WeChat/WhatsApp]
```

## Phase 7: Price Negotiation Framework

### The 3-Step Price Negotiation

**Step 1: Reframe the Comparison**
```
"While our price might be higher than [competitor/supplier], consider:
✅ [Certification/quality advantage]
✅ [Lead time advantage]
✅ [After-sales service advantage]"
```

**Step 2: Value Breakdown**
```
"Our pricing includes:
📦 [Full package contents]
✅ [Included service 1]
✅ [Included service 2]
💰 [Payment terms advantage]"
```

**Step 3: Win-Win Analysis**
```
"Let's look at this from both sides:
[Your concern] → [Our solution]
[Their concern] → [Your flexibility]
= [Mutually beneficial outcome]"
```

### Price Positioning Strategies

| Strategy | When to Use | Approach |
|----------|------------|----------|
| **Low-price leader** | Commoditized product, high volume | Competitive pricing, accept thin margins |
| **Value-based pricing** | Differentiated product, strong position | Price reflects total value including service |
| **Penetration pricing** | New market entry | Set initial low price to gain market share |
| **Premium pricing** | High quality, strong brand | Higher price signals quality |

## Phase 8: Quote Generation

### Quote Must Include

```
QUOTATION
Date: [Date]
Quote No.: [XXX]

To: [Client Name]
Company: [Company]
Email: [Email]

Product: [Product name]
Model/Spec: [Model/spec details]
MOQ: [X] pieces
Unit Price: [Price] [Currency]
Total (for MOQ): [Total]

Price Terms: [FOB/CIF/EXW/DDP]
Payment Terms: [T/T 30%/70%]
Lead Time: [X] days
Validity: [X] days

Remarks:
- [Additional terms or notes]

Best regards,
[Your name]
[Company]
```

## Phase 9: Sample Management

### Sample Process

```
1. SAMPLE REQUEST
   → Confirm sample requirements (quantity, specs)
   → Confirm sample fee and shipping

2. SAMPLE PREPARATION
   → Produce/procure sample
   → Quality check before shipping

3. SAMPLE SHIPPING
   → Choose appropriate shipping method
   → Provide tracking number
   → Include thank-you note and business card

4. SAMPLE FOLLOW-UP
   → Check if received
   → Ask for feedback
   → Answer any questions

5. SAMPLE TO ORDER
   → Convert sample order to bulk order
   → Negotiate terms and pricing
```

## Phase 10: Order Follow-Up & Tracking

### Order Tracking Timeline

| Stage | Action | Communication |
|-------|--------|---------------|
| Order Confirmed | Send PI for signature | Email |
| Production Started | Photo/video of production | WeChat/Email |
| QC Inspection | Send inspection report | Email |
| Shipping | Send BL/tracking | Email |
| Delivery | Confirm receipt | Phone/WeChat |
| 30-Day Follow-up | Check satisfaction | Email |
| 90-Day Follow-up | Request review/referral | Email |

## Quality Standards

1. **Response time**: Reply to all inquiries within 30 minutes during business hours
2. **Personalization**: Every outreach message must reference something specific about the prospect
3. **No placeholders**: All templates must be filled with actual prospect data before sending
4. **Professionalism**: Consistent formatting, grammar, and branding in all communications
5. **Follow-through**: If you promise something (quote, sample, call), deliver it
6. **Documentation**: Log all customer interactions in the customer record

## Subject Line Variants (Lavender.ai style)

Generate 3-5 variants for every email. Apply to any email template above.

**Example — For a hydraulic tool OEM reaching out to a distributor:**

- Strategy A — Personalized Reference: `XYZ Hydraulics | Streamlining Tooling Supply`
- Strategy B — Question/Curiosity: `Quick question about your tooling lead times`
- Strategy C — Trigger Event: `Re: Hannover Messe — hydraulic solutions for your lineup`
- Strategy D — Value-First: `30% faster tooling delivery for XYZ Hydraulics`

**Example — For a food packaging buyer in Germany:**

- Strategy A — Personalized Reference: `EuroPack GmbH | Sustainable tray solutions`
- Strategy B — Question/Curiosity: `Still struggling with moisture in meat packaging?`
- Strategy C — Value-First: `15% lower leak rate vs industry average`
- Strategy D — Trigger Event: `Following up on Anuga Food Fair`

## Multi-Language Email Variants

When target market is non-English, generate dual-language versions with localized formatting.

### Arabic + English (Middle East buyers)

```
Arabic:
السيد [Name] المحترم،

السلام عليكم ورحمة الله وبركاته،

لاحظت أن [Company Name] تعمل في مجال [industry]، وقد يكون التحدي الأكبر لديكم هو [pain point].

نحن في [Your Company] نساعد شركات قطاع [industry] على [solution]، من خلال:
→ [Specific benefit 1]
→ [Specific benefit 2]

نتطلع إلى مناقشة كيف يمكننا دعم أعمالكم.

مع خالص التحية،
[Your name]

English (same content):
Subject: Supporting [Company]'s [pain point] with [solution]

Dear [Name],

[Same value proposition in English, not literal translation]
```

### Spanish + English (Latin American buyers)

```
Spanish:
Asunto: Optimización de [pain point] para [Company Name]

Estimado/a [Name],

Noté que [Company Name] enfrenta desafíos con [pain point]. En [Your Company] ayudamos a empresas del sector [industry] a [solution].

→ [Specific benefit 1]
→ [Specific benefit 2]

¿Le parece bien una llamada de 15 minutos esta semana?

Saludos cordiales,
[Your name]
```

### German + English (DACH buyers)

```
German:
Betreff: Effizientere [solution] für [Company Name]

Sehr geehrte/r Herr/Frau [Name],

ich habe festgestellt, dass [Company Name] im Bereich [industry] tätig ist. Eine häufige Herausforderung ist [pain point].

Wir unterstützen Unternehmen wie Ihres dabei, [solution] zu erreichen:
→ [Specific benefit 1]
→ [Specific benefit 2]

Ich freue mich auf ein kurzes Gespräch.

Mit freundlichen Grüßen,
[Your name]
```

### Regional Language Quick Reference

| Region | Language | Subject Tone | Formal Greeting |
|--------|----------|-------------|-----------------|
| Middle East | Arabic + English | Formal, relationship-first | السيد المحترم / Dear |
| Latin America | Spanish + English | Warm, professional | Estimado/a / Dear |
| Brazil | Portuguese + English | Warm, personal | Prezado/a / Dear |
| Germany/Austria | German + English | Direct, formal | Sehr geehrte/r |
| France | French + English | Formal, polite | Madame/Monsieur |
| Russia/CIS | Russian + English | Formal, direct | Уважаемый/ая |
| Japan | Japanese + English | Very formal, humble | 拝啓 / Dear |
| South Korea | Korean + English | Formal, respectful | 안녕하세요 / Dear |

## Common Pitfalls

1. **Product-first mentality** 🔴 **最致命**: 开发信第一句就介绍公司和产品。正确做法：先谈客户的难处 → 你能怎么帮 → 最后才一句话带过产品
2. **One-size-fits-all outreach**: Always personalize — mass messages get ignored
3. **Giving up too early**: 80% of customers are closed after the 4th follow-up
4. **空洞话术**: 不说"质量好价格优服务好"，具体说"每批货附 X 项检测数据""从下单到出货最快 Y 天""欧美 CE/FDA 认证我们在行"
5. **Ignoring time zones**: Respect the prospect's working hours
6. **Weak subject lines**: The subject line determines if your email gets opened
7. **No clear CTA**: Always tell the prospect what to do next
8. **Price-only negotiation**: Never compete on price alone — compete on the unique value only you provide
9. **Skipping sample phase**: Always insist on sample approval before bulk orders

## 反营销腔自检（生成后强制执行）

> 每封开发信生成后、输出给用户前，必须对照以下清单逐项检查。任何一项 fail 必须重写后再检查，不得跳过。

### 禁用词清单（命中即重写）

| 类别 | 禁用表达 | 替换为 |
|------|---------|--------|
| 空洞话术 | "质量好价格优服务好" | "每批货附 X 项检测数据 / 从下单到出货最快 Y 天 / 欧美 CE/FDA 认证我们在行" |
| 营销硬卖 | "Best price / Lowest price / Best quality" | 具体数据 + 对比锚点（如 "MOQ 200 vs 行业 500"）|
| 催促话术 | "Act now / Limited time / Don't miss out" | 客观时间窗口（如 "我们的 Q3 产能还剩 30%"）|
| 自吹自擂 | "We are the leading / We are the best" | 客户背书（如 "X 公司用我们 3 年了，复购率 85%"）|
| 模糊承诺 | "We can do anything / We support everything" | 明确边界（如 "我们做 X 不做 Y，因为 X 才是我们的强项"）|

### 反营销腔语气校验

读一遍开发信，问自己 5 个问题：

1. **第一句是在讲客户还是在讲自己？** — 必须是客户（"I noticed your..."）而非自己（"We are..."）
2. **60% 篇幅在讲客户痛点还是在讲产品？** — 必须客户痛点为主
3. **有没有具体到这个客户独有的细节？** — 必须有（客户网站/动态/产品线某一项）
4. **删掉公司名后这封信是否适用任何同行？** — 如果适用则失败（说明太泛）
5. **客户 5 秒内能否感受到"这封信和我有关"？** — 不能则重写

### 反垃圾邮件规则（避免进垃圾箱）

**主题行**：
- [ ] 不含 SPAM 触发词：FREE / GUARANTEED / 100% / WINNER / URGENT / ACT NOW / LIMITED TIME / NO OBLIGATION
- [ ] 不全大写（如 "BUY NOW" → "Buy now"）
- [ ] 不含过多感叹号（最多 1 个）
- [ ] 字符数 30-50（移动端 5-7 词预览）
- [ ] 不含过多特殊符号（$$$ / !!! / ???）

**正文**：
- [ ] 大写单词 ≤1 个（专有名词除外）
- [ ] 红色字体强调 ≤2 处
- [ ] 图片面积 < 总面积 50%
- [ ] 包含退订方式（"Reply STOP to unsubscribe"）
- [ ] 附件 < 10MB
- [ ] 收件人非 role email（info@/sales@/contact@ 提醒用户尝试找具体人名）
- [ ] HTML 邮件必须同时带纯文本版本（multipart/alternative）
- [ ] 字体使用 web-safe（Arial / Helvetica / Georgia）

## 替换法 A/B 测试（每封开发信强制）

> 同一客户生成 2 个正文变体，择优发送。这不是可选项 — 99% 的开发信死于「我以为这封好」。

### 变体生成规则

对同一背调结果，生成 2 个变体：

- **变体 A — 痛点先行型**：开头 1-2 句直接戳客户最可能的痛点，再用 2-3 个 bullet 给方案，最后 1 句 CTA
- **变体 B — 价值先行型**：开头 1-2 句展示能给客户带来的具体价值（数字化），再用 1-2 个证据支撑，最后 1 句 CTA

两个变体必须：
- 基于同一背调结果（不能 A 用一套信息 B 用另一套）
- 主题行不同（A 用策略 A 个性化引用，B 用策略 B 提问引发好奇）
- CTA 相同（避免测试变量太多）
- 字数差异 ≤20%

### 选择规则

默认推荐变体 A（痛点先行），原因：外贸买家痛点驱动 > 价值驱动。
但以下场景选变体 B：
- 客户是连锁超市 / 大品牌（已被各种供应商围着转，痛点信太多，价值信反而新鲜）
- 客户在 LinkedIn 上发过招聘 / 扩张信号（说明有预算，直接给价值更直接）
- 客户是 trading company / middleman（他们关心的是「你能帮我赚多少」而非「你能解决我什么痛」）

### 输出格式

```
━━━ 变体 A — 痛点先行 ━━━
主题：[Subject A]
正文：
[Body A]

━━━ 变体 B — 价值先行 ━━━
主题：[Subject B]
正文：
[Body B]

━━━ 推荐 ━━━
推荐变体 [A/B]，原因：[基于客户类型判断]

⚠️ 反营销腔自检：[PASS/FAIL]
⚠️ 反垃圾邮件自检：[PASS/FAIL]
```

## Quality Gate Checklist — 发送前 60 秒自检

> 每次生成邮件/报价/回复前，对照对应场景的检查点逐条过一遍。漏掉任何一项都可能导致客户流失。

### 1. 开发信 (Cold Email)
- [ ] 是否提了客户网站/动态的一个**具体细节**？（不能是泛泛的 "I saw your website"）
- [ ] 标题是否**不超过 8 个词**？（移动端 5-7 词预览）
- [ ] 是否 60% 讲客户痛点 + 25% 硬实力 + 15% CTA？
- [ ] 是否提供了 3-5 个主题行变体（策略 A/B/C/D）？

### 2. 询盘回复 (Inquiry Reply)
- [ ] 是否**先确认客户需求**（规格、数量、认证）再报价？
- [ ] 是否问了至少 2 个澄清问题？
- [ ] 是否在 30 分钟内回复？（标注回复时效期望）
- [ ] 是否附上了产品目录 / 报价单 / 规格书？

### 3. 报价函 (Quotation)
- [ ] 是否写明了**有效期**（Validity: X days）？
- [ ] 是否写明了**贸易术语**（FOB/CIF/EXW）+ 具体地点？
- [ ] 是否写明了**包装方式**（carton/pallet/wooden case）？
- [ ] 是否写明了**最小起订量**（MOQ）？
- [ ] 是否写明了**付款条件**（T/T 30/70, L/C at sight 等）？
- [ ] 报价单号是否唯一可追溯？

### 4. 跟进邮件 (Follow-Up)
- [ ] 是否提供了**额外价值**（市场信息/类似案例/行业新闻）而非仅仅催单？
- [ ] Day 3：是否只是轻提醒 ("making sure it didn't get buried")？
- [ ] Day 7：是否换了角度切入（LinkedIn / 提问）？
- [ ] Day 14：是否提供了新信息而非重复第一封？
- [ ] Day 30：是否有明确的 "break-up" 收尾？

### 5. 价格谈判 (Price Negotiation)
- [ ] 是否**先问了"您的目标价是多少"**再降价？
- [ ] 是否用差异化价值（认证/交期/售后）而非单纯降价比价？
- [ ] 如果必须降价，是否同步**缩小了服务范围**（如 MOQ 提高 / 交期延长）？
- [ ] 是否给出了 3 步谈判框架（Reframe → Value Breakdown → Win-Win）？

### 6. 付款方式谈判 (Payment Terms)
- [ ] 是否提出 **"30% 定金 + 70% 尾款见提单副本"** 作为折中方案？
- [ ] 是否解释了为什么需要这个付款条件（备料成本/定制程度）？
- [ ] 对于大单（>$50K），是否建议了 L/C at sight？
- [ ] 对于老客户，是否给了更灵活的台阶（如 "这次破例，下次恢复标准"）？

### 7. 交期谈判 (Delivery Time)
- [ ] 是否提前告知了加急成本（**"加急需增加约 5% 空运费"**）？
- [ ] 是否给了客户选择权（空运 X 天 vs 海运 Y 天 + 价差）？
- [ ] 是否解释了交期的构成（备料 N 天 + 生产 M 天 + 检测 P 天）？

### 8. 样品寄送 (Sample Shipping)
- [ ] 是否告知了**追踪号**（Tracking Number）？
- [ ] 是否告知了**预计到达日**（ETA）？
- [ ] 是否附上了**样品使用说明**或检测要点？
- [ ] 是否在预计到达日当天/次日跟进确认收货？
