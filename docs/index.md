---
layout: default
---

<style>
  .container { max-width: 100% !important; padding: 0 2rem !important; }
  .container .content { max-width: 100% !important; }
  pre, code { white-space: pre-wrap !important; word-break: break-all !important; }
  pre { padding: 1rem !important; font-size: 0.9rem !important; }
  .step-num { display:inline-block; width:32px; height:32px; line-height:32px;
    text-align:center; background:#2563EB; color:#fff; border-radius:50%;
    font-weight:bold; font-size:16px; margin-right:8px; }
  .step-title { font-size:1.3rem; font-weight:bold; margin:1.5rem 0 0.5rem; }
</style>

<!-- Hero -->
<div style="text-align:center; padding:2rem 1rem 1rem;">
  <h1 style="font-size:2.4rem; margin-bottom:0.2em;">Smart Trade AI</h1>
  <p style="font-size:1.2rem; color:#58a6ff; margin:0;">外贸业务员的本地 AI 助手</p>
  <p style="color:#8b949e;">Windows / macOS 安装教程 · 不需要懂技术，跟着步骤走，20 分钟装好</p>
</div>

<div style="text-align:center; margin:1rem 0;">
  <p style="color:#8b949e; margin-bottom:0.5rem;">安装遇到问题？扫码加微信，备注「Trade」</p>
  <img src="wechat-contact.jpeg" alt="WeChat Contact" width="180" style="border-radius:8px;">
</div>

---

## 这个工具能帮你做什么？

| 你平时的麻烦 | 用了这个工具之后 |
|-------------|----------------|
| 每天打开好几个网站查汇率、金价、新闻 | 每天早上自动生成一份简报，汇率、行情、客户提醒全在里面 |
| 想了解一个新客户靠不靠谱，不知道从哪查 | 输入邮箱或公司名，自动帮你查域名、制裁名单、LinkedIn 等 6 项 |
| 给客户写开发信，每封都要重新想 | 告诉它客户是做什么的，它帮你写好开发信 |
| 阿里国际站、中国制造网要每天登录看有没有新询盘 | 它定时帮你检查，有新的就提醒你 |
| 客户资料散落在微信、Excel、邮件里，找起来费劲 | 统一管理，按重要程度分 A/B/C 级，还能关联合同文件 |
| 不知道 LinkedIn 该发什么内容 | 每周帮你规划好要发什么，轮换不同话题 |

---

## macOS 安装

如果你用的是 Mac 电脑，按以下步骤操作。

### 第一步：确保科学上网已启动

这个工具需要从 GitHub 下载代码。在开始之前，**必须先打开你的科学上网工具**（VPN / Clash / V2Ray 等），确保网络通畅。

**验证方法：** 打开浏览器，在地址栏输入 `github.com`，回车。如果页面能正常打开，说明网络没问题，可以继续。

### 第二步：注册 DeepSeek 并获取 API Key

1. 用浏览器打开 **platform.deepseek.com**
2. 点击「注册」，用手机号注册一个账号
3. 登录后，点击「**充值**」，**充值 10 元以上**（按用量扣费，10 块钱能用很久）
4. 在左侧菜单找到「**API Keys**」，点击进入
5. 点击「**创建 API Key**」，名称填 `trade`，点确定
6. 页面上会显示一串字符（以 `sk-` 开头）——这就是你的 **DeepSeek API Key**
7. **立刻复制保存**，关掉后就再也看不到了

### 第三步：注册 Tavily 并获取 API Key（建议）

Tavily 是联网搜索引擎，让 AI 能搜索实时信息。

1. 用浏览器打开 **tavily.com**
2. 点击「Sign Up」，**用 Gmail 邮箱注册**
3. 登录后进入 Dashboard，在 API Keys 区域找到你的 Key（以 `tvly-` 开头）
4. **复制保存**到记事本里

> Tavily 每月有 1000 次免费搜索额度，个人使用足够了。不注册不影响对话功能，但搜索和客户背调质量会受明显影响。

### 第四步：检查 Python 架构（M 芯片 Mac 必须看）

如果你是 M1/M2/M3/M4 芯片的 Mac，先确认 Python 是原生 arm64 版本：

```bash
python3 -c "import platform; print(platform.machine())"
```

如果输出 `arm64`，继续下一步。如果输出 `x86_64`，说明你用的是 Rosetta 转译的 Python，**必须先换成原生版本**：

