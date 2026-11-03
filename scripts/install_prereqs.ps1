#Requires -Version 5
# ==============================================================================
# Hermes Agent 前置软件安装脚本 — Windows (PowerShell)
# ==============================================================================
# 安装 hermes-agent（NousResearch/hermes-agent）所需的全部前置软件。
# 仅安装必需的系统依赖，不包含 hermes-agent 自身。
#
# 使用方式（PowerShell 5.1+）：
#   powershell -ExecutionPolicy Bypass -File install_prereqs.ps1
#
# 或者一键安装（curl | iex）：
#   irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1 | iex
#   （官方安装脚本已包含所有前置软件，以上仅作独立运行参考）
# ==============================================================================

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# ─────────────────────────────────────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────────────────────────────────────
# Hermes v0.21.6+ 只提供 Python 3.14 的依赖集，Trade 进程内嵌 Hermes，
# 必须同 ABI —— 这里不能再检查/推荐 3.11。
$PythonVersion = "3.14"
$NodeVersion = "22"
$HermesHome = "$env:LOCALAPPDATA\hermes"

# ─────────────────────────────────────────────────────────────────────────────
# 颜色输出
# ─────────────────────────────────────────────────────────────────────────────
function Write-Info  { param([string]$m) Write-Host "→ $m" -ForegroundColor Cyan }
function Write-Success{ param([string]$m) Write-Host "✓ $m" -ForegroundColor Green }
function Write-Warn   { param([string]$m) Write-Host "⚠ $m" -ForegroundColor Yellow }
function Write-Err    { param([string]$m) Write-Host "✗ $m" -ForegroundColor Red }
function Write-Step   { param([int]$n, [string]$m) Write-Host "`n[$n] $m" -ForegroundColor Magenta }

# ─────────────────────────────────────────────────────────────────────────────
# 前置检查
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================================" -ForegroundColor Magenta
Write-Host "  Hermes Agent 前置软件安装脚本 (Windows)" -ForegroundColor Magenta
Write-Host "  仅安装系统依赖，不包含 Hermes Agent 本身" -ForegroundColor Magenta
Write-Host "============================================================" -ForegroundColor Magenta
Write-Host ""

# 检测是否为管理员（用于 winget 安装）
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

# 检测 winget
$hasWinget = $null -ne (Get-Command winget -ErrorAction SilentlyContinue)

# 检测 choco
$hasChoco = $null -ne (Get-Command choco -ErrorAction SilentlyContinue)

# 检测 scoop
$hasScoop = $null -ne (Get-Command scoop -ErrorAction SilentlyContinue)

Write-Info "管理员模式: $isAdmin"
Write-Info "winget: $hasWinget"
Write-Info "choco: $hasChoco"
Write-Info "scoop: $hasScoop"
Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# 1. Git（Bash 环境，Hermes terminal tool 和 agent-browser 必需）
# ─────────────────────────────────────────────────────────────────────────────
Write-Step 1 "Git（Hermes terminal tool 和 agent-browser 必需）"

if (Get-Command git -ErrorAction SilentlyContinue) {
    $gitVer = git --version
    Write-Success "Git 已安装: $gitVer"
} else {
    Write-Warn "Git 未安装"
    Write-Info "安装选项（按优先级）："

    if ($hasWinget) {
        Write-Info "  选项 A — winget（推荐）:"
        Write-Info "    winget install Git.Git --silent --accept-package-agreements --accept-source-agreements"
        if ($isAdmin) {
            winget install Git.Git --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
            if ($?) { Write-Success "Git 安装完成" }
        }
    }
    if ($hasChoco) {
        Write-Info "  选项 B — Chocolatey:"
        Write-Info "    choco install git -y"
    }
    Write-Info "  选项 C — 手动下载:"
    Write-Info "    https://git-scm.com/download/win"
    Write-Info "  选项 D — 使用 Hermes 安装器（自动下载 PortableGit）:"
    Write-Info "    irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1 | iex"
}

# ─────────────────────────────────────────────────────────────────────────────
# 2. Python（Hermes Python 包必需）
# ─────────────────────────────────────────────────────────────────────────────
Write-Step 2 "Python $PythonVersion（Hermes Python 包必需）"

$pythonFound = $false
$pythonPath = $null

# 尝试通过 uv 查找
$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
if ($uvCmd) {
    try {
        $found = & uv python find $PythonVersion 2>$null
        if ($found -and (Test-Path $found)) {
            $ver = & $found --version 2>$null
            if ($ver -match "Python $PythonVersion") {
                $pythonPath = $found
                $pythonFound = $true
                Write-Success "Python 找到: $ver (via uv)"
            }
        }
    } catch { }
}

# 尝试查找系统 Python
if (-not $pythonFound) {
    $sysPy = Get-Command python -ErrorAction SilentlyContinue
    if ($sysPy) {
        $ver = python --version 2>$null
        if ($ver -match ("Python " + [regex]::Escape($PythonVersion))) {
            $pythonFound = $true
            $pythonPath = $sysPy.Source
            Write-Success "系统 Python: $ver"
        }
    }
}

