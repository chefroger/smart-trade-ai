# ==============================================================================
# Foreign Trade Assistant - Windows installer bootstrap (ASCII only)
#
# Why this file exists (2026-11-03, customer machine):
#   The real installer (install-core.ps1) is UTF-8 *with BOM*, because Windows
#   PowerShell 5.1 decodes BOM-less files with the system code page (GBK) and
#   would fail on the Chinese text when run as `-File`. But `irm ... | iex`
#   passes that BOM into the script text, and 5.1 then tries to execute the
#   first token literally: "The term '\uFEFF#Requires' is not recognized".
#
#   This bootstrap is deliberately pure ASCII with no BOM, so BOTH paths work:
#     irm <this file> | iex
#     powershell -ExecutionPolicy Bypass -File install.ps1
#   It loads install-core.ps1, decodes it as UTF-8, strips any BOM, and runs it.
# ==============================================================================

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# GitHub requires TLS 1.2; Windows PowerShell 5.1 does not always negotiate it.
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
} catch {}

$CoreUrl = "https://raw.githubusercontent.com/chefroger/smart-trade-ai/main/scripts/install-core.ps1"

try {
    $code = $null

    # Local checkout: use the sibling file (works offline; also keeps tests honest).
    $here = $PSScriptRoot
    if ($here) {
        $localCore = Join-Path $here "install-core.ps1"
        if (Test-Path -LiteralPath $localCore) {
            $code = [System.IO.File]::ReadAllText($localCore, [System.Text.Encoding]::UTF8)
        }
    }

    # Piped through `irm | iex` (or downloaded alone): fetch the real installer.
    if (-not $code) {
        $resp = Invoke-WebRequest -UseBasicParsing -Uri $CoreUrl
        $body = $resp.Content
        if ($body -is [byte[]]) {
            $code = [System.Text.Encoding]::UTF8.GetString($body)
        } else {
            $code = [string]$body
        }
    }

    # Strip a leading UTF-8 BOM if the transport preserved it.
    $code = $code.TrimStart([char]0xFEFF)

    Invoke-Expression $code
}
catch {
    Write-Host ""
    Write-Host "  Installation aborted: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  Installer URL: $CoreUrl" -ForegroundColor Yellow
    Write-Host "  Please send both lines above to support." -ForegroundColor Yellow
    exit 1
}
