# ==============================================================================
# Foreign Trade Assistant — 一键安装脚本 (Windows PowerShell)
# ==============================================================================
# 使用方式:
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# 全程使用 venv，不碰系统 Python site-packages。
# ==============================================================================

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  Foreign Trade Assistant — 安装向导" -ForegroundColor Cyan
Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# Step 1: 检查 Python
# ─────────────────────────────────────────────────────────────────────────────
Write-Host "Step 1/5: 检查 Python 环境" -ForegroundColor White

$PythonCmd = $null
foreach ($cmd in @("python3", "python")) {
    try {
        $ver = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        $major = & $cmd -c "import sys; print(sys.version_info.major)" 2>$null
        $minor = & $cmd -c "import sys; print(sys.version_info.minor)" 2>$null
        if ([int]$major -gt 3 -or ([int]$major -eq 3 -and [int]$minor -ge 11)) {
            $PythonCmd = $cmd
            Write-Host "  ✓ Python $ver ($(& $PythonCmd -c "import sys; print(sys.executable)"))" -ForegroundColor Green
            break
        }
    } catch {}
}

if (-not $PythonCmd) {
    Write-Host "  ✗ 需要 Python >= 3.11，但未找到。" -ForegroundColor Red
    Write-Host ""
    Write-Host "  请先安装 Python："
    Write-Host "    winget install Python.Python.3.12"
    Write-Host "    或从 https://www.python.org/downloads/ 下载"
    exit 1
}

# ─────────────────────────────────────────────────────────────────────────────
# 创建 venv
# ─────────────────────────────────────────────────────────────────────────────
$TradeHome = if ($env:TRADE_HOME) { $env:TRADE_HOME } else { "$env:LOCALAPPDATA\trade" }
$VenvDir = "$TradeHome\venv"
if (-not (Test-Path "$VenvDir\Scripts\python.exe")) {
    Write-Host "  → 创建虚拟环境..."
    & $PythonCmd -m venv $VenvDir
}
$PipCmd = "$VenvDir\Scripts\pip.exe"
$PyCmd  = "$VenvDir\Scripts\python.exe"
Write-Host "  ✓ 虚拟环境就绪 ($VenvDir)" -ForegroundColor Green

# 克隆或更新一个 git 仓库；失败返回 $false，由调用方决定是否中止。
#
# 为什么要这些判断（与 install.sh 同步，都是实测踩出来的）：
#   1. 只有目录**是有效 git 仓库**（.git 且 HEAD 可解析）才算「已安装」。克隆被中断时
#      git 会留下空目录，旧逻辑 Test-Path 会把它当成已装 → 之后 pull 静默失败、
#      pip 在残缺树里报出误导性错误，且**重试永远无法恢复**。
#   2. 浅克隆 --depth 1：全历史克隆在弱网下最慢、最易失败。
#   3. 不吞 git 的 stderr：用户要靠它排查网络问题。
function Invoke-CloneOrUpdate {
    param([string]$Name, [string]$Repo, [string]$Dest)

    $isRepo = $false
    if (Test-Path "$Dest\.git") {
        git -C $Dest rev-parse --verify HEAD 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { $isRepo = $true }
    }

    if ($isRepo) {
        Write-Host "  → 更新已有仓库..." -ForegroundColor Cyan
        git -C $Dest pull --ff-only origin main
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ⚠ git pull 失败，继续使用现有代码" -ForegroundColor Yellow
        }
        return $true
    }

    if (Test-Path $Dest) {
        Write-Host "  ⚠ 已存在的目录不是有效的代码仓库（上次克隆中断的残留），重新克隆：$Dest" -ForegroundColor Yellow
        Remove-Item -Recurse -Force $Dest
    }

    New-Item -ItemType Directory -Path (Split-Path $Dest -Parent) -Force | Out-Null
    git clone --depth 1 --branch main $Repo $Dest
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ✗ 无法克隆 $Name（git 的报错见上）。请确认网络后重新运行本脚本。" -ForegroundColor Red
        return $false
    }
    return $true
}

# ─────────────────────────────────────────────────────────────────────────────
# Step 2: 安装 hermes-agent
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Step 2/5: 安装 hermes-agent" -ForegroundColor White

$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { "$env:LOCALAPPDATA\hermes" }

