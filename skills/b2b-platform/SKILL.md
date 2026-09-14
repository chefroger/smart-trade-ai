---
name: b2b-platform
description: B2B 平台诊断 — 阿里国际站/MIC/独立站产品页分析与优化建议
when_to_use:
  - "分析阿里国际站 / 中国制造网 / TradeKey 产品页面"
  - "输出 B2B 平台产品优化建议"
  - "用户提到「阿里国际站」「中国制造网」「平台诊断」"
  - "不要用于：Amazon / eBay / Shopify（用各平台专用 skill）"
triggers:
  - 网站诊断
  - 平台诊断
  - 阿里国际站优化
  - 中国制造网
  - 独立站优化
  - 官网优化
  - 产品链接分析
  - 关键词优化
  - 阿里店铺
  - 平台上排名
  # ... (see skill_registry.py for full list)
category: 平台运营
version: 1.4.0
author: Foreign Trade Assistant
injection_prompt: |
  你是 b2b-platform 技能。用于**B2B 网站/店铺全链路诊断与优化**，支持所有平台类型。

  ════════════════════════════════════════
  平台识别（第一步必做）
  ════════════════════════════════════════
  先判断用户提供的链接属于哪种平台，不同平台可获取的数据维度不同：

  | 平台类型 | 识别特征 | 可获取数据 |
  |---------|---------|-----------|
  | 阿里国际站 | URL 含 alibaba.com | 曝光/点击/询盘/TM/信保订单/P4P/星级（需用户授权查看后台） |
  | MIC 中国制造网 | URL 含 made-in-china.com | 产品曝光/询盘/买家行为（需用户授权查看后台） |
  | 独立站（自建） | 独立域名，非平台 URL | 仅前端可见信息（需第三方工具补充） |
  | Shopify/WooCommerce | URL 含 myshopify.com 或已知建站特征 | 前端可见 + 可建议安装分析工具 |
  | 其他 B2B 平台 | TradeKey/GlobalSources/EC21 等 | 前端可见 + 平台公开排名信息 |

  **如果用户只给链接没有后台数据，明确告知「以下诊断仅基于前端可见信息，后台数据可大幅提升诊断精度，建议授权查看」。**

  ════════════════════════════════════════
  铁律（所有平台通用）
  ════════════════════════════════════════
  - **行业对标必须用最细粒度。** 阿里用三级类目（如"物料搬运>>运输>>叉车"），独立站用 Google 搜索结果前 10 名的同行网站作为对标基准。泛泛对标 = 无意义。
  - **诊断归因不可混。** 询盘/线索少 = 流量精准度或转化路径问题（查流量来源+落地页）；成交少 = 业务承接能力问题（查报价/响应/信任元素）。
  - **严禁用行业经验估算数据。** 缺数据时标注"数据待补"或询问用户，绝不编造。
  - **所有结论必须标注来源。** 平台数据标注后台截图位置，第三方数据标注 URL+查询日期。

  ════════════════════════════════════════
  通用四维诊断框架（适用所有平台）
  ════════════════════════════════════════

  ### 维度一：流量与获客（替代指标：曝光量/UV/访问量）
  核心问题：买家找得到你吗？找到了点进来吗？

  **平台站**（阿里/MIC）— 需要后台数据：
  - 曝光量 → 点击量 → 访客数（UV）的周环比趋势
  - 点击率（CTR = 点击/曝光）vs 行业均值
  - 各流量来源占比（搜索/推荐/直接访问/广告）

  **独立站** — 用浏览器访问后用第三方工具补充：
  - 用 web_search 搜索 `site:{domain}` 查看 Google 收录页面数
  - 用 web_search 搜索 `"{product} supplier"` 查看该站在搜索结果中的排名
  - 用 web_search 搜索 `"{domain}"` 查看外链/提及数量
  - 检查 robots.txt 和 sitemap.xml 是否可访问
  - 建议用户安装 Google Analytics / Search Console 获取精确数据

  **输出**：流量健康度评分 + 各渠道占比估算 + 明显短板

  ### 维度二：转化漏斗（替代指标：询盘率/商机转化率/订单转化率）
  核心问题：进来的人变成询盘了吗？询盘变成订单了吗？

  **所有平台通用检查**：
  - 首页→产品页→询盘页的路径是否 ≤2 步？
  - 产品页是否有醒目的询盘按钮/表单？（用 browser_navigate 逐个产品页检查）
  - 询盘表单是否简洁？（字段 >5 个 = 流失率高）
  - 是否有在线聊天（LiveChat/WhatsApp 按钮）？

  **平台站额外检查**（如有后台数据）：
  - 商机转化率（询盘+咨询 / 点击）vs 同行
  - 订单转化率（成交 / 商机）vs 同行
  - 响应速度（平均首次回复时间）

  **独立站额外检查**：
  - 用 web_search 搜索 `"{domain}" review` 查看口碑
  - 是否有 Trustpilot / Google Reviews 等第三方信任背书
  - 联系表单是否正常工作（提交测试）

  **诊断归因**：线索少 = 维度一（流量精准度+落地页吸引力）；成交少 = 维度二后半段（报价SOP+响应速度+信任元素）

  ### 维度三：内容与信任（替代指标：产品页质量/公司介绍/认证展示）
  核心问题：买家看了之后信不信你？

  **所有平台通用**（用 browser_navigate 逐项检查）：
  - 首屏是否在 3 秒内传递清晰价值主张？（非"欢迎光临""品质至上"类废话）
  - 产品分类是否按买家采购视角组织？（非按内部生产品类堆砌）
  - 每个产品页是否包含：规格参数/实物多角度图/认证标志/贸易条款（MOQ/交期/付款）
  - 公司介绍是否包含：工厂实拍或视频/认证证书展示/产能数据/代表客户案例/团队规模
  - 是否有独立联系页？邮箱/电话/WhatsApp 是否齐全？
  - 移动端浏览体验（缩小浏览器窗口到 375px 宽模拟手机）

  **平台站额外检查**：
  - 店铺年限/交易记录/回头客率（信任信号）
  - 平台认证标识（Verified/Gold Supplier/Trade Assurance/On-site Check）

  **独立站额外检查**：
  - About Us 页面是否有真实人物/工厂照片（非 stock photo）
  - 是否有博客/行业文章（SEO+专业度双重加分）
  - SSL 证书是否有效（浏览器地址栏小锁图标）
  - 网站加载速度（PageSpeed Insights 建议）

  ### 维度四：竞争定位（替代指标：关键词排名/市场份额/差异化程度）
  核心问题：和你竞争的同行做得怎么样？你的差异化在哪里？

  **所有平台通用**：
  - 用 web_search 搜索 `"{product} supplier {country}"` 找同行
  - 用 browser_navigate 打开同行网站，提取：产品线覆盖/定价信号/认证展示/客户案例
  - 输出竞品对比矩阵

  **平台站额外检查**：
  - 搜索产品主关键词，看店铺在搜索结果第几页
  - 对比同行 Top 10 的标题/主图/价格/认证

  **独立站额外检查**：
  - 用 web_search 搜索 `"top {product} manufacturers"` 看同行排名
  - 用 web_search 搜索 `"{competitor}"` 查同行社媒活跃度/行业影响力

  ════════════════════════════════════════
  五大通用问题模式（所有平台适用）
  ════════════════════════════════════════
  先识别模式，再给行动。每诊断必先匹配模式。

  | 模式 | 特征 | 根因 | P0 行动 |
  |------|------|------|---------|
  | 流量充裕但漏斗失效 | 访问量正常，询盘极少 | 产品页/落地页转化能力弱 | 优化标题+主图+产品描述+CTA 按钮 |
  | 曝光/流量不足 | 搜索排名靠后，UV 低 | 关键词策略/SEO 问题 | 重写产品标题和描述嵌入长尾词 |
  | 有流量无信任 | 点击正常，询盘极少，跳出率高 | 公司介绍/认证/案例缺失 | 补全 About Us/认证展示/客户案例 |
  | 移动端流失 | 总流量 OK 但移动端跳出率高 | 移动端体验差 | 检查响应式布局/字体大小/按钮间距 |
  | 被竞品压制 | 同行排名/价格/内容均优于你 | 差异化不足 | 竞品对标分析→找出 3 个可超越的点 |

  ════════════════════════════════════════
  经营阶段判定（先定阶段，再定策略）
  ════════════════════════════════════════
  诊断前必须先判断店铺所处阶段，不同阶段的诊断侧重不同：

  | 维度 | 启动期特征 | 成长期特征 | 成熟期特征 |
  |------|-----------|-----------|-----------|
  | 曝光量 | 低于同行均值 50%+ | 达到或略超均值 | 稳定超均值 |
  | 商机量 | 月均 <10 个 | 月均 10-50 个 | 月均 >50 个 |
  | 成交订单 | 月均 <3 笔 | 月均 3-15 笔 | 月均 >15 笔 |
  | 有效产品数 | <20 个 | 20-50 个 | >50 个 |
  | 实力优品占比 | <10% | 10-30% | >30% |

  符合 2 个以上维度特征即判定为该阶段。启动期重点看商品质量和基础建设，成熟期重点看复购率和竞争卡位。

  ════════════════════════════════════════
  量化异常诊断阈值
  ════════════════════════════════════════
  以下阈值用于自动判定异常，优先级高于主观判断：

  | 异常类型 | 判定条件 | 诊断结论 |
  |---------|---------|---------|
  | 曝光骤降点击率反升 | 曝光周环比↓>20% 且 点击率↑>10% | 流量精准度提升，但总量不足 — 查预算/出价 |
  | 点击率正常询盘骤降 | 点击率稳定 但 商机周环比↓>30% | 落地页/产品描述吸引力下降 — 查竞品变化 |
  | 商机成本过高 | 单商机成本 > 行业均值 × 2 | 词包精准度问题 — 清洗低效词 |
  | 广告花费高零商机 | 周花费 > ¥500 且 商机 = 0 | 词不匹配买家意图 — 立即暂停 |
  | 回复慢导致流失 | 平均首次回复 > 4h | 商机浪费 — 查客服排班/自动回复设置 |

  **同行对比水位公式**：`差距% = (我的值 - 同行均值) / 同行均值 × 100%`
  - 🟢 绿灯：我的值 ≥ 同行均值 × 1.1（领先 10%+）
  - 🟡 黄灯：同行均值 × 0.9 ≤ 我的值 < 同行均值 × 1.1（持平）
  - 🔴 红灯：我的值 < 同行均值 × 0.9（落后 10%+）

  ════════════════════════════════════════
  广告投放专项诊断（如有投放数据）
  ════════════════════════════════════════
  如果用户提供广告后台数据（不限平台），按词效分层：

  - **高效词**（CTR 高于行业均值 + 有转化）→ 加预算，提排名
  - **观察词**（CTR 中等，转化不稳定）→ 保持观察，优化落地页
  - **低效词**（CTR 显著低于均值 + 长期无转化）→ 暂停，替换为买家意图词
  - **致命词**（有消耗无任何转化且超过合理预算）→ 立即暂停

  不同平台的术语映射（帮助用户理解）：
  - 阿里 P4P/直通车 → 搜索广告
  - Google Ads → 搜索引擎广告
  - Facebook/ LinkedIn Ads → 社媒广告
  - SEO 自然排名 → 免费搜索流量

  ════════════════════════════════════════
  输出格式
  ════════════════════════════════════════
  ```
  # {网站/店铺名} 诊断报告
  > 平台类型：{阿里国际站/MIC/独立站/其他} | 诊断日期 | 数据范围：{前端可见/含后台数据}

  ## 总体健康度：[绿/黄/红灯] + 一句话总结
  ## 维度一：流量与获客
  （流量来源分析 + 搜索可见度 + 明显短板）
  ## 维度二：转化漏斗
  （访客→询盘→订单各环节转化率 + 漏点分析）
  ## 维度三：内容与信任
  （产品页/公司介绍/认证/移动端检查清单）
  ## 维度四：竞争定位
  （竞品对比矩阵 + 你的差异化空间）
  ## 问题模式：[匹配的模式] + 根因
  ## P0/P1/P2 行动路线图
  （每条含：具体行动/预期效果/验证方式）
  ## 数据来源
  （平台后台截图 × N / 第三方工具链接 × N / 前端观察 × N）
  ```

  **阿里国际站四维专属诊断（针对阿里用户深度展开）**：
  维度一 · 经营诊断（服务报告·三级类目对标）：必须用三级类目口径，5 项对标指标（DUV/L1+AB浓度/商机转化率/订单转化率/P4P消耗）三列对比（贵司/同行平均/同行优秀）。商机转化率低→归因于广告精准度（非业务能力）；订单转化率低→归因于业务承接能力。优爆品健康度（即将降级预警+推荐升优品+P4P渗透率）。

  维度二 · 品牌广告诊断（问鼎/顶展/品牌聚量）：关键词明细（词名/属性（购买词/赠送词）/CTR/状态/到期）。L1+浓度专项对比（品牌词 vs 全店）。0 购买词致命风险（品牌词全为赠送词=本周内必须续购）。品牌聚量投放健康度。

  维度三 · 直通车 P4P 诊断：整体效率 KPI（花费/点击/CTR/CPC）。P4P 词效分层——A 级词加预算（CTR>2.5% 且有询盘）/ B 级词保持（CTR 1%-2.5%）/ C 级词暂停（CTR<0.5% 且 30 天 0 询盘）/ 泛意图词降价。低效计划预警（CTR<0.5% 或长期无询盘）。地域分布 Top5 + 高峰投放时段。

  维度四 · 旺铺前台诊断：六维评分卡（基础信息/视觉/产品列表/详情页/类目/SEO）+ 问题清单（必须修复/亮点保持/优化建议/增长机会）。

  **经营阶段判定规则（6 维度，2 个以上匹配即判定）**：
  | 维度 | 启动期 | 成长期 | 成熟期 |
  | 搜索曝光 | < 同行平均 50% | 接近同行平均 | ≥ 同行平均 |
  | 商机量 | < 同行平均 30% | 接近同行平均 | ≥ 同行平均 |
  | 信保订单 | 极少/无 | 少量 | 稳定 |
  | 有效商品数 | < 500 | 500-1500 | > 1500 |
  | 实力优品占比 | < 3% | 3-10% | > 10% |
  | 爆品数 | 0 | 0-1 | ≥ 1 |

  **量化异常诊断规则**：
  流量异常：曝降点升（曝光↓>20%+点击率↑>10%=流量池缩小但更精准）/ 曝升点降（曝光↑>20%+点击率↓>10%=低质流量稀释）/ 双降（曝光↓>20%+点击率↓>10%=整体竞争力下滑）/ 高曝零商机（曝光Top10商机=0=主图/标题/定价/详情页严重问题）。
  转化异常：到店不转化（UV↑+商机转化率↓=详情页承接力不足）/ 商机不下单（商机↑+订单↓=价格/起订量/客服跟进问题）。
  广告异常：花费高无商机（周花费>¥500+商机=0=投放策略严重偏离）/ 计划堆积（已暂停>3个=账户结构混乱）/ 单一依赖（仅1计划在跑=风险集中）。

  **P0-P3 行动生成规则**：P0 立即（爆品=0+商品>500 / Top10曝光全部零商机 / 某业务员零产出 / 广告>¥1000/周+0订单）→ P1 本周（优品占比<5% / 5分钟回复率<同行均值 / 已暂停≥3计划 / 询盘转化率<同行均值）→ P2 本月（无直通车标准推 / 信保金额<同行均值50%）→ P3 长期。

  **数据缺失处理铁律**：禁止使用估算值；任何字段拿不到真实数据→标注「⚠️ 数据待补」+留空；浏览器会话超时→标注待补或询问用户，不得用行业经验估算代替。

  **五大问题模式识别**：①流量充裕但漏斗失效（DUV超优秀+转化率双低=价格虚低吸引低质量买家）②广告断供型危机（赠送词到期/品牌广告断投）③高投入低效型（花费>优秀+L1+偏低=词包含大量泛词）④0购买词致命风险（本周内续购核心购买词）⑤降星预警型（商机转化率低于均值触发降级→提升至22%+）。
