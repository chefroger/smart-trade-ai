#Requires -Version 5.1
# ==============================================================================
# Foreign Trade Assistant — 一键安装脚本 (Windows PowerShell)
# ==============================================================================
# 使用方式:
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# 全程使用 venv，不碰系统 Python site-packages。
# ==============================================================================

$ErrorActionPreference = "Stop"

# 控制台输出用 UTF-8 —— 否则中文提示在默认 GBK 代码页下是乱码，
# 用户群是电脑小白，乱码等于「看不懂 = 不敢用」。
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

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

# Microsoft Store 的「应用执行别名」是空壳：调它不会返回版本，
# 而是**弹开 Microsoft Store**（安装器会像卡死一样停在那里）。
# 所以 PATH 上的候选必须先排除 WindowsApps 目录下的别名。
function Test-NotStoreAlias {
    param([string]$Path)
    if (-not $Path) { return $true }
    return ($Path -notlike "*\Microsoft\WindowsApps\*")
}

foreach ($cmd in @("python3.14", "python3", "python")) {
    try {
        $resolved = $cmd
        $onPath = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($onPath) { $resolved = $onPath.Source }
        # 跳过 Store 别名（会弹商店）
        if (-not (Test-NotStoreAlias $resolved)) { continue }
        if (& $IsPython314 $cmd) {
            $PythonCmd = $cmd
            $pyPath = (& $cmd -c "import sys; print(sys.executable)" 2>$null)
            Write-Host "  ✓ Python 3.14 ($pyPath)" -ForegroundColor Green
            break
        }
    } catch {}
}

# Windows 自带的 `py` 启动器可以**显式指定版本**（`py -3.14`）。
# PATH 上的 `python` 常指向 3.11/3.13（用户装过多个版本），
# 而 `py -3.14` 能精确命中 —— 这是 Windows 独有、PATH 探测覆盖不到的入口。
if (-not $PythonCmd) {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        & $pyLauncher.Source -3.14 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 14) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            # 用数组保存「启动器 + 参数」，`& $cmd` 会把它拆成两个参数
            $PythonCmd = @($pyLauncher.Source, "-3.14")
            $pyPath = (& $pyLauncher.Source -3.14 -c "import sys; print(sys.executable)" 2>$null)
            Write-Host "  ✓ Python 3.14 ($pyPath)" -ForegroundColor Green
        }
    }
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
$VenvReal = "$TradeHome\venv"
$VenvDir  = $VenvReal
# 非空 = 旧环境还在原地、新环境建在 .new 里、依赖装完才切换（切换点见 Step 3 末尾）
$VenvOld  = $null