```bash
# 安装原生 arm64 Python
brew install python@3.11
# 确保用 Homebrew 的 Python
export PATH="/opt/homebrew/bin:$PATH"
```

> 如果用 Rosetta Python，Hermes 的 C 扩展会加载失败，导致 Trade 无法启动。

### 第五步：安装 Hermes Agent（AI 引擎）

Hermes Agent 是驱动 AI 的底层引擎，Trade 基于它运行。

打开「终端」（在 Launchpad 或 Spotlight 搜索"终端"），粘贴以下命令：

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
```

等待几分钟，看到「安装完成」提示即可。

> 如果安装过程中卡在 "Installing Node.js dependencies (browser tools)"，按 `Ctrl+C` 终止，不影响 Trade 使用。

### 第六步：配置 Hermes（大模型 + 搜索）

在终端输入：

```bash
hermes setup
```

出现交互配置界面后：
1. 用键盘 **上下方向键** 选择「**DeepSeek**」→ 按回车
2. 选择模型时，选「**deepseek-v4-flash**」→ 按回车
3. 粘贴你的 **DeepSeek API Key** → 按回车
4. 搜索服务选「**Tavily**」→ 按回车
5. 粘贴你的 **Tavily API Key** → 按回车

看到「配置成功」提示就完成了。

### 第七步：验证 Hermes 是否正常

在终端输入：

```bash
hermes
```

等它启动后，在对话框里输入 `hello`，按回车。如果 AI 正常回复了，说明大模型配置成功。按 `Ctrl+C` 退出。

### 第八步：让 AI 帮你安装 Trade

重新启动 Hermes（输入 `hermes`），在聊天框里**复制粘贴**下面这句话：

```
请帮我安装 trade，地址是 https://github.com/chefroger/smart-trade-ai
```

AI 会自己去 GitHub 查看项目说明，然后自动执行所有安装命令。遇到报错它会自己排查重试，你只需要等它装完。

装完后，关闭终端，重新打开一个，输入：

```bash
trade
```

浏览器会自动打开 Trade 界面。如果没有自动打开，手动访问 **http://127.0.0.1:9119/trade**。

### 第九步：设置 Trade 开机自启（可选）

如果希望开机后 Trade 自动运行，在终端执行：

```bash
hermes gateway install
```

这会安装一个 macOS 后台服务，开机后自动启动 Gateway。

> 以后的使用方式：打开电脑等约 30 秒，直接浏览器访问 **http://127.0.0.1:9119/trade** 即可。

---

## Windows 安装

如果你用的是 Windows 电脑，按以下步骤操作。

### 第一步：确保科学上网已启动

这个工具需要从 GitHub 下载代码，而 GitHub 在国内访问不稳定。在开始之前，**必须先打开你的科学上网工具**（VPN / Clash / V2Ray 等），确保网络通畅。

**验证方法：** 打开 **Google Chrome 浏览器**，在地址栏输入 `github.com`，回车。如果页面能正常打开，说明网络没问题，可以继续。

> 如果 GitHub 打不开，检查你的科学上网工具是否已启动、是否设为**全局模式**或 **TUN 模式**。

---

## 第二步：注册 DeepSeek 并获取 API Key

AI 不是免费的，需要去 DeepSeek 注册账号并充值。

1. 用 **Google Chrome 浏览器** 打开 **platform.deepseek.com**
2. 点击「注册」，用手机号注册一个账号
3. 登录后，点击页面上的「**充值**」，**充值 10 元以上**（按用量扣费，10 块钱能用很久）
4. 在左侧菜单找到「**API Keys**」，点击进入
5. 点击「**创建 API Key**」，名称填 `trade`，点确定
6. 页面上会显示一串字符（以 `sk-` 开头）——这就是你的 **DeepSeek API Key**
7. **立刻复制保存**，关掉后就再也看不到了

> 把这串 Key 先粘贴到记事本里，后面要用。

---

## 第三步：注册 Tavily 并获取 API Key

Tavily 是联网搜索引擎，让 AI 能搜索实时信息。

1. 用 **Google Chrome 浏览器** 打开 **tavily.com**
2. 点击「Sign Up」，**用 Gmail 邮箱注册**一个账号
3. 登录后进入 Dashboard，在 API Keys 区域找到你的 Key（以 `tvly-` 开头）
4. **复制保存**到记事本里

> Tavily 每月有 1000 次免费搜索额度，个人使用足够了。

---

## 第四步：在桌面创建 API Key 文件

把刚才拿到的两个 Key 整理到一个文件里，后面配置时会用到。

1. 在桌面上**右键** → 新建 → 文本文档
2. 把文件重命名为 `apikey.txt`
3. 打开文件，按以下格式粘贴：

```
DeepSeek API Key: sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
Tavily API Key: tvly-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