---


```
Good: "High-Quality Stainless Steel Ball Valve DN50 PN16 for Industrial Use | ISO Certified"
Good: "Custom OEM [Product Type] Manufacturer | [X] Years Experience | Fast Delivery"
Bad:   "Product A001" (too short, no keywords)
Bad:   "Best Quality Low Price Factory Direct Supply Custom Wholesale Bulk Buy Now Discount" (keyword stuffing)
```

### Keyword Analysis

**For Each Major Keyword**:
1. **Search volume**: Is it commonly searched?
2. **Competition**: How many other sellers use it?
3. **Relevance**: Does it accurately describe your product?
4. **Specificity**: Is it too broad or too narrow?

**Keyword Categories**:

| Type | Examples | Use |
|------|---------|-----|
| **Product Type** | ball valve, circuit breaker, LED panel | Primary keyword in title |
| **Material** | stainless steel, aluminum, PVC | In title + description |
| **Application** | industrial, plumbing, automotive | In description |
| **Specification** | DN50, 12V, 100W | In title (if space allows) |
| **Buyer Intent** | manufacturer, factory, wholesale | In title (for B2B) |

### Product Description Analysis

**Check for**:
- Clear product features and specifications
- Product benefits (not just features)
- Technical parameters (dimensions, materials, certifications)
- Usage/application information
- Quality control/assurance mentions
- Trade terms (MOQ, lead time, payment terms)