# 已有 venv 但解释器**不是 3.14** → 必须重建。旧装机器就地升级 trade 时，代码与依赖
# 都换了、venv 的解释器还是旧的（`trade update` 只更新代码与依赖，不重建 venv），
# 于是 Hermes 的 pm 激活会把 cp314 的包塞进旧解释器 → 聊天只报「AI Agent 模块未加载」。
# **重建不会丢任何用户数据**：数据在 $TradeHome 下（数据库、公司目录），不在 venv 里。
if ((Test-Path "$VenvDir\Scripts\python.exe") -and -not (& $IsPython314 "$VenvDir\Scripts\python.exe")) {
    # 先把旧版本号取出来写进提示 —— 用户需要知道「现在跑的是几」才能判断要不要处理
    $oldVer = & "$VenvDir\Scripts\python.exe" -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    if (-not $oldVer) { $oldVer = "未知" }
    Write-Host "  ! 已有的运行环境是 Python $oldVer，需要 3.14 —— 正在重建（不会动你的数据）..." -ForegroundColor Yellow
    # 换掉之前留一份已装包清单：venv 里可能有用户手动 pip install 的东西，
    # 这份清单是事后唯一的追查线索。失败不影响安装（best-effort）。
    try {
        if (-not (Test-Path $TradeHome)) { New-Item -ItemType Directory -Path $TradeHome -Force | Out-Null }
        & "$VenvDir\Scripts\pip.exe" freeze 2>$null | Out-File -FilePath "$TradeHome\venv-packages-before-rebuild.txt" -Encoding utf8
        Write-Host "  → 已把重建前的包清单留档：$TradeHome\venv-packages-before-rebuild.txt" -ForegroundColor Cyan
    } catch {}
    # **不在原地重建**（2026-10-16 改，与 install.sh 同步）。原实现是 Remove-Item 后立刻重建，
    # 中间任何一步失败（断网 / 磁盘满 / 找不到 3.14 / 依赖装不上）都会留下
    # 「旧的已经删了、新的没建成」——用户软件直接打不开，而客群是电脑小白，无力自救。
    # 改为把新环境建到 .new、依赖全部装成功后才切换，失败时旧环境原样可用。
    $VenvOld = $VenvDir
    $VenvDir = "$VenvReal.new"
    # 只清上一次失败残留的 .new —— 它从来不是用户数据，删了不影响任何人
    if (Test-Path $VenvDir) { Remove-Item -Recurse -Force $VenvDir }
}
if (-not (Test-Path "$VenvDir\Scripts\python.exe")) {
    Write-Host "  → 创建虚拟环境..."
    & $PythonCmd -m venv $VenvDir
    # 原生命令非零退出**不会抛异常**（本文件后面有多处踩坑记录）——
    # 不查就是「venv 没建成」却继续往下走，用户最后只看到一句
    # ModuleNotFoundError，而真正的原因是这里。
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path "$VenvDir\Scripts\python.exe")) {
        Write-Host "  ✗ 虚拟环境创建失败（上面的报错见上）。请检查磁盘空间与路径权限后重试。" -ForegroundColor Red
        exit 1
    }
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
# 兜底：在 Hermes 根目录里**递归找** hermes.cmd / hermes.exe（限制深度）。
# **刻意不写死布局** —— 上游换安装布局时，写死的路径会「静默找不到」，
# 用户看到的只是「未找到 hermes 命令」，而实际上它就在硬盘上。
if (-not $hermesCmd -and (Test-Path $HermesHome)) {
    # 用 -Filter 而不是 -Include：后者在 -Recurse 下要求路径以 \* 结尾，
    # 否则过滤条件会被**整体忽略**（返回目录里所有文件），第一个命中的是随机文件。
    $found = Get-ChildItem -Path $HermesHome -Filter "hermes.*" `
        -Recurse -Depth 4 -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -eq ".cmd" -or $_.Extension -eq ".exe" } |
        Select-Object -First 1
    if ($found) { $hermesCmd = $found.FullName }
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

# ── 前置检查：git 与长路径 ────────────────────────────────────────────────
# git 是下载代码的硬前提。缺了它，用户看到的是 git 自己的英文报错
# （'git' 不是内部或外部命令），小白完全无从下手 —— 这里直接给出安装命令。
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "  ✗ 未找到 git —— 无法下载 Trade 代码。" -ForegroundColor Red
    Write-Host ""
    Write-Host "  请先安装 Git（任选一种；装完**重开** PowerShell 再运行本脚本）：" -ForegroundColor White
    Write-Host "    winget install Git.Git"
    Write-Host "    或手动下载：https://git-scm.com/download/win"
    exit 1
}

# 长路径（MAX_PATH）：Windows 默认 260 字符上限，venv 里的 site-packages
# 路径很深，撞上限时报的是 'Filename too long'。这不是致命问题 ——
# 能装成就装成，装不成下面这行命令能救，所以只提示、不阻断。
try {
    $longPaths = (Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" `
        -Name LongPathsEnabled -ErrorAction Stop).LongPathsEnabled
} catch {
    $longPaths = 0
}
if ($longPaths -ne 1) {
    Write-Host "  ⚠ 系统未开启长路径支持（Windows 默认 260 字符上限）。" -ForegroundColor Yellow
    Write-Host "    若安装中途报 'Filename too long'，用**管理员** PowerShell 执行下面这行后重试：" -ForegroundColor Yellow
    Write-Host "      New-ItemProperty -Path `"HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem`" -Name LongPathsEnabled -Value 1 -PropertyType DWORD -Force"
}

# 记录回滚点（2026-10-16 加，与 install.sh 同步）。重建场景下依赖若装不上，代码必须能
# 退回升级前 —— 否则「新代码 + 旧 venv」照样起不来，等于把「重建失败」升级成「彻底打不开」。
# 新装用户这里是空的，Invoke-RollbackCode 自然什么都不做。
$TradeHeadBefore = $null
if (Test-Path "$TradeDir\.git") {
    $sha = git -C $TradeDir rev-parse HEAD 2>$null
    if ($LASTEXITCODE -eq 0 -and $sha) { $TradeHeadBefore = "$sha".Trim() }
}

function Invoke-RollbackCode {
    if (-not $TradeHeadBefore) { return }
    Write-Host "  ⚠ 正在把代码回退到升级前的版本（$($TradeHeadBefore.Substring(0,8))）..." -ForegroundColor Yellow
    git -C $TradeDir reset --hard $TradeHeadBefore 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ 代码已回退，旧版本仍可正常使用" -ForegroundColor Green
    } else {
        Write-Host "  ✗ 代码回退失败 —— 请把上面的输出发给技术支持" -ForegroundColor Red
    }
    # 丢弃半成品的新环境；旧环境（$VenvOld）始终没被动过
    if ($VenvOld -and (Test-Path $VenvDir)) { Remove-Item -Recurse -Force $VenvDir }
}

if (-not (Invoke-CloneOrUpdate "foreign-trade-assistant" $TradeRepo $TradeDir)) { exit 1 }

Push-Location $TradeDir
# 装依赖 + trade 自身。
# 每个 pip 后都必须查 $LASTEXITCODE —— 原生命令非零退出不抛异常（见本文件前面的说明），
# 不查就会在弱网/磁盘满时把失败当成成功，用户之后运行 trade 只得到
# ModuleNotFoundError，且开机自启任务每次登录静默失败。
& $PipCmd install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ✗ 依赖安装失败（pip 的报错见上）。请检查网络后重新运行本脚本。" -ForegroundColor Red
    Invoke-RollbackCode
    Pop-Location
    exit 1
}
& $PipCmd install -e "." --no-deps
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ✗ Foreign Trade Assistant 安装失败（pip 的报错见上）。" -ForegroundColor Red
    Invoke-RollbackCode
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
    Invoke-RollbackCode
    exit 1
}

# ─────────────────────────────────────────────────────────────────────────────
# 新运行环境验证通过后，才切换到位（对应前面的 .new 方案）
#
# 为什么压到这么后面：切换是**唯一不可逆的一步**。把它放在「建 venv / git pull /
# pip install / import 探针」全部成功之后，失败面就只剩两个目录改名 —— 本地文件
# 操作，几乎不会失败；即便失败，下面也保留了 .old 供恢复。
# ─────────────────────────────────────────────────────────────────────────────
if ($VenvOld) {
    Write-Host "  → 新运行环境已就绪，正在切换..." -ForegroundColor Cyan
    $VenvOldBak = "$VenvOld.old"
    if (Test-Path $VenvOldBak) { Remove-Item -Recurse -Force $VenvOldBak }
    $swapOk = $false
    try {
        Move-Item -Path $VenvOld -Destination $VenvOldBak -Force
        Move-Item -Path $VenvDir -Destination $VenvOld -Force
        $swapOk = $true
    } catch {}
    if ($swapOk) {
        if (Test-Path $VenvOldBak) { Remove-Item -Recurse -Force $VenvOldBak }
        $VenvDir = $VenvOld
        $PipCmd  = "$VenvDir\Scripts\pip.exe"
        $PyCmd   = "$VenvDir\Scripts\python.exe"
        Write-Host "  ✓ 已切换到 Python 3.14 运行环境" -ForegroundColor Green
    } else {
        # 把旧环境挪回来，丢弃半成品
        Write-Host "  ✗ 切换运行环境失败，正在恢复原环境..." -ForegroundColor Red
        if (Test-Path $VenvOldBak) { Move-Item -Path $VenvOldBak -Destination $VenvOld -Force }
        if (Test-Path "$VenvReal.new") { Remove-Item -Recurse -Force "$VenvReal.new" }
        Invoke-RollbackCode
        exit 1
    }
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

# chat-memory 插件：trade 自带的工具（让 LLM 能查 conversations 表的历史对话）。
# setup() 会兜底同步 + 写 config.yaml；这里做一次显式的初始安装，幂等。
& $PyCmd -c "from trade.bootstrap import sync_chat_memory_plugin, ensure_chat_memory_plugin_enabled; sync_chat_memory_plugin(); ensure_chat_memory_plugin_enabled()"
if ($LASTEXITCODE -eq 0) {
    Write-Host "  ✓ chat-memory 插件已部署到 ~/.hermes\plugins\chat-memory" -ForegroundColor Green
} else {
    Write-Host "  ⚠ chat-memory 插件部署失败（首次启动时会自动重试）" -ForegroundColor Yellow
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

# 把用户目录前缀换成环境变量引用，让写进 .cmd 的内容保持**纯 ASCII**。
#
# 与 trade/post_install/win_setup.py 的 to_batch_path 同构：cmd.exe 按系统 OEM
# 代码页读 .bat，中文用户名（C:\Users\张伟\...）直接写进去，在**英文**系统上
# 会被替换成 '?'（且不报错）——于是表现为「后台能跑、命令坏了」，最难排查。
# 用 %LOCALAPPDATA% / %USERPROFILE% 在运行时展开，就完全绕开了编码问题。
function ConvertTo-BatchPath {
    param([string]$Path)
    if (-not $Path) { return $Path }
    foreach ($envName in @("LOCALAPPDATA", "USERPROFILE")) {
        $prefix = [Environment]::GetEnvironmentVariable($envName)
        if ($prefix -and $Path.ToLower().StartsWith($prefix.ToLower())) {
            return "%$envName%" + $Path.Substring($prefix.Length)
        }
    }
    return $Path
}

$BatchHermesHome = ConvertTo-BatchPath $HermesHome
$BatchTradeHome  = ConvertTo-BatchPath $TradeHome
$BatchPyCmd      = ConvertTo-BatchPath $PyCmd
$BatchServerPy   = ConvertTo-BatchPath "$TradeDir\server.py"

@"
@echo off
set HERMES_HOME=$BatchHermesHome
REM Keep TRADE_HOME: a custom data dir must survive the launcher, otherwise the
REM service reads a different directory than the one the installer populated.
set TRADE_HOME=$BatchTradeHome
REM Disable Hermes lazy-install restart: without it the agent thread is re-exec'd
REM into Hermes' own store python (no trade package there) and dies silently.
REM bootstrap.py sets it too; this is the belt-and-braces copy.
set HERMES_DISABLE_LAZY_INSTALLS=1
"$BatchPyCmd" "$BatchServerPy" %*
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