4. 保存并关闭。后面配置 Hermes 时需要从这里复制粘贴。

---

## 第五步：安装 Hermes Agent（AI 引擎）

Hermes Agent 是驱动 AI 的底层引擎，Trade 基于它运行。

### 5.1 以管理员身份打开 PowerShell

1. 按键盘 **Win 键**，输入 `powershell`
2. **右键点击**搜索结果里的「Windows PowerShell」
3. 选择「**以管理员身份运行**」
4. 弹出提示问"是否允许此应用对设备进行更改"，点「**是**」

### 5.2 开启长路径支持

在 PowerShell 里粘贴下面这行命令，按回车：

```
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
```

### 5.3 一键安装 Hermes

接着执行下面这行命令：

```
irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1 | iex
```

等待几分钟，看到「安装完成」提示即可。

> 在 PowerShell 里粘贴的方法是**点一下鼠标右键**（不是 Ctrl+V）。

---

## 第六步：配置 Hermes（大模型 + 搜索）

安装完成后，在同一个 PowerShell 窗口输入：

```
hermes setup
```

这时会出现交互配置界面，按以下步骤操作：

1. 用键盘的 **上下方向键** 选择「**DeepSeek**」→ 按回车
2. 选择模型时，选「**deepseek-v4-flash**」（即 DeepSeek V4 Flash）→ 按回车
3. 粘贴你的 **DeepSeek API Key**（从桌面的 `apikey.txt` 复制）→ 按回车
4. 搜索服务选「**Tavily**」→ 按回车
5. 粘贴你的 **Tavily API Key** → 按回车

看到「配置成功」提示就完成了。

---

## 第七步：验证 Hermes 是否正常

在 PowerShell 里输入：

```
hermes
```

等它启动后，在对话框里输入：

```
hello
```

按回车发送。如果 AI 正常回复了，说明大模型配置成功。

> 按 `Ctrl+C` 可以退出 Hermes，回到命令行。

---

## 第八步：让 AI 帮你安装 Trade

重新启动 Hermes（输入 `hermes`），在聊天框里**复制粘贴**下面这句话：

```
请帮我安装 trade，地址是 https://github.com/chefroger/smart-trade-ai
```

AI 会自己去 GitHub 查看项目说明，然后自动执行所有安装命令。遇到报错它会自己排查重试，你只需要等它装完。

装完后，**关闭当前 PowerShell，重新打开一个新的**，输入：

```
trade
```

浏览器会自动打开 Trade 界面。如果没有自动打开，手动访问 **http://127.0.0.1:9119/trade**。

> 验证能用后，按 `Ctrl+C` 退出 trade（暂时退出，下一步设置开机自启后会自动运行）。

---

## 第九步：设置 Hermes Gateway 开机自启

Hermes Gateway 是定时任务调度器，Trade 的定时简报、定时询盘检查都依赖它。必须让它随系统启动，否则每天还要手动开。

在 PowerShell 里执行：

```
hermes gateway install
```

看到「服务已安装」或类似提示即成功。**以后开机时 Hermes Gateway 会自动在后台运行，无需手动启动。**

> 验证是否装好：按 `Win+R`，输入 `services.msc`，回车。在列表里找到「Hermes Gateway」服务，状态应为「正在运行」。

---

## 第十步：设置 Trade 开机自启（无终端窗口）

上一步装好了 Gateway，但 Trade 本身还没设为自启。这一步用**注册表 + VBS 脚本**的方式让 Trade 开机自动运行，**且不弹出任何终端窗口**——开机后直接打开浏览器访问 **http://127.0.0.1:9119/trade** 就能用。

### 10.1 创建启动器脚本（VBS + BAT，带日志）

把下面**整段命令**复制粘贴到 PowerShell 里，按回车：