if (-not $pythonFound) {
    Write-Warn "Python $PythonVersion 未找到"
    Write-Info "Hermes 安装器会自动通过 uv 安装 Python，无需手动安装"
    Write-Info "（使用 Hermes 安装器安装时，会自动处理 Python）:"
    Write-Info "  irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1 | iex"
}

# ─────────────────────────────────────────────────────────────────────────────
# 3. uv（Python 包管理器，Hermes 安装器核心工具）
# ─────────────────────────────────────────────────────────────────────────────
Write-Step 3 "uv（Python 包管理器，Hermes 安装器核心工具）"

if (Get-Command uv -ErrorAction SilentlyContinue) {
    $ver = uv --version
    Write-Success "uv 已安装: $ver"
} else {
    Write-Warn "uv 未安装"
    if ($hasWinget) {
        Write-Info "通过 winget 安装 uv..."
        # winget 官方包 ID 是 astral-sh.uv（不是 Astronaut.uv）；
        # 不用 2>&1：PS 5.1 + EAP Stop 下原生命令 stderr 重定向会中止脚本。
        winget install --id astral-sh.uv -e --silent --accept-package-agreements --accept-source-agreements | Out-Null
        if ($LASTEXITCODE -eq 0) {
            # 刷新 PATH
            $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
            if (Get-Command uv -ErrorAction SilentlyContinue) {
                Write-Success "uv 安装完成: $(uv --version)"
            }
        }
    }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Info "手动安装 uv（PowerShell）:"
        Write-Info '  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
        Write-Info "详细说明: https://docs.astral.sh/uv/getting-started/installation/"
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# 4. Node.js（可选，浏览器工具需要）
# ─────────────────────────────────────────────────────────────────────────────
Write-Step 4 "Node.js $NodeVersion LTS（可选，浏览器工具需要）"

if (Get-Command node -ErrorAction SilentlyContinue) {
    Write-Success "Node.js 已安装: $(node --version)"
} else {
    Write-Warn "Node.js 未安装（可选：Hermes 浏览器工具需要）"

    if ($hasWinget) {
        Write-Info "通过 winget 安装 Node.js LTS..."
        winget install OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
        if ($?) {
            $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
            if (Get-Command node -ErrorAction SilentlyContinue) {
                Write-Success "Node.js 安装完成: $(node --version)"
            }
        }
    }
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        if ($hasChoco) {
            Write-Info "通过 Chocolatey 安装: choco install nodejs -y"
        }
        Write-Info "手动下载: https://nodejs.org/en/download/"
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# 5. ripgrep（可选，加快 Hermse 文件搜索速度）
# ─────────────────────────────────────────────────────────────────────────────
Write-Step 5 "ripgrep（可选，加快 Hermse 文件搜索速度）"

if (Get-Command rg -ErrorAction SilentlyContinue) {
    $rgVer = rg --version | Select-Object -First 1
    Write-Success "ripgrep 已安装: $rgVer"
} else {
    Write-Warn "ripgrep 未安装（可选：文件搜索会使用 findstr 替代）"

    if ($hasWinget) {
        winget install BurntSushi.ripgrep.MSVC --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
        if ($?) { Write-Success "ripgrep 安装完成" }
    }
    if (-not (Get-Command rg -ErrorAction SilentlyContinue)) {
        if ($hasChoco) {
            Write-Info "通过 Chocolatey: choco install ripgrep -y"
        }
        Write-Info "手动下载: https://github.com/BurntSushi/ripgrep#installation"
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# 6. ffmpeg（可选，TTS 语音消息需要）
# ─────────────────────────────────────────────────────────────────────────────
Write-Step 6 "ffmpeg（可选，TTS 语音消息需要）"

if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    $ffVer = ffmpeg -version 2>&1 | Select-Object -First 1
    Write-Success "ffmpeg 已安装: $ffVer"
} else {
    Write-Warn "ffmpeg 未安装（可选：TTS 语音功能不可用）"

    if ($hasWinget) {
        winget install Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
        if ($?) { Write-Success "ffmpeg 安装完成" }
    }
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
        if ($hasChoco) {
            Write-Info "通过 Chocolatey: choco install ffmpeg -y"
        }
        Write-Info "手动下载: https://ffmpeg.org/download.html"
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# 完成总结
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  前置软件检查完成" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  接下来安装 Hermes Agent:" -ForegroundColor White
Write-Host ""
Write-Host "  PowerShell 一键安装（推荐）:" -ForegroundColor Cyan
Write-Host "    irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1 | iex" -ForegroundColor Gray
Write-Host ""
Write-Host "  或者下载安装脚本后运行:" -ForegroundColor Cyan
Write-Host "    Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1' -OutFile install.ps1" -ForegroundColor Gray
Write-Host "    .\install.ps1" -ForegroundColor Gray
Write-Host ""
Write-Host "  安装完成后验证 Hermes:" -ForegroundColor White
Write-Host "    hermes --version" -ForegroundColor Gray
Write-Host "    python pre_install_check.py" -ForegroundColor Gray
Write-Host ""