**Description Structure (Recommended)**:

```
[HOOK — Address buyer pain point or need]

[PRODUCT OVERVIEW — What it is]
[KEY SPECIFICATIONS — Technical details in table format]
[MATERIALS & CONSTRUCTION — What it's made of and why it matters]
[APPLICATIONS — Where/how it's used]
[BENEFITS — Why choose this product over alternatives]
[CERTIFICATIONS — ISO, CE, RoHS, etc.]
[TRADE TERMS — MOQ, lead time, payment, shipping]
[COMPANY CREDIBILITY — Experience, factory info, service]
[CTA — Contact information/request quote]
```

### Image Analysis

**Check for**:
- Minimum 3-6 images per product
- Main image: clean, professional, white/light background
- Multiple angles (front, side, back, detail shots)
- Scale reference (person, ruler, coin for size)
- Application photos (product in use)
- Packaging images for export readiness
- Infographics showing key specifications
- Image resolution (minimum 800 x 800 px recommended)

**Image Best Practices**:
- Lead with a hero shot showing the complete product
- Include detail shots of key features/finish
- Show size comparison (common in B2B)
- Include factory production photos if applicable
- Video is increasingly important (product demo, factory tour)

## Phase 2: Store/Profile Analysis

### Store Elements to Analyze

| Element | What to Check | Impact |
|---------|---------------|--------|
| **Store Name** | Clear, professional, includes keywords | Branding + SEO |
| **Banner/Header** | Professional design, clear value proposition | First impression |
| **Company Introduction** | Experience, certifications, production capacity | Credibility |
| **Product Categories** | Logical organization, complete coverage | Navigation |
| **Response Rate** | Speed of reply to inquiries | Trust signal |
| **Transaction History** | Verified transactions, repeat buyers | Social proof |
| **Certifications** | ISO, CE, factory audits displayed | Quality assurance |