# 注意：PowerShell 里**原生命令非零退出不会抛异常**，所以不能用 try/catch 判断成败，
# 必须显式看 $LASTEXITCODE（旧代码的 try/catch 从不触发 → 整个安装分支是死代码）。
& $PyCmd -c "import hermes_cli" 2>$null
if ($LASTEXITCODE -eq 0) {
    $hermesVer = & $PyCmd -c "import hermes_cli; print(hermes_cli.__version__)" 2>$null
    Write-Host "  ✓ hermes-agent 已安装 (v$hermesVer)" -ForegroundColor Green
} else {
    Write-Host "  → 正在安装 hermes-agent ..." -ForegroundColor Cyan

    $HermesRepo = "https://github.com/NousResearch/hermes-agent.git"
    $HermesDir = "$HermesHome\hermes-agent"

    if (-not (Invoke-CloneOrUpdate "hermes-agent" $HermesRepo $HermesDir)) { exit 1 }

    Push-Location $HermesDir
    & $PipCmd install -e "."
    Pop-Location
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ✗ hermes-agent 依赖安装失败（pip 的报错见上）" -ForegroundColor Red
        exit 1
    }

    & $PyCmd -c "import hermes_cli"
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ hermes-agent 安装完成" -ForegroundColor Green
    } else {
        Write-Host "  ✗ hermes-agent 安装失败（无法导入 hermes_cli）" -ForegroundColor Red
        exit 1
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# Step 3: 安装 foreign-trade-assistant
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Step 3/5: 安装 Foreign Trade Assistant" -ForegroundColor White

$TradeRepo = "https://github.com/chefroger/smart-trade-ai.git"
$TradeDir = "$TradeHome\foreign-trade-assistant"

if (-not (Invoke-CloneOrUpdate "foreign-trade-assistant" $TradeRepo $TradeDir)) { exit 1 }

Push-Location $TradeDir
# 装依赖 + trade 自身
& $PipCmd install -r requirements.txt
& $PipCmd install -e "." --no-deps
Pop-Location

Write-Host "  ✓ Foreign Trade Assistant 安装完成" -ForegroundColor Green

# ─────────────────────────────────────────────────────────────────────────────
# Step 4: 安装 B2B skills
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Step 4/5: 安装 B2B skills" -ForegroundColor White

# 必须用真实存在的入口：此前写的是 `python -m trade.post_install install`，而该包
# **没有 __main__.py** → 从未生效过；再加上原生命令失败不抛异常，旧代码会在失败时
# 照样打印「✓ 完成」（虚假成功）。实测新装后 skills 数为 0。
& $PyCmd -c "from trade.post_install import install_skills; install_skills()"
if ($LASTEXITCODE -eq 0) {
    Write-Host "  ✓ B2B skills 安装完成" -ForegroundColor Green
} else {
    Write-Host "  ⚠ B2B skills 安装可能不完整（首次启动时会自动同步）" -ForegroundColor Yellow
}

# ─────────────────────────────────────────────────────────────────────────────
# Step 5: 初始化数据目录
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Step 5/5: 初始化数据目录" -ForegroundColor White

$DataDir = "$TradeHome\data"
New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
New-Item -ItemType Directory -Path "$TradeHome\companies" -Force | Out-Null

try {
    & $PyCmd -c "from trade.database import init_db; init_db()" 2>$null
    Write-Host "  ✓ 数据库初始化完成 ($DataDir\trade.db)" -ForegroundColor Green
} catch {
    Write-Host "  → 数据库将在首次启动时自动初始化" -ForegroundColor Cyan
}

# ─────────────────────────────────────────────────────────────────────────────
# 导出 trade 命令
# ─────────────────────────────────────────────────────────────────────────────
$LocalBin = "$env:LOCALAPPDATA\local\bin"
New-Item -ItemType Directory -Path $LocalBin -Force | Out-Null

@"
@echo off
set HERMES_HOME=$HermesHome
REM 禁用 Hermes 懒加载重启：否则 agent 创建时会被 exec 到 Hermes 自带的 store python
REM （那里没有 trade 包），agent 线程以 RelaunchExit(SystemExit) 静默死亡，
REM 前端只会看到「Agent 未返回有效响应」。bootstrap.py 里也设了一处，这里是双保险。
set HERMES_DISABLE_LAZY_INSTALLS=1
"$PyCmd" "$TradeDir\server.py" %*
"@ | Out-File -FilePath "$LocalBin\trade.cmd" -Encoding ASCII

# 检测 PATH 中是否已包含 $LocalBin
$currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($currentPath -notlike "*$LocalBin*") {
    [Environment]::SetEnvironmentVariable("PATH", "$LocalBin;$currentPath", "User")
    Write-Host "  ✓ 已将 trade 命令加入 PATH（新终端生效）" -ForegroundColor Green
}

# ─────────────────────────────────────────────────────────────────────────────
# 开机自启动（Windows Task Scheduler — 用户登录后以最小窗口运行）
# ─────────────────────────────────────────────────────────────────────────────
$TaskName = "SmartTradeAI"
$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $ExistingTask) {
    $Action = New-ScheduledTaskAction -Execute $PyCmd -Argument "$TradeDir\server.py --no-browser"
    $Trigger = New-ScheduledTaskTrigger -AtLogon
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew
    $Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description "Smart Trade AI — 外贸 AI 助手开机自启动" -Force | Out-Null
    Write-Host "  ✓ 已设置开机自启动" -ForegroundColor Green
} else {
    Write-Host "  ✓ 开机自启动任务已存在" -ForegroundColor Green
}

Write-Host ""
Write-Host "══ 安装完成 ══" -ForegroundColor Green
Write-Host ""
Write-Host "  启动方式:"
Write-Host "    新终端: trade"
Write-Host "    或: $PyCmd $TradeDir\server.py"
Write-Host "    Trade 将在每次开机后自动启动（后台静默运行）"
Write-Host ""
Write-Host "  启动后打开: http://127.0.0.1:9119/trade"
Write-Host ""
Write-Host "  数据位置:"
Write-Host "    用户数据: $TradeHome\"
Write-Host "    Hermes 配置: $HermesHome\"
Write-Host ""
