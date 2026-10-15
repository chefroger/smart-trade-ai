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

# Trade 必须跑在 **Python 3.14** 上：Hermes 从 v0.21.6 起只提供 3.14 的依赖集
# （requires-python 里那个 `>=3.11` 只是留给旧安装「跑完自己的升级步骤」的过渡桥），
# 而 Trade 是**进程内**嵌 Hermes 的，解释器必须与 Hermes 的托管环境同 ABI。
# 在 3.11~3.13 上会变成「装得上、起不来」，所以这里不再接受 3.11~3.13。
$PythonCmd = $null
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { "$env:LOCALAPPDATA\hermes" }

# 判据：解释器正好是 3.14（不是「>= 3.11」下限）
$IsPython314 = { param($cmd) & $cmd -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 14) else 1)" 2>$null; $LASTEXITCODE -eq 0 }

foreach ($cmd in @("python3.14", "python3", "python")) {
    try {
        if (& $IsPython314 $cmd) {
            $PythonCmd = $cmd
            Write-Host "  ✓ Python 3.14 ($(& $PythonCmd -c "import sys; print(sys.executable)"))" -ForegroundColor Green
            break
        }
    } catch {}
}

# 退路：Hermes 自带的托管解释器 —— 优先用它：与 Hermes 的运行时 ABI 完全一致。
#
# **刻意不写死布局**。2026-10-15 用户实测（Linux 侧同源问题）：按代码推断出来的单一
# glob 在真机上一个都匹配不到 —— 真实布局有两棵代际树，且代际里还套一层 venv/
# （权威来源 pm/operations.py:152/210 `generation / "venv"`、
#   pm/install_states.py:72 的两棵树）。写死布局一旦猜错就是「静默找不到」。
# 所以改成**递归找 + 按版本号验**：对布局变化免疫，多找到的由 $IsPython314 兜住
# （任一份 3.14 都能建 Trade 的 venv，同为 cp314 ABI）。
# -Depth 6 刚好到 <tree>\<gen>\venv\Scripts\python.exe，再深就进 Lib\site-packages 了。
if (-not $PythonCmd) {
    $candidates = Get-ChildItem -Path "$HermesHome\installs", "$HermesHome\tools" `
        -Filter "python*.exe" -Recurse -Depth 6 -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^python(3\.14)?\.exe$' }
    foreach ($cand in $candidates) {
        try {
            if (& $IsPython314 $cand.FullName) {
                $PythonCmd = $cand.FullName
                Write-Host "  ✓ 使用 Hermes 自带的 Python 3.14 ($PythonCmd)" -ForegroundColor Green
                break
            }
        } catch {}
    }
}

if (-not $PythonCmd) {
    Write-Host "  ✗ 需要 Python 3.14，但未找到。" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Trade 必须与 Hermes 用同一个 Python 大版本（3.14）。任选一种方式：" -ForegroundColor White
    Write-Host ""
    Write-Host "  1) 让 Hermes 自带（推荐）—— 先安装 Hermes，它会自带 3.14，本脚本能自动找到：" -ForegroundColor White
    Write-Host "       irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1 | iex"
    Write-Host ""
    Write-Host "  2) 自己装 3.14：" -ForegroundColor White
    Write-Host "       winget install Python.Python.3.14"
    exit 1
}

# ─────────────────────────────────────────────────────────────────────────────
# 创建 venv
# ─────────────────────────────────────────────────────────────────────────────
$TradeHome = if ($env:TRADE_HOME) { $env:TRADE_HOME } else { "$env:LOCALAPPDATA\trade" }
$VenvDir = "$TradeHome\venv"
# 已有 venv 但解释器**不是 3.14** → 必须重建。旧装机器就地升级 trade 时，代码与依赖
# 都换了、venv 的解释器还是旧的（`trade update` 只更新代码与依赖，不重建 venv），
# 于是 Hermes 的 pm 激活会把 cp314 的包塞进旧解释器 → 聊天只报「AI Agent 模块未加载」。
# **删掉它不会丢任何用户数据**：数据在 $TradeHome 下（数据库、公司目录），不在 venv 里。
if ((Test-Path "$VenvDir\Scripts\python.exe") -and -not (& $IsPython314 "$VenvDir\Scripts\python.exe")) {
    Write-Host "  ! 已有的运行环境不是 Python 3.14 —— 正在重建（不会动你的数据）..." -ForegroundColor Yellow
    # Remove-Item 之前留一份已装包清单：venv 里可能有用户手动 pip install 的东西，
    # 重建不可逆，这份清单是事后唯一的追查线索。失败不影响安装（best-effort）。
    try {
        if (-not (Test-Path $TradeHome)) { New-Item -ItemType Directory -Path $TradeHome -Force | Out-Null }
        & "$VenvDir\Scripts\pip.exe" freeze 2>$null | Out-File -FilePath "$TradeHome\venv-packages-before-rebuild.txt" -Encoding utf8
        Write-Host "  → 已把重建前的包清单留档：$TradeHome\venv-packages-before-rebuild.txt" -ForegroundColor Cyan
    } catch {}
    Remove-Item -Recurse -Force $VenvDir
}
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
#   2. 浅克隆 --depth 1：全历史克隆在弱网下最慢、最易失败。跟 main 时本地没有 tag，
#      Hermes 版本推导会退化为「未知」（Trade 警告后继续启动）；固定版本模式
#      （--branch <tag>）会把该 tag 一并带上，版本可正常解出。
#   3. 不吞 git 的 stderr：用户要靠它排查网络问题。
function Invoke-CloneOrUpdate {
    param([string]$Name, [string]$Repo, [string]$Dest, [string]$Ref = "main")

    $isRepo = $false
    if (Test-Path "$Dest\.git") {
        git -C $Dest rev-parse --verify HEAD 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { $isRepo = $true }
    }

    if ($isRepo) {
        # 固定版本模式（Ref != main，Hermes 用）：不 pull —— 在 tag 检出上 pull main
        # 会把它拖到 main 尖端，固定就失去意义。已有检出保持原样。
        if ($Ref -ne "main") {
            Write-Host "  → 已有 $Name 检出，保持现状（固定版本 $Ref，不跟随 main）" -ForegroundColor Cyan
            return $true
        }
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
    git clone --depth 1 --branch $Ref $Repo $Dest
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
Write-Host "Step 2/5: 检查 Hermes Agent" -ForegroundColor White

# **不再把 Hermes 克隆/安装进 Trade 的 venv**（旧的固定 tag 方案已废除）。
# 现在机器上只有**一份** Hermes：用户自己装的那份。Trade 通过 sys.path 指向它，
# 并让它的 pm 托管环境提供 Hermes 的依赖（见 trade/bootstrap.py 与 COMPATIBILITY.md）。
#
# 旧方案把 Hermes 装进 Trade 的 venv，并与用户那份抢同一个 checkout 目录，
# 结果是「pin 静默失效 + 把用户的 Hermes 降级」（见 COMPATIBILITY.md 跟进记录）。
#
# 版本是否够新由 Trade 启动时判定；过旧会在界面里自动升级（trade/hermes_upgrade.py），
# 所以这里只确认它存在，不在这里改动用户的 Hermes。
$hermesCmd = $null
foreach ($candidate in @("$env:LOCALAPPDATA\hermes\hermes-agent\.hermes\bin\hermes.cmd",
                         "$env:USERPROFILE\.local\bin\hermes.cmd",
                         "$env:USERPROFILE\.local\bin\hermes.exe")) {
    if (Test-Path $candidate) { $hermesCmd = $candidate; break }
}
if (-not $hermesCmd) {
    $onPath = Get-Command hermes -ErrorAction SilentlyContinue
    if ($onPath) { $hermesCmd = $onPath.Source }
}

if ($hermesCmd) {
    Write-Host "  ✓ 已找到 hermes 命令（$hermesCmd）" -ForegroundColor Green
} else {
    Write-Host "  ✗ 未找到 hermes 命令 —— 请先安装 Hermes Agent。" -ForegroundColor Red
    Write-Host ""
    Write-Host "  复制下面这一行，粘贴到 PowerShell 后回车：" -ForegroundColor White
    Write-Host "    irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1 | iex"
    Write-Host ""
    Write-Host "  装好后重新运行本安装脚本。" -ForegroundColor White
    exit 1
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

# 可选依赖：客户语义检索用的向量扩展（sqlite-vec）。
# **单独装、失败只警告** —— 不是主链依赖：不装则语义检索自动降级关键词，
# 其余功能零影响；个别平台（如 Windows ARM）没有对应 wheel，
# 不能因为一个可选能力让整台机器的安装失败。
& $PyCmd -c "import sqlite_vec" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "  ✓ sqlite-vec 已安装（客户语义检索可用）" -ForegroundColor Green
} else {
    & $PipCmd install "sqlite-vec>=0.1.6" *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ sqlite-vec 安装完成（客户语义检索可用）" -ForegroundColor Green
    } else {
        Write-Host "  ⚠ sqlite-vec 未安装：客户语义检索将降级为关键词检索（其余功能不受影响）" -ForegroundColor Yellow
    }
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
# 两处都必须在调 doctor 之前处理：
#   1. `prepare_hermes_import_paths()` —— Hermes 不再装进 Trade 的 venv，不先准备
#      sys.path 就直接 import doctor 会报 `No module named 'run_agent'`（干净机器实测）。
#   2. doctor 自己会 import Hermes，会触发 pm 激活剥离 venv 的 site-packages；
#      那一步的恢复也在这个函数里，漏了会让后面 holehe/sqlite-vec 误报「未安装」。
# 「Hermes 版本」这一项刻意不计入致命项：版本过旧不需要在这里解决 —— Trade 启动后
# 会在界面里自动升级 Hermes（见 trade/hermes_upgrade.py）。若这里判失败并退出，
# 用户就永远看不到那个升级界面了。
& $PyCmd -c "import sys; from trade.bootstrap import prepare_hermes_import_paths; prepare_hermes_import_paths(); from trade.doctor import run_doctor, format_report, has_fatal_failure; r = run_doctor(deep=False); print(format_report(r)); sys.exit(1 if has_fatal_failure(r, ignore_names=('Hermes 版本',)) else 0)"
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