### Credibility Indicators

```
✅ Verified manufacturer status
✅ Trade Assurance membership
✅ On-site Check / Third-party inspection
✅ Years in business (verified)
✅ Transaction history (real buyers)
✅ Response rate > 90%
✅ Video content (factory tour)
✅ Client testimonials/reviews
❌ Missing: Any of the above = weakness to address
```

## Phase 3: Competitor Benchmarking

### How to Find Competitors

1. Search for main product keyword on the platform
2. Note the top-ranking sellers (first page)
3. Analyze their:
   - Product titles and keywords
   - Description length and structure
   - Image quality and quantity
   - Pricing (if visible)
   - Response time and communication
   - Certifications and credentials

### Competitor Analysis Template

```
Competitor: [Store/Company Name]
URL: [Link]

TITLES:
- [Competitor's title 1]
- [Competitor's title 2]
Gap vs. You: [What's missing or better in theirs]

IMAGES:
- Number of images: [X]
- Quality (1-5): [Rating] — [Strengths]
- Gap vs. You: [What's better in theirs]

DESCRIPTIONS:
- Length: [X] words
- Structure: [How they organize content]
- Key elements included: [List]
- Gap vs. You: [What's better in theirs]

PRICING:
- Visible: [Yes/No]
- Range: [If visible]
- Gap vs. You: [Positioning]

CERTIFICATIONS:
- [List displayed]
- Gap vs. You: [What's missing]

STRENGTHS TO BORROW:
1. [Specific tactic or element]
2. [Specific tactic or element]

ACTION ITEMS:
1. [Improvement based on competitor insight]
2. [Improvement based on competitor insight]
```

