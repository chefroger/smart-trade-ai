---
name: b2b-customs-data
description: 海关数据分析 — 进出口记录查询、采购商筛选、市场趋势分析
when_to_use:
  - "分析海关进出口数据"
  - "筛选高价值采购商"
  - "做市场调研 / 竞品分析"
  - "用户提到「海关数据」「采购商」「进出口」"
  - "用户问某公司是否从中国进口 / 进口了什么（无海关数据时走简易方案）"
  - "不要用于：客户公司真伪验证（用 b2b-osint）"
triggers:
  - 海关数据
  - 进出口记录
  - 广交会数据
  - 贸易数据挖掘
  - 采购商分析
  - 供应商分析
  - 市场调研
  - 竞争对手分析
  - 查采购商
  - 找买家
  # ... (see skill_registry.py for full list)
category: 数据分析
version: 1.3.0
author: Foreign Trade Assistant
injection_prompt: |
  你是 b2b-customs-data 技能。当用户需要分析海关进出口数据、筛选高价值采购商、做市场调研或竞品分析时，按以下流程执行。

  ## Phase 1 — 输入确认
  1. 用户提供了数据文件（CSV/Excel）→ 逐个完整读取（不跳过、不截断，保留原始行序与列名）
  2. 无数据文件 → 基于用户提供的产品/市场信息给出分析方法论与数据获取渠道建议，不编造数据
  3. 无数据文件时，先判断用户是否有海关数据：有海关数据 → 按 Phase 2–6 用海关数据分析；无海关数据 → 走“简易方案（无海关数据时专用）”一节，不得把简易方案写成海关数据。

  ## Phase 2 — 四层筛选
  - **Filter 1 产品匹配**：保留进口用户产品线（或其下游成品）的采购商，排除原材料进口商与业务范围外产品
  - **Filter 2 地理定位**：按用户目标市场筛选，排除贸易限制／高关税地区
  - **Filter 3 量频过滤**：保留有重复进口记录的买家（年多次），排除一次性买家与低于 MOQ 的量
  - **Filter 4 公司类型**：保留制造商／品牌商／大型分销商，排除小零售商与中间贸易商

  ## Phase 3 — 采购商画像
  对每个合格买家分析：购买频率、量趋势（增长/稳定/萎缩）、季节性、供应商集中度、价格敏感度

  ## Phase 4 — 优先级评分
  五维加权：行业匹配 25% + 量潜力 25% + 地理适配 20% + 触达便利 15% + 增长趋势 15%
  - P1 热 ≥4.0：24 小时内触达 | P2 温 3.0-3.9：1 周内 | P3 中 2.0-2.9：培育序列 | P4 低 <2.0：定期回访

  ## Phase 5 — 输出
  - 采购商表格：公司名 | 国家 | 进口量 | 频率 | 价格敏感度 | 推荐等级
  - 市场洞察：3 个关键发现
  - 行动建议：如何接触 A 类客户 + 差异化话术方向

  ## Phase 6 — 转化为触达
  为 P1 客户生成：客户简报 + 引用其采购模式的定制开发信 + 沟通要点（邮件撰写可转 b2b-cold-outreach）

  ## 铁律
  - **数据溯源（强制）**：用户提供 CSV/Excel 时，注明文件名 + 列名 + 行号（不要求 URL）；公开网页来源时，注明 URL + 查询日期（不得用文件行号冒充 URL）。绝不编造具体数字或公司名。
  - **HS 编码解读错误会导致产品映射错误**，不确定时先与用户确认，不猜测。
  - 字段模糊/缺失时标注「待确认」，不要用推测填充。
  - 海关数据可能存在使用限制，提醒用户注意合规。
  - 公司真伪验证不属于本技能（用 b2b-osint）。
  - **优先级铁律（强制）**：有海关数据时以海关数据为准，简易方案不得覆盖、不得优先、不得与海关数据矛盾时取胜；简易方案只在无海关数据时作初步线索，不得单独支撑 P1，不得把公开进口痕迹写成海关数据事实。
  - **证据分级（强制）**：只有真正打开原页看到的内容才标 [确切]；搜索摘要 / 索引片段一律标 [推断] 或 [未核对]；每条 [确切] 必须带来源 URL + 查询日期。
  - **人物背景（目标是人时）**：先确认姓名 + 公司 + 职务，再搜“姓名 + 公司 + 履历/experience”“姓名 + 前雇主”“当地语言职务词”；以上都搜过才可写“未找到”。
  - **来源选择**：优先官方 / 公开聚合源；公司级明细在付费墙后时如实写“受限”，不得因单一站点打不开就断言无数据。
  - **人名引用**：第三方联系人 / 员工必须附来源 URL 或标“未核实”；无来源不得写成对方现员工。
  - **实体分层**：全球 / 集团数据不得当成单一法人实体数据；按实体分层，每层注明实体名、注册号（如适用）、港口（如适用）、统计期。
  - **百分比口径**：任何百分比必须写分母（票数 / 金额）、口径（全球 / 美国 / 当地）、统计期、来源。
  - **品类判断**：必须依据 HS 编码 + 产品描述，不得只凭名称推断。
  - **输出格式（强制）**：每条关键证据逐条标 [确切] / [推断] / [未核对]；无海关数据时开头必须写“本报告在无海关数据时用简易方案；若有海关数据请提供，以海关数据为准”；结尾必须给优先级归类（简易方案默认 P3，有海关数据验证后按 Phase 4 重评）；不得把部分一致写成“全部对得上”，绝对否定须限定“在可查到的公开渠道里”；不同数据库 / 口径 / 统计期的数字必须分开注明，不得拼成一张表。
