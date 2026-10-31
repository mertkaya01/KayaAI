<#
.SYNOPSIS
    kayaAI - gerçek Ollama ile Faz 1 kabul testleri + kısa benchmark.
    Sonuç: data\smoke_report.json (bu dosyayı geliştirme oturumuna yapıştırın).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\windows\smoke.ps1
    powershell -ExecutionPolicy Bypass -File scripts\windows\smoke.ps1 -Quick
#>
[CmdletBinding()]
param([switch]$Quick)

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $ProjectRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$env:PYTHONUTF8 = "1"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Önce kurulum: powershell -ExecutionPolicy Bypass -File scripts\windows\setup.ps1" -ForegroundColor Red
    exit 1
}

Write-Host "==> Birim testleri" -ForegroundColor Cyan
& $VenvPython -m pytest -q
if ($LASTEXITCODE -ne 0) { Write-Host "Birim testleri başarısız." -ForegroundColor Red; exit 1 }

Write-Host "`n==> Gerçek model kabul testleri" -ForegroundColor Cyan
$smokeArgs = @("scripts\smoke_ollama.py")
if ($Quick) { $smokeArgs += "--quick" }
& $VenvPython @smokeArgs
exit $LASTEXITCODE
