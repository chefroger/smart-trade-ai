# Smart Trade AI

[![Test](https://github.com/chefroger/smart-trade-ai/actions/workflows/test.yml/badge.svg)](https://github.com/chefroger/smart-trade-ai/actions/workflows/test.yml)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)

[中文](README.md) | [English](README.en.md)

> **重要提示**  
> 本工具依赖 GitHub 和 Python 包索引（PyPI）进行安装和更新，安装和使用过程中**需要稳定的科学上网环境**。  
> Smart Trade AI 基于大语言模型（LLM）生成回复。受限于当前技术，大模型可能出现幻觉（hallucination），**所有输出内容仅供参考，不构成任何商业建议或法律依据**。涉及合同条款、报价金额、合规判断、客户背调等关键业务决策时，请务必自行核实。使用本工具所产生的任何风险由用户自行承担。

<div align="center">
  <h3>外贸业务员的 AI 助手</h3>
  <p>在本地运行，数据留在自己电脑里</p>
</div>

**写开发信、查客户背景、维护 B2B 平台——这些重复劳动，这个工具帮你 10 分钟搞定。界面支持中英双语切换，也适合外籍同事或海外团队使用。**

---

<p align="center">
  <img src="docs/screenshot-2.png" alt="Customer & Cron Panel" width="75%">
  <br>
  <em>客户管理 + 定时任务面板</em>
</p>

---

## 为什么外贸人需要这个？

| 痛点 | 不用这个工具 | 用了之后 |
|------|-------------|---------|
| 早安简报 | 每天打开 5 个网站查汇率/金价/新闻 | 自动生成，含实时汇率+大宗商品行情+客户跟进提醒 |
| 客户背调 | 手动 Google → LinkedIn → WHOIS | 一键 6 层验证：邮箱注册检测→WHOIS→制裁名单→邮箱验证→技术栈→LinkedIn |
| 开发信 | 每封手动写，客户多了记不清 | 根据客户画像自动生成，带具体痛点引用 |
| B2B 平台 | 每天登录阿里国际站/中国制造网看数据 | 定时自动检查，新询盘/待跟进报价一目了然 |
| LinkedIn | 不知道发什么内容 | AI 按周生成内容日历，轮换行业洞察/产品案例/互动提问 |
| 客户资料 | 散落在 Excel/微信/邮件里 | 统一管理，A/B/C 分级，关联文档库 |

---

<p align="center">
  <img src="docs/screenshot-1.png" alt="AI Chat Interface" width="75%">
  <br>
  <em>AI 对话界面 — 自动调用 web_search / read_file / database 工具</em>
</p>

---

## 前置条件：LLM API Key

> Smart Trade AI 使用 Hermes Agent 作为底层 AI 驱动。你需要去模型厂商那里注册并获取 API Key。

推荐方案：

| 方案 | 模型 | 适合场景 | 注册地址 |
|------|------|---------|---------|
| **推荐** | DeepSeek V4 Flash | 日常对话、文档分析、开发信 | [platform.deepseek.com](https://platform.deepseek.com) → 充值 → API Keys |

> 不再推荐 MiniMax — M3 上线后价格大幅上涨，已无性价比优势。

获取 API Key 后在终端运行 `hermes setup`，选择对应的 provider 并填入 Key 即可。

---

## 特别说明

### 网络环境要求

安装过程中需要从 GitHub 克隆仓库并下载 Python 依赖，**请确保你的网络能稳定访问 GitHub**。如果安装 Hermes 时反复失败，大概率是网络问题：

- **境内用户建议全程开启 VPN（全局模式）**，否则 `git clone` 和 `pip install` 容易超时或中断
- 如果 VPN 不稳定，可以多次重试安装命令，脚本支持断点续装
- Windows 用户如果 VPN 代理未生效，尝试在 PowerShell 中先设置代理：
  ```powershell
  $env:HTTPS_PROXY = "http://127.0.0.1:你的代理端口"
  ```

### Tavily Search API（强烈建议注册）

Trade 的搜索和客户尽职调查功能依赖 Tavily 的 AI 搜索引擎。注册免费账号即可获得每月 1000 次免费搜索额度，对个人使用完全够用：

1. 访问 [tavily.com](https://tavily.com) 注册账号
2. 在 Dashboard → API Keys 中复制你的 API Key
3. 在终端执行 `hermes setup`，找到 Tavily 选项并填入 Key

> 不注册不影响对话功能，但搜索和客户背调质量会受到明显影响。

### 如果 Trade 安装失败

手动安装 Trade 涉及 `git clone` + `pip install` + `install-trade-skills` 三个步骤，网络波动可能导致某一步失败。如果你已经成功安装了 **Hermes Agent 并配置好了 LLM**，但 Trade 安装遇到困难，可以直接把 Trade 的仓库地址告诉 Hermes，让它帮你完成安装：

> 在 Hermes 对话中直接说：
> 「帮我安装 Trade，仓库地址是 https://github.com/chefroger/smart-trade-ai.git」

Hermes 会自动完成 clone、安装依赖、注册 skills 等全部步骤，成功率远高于手动操作。

---

## 3 分钟上手

提供三种安装方式，按你的场景挑一种即可：

| # | 方式 | 适合场景 |
|---|------|---------|
| 1 | **Hermes 代装** | 已装好 Hermes 并配置好 LLM，让 AI 帮你装 Trade |
| 2 | **一键脚本** | macOS/Linux，或 Windows 想用命令行 |
| 3 | **手动一步步装** | 想完全控制每一步 |

---

### 方式 1：让 Hermes 帮你装 Trade（推荐给 AI 用户）

如果你已经装好 Hermes Agent 并配置好 LLM + Tavily 搜索，最省心的方式是让 AI 自己装 Trade——它能根据你的环境动态调整命令，成功率比固定脚本更高。

**前置条件**：已通过 `hermes setup` 配置好 LLM provider 和 API Key，**强烈建议同时配置 [Tavily](https://tavily.com) 搜索**（免费），否则 AI 无法访问 GitHub 仓库信息。

**操作步骤：**

1. 启动 Hermes：

```bash
hermes
```

2. 在 Hermes 对话框中直接粘贴下面这句话（中文即可）：

> 请分析 https://github.com/chefroger/smart-trade-ai 这个 GitHub 仓库，并帮我安装

3. Hermes 会自动：访问仓库 README → 识别安装步骤 → `git clone` → `pip install` → `install-trade-skills` → 初始化数据库
4. 安装完成后，**新开一个 PowerShell**（让 PATH 生效），启动 Trade：

```powershell
trade
# → 浏览器自动打开 http://127.0.0.1:9119/trade
```

> 如果 `trade` 命令找不到，说明 PATH 没生效，可以改用：
> ```powershell
> cd $env:LOCALAPPDATA\trade\foreign-trade-assistant
> python server.py
> ```
> 然后浏览器手动打开 http://127.0.0.1:9119/trade

> AI 会根据你当前的环境（Python 版本、操作系统、已有依赖）动态调整命令，遇到报错也能自行排查重试，比固定脚本更鲁棒。

---

### 方式 2：一键脚本（macOS / Linux）

```bash
curl -fsSL https://raw.githubusercontent.com/chefroger/smart-trade-ai/main/scripts/install.sh | bash
```

脚本自动完成：Python 环境检查 → Hermes Agent → Trade 安装 → 38 个 skills → 数据库初始化。

> **如果你希望安装前先审查脚本**：
> ```bash
> curl -fsSLO https://raw.githubusercontent.com/chefroger/smart-trade-ai/main/scripts/install.sh
> less install.sh       # 审查后
> bash install.sh
> ```

### 想固定版本？从 Release 装

访问 [Releases](https://github.com/chefroger/smart-trade-ai/releases) 下载最新版，或指定版本：

```bash
git clone --branch v0.6.7 https://github.com/chefroger/smart-trade-ai.git ~/.trade/smart-trade-ai
cd ~/.trade/smart-trade-ai && pip install -e ".[docs]"
install-trade-skills
python server.py
```

### 方式 3：手动一步步装

**前置条件**：Python >= 3.11 · Git · LLM API Key（OpenAI / Anthropic / DeepSeek / MiniMax 等）

```bash
# 1. 安装 Hermes Agent（AI 引擎）
git clone --branch main https://github.com/NousResearch/hermes-agent.git ~/.hermes/hermes-agent
cd ~/.hermes/hermes-agent && pip install -e "."

# 2. 配置 LLM
hermes setup      # 按提示选择 provider、填入 API Key

# 3. 安装 Smart Trade AI
git clone --branch main https://github.com/chefroger/smart-trade-ai.git ~/.trade/foreign-trade-assistant
cd ~/.trade/foreign-trade-assistant && pip install -e ".[docs]"

# 4. 安装 skills 并启动
install-trade-skills
python server.py
# → 浏览器打开 http://127.0.0.1:9119/trade
```

### Windows

**安装前需手动安装 Python 和 Git：**

1. **Python** — 从 [python.org](https://www.python.org/downloads/) 下载 **Python 3.11 ~ 3.13 Windows installer (64-bit)**，安装时勾选「Add Python to PATH」。
2. **Git** — 从 [git-scm.com](https://git-scm.com/download/win) 下载 Windows installer，默认选项一路下一步即可。或在 PowerShell 中执行 `winget install --id Git.Git -e --silent`。

> Node.js 无需手动安装 — Hermes 的一键安装脚本会自动处理。

安装好 Python 和 Git 后，**重新打开 PowerShell**（让 PATH 生效），执行：

```powershell
# 0. 启用 Windows 长路径支持（以管理员身份运行 PowerShell，仅需一次）
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
# 执行后需重启电脑

# 1. 安装 Hermes Agent（自动处理 Node.js + Git + 依赖）
irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1 | iex

# 2. 配置 LLM
hermes setup

# 3. 安装 Smart Trade AI
git clone --branch main https://github.com/chefroger/smart-trade-ai.git $env:LOCALAPPDATA\trade\foreign-trade-assistant
cd $env:LOCALAPPDATA\trade\foreign-trade-assistant; pip install -e "."; install-trade-skills

python server.py
# → 浏览器打开 http://127.0.0.1:9119/trade
```

> 如果第 3 步 `pip install` 报 `Filename too long` 错误，说明长路径未生效，请确认已完成第 0 步并重启电脑。

---

## 38 项专业能力

| 场景 | 能力 |
|------|------|
| 平台诊断 | 分析阿里国际站/中国制造网产品页面，输出优化建议 |
| 社媒营销 | 生成 Facebook/Instagram/TikTok/YouTube 内容日历 |
| LinkedIn 运营 | Profile 优化 + 内容策略 + InMail 模板 |
| 海关数据 | 分析进出口数据，筛选高价值采购商 |
| 客户开发 | 多通道搜索（Google Maps/LinkedIn/Facebook）+ 开发信生成 + 询盘回复 + 报价谈判 |
| 冷 Outreach 邮件 | 个性化开发信/推广信/跟进信，语言匹配+反垃圾规则+产品参数速查 |
| 开发信仿写 | 分析优秀邮件样本的 AIDA 结构和语气，应用到自家产品生成新邮件 |
| 客户管理 | 多维度分级（等级/买家类型/主营品类/匹配度）+ 详情面板+文档库关联+CSV 批量导入+去重 |
| 客户背调 | 6 层验证：邮箱平台检测→WHOIS→企业邮箱验证→制裁名单→技术栈→LinkedIn |
| 客户画像 | 单一客户 15 维深度画像：决策链/采购偏好/社交风格/送礼建议等 |
| 客户开发向导 | 三问启动 + 自动搜索 + 开发信生成，零门槛找客户 |
| 买家画像 | 按决策角色（采购/技术/老板）分层定制 FAB 价值主张和沟通策略 |
| 销售管线 | 客户旅程 5 阶段映射 + 30 天跟进表 + KPI 追踪 + 管线健康度看板 |
| 邮箱情报 | 120+ 平台邮箱注册检测，识别企业 vs 个人邮箱 |
| 文档分析 | 读取本地 PDF/Word/Excel/PPT，AI 逐个文件完整解析，不跳过不截断 |
| 商务文档生成 | 一键生成报价单、PI、合同（DOCX/XLSX/PPTX）+ 可下载单证模板 |
| 市场分析 | 目标国认证要求/关税政策/关键词武器库/3 秒 Hook 等系统化市场进入策略 |
| 数据目录 | 结构化知识库管理：产品/客户/报价/合同/认证/物流 |
| 每日简报 | 实时汇率+大宗商品+市场新闻+客户跟进提醒 |
| 定时任务 | 工作日自动化：早报/开发信/社媒/每日总结 |
| 新客引导 | 首次使用两步引导：创建公司→粘贴客户网址体验 OSINT+开发信自动生成 |
| 对话记录 | 按公司隔离的聊天记忆，支持搜索/回溯+AI回复评分反馈 |
| 询盘回复训练 | 双AI对抗训练法（模拟买家 vs 生成回复），迭代打磨至 9.5 分 |
| 履约运营 | 催款/索赔/展会/验厂/物流/售后/满意度/年度总结等 11 个场景 |
| 贸易合规 | 文化禁忌检查/缩写规范/ICC术语/翻译二审/投标/电商上架 |
| 自动客户开发 | 定时扫描目标市场，自动识别潜在客户并分析匹配度 |
| KOL 风格模仿 | 分析行业 LinkedIn 大V 的内容风格（语气/结构/Hook）并应用到自家品牌 |
| Reddit 互动 | 在 Reddit 专业社区通过评论建立行业信任、引流 B2B 客户 |
| SEO+AEO 文章 | 针对 Google 搜索和 AI 搜索引擎（Perplexity/Gemini/ChatGPT）优化内容 |
| 短视频脚本 | B2B 产品/工厂短视频脚本（TikTok/YouTube Shorts/Reels）含分镜表 |
| 展会管理 | 展会全流程：展前邀约+展中记录+展后 48h 跟进+客户分级 |
| 产品描述 | FAB 方法生成产品卖点与销售资料（Sales Kit/官网/开发信嵌入段落） |
| 决策教练 | 六顶思考帽方法辅助外贸决策分析（选供应商/参展/付款条件变更等） |
| 询盘分析会 | 周度询盘复盘，逐人点评，重点询盘分析，输出跟进行动表 |
| 销冠经验库 | 将资深销售的隐性经验转化为SOP/话术库/新人培训体系 |
| 商业提案生成 | 三档方案对比 + ROI分析 + 实施路线图，支持客户提案 |
| 工程图纸分析 | 分析客户发来的 PDF 工程图纸，提取零件名/材料/尺寸/公差（实验性，结果需人工核实） |
| Skill 生成器 | 用自然语言描述需求，自动生成新 skill 并注册到系统 |

---

## 数据安全

- **业务数据默认存储在本地**（`~/.trade/`），不上传任何服务器
- 如使用 **Ollama 等本地模型**，可实现完整本地运行，数据完全不出电脑
- 如使用 **OpenAI / Anthropic / DeepSeek / MiniMax 等云端 LLM**，用户输入和必要上下文会发送至所选服务商——不包含客户身份信息
- 多公司数据隔离（`X-Company-ID` header）
- 绑定 `127.0.0.1`，仅本机浏览器可访问
- **升级前自动备份数据库**到 `~/.trade/backups/`

### 多公司记忆共享说明

长期记忆摘要会追加写入 Hermes 的全局 `~/.hermes/memories/MEMORY.md`，通过条目内 `[公司: XXX]` 标记做软隔离。Hermes 原生检索依赖该标记过滤——正常使用时不会跨公司命中，但这是"共享文件 + 标记隔离"而非"物理隔离"。若你使用多家公司且对隔离要求极高，请注意这一设计边界。

### 网络暴露警告

默认仅绑定 `127.0.0.1`。**不要使用 `--host 0.0.0.0` 将服务暴露到局域网或公网**——会话 token 以明文注入 HTML，任何能访问该端口的设备都可读取 token 并冒充操作。如需远程访问，请通过 SSH 隧道或反向代理 + 额外认证层，而不是直接改 bind 地址。

> **免责声明**：文档中提及的 Alibaba、LinkedIn、Facebook、Instagram、TikTok、YouTube、WhatsApp 等均为其各自所有者的商标。本工具仅提供对这些平台数据的分析辅助，与上述平台无关联。制裁名单数据来源于 OFAC/UN/EU 公开数据，结果仅供参考，不构成法律意见。详见 [SECURITY.md](SECURITY.md)。

---

## 技术栈

- **AI 引擎**: [Hermes Agent](https://github.com/NousResearch/hermes-agent)（MIT 开源）
- **后端**: FastAPI + SQLite + uvicorn
- **前端**: 原生 JavaScript SPA（HTML/CSS/JS 三文件，零构建工具依赖）
- **LLM**: 兼容 OpenAI / Anthropic / DeepSeek / MiniMax / Ollama 等
- **文档解析**: PyMuPDF / python-docx / openpyxl / python-pptx

---

## 项目结构

```
trade/                     B2B 业务层
├── api/                   FastAPI 路由（10 个业务域）
├── osint/                 客户背调模块（6 层检测）
├── skill_router.py        Skill 自动匹配引擎
├── skill_registry.py      38 个 skill 注册表（纯数据）
├── bootstrap.py            启动引导（Hermes 版本检查、env 加载、Skills 同步）
├── app.py                  FastAPI app factory
└── ... + 38 个业务模块

skills/                    38 个 B2B skills（Markdown 驱动）
tests/                     测试覆盖（database/business/api/osint/smoke）
server.py                  FastAPI 入口
```

---

## 开发

```bash
pip install -e ".[dev,docs]"
python -m pytest tests/ -v   # 运行测试
ruff check trade/ server.py  # 代码检查
```

## 文档

- [Windows 安装教程](docs/index.md) — 零基础用户 20 分钟快速安装指南
- [项目需求文档](项目需求文档.md) ([English](项目需求文档.en.md))
- [业务概览](业务概览.md) ([English](业务概览.en.md))
- [Trade 数据目录结构设计](Trade数据目录结构设计.md) ([English](Trade数据目录结构设计.en.md))
- [使用说明书](使用说明书.md) ([English](使用说明书.en.md))
- [COMPATIBILITY.md](COMPATIBILITY.md) — Hermes 版本兼容性记录
- [数据库 Schema](docs/database-schema.md)

---

## 故障排除

### 用 Hermes 更新 Trade（推荐）

最快的方式是让 AI 帮你更新。打开终端，启动 Hermes，在对话框里输入：

```
帮我更新trade，并重启trade，地址是https://github.com/chefroger/smart-trade-ai
```

Hermes 会自动执行 `git pull` → `pip install` → `install-trade-skills` → 数据库检查 → 重启 Trade。遇到报错它会自行排查重试，比手动操作更省心。

### 系统升级按钮无反应

点击「系统升级」按钮后，系统会自动执行 `git pull` + `pip install` + skills 更新，完成后**自动重启服务并刷新页面**。重启时新进程先启动并等待旧进程释放端口（最多 10 秒），避免端口冲突。整个过程中页面会短暂不可用，之后自动恢复。

如果升级后页面没有自动刷新，或出现异常，请手动按 `Ctrl+Shift+R`（Windows）/ `Cmd+Shift+R`（macOS）强制刷新浏览器。

如果升级按钮完全无响应（常见于从极旧版本升级），请按以下步骤手动操作：

**macOS：**

1. 关闭 Trade 页面（浏览器标签页）
2. 打开「终端」（在 Launchpad 或 Spotlight 搜索"终端"）
3. 逐行复制粘贴以下命令，每行按回车：

```bash
cd ~/.trade/foreign-trade-assistant
git pull origin main
pip install -e "."
install-trade-skills
```

4. 所有命令执行完后，关闭终端
5. 双击桌面上的 Trade 图标启动，或重新运行 `python server.py`

**Windows：**

1. 关闭 Trade 页面
2. 按键盘 `Win + R`，输入 `powershell`，回车
3. 逐行复制粘贴以下命令，每行按回车：

```powershell
cd $env:LOCALAPPDATA\trade\foreign-trade-assistant
git pull origin main
pip install -e "."
install-trade-skills
```

4. 所有命令执行完后，关闭 PowerShell
5. 双击桌面上的 Trade 图标启动，或在终端重新运行 `python server.py`

**Linux：**

1. 关闭 Trade 页面
2. 打开终端
3. 逐行复制粘贴以下命令，每行按回车：

```bash
cd ~/.trade/foreign-trade-assistant
git pull origin main
pip install -e "."
install-trade-skills
```

4. 重新运行 `python server.py` 启动

> 如果执行 `git pull` 时报错找不到 `git`，说明 Git 未安装。请先打开终端输入 `hermes` 确认 Hermes 正常，或从 [git-scm.com](https://git-scm.com) 下载安装 Git 后再试。

### 升级时报错「更新结果未知」「更新失败」「请求超时」等

前端升级失败的错误提示各不相同，但**根本原因几乎都是网络问题**——`git pull` 或 `pip install` 无法稳定连接 GitHub/PyPI。**所有此类错误的解决方法完全相同**：跳过前端，直接在终端里手动执行更新命令。

**macOS / Linux：**

1. 关闭 Trade 页面，打开终端
2. 逐行执行（确保 VPN 全局模式已开启）：

```bash
cd ~/.trade/foreign-trade-assistant
git pull origin main
pip install -e "."
install-trade-skills
python server.py
```

**Windows：**

1. 关闭 Trade 页面，按 `Win + R`，输入 `powershell`，回车
2. 逐行执行（确保 VPN 全局模式已开启）：

```powershell
cd $env:LOCALAPPDATA\trade\foreign-trade-assistant
git pull origin main
pip install -e "."
install-trade-skills
python server.py
```

**常见错误对照：**

| 前端提示 | 实际原因 | 手动执行哪步 |
|---------|---------|------------|
| ⚠️ 更新结果未知，请检查网络 | `git pull` 超时（120s）或 HTTP 错误 | 全部 4 步 |
| ⚠️ 请求超时 | `fetch()` 120s AbortController 触发 | 全部 4 步 |
| ❌ 更新失败: Git 未安装或不在 PATH 中 | 系统找不到 `git` 命令 | [安装 Git](https://git-scm.com/download/win) 后全部 4 步 |
| ❌ 更新失败: pip install failed | 依赖包下载失败（PyPI 不通） | `pip install -e "."` 重试 |
| ❌ 更新失败: git pull / clone failed | GitHub 连不上 | 开 VPN 全局模式后重试 `git pull` |

> 如果 VPN 已开启但仍失败，尝试在终端中先设置代理再执行更新：
> ```bash
> # macOS / Linux
> export https_proxy=http://127.0.0.1:你的代理端口
>
> # Windows PowerShell
> $env:HTTPS_PROXY = "http://127.0.0.1:你的代理端口"
> ```

### 拖拽文件 / 上传报错「拒绝访问」

如果你在聊天框拖入 Excel 等文件时看到类似 `[WinError 5] 拒绝访问: 'C:\\Windows\\System32\\.hermes'` 的错误，说明程序找不到正确的数据目录。

**macOS：**

1. 关闭 Trade 页面，打开「终端」
2. 执行以下命令再启动：

```bash
export HERMES_HOME="$HOME/.hermes"
python server.py
```

**Windows：**

1. 关闭 Trade 页面，按 `Win + R`，输入 `powershell`，回车
2. 执行以下命令再启动：

```powershell
$env:HERMES_HOME = "$env:LOCALAPPDATA\hermes"
python server.py
```

**Linux：**

1. 关闭 Trade 页面，打开终端
2. 执行以下命令再启动：

```bash
export HERMES_HOME="$HOME/.hermes"
python server.py
```

### 升级后页面样式异常

浏览器缓存了旧版 CSS/JS，按 `Cmd+Shift+R` (macOS) 或 `Ctrl+Shift+R` (Windows) 强制刷新即可。

---

## 联系作者

<div style="display:flex;gap:40px;align-items:flex-start;">
  <div>
    <img src="docs/wechat-contact.jpeg" alt="WeChat" width="200"><br>
    <small>微信扫码 · 备注「Trade」</small>
  </div>
  <div>
    <img src="docs/whatsapp-contact.png" alt="WhatsApp" width="200"><br>
    <small>WhatsApp</small>
  </div>
</div>

商务合作或技术支持请发邮件至 lauroge@gmail.com。

---

Smart Trade AI — 外贸业务员的本地 AI 助手。