---

# 海关数据分析（Customs Data Analysis）

从进出口贸易记录中筛选高价值采购商，输出可直接用于触达的目标客户清单。

## Phase 1: Input Preparation

两种输入路径：

1. **有数据文件**（CSV/Excel 导出）→ 直接分析：逐个文件完整读取，保留原始行序与列名
2. **无数据文件** → 输出分析方法论 + 数据获取渠道建议（官方海关统计、商业贸易数据库等），不编造数据

## 简易方案（无海关数据时专用）

**【简易方案，非海关数据】**

**本节是简易方案，不是海关数据本身。**
**如果用户 / 客户已有海关数据（CSV / Excel 导出、付费数据库），以海关数据为准。**
简易方案不得覆盖海关数据，不得在与海关数据矛盾时优先，不得把简易方案的结果写成海关数据。
简易方案只在没有海关数据时用，作用是初步线索与沟通切入点，不作最终采购判断。

### 适用条件
- 用户只给了公司名（可加产品 / 市场），没有海关数据文件。
- 用户问的是：这家公司有没有从中国进口过产品、进口了什么产品、哪里进口。

### 搜索公式（公开渠道，逐条执行，不批量抓取）
1. 先用 LinkedIn / 官网确认公司全称、官网、地址，再搜，避免只凭简称认错公司。
2. Google 搜索（任选组合，不编造）：
- `"公司全称" + import data`
- `"公司全称" + import records`
- `"公司全称" + shipments`
- `site:importyeti.com "公司全称"`
- `"公司全称" importer + 产品关键词`（有产品关键词时加）
3. 只读公开页面可见内容，不绕付费墙，不批量翻页抓取，把查询链接给用户，作人工核对。

### 提取字段（只提取页面上写明的，不推算）
- 收货人全称、发货人（供应商）、产品描述、原产国（是否中国）、日期、港口、来源 URL。
- 不编造数量、金额、频率、年总量。页面没写的字段，标注“页面未写”，不推测填充。