```powershell
# 探测 trade.exe 完整路径（避免开机时 PATH 未完全加载导致找不到）
$tradeExe = (Get-Command trade -ErrorAction Stop).Source
if (-not $tradeExe) {
    Write-Host "❌ 找不到 trade.exe，请先确认 trade 已安装" -ForegroundColor Red
} else {
    Write-Host "找到 trade.exe：$tradeExe" -ForegroundColor Green
    $dir = "$env:LOCALAPPDATA\trade"
    $bat = "$dir\trade-autostart.bat"
    $vbs = "$dir\trade-autostart.vbs"
    $logFile = "$dir\trade-autostart.log"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null

    # .bat 用完整路径调用 trade.exe 并重定向日志（启动失败时可查日志）
    @"
@echo off
"$tradeExe" > "$logFile" 2>&1
"@ | Out-File -FilePath $bat -Encoding ASCII

    # VBS 隐藏窗口启动 .bat（不等待，不弹窗）
    @"
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c ""$bat""", 0, False
"@ | Out-File -FilePath $vbs -Encoding ASCII

    Write-Host "已创建启动器：$vbs" -ForegroundColor Green
    Write-Host "日志文件：$logFile（启动失败时打开它排查）" -ForegroundColor Yellow
}
```

看到绿色「已创建启动器」即成功。

> **这段命令做了什么：**
> 1. 用 `Get-Command trade` 探测 `trade.exe` 的完整路径，写入 .bat 文件——**不依赖 PATH**，开机早期也能找到
> 2. .bat 把 trade 的所有输出重定向到 `trade-autostart.log`——启动失败时打开这个日志就能看到错误，不用两眼一抹黑
> 3. VBS 以**隐藏窗口**模式启动 .bat——不会弹出黑框终端

### 10.2 写入注册表，开机自动运行该脚本

继续在 PowerShell 里粘贴下面这行，按回车：

