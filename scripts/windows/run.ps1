<#
.SYNOPSIS
    kayaAI komutlarını sanal ortamı etkinleştirmeden çalıştırır.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\windows\run.ps1 doctor
    powershell -ExecutionPolicy Bypass -File scripts\windows\run.ps1 ask "Merhaba, nasılsın?"
    powershell -ExecutionPolicy Bypass -File scripts\windows\run.ps1 tasks
#>
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$env:PYTHONUTF8 = "1"
if (-not (Test-Path $VenvPython)) {
    Write-Host "Önce kurulum: powershell -ExecutionPolicy Bypass -File scripts\windows\setup.ps1" -ForegroundColor Red
    exit 1
}
& $VenvPython -m kayaai @args
exit $LASTEXITCODE
