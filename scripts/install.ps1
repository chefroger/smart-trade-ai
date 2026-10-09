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
# 装依赖 + trade 自身。
# 每个 pip 后都必须查 $LASTEXITCODE —— 原生命令非零退出不抛异常（见本文件前面的说明），
# 不查就会在弱网/磁盘满时把失败当成成功，用户之后运行 trade 只得到
# ModuleNotFoundError，且开机自启任务每次登录静默失败。
& $PipCmd install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ✗ 依赖安装失败（pip 的报错见上）。请检查网络后重新运行本脚本。" -ForegroundColor Red
    Pop-Location
    exit 1
}
& $PipCmd install -e "." --no-deps
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ✗ Foreign Trade Assistant 安装失败（pip 的报错见上）。" -ForegroundColor Red
    Pop-Location
    exit 1
}
Pop-Location

# 真实探针：确认装完确实能导入（与 Step 2 的 `import hermes_cli` 对齐）。
# 只看 pip 退出码还不够 —— editable 安装可能"成功"但路径不对。
& $PyCmd -c "import trade.app"
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ✗ Foreign Trade Assistant 装好了但无法导入，安装不完整。" -ForegroundColor Red
    exit 1
}

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
"@ | Out-File -FilePath "$LocalBin\trade.cmd" -Encoding OEM

# 检测 PATH 中是否已包含 $LocalBin
$currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($currentPath -notlike "*$LocalBin*") {
    [Environment]::SetEnvironmentVariable("PATH", "$LocalBin;$currentPath", "User")
    Write-Host "  ✓ 已将 trade 命令加入 PATH（新终端生效）" -ForegroundColor Green
}

# ─────────────────────────────────────────────────────────────────────────────
# 开机自启动（隐藏窗口）+ 桌面快捷方式
#
# 委托给 trade.post_install.win_setup —— 那是唯一实现，服务启动时也会幂等调用。
# 以前这里用 Register-ScheduledTask 直接跑 python.exe，是控制台程序 → 登录必弹
# 终端窗口；而且只在这一处配，走「让 Hermes 装 Trade」流程的用户根本拿不到。
# ─────────────────────────────────────────────────────────────────────────────
& $PyCmd -c "from trade.post_install.win_setup import ensure_windows_setup, trade_dir_from_module; [print('  ' + m) for m in ensure_windows_setup(trade_dir_from_module())]"
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ⚠ 开机自启动/桌面快捷方式设置失败（不影响 Trade 使用，可稍后重试）" -ForegroundColor Yellow
}

# ─────────────────────────────────────────────────────────────────────────────
# 安装后自检（快检：零 token，不发真实请求）
#
# 端到端验活（真发一次对话 / 一张图 / 一次搜索）在**首次启动时**跑 ——
# 那时服务与配置都已就位，且结果会落盘、在界面提示。这里只做能立刻发现
# "装坏了"的快检，避免安装脚本因为网络波动误报失败而挡住用户。
# ─────────────────────────────────────────────────────────────────────────────
& $PyCmd -c "import sys; from trade.doctor import run_doctor, format_report, has_fatal_failure; r = run_doctor(deep=False); print(format_report(r)); sys.exit(1 if has_fatal_failure(r) else 0)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ✗ 自检发现致命问题，安装不完整。请把上面的输出发给技术支持。" -ForegroundColor Red
    exit 1
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