```powershell
New-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "TradeAutoStart" -Value "wscript.exe `"$env:LOCALAPPDATA\trade\trade-autostart.vbs`"" -PropertyType String -Force
```

没有报错就说明写入成功。

### 10.3 立即测试（可选但推荐）

不想等到明天才验证？在 PowerShell 里执行：

```powershell
wscript.exe "$env:LOCALAPPDATA\trade\trade-autostart.vbs"
```

等约 15 秒，然后打开浏览器访问 **http://127.0.0.1:9119/trade**。如果能看到 Trade 界面，且**没有弹出任何终端窗口**，说明配置完全正确。

> **如果打不开**：打开文件 `%LOCALAPPDATA%\trade\trade-autostart.log`（直接在资源管理器地址栏粘贴这个路径回车），看里面的错误信息。最常见的是 `ModuleNotFoundError`——说明 trade 安装有问题，回到第八步重装。

> **以后的使用方式：** 每天打开电脑，等约 30 秒（系统启动 + Trade 自动启动），直接浏览器访问 **http://127.0.0.1:9119/trade** 即可，**再也不用打开 PowerShell 手动输入 `trade`**。

### 10.4 如果想取消开机自启

将来不想要自启了，在 PowerShell 里执行：

```powershell
Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "TradeAutoStart" -Force
```

即可移除自启，不影响 Trade 本身的使用。

---

## 如何更新 Trade

Trade 会持续更新，新版本增加功能和修复问题。最简单的方式是让 AI 帮你更新：

1. 按 `Win+R`，输入 `powershell`，回车
2. 输入 `hermes` 启动 Hermes
3. 在对话框里输入：

```
帮我更新trade，并重启trade，地址是https://github.com/chefroger/smart-trade-ai
```

4. 等 AI 执行完毕，看到「重启完成」提示后，刷新浏览器页面（`Ctrl+Shift+R`）即可。

> 如果 `hermes` 命令找不到，说明 Hermes 没装好，回到第五步重装。

---

## 常见问题

| 你看到的现象 | 怎么解决 |
|------------|---------|
| 第五步安装 Hermes 卡住不动 | 科学上网没开好。确认 VPN 是全局模式，关掉 PowerShell 重开再试 |
| `hermes` 输入后提示「不是内部或外部命令」 | 关掉 PowerShell 重新打开一个新的 |
| `trade` 输入后提示「不是内部或外部命令」 | 改成输入 `cd $env:LOCALAPPDATA\trade\foreign-trade-assistant` 然后 `python server.py` |
| Hermes 对话没反应 | API Key 没配置对。重新运行 `hermes setup` 检查 |
| 浏览器打开显示「无法访问此网站」 | 程序没在运行。打开一个新的 PowerShell，输入 `trade` 启动 |
| 开机后访问 127.0.0.1:9119/trade 打不开 | Trade 自启还没跑完，等 30 秒再试。若仍不行，打开 `%LOCALAPPDATA%\trade\trade-autostart.log` 看错误日志；或按 `Win+R` 输入 `taskmgr` 回车，看进程里有没有 `python.exe`，没有就手动运行第十步的 VBS 脚本 |
| 定时任务（每日简报等）不执行 | 第九步的 Hermes Gateway 没装好或没运行。重新执行 `hermes gateway install`，再到 `services.msc` 确认服务状态 |
| 提示「Filename too long」 | 第五步的长路径设置没做。回到 5.2 执行那行命令，然后**重启电脑** |
| M 芯片 Mac 启动 Trade 报错 (Mach-O / 422) | 用了 Rosetta 转译的 Python。按 macOS 第四步检查 Python 架构，切换到原生 arm64 Python |

---

<p style="text-align:center; color:#8b949e; margin-top:3rem;">
  Smart Trade AI — 外贸业务员的本地 AI 助手<br>
  <a href="https://github.com/chefroger/smart-trade-ai">GitHub</a> ·
  <a href="https://github.com/chefroger/smart-trade-ai/releases">Releases</a>
</p>

---

## Skills 参考手册

Trade 会自动识别你的意图，匹配合适的技能。以下是全部 38 个技能的详细说明和使用示例。

### 38 个技能速查

| # | 技能 | 功能 | 典型提示词示例 |
|---|------|------|---------------|
| 1 | **b2b-osint** | 客户背景调查（6 层检测） | 帮我查一下这家公司 / 背调这个邮箱 / 查一下域名注册时间 |
| 2 | **b2b-email-intel** | 邮箱情报（120+ 平台检测） | 查一下这个邮箱哪个平台注册了 / 邮箱是真的吗 |
| 3 | **b2b-lead-generation** | 多通道客户搜索与开发 | 帮我找一下德国的 XX 产品客户 / 写一封开发信给美国客户 |
| 4 | **b2b-document** | 本地文档分析与提取 | 分析一下这份报价单 / 帮我看看这个合同有什么问题 |
| 5 | **b2b-doc-generation** | 生成报价/合同/提案文件 | 帮我生成一份 PDF 报价单 / 做一份产品介绍 PPT |
| 6 | **b2b-platform** | B2B 平台店铺诊断优化 | 帮我看看这个阿里国际站产品页 / 优化一下产品标题 |
| 7 | **b2b-linkedin-marketing** | LinkedIn 营销策略与内容 | 帮我想一下领英发什么内容 / 写一个 LinkedIn Add Note |
| 8 | **b2b-social-media** | 社媒营销（FB/Ins/TikTok/YT） | 帮我做一个 Facebook 内容计划 / 写一个 TikTok 脚本 |
| 9 | **b2b-customs-data** | 海关数据分析找采购商 | 帮我看看谁在进口这个产品 / 分析一下这个 HS 编码 |
| 10 | **b2b-onboarding** | 新公司全套部署方案 | 我刚做外贸，帮我制定一个营销方案 / 新公司怎么开始 |
| 11 | **b2b-daily-automation** | 定时任务（早报/晚报/周报） | 每天早上 8 点给我一份简报 / 设置一个每日工作总结 |
| 12 | **b2b-customer-mgmt** | 客户档案与分级管理 | 帮我查一下 XX 公司的信息 / A 级客户有哪些 |
| 13 | **b2b-data-directory** | 数据目录结构管理 | 我的数据存在哪了 / 帮我初始化一下数据目录 |
| 14 | **chat-memory** | 历史对话查询 | 上次和 XX 公司聊到什么了 / 之前那份报价是多少 |
| 15 | **b2b-skill-generator** | 动态创建新的 B2B Skill | 帮我创建一个新的 skill，用来查 XX |
| 16 | **b2b-trade-ops** | 外贸履约与售后沟通 | 帮我写一封催款邮件 / 客户投诉质量有问题怎么办 |
| 17 | **b2b-trade-compliance** | 合规检查与文化禁忌 | 这个颜色在沙特有什么忌讳吗 / 检查一下 FOB 写对了没有 |
| 18 | **b2b-cold-outreach** | 冷 outreach 邮件撰写 | 给德国的 XX 公司写一封开发信 / 写一封产品推广信 |
| 19 | **auto-trade-customer-development** | 全自动客户开发流水线 | 帮我跑一轮自动化客户开发 / 全自动开发一批客户 |
| 20 | ~~**auto-smtp-email**~~ | ~~SMTP 邮件发送 — 已禁用~~ | ~~把这封开发信发出去 / 群发这批邮件~~ |
| 21 | **b2b-email-imitation** | 开发信仿写与再创作 | 参考这封邮件，帮我写一个类似的 / 模仿这个风格写一封开发信 |
| 22 | **b2b-buyer-persona** | 买家画像与角色分层 | 帮我分析一下买家画像 / 针对采购经理应该怎么沟通 |
| 23 | **b2b-market-analysis** | 市场分析作战地图 | 分析一下德国市场进入策略 / 帮我做一个中东市场调研 |
| 24 | **b2b-sales-pipeline** | 销售管线与跟进策略 | 这个客户一个月没回了怎么办 / 帮我设计一个 30 天跟进计划 |
| 25 | **b2b-inquiry-training** | 询盘回复训练 | 帮我练一下询盘回复 / 模拟一个刁钻买家 |
| 26 | **b2b-kol-imitation** | KOL 风格模仿 | 模仿这个领英大V的风格 / 分析这个账号的内容策略 |
| 27 | **b2b-reddit-engagement** | Reddit 社区互动 | 帮我在 Reddit 写一条专业评论 / 在哪个 subreddit 发帖 |
| 28 | **b2b-seo-aeo** | SEO+AEO 文章生成 | 写一篇针对 AI 搜索优化的行业文章 / 帮我做 Pillar Page |
| 29 | **b2b-short-video** | 短视频脚本生成 | 帮我写一个 TikTok 产品视频脚本 / 工厂参观短视频 |
| 30 | **b2b-exhibition** | 展会全流程管理 | 帮我写展会邀约邮件 / 展会后的跟进计划 |
| 31 | **b2b-product-description** | 产品描述生成 | 帮我把这款产品写成销售资料 / 用 FAB 分析产品卖点 |
| 32 | **b2b-six-thinking-hats** | 六顶思考帽决策 | 帮我分析这个决策 / 要不要给这个客户独家代理权 |
| 33 | **b2b-customer-intel** | 客户深度画像 | 帮我做一份某客户的深度画像 / 这个客户有什么偏好 |
| 34 | **b2b-customer-finder** | 客户开发向导 | 三问启动：卖什么→卖到哪→找谁，自动搜索生成开发信 |
| 35 | **b2b-inquiry-meeting** | 询盘分析会主持 | 周度复盘 / 逐人点评 / 重点询盘 / 跟进行动表 |
| 36 | **b2b-sales-playbook** | 销冠经验封装器 | 将销冠经验转化为SOP/话术库/新人路线/避坑清单 |
| 37 | **b2b-guarantee-proposal** | 商业提案生成器 | 三档方案对比 + ROI分析 + 实施路线图 |
| 38 | **b2b-tech-drawing** | 工程图纸分析（实验性） | 帮我看看这张图纸 / 分析这个铸件图 / 提取图纸尺寸 |

### 技能自动匹配原理

当你在聊天框输入内容时，Trade 会自动匹配关键词，调用最合适的 skill。匹配规则：

- **词边界匹配**（+3 分）：独立关键词命中，如"背调"、"开发信"、"海关数据"
- **子串匹配**（+1 分）：关键词出现在句子中，如"帮我查一下这个公司"匹配到"查公司"
- **显式调用**（最高优先级）：用"用 b2b-xxx" 或 "加载 skill b2b-xxx" 直接指定

得分最高的 skill 会被激活。如果连续使用同一个 skill，系统会用简短的提示词继续（节省 token）。

### 如何查看当前激活的技能

当 Trade 匹配到一个 skill 时，在回复的开头会显示技能名称，如 `[SKILL AUGMENTATION] 技能触发：b2b-osint`。你也可以直接输入"用 b2b-osint 查一下这个邮箱"来强制指定某个技能。

> **设计理念**：Trade 辅助用户梳理工作流程、生成邮件草稿、撰写文档，
> **但不替用户直接发送邮件/文件给客户**。AI 可能出错，所有对外内容必须
> 经用户复核确认后自主发出。`auto-smtp-email` 已被禁用，不会由系统触发。

### 技能别名

部分技能之间存在别名关联，输入一个技能名可能触发相关联的技能：

| 输入技能 | 也会触发 |
|----------|---------|
| b2b-osint | b2b-email-intel |
| b2b-lead-generation | b2b-customer-mgmt |
| b2b-trade-ops | b2b-customer-mgmt |
| auto-trade-customer-development | b2b-lead-generation, b2b-osint, ~~auto-smtp-email~~ |
