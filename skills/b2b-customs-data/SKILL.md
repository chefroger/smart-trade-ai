---
name: b2b-customs-data
description: 海关数据分析 — 进出口记录查询、采购商筛选、市场趋势分析
when_to_use:
  - "分析海关进出口数据"
  - "筛选高价值采购商"
  - "做市场调研 / 竞品分析"
  - "用户提到「海关数据」「采购商」「进出口」"
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
version: 1.1.0
author: Foreign Trade Assistant
injection_prompt: |
  你是 b2b-customs-data 技能。当用户需要分析海关进出口数据、筛选高价值采购商、做市场调研或竞品分析时，按以下流程执行。

  ## Phase 1 — 输入确认
  1. 用户提供了数据文件（CSV/Excel）→ 逐个完整读取（不跳过、不截断，保留原始行序与列名）
  2. 无数据文件 → 基于用户提供的产品/市场信息给出分析方法论与数据获取渠道建议，不编造数据

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
  - **数据溯源（强制）**：文件分析注明文件名+列名+行号；市场判断注明来源 URL，或明确标注「分析推断，非实际数据」。绝不编造具体数字或公司名。
  - **HS 编码解读错误会导致产品映射错误**，不确定时先与用户确认，不猜测。
  - 字段模糊/缺失时标注「待确认」，不要用推测填充。
  - 海关数据可能存在使用限制，提醒用户注意合规。
  - 公司真伪验证不属于本技能（用 b2b-osint）。
---

# 海关数据分析（Customs Data Analysis）

从进出口贸易记录中筛选高价值采购商，输出可直接用于触达的目标客户清单。

## Phase 1: Input Preparation

两种输入路径：

1. **有数据文件**（CSV/Excel 导出）→ 直接分析：逐个文件完整读取，保留原始行序与列名
2. **无数据文件** → 输出分析方法论 + 数据获取渠道建议（官方海关统计、商业贸易数据库等），不编造数据

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
"Your import data shows peak season in [Q2]. 
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