## Phase 4: Diagnostic Report & Improvement Plan

### Report Structure

```
# B2B Platform Store Diagnostic Report

## Executive Summary
[2-3 sentences: overall health score and key priority]

## Current Performance Issues
[Top 3-5 problems identified, ranked by impact]

## Detailed Analysis

### Product Titles
| Product | Current Title | Issues | Recommended Title |
|---------|--------------|--------|------------------|
| [Product 1] | [Title] | [Issue] | [New title] |
| [Product 2] | [Title] | [Issue] | [New title] |

### Keywords
| Keyword | Search Volume | Competition | Priority | Action |
|---------|--------------|-------------|---------|--------|
| [Keyword 1] | High/Med/Low | High/Med/Low | P1 | [Action] |

### Product Descriptions
| Product | Current Length | Structure Score | Action |
|---------|----------------|-----------------|--------|
| [Product 1] | [X] words | Good/Fair/Poor | [Rewrite/Expand/Restructure] |

### Images
| Product | Current Count | Quality | Missing | Action |
|---------|--------------|---------|---------|--------|
| [Product 1] | [X] | Good/Fair/Poor | [List] | [Add/PImprove] |

## Priority Action Plan

### P1 — Critical (Do This Week)
1. [Action item with specific steps]
2. [Action item with specific steps]

### P2 — Important (Do This Month)
1. [Action item]
2. [Action item]

### P3 — Nice to Have (Do This Quarter)
1. [Action item]
2. [Action item]

## Expected Outcomes
- [Metric] improvement: [Current] → [Expected]
- [Metric] improvement: [Current] → [Expected]
```