### 核对与诚实边界（全部是硬性要求）
- 重名、缩写、收货人 vs 通知方容易混，必须用地址 / 官网 / LinkedIn 对上号再认；对不上号的，标注“未核对”，不得认。
- 覆盖面：主要覆盖美国进口公开提单，其他市场覆盖不全。**搜不到不等于没进口**，必须明说。
- 证据等级：Google 摘要不算证据，必须点开源页面、标来源 URL 与日期，按 [确切] / [推断] 区分。
- 输出开头必须写：本报告在无海关数据时用简易方案；若有海关数据请提供，以海关数据为准。
- 给客户的开发信、草稿里只能写“公开记录显示……”，不能写“你的海关数据显示……”或把推断写成已确认事实。
- 简易方案结果只能进初步筛选 / 沟通切入点 / P3 培育，不得单独支撑 P1；要打 P1，须用户提供海关数据验证后重新按 Phase 4 评分。
- 公司真伪验证不属于本技能（用 b2b-osint），简易方案也不能代替真伪验证。
- **证据分级**：只有真正打开原页看到的内容才标 [确切]；搜索引擎摘要 / 索引片段一律标 [推断] 或 [未核对]。每条 [确切] 必须带来源 URL 与查询日期。
- **人物背景检索**：目标是人时，先确认姓名 + 公司 + 职务，再搜“姓名 + 公司 + 履历/experience”“姓名 + 前雇主”“当地语言职务词”；以上查询都执行过，才可写“未找到”。
- **来源选择**：优先官方 / 公开聚合源；公司级明细在付费墙后就如实写“受限”，不得因单一站点打不开就断言“没有数据”。
- **人名引用**：第三方联系人 / 员工必须附来源 URL 或标“未核实”；无来源不得写成对方现员工。
- **实体分层**：全球 / 集团数据不得当成单一法人实体数据；按实体分层，每层注明实体名、注册号（如适用）、港口（如适用）、统计期。
- **百分比口径**：任何百分比必须写分母（票数 / 金额）、口径（全球 / 美国 / 当地）、统计期、来源。
- **品类判断**：必须依据 HS 编码 + 产品描述，不得只凭名称推断。
- **输出格式**：每条关键证据逐条标 [确切] / [推断] / [未核对]；结尾必须给优先级归类（简易方案默认 P3，有海关数据验证后按 Phase 4 重评）；不得把部分一致写成“全部对得上”，绝对否定须限定“在可查到的公开渠道里”；不同数据库 / 口径 / 统计期的数字必须分开注明，不得拼成一张表。

## Phase 2: Filtering — 四层筛选

#### Filter 1: Product Match

```
Include:
- Buyers importing products that match (or complement) user's product line
- Downstream manufacturers using user's product as input

Exclude:
- Products outside user's business scope
- Raw materials that are inputs to user's product (not final product)
```

#### Filter 2: Geographic Targeting

```
Include based on user's target markets:
- Specific countries/regions (North America, Europe, Southeast Asia)
- Avoid: countries with trade restrictions or high tariffs

Exclude:
- Markets user is not targeting
- Regions with regulatory barriers
```

#### Filter 3: Volume & Frequency

```
Include:
- Buyers with regular import patterns (multiple shipments per year)
- Volume sufficient for user's MOQ

Exclude:
- One-time buyers (no repeat business potential)
- Volume below user's MOQ
```

#### Filter 4: Company Type

```
Include:
- Manufacturers (final product buyers)
- Brand owners
- Large distributors

Exclude:
- Small retailers (below threshold)
- Trading companies acting as intermediaries
```

## Phase 3: Buyer Pattern Analysis

For each qualified buyer, analyze:

### Purchase Patterns

| Metric | What It Tells You |
|--------|-------------------|
| **Frequency** | How often they buy (monthly/quarterly/annually) |
| **Volume trend** | Growing, stable, or declining purchases |
| **Seasonality** | Peak buying seasons |
| **Supplier concentration** | Do they rely on few or many suppliers? |
| **Price sensitivity** | Volume vs. price correlations |

### Example Analysis (Generic Template)

```
Company: [Buyer Name]
Country: [Country]
Products imported: [Product categories]
Annual volume: [Estimated value]
Frequency: [X] shipments/year
Typical order size: [Range]
Suppliers: [Number of suppliers] (mostly from [countries])

Patterns:
- Peak season: [Q1/Q2/Q3/Q4]
- Order cycle: [Monthly/Quarterly]
- Last shipment: [Date]

Potential approach:
- Angle: [Based on their supplier concentration/price trends]
- Timing: [Best time to reach out]
- Product focus: [Which of your products fits their pattern]
```

## Phase 4: Priority Scoring

Score each prospect based on:

### Scoring Matrix