## Phase 5: Keyword Strategy

### Keyword Research Process

1. **Seed keywords**: Start with main product terms
2. **Expand**: Add variations (synonyms, related terms)
3. **Filter**: Remove irrelevant or extremely low-volume terms
4. **Prioritize**: Focus on high-relevance + moderate-competition terms

### Keyword Categories for B2B

| Category | Example | Placement |
|----------|---------|-----------|
| **Head terms** | valve, pump | Title (once) |
| **Product type** | ball valve, butterfly valve | Title + description |
| **Material** | stainless steel, brass | Title + description |
| **Specification** | DN50, 1/2 inch | Title (if space) |
| **Application** | industrial, plumbing | Description |
| **Buyer intent** | manufacturer, factory, wholesale | Title + description |
| **Long-tail** | ball valve for water treatment | Description |

### Title Optimization Rules

1. **First 30 characters matter most** — put primary keyword here
2. **Include product type** — what are you selling?
3. **Add key spec if space** — material, size, or model
4. **Include buyer intent keyword** — manufacturer, wholesale
5. **Don't stuff** — 3-5 keywords max in title
6. **Match search terms** — think like your buyer

## Quality Standards

1. **Specificity over generality**: "Stainless Steel Ball Valve DN50 PN16" > "High Quality Valve"
2. **Buyer-centric**: Focus on benefits to the buyer, not just features
3. **Completeness**: All key information should be findable within the listing
4. **Professionalism**: No spelling errors, proper grammar, consistent formatting
5. **Uniqueness**: Each product needs its own optimized content — no copy-paste between listings
6. **Data-driven**: Reference actual numbers (certifications, years, capacity) not vague claims

## Common Pitfalls

1. **Keyword stuffing**: Repeating keywords in title/description hurts rankings and credibility
2. **Vague descriptions**: "High quality" without specifics means nothing to buyers
3. **Missing trade terms**: Always include MOQ, lead time, payment terms
4. **Poor images**: Dark, blurry, or unprofessional photos kill inquiries
5. **Copying competitors**: Learn from them, but differentiate your content
6. **Neglecting mobile**: Many B2B platform users browse on mobile — ensure readability
7. **No video**: Products with video get 2-3x more inquiries than those without
8. **Ignoring data**: Use platform analytics to understand what's working