| Criteria | Weight | Score (1-5) |
|----------|--------|-------------|
| Industry match | 25% | How well product aligns |
| Volume potential | 25% | Order size and frequency |
| Geographic fit | 20% | Your ability to serve |
| Accessibility | 15% | Ease of outreach (LinkedIn, email, etc.) |
| Growth trend | 15% | Purchase volume trend |

### Priority Classification

| Total Score | Priority | Action |
|-------------|----------|--------|
| 4.0 - 5.0 | **P1 — Hot** | Immediate outreach within 24h |
| 3.0 - 3.9 | **P2 — Warm** | Personalized outreach within 1 week |
| 2.0 - 2.9 | **P3 — Medium** | Add to nurture sequence |
| < 2.0 | **P4 — Low** | Periodic check-ins only |

## Phase 5: Output — Target Customer List

### Output Format

```
# B2B Trade Data Analysis Report

## Summary
- Total records analyzed: [X]
- Qualified prospects: [X]
- By priority: P1=[X], P2=[X], P3=[X], P4=[X]
- Geographic distribution: [Chart/Table]

## P1 Prospects (Immediate Action)

### 1. [Company Name]
| Field | Details |
|-------|---------|
| Country | [Country] |
| Products | [Product categories] |
| Est. Annual Volume | [Value] |
| Frequency | [X]x/year |
| Last Purchase | [Date] |
| Key Suppliers | [Countries] |
| Approach Angle | [How to position] |
| Recommended Action | [Specific next step] |

### 2. [Company Name]
[Same structure]

## P2 Prospects (This Week)

[Same structure]

## P3-P4 Prospects (Nurture)

[Condensed list format]

## Market Insights

1. [Key finding about the market]
2. [Key finding about competitor suppliers]
3. [Opportunity identified]

## Appendix: Full Data Table

| Company | Country | Product | Volume | Frequency | Score | Priority |
|---------|---------|---------|--------|-----------|-------|----------|
| [Name] | [Country] | [Product] | [Value] | [Freq] | [X.X] | P1 |
```

## Phase 6: Integration with Outreach

### From Data to Action

For P1 prospects, generate:

1. **Customer Brief**: 1-page summary of the prospect
2. **Customized Outreach**: Cold email referencing their specific purchase patterns
3. **Talking Points**: Based on their supplier concentration, price trends, seasonality

### Outreach Angle Examples

```
If they buy from multiple suppliers:
"We noticed you work with several [product] suppliers in [country]. 
We're a specialized manufacturer focusing on [specific product segment]. 
Would you be open to exploring if we can offer better [specific advantage]?"

If they have seasonal patterns:
"Public records show peak season in [Q2]. 
We're reaching out now because we'd like to discuss how we can 
support your [Q2] requirements with our [product] capabilities."

If they recently expanded volume:
"Congratulations on your growth in [product category]! 
We've helped similar companies scale their [specific need]. 
Would you be open to a brief call to explore if we're a fit?"
```

## Quality Standards

1. **Data accuracy**: Cross-check key data points (company names, volumes) against multiple rows
2. **HS code validation**: Ensure HS codes are correctly interpreted for product mapping
3. **Currency consistency**: Note currency in value fields; flag inconsistencies
4. **No assumptions**: If a field is ambiguous, note it rather than guess
5. **Source citation**: Always cite the source file and row numbers for key findings
6. **Column mapping disclosure**: 分析报告中首次引用数据时，注明对应的原始文件列名。
   例如："进口量数据来自文件中「Total Import QTY」列"。这样用户可以快速判断列解读是否正确。
7. **Completeness**: Include all relevant fields in output, even if values are missing

## Common Pitfalls

1. **Over-relying on volume**: Big buyers may already have established suppliers — look for disruption opportunities
2. **Ignoring frequency**: One-time large orders may not indicate ongoing business potential
3. **Missing seasonality**: Outreach timed wrong can kill opportunity before it starts
4. **Generic outreach**: Always customize message based on the specific buyer's patterns
5. **Not verifying data**: Company names may have typos or different spellings — verify before outreach
6. **Privacy concerns**: Customs data may have usage restrictions — ensure compliance
