<#
.SYNOPSIS
    kayaAI MCP sunucusunu doğrular ve Claude Code için proje yapılandırmasını (.mcp.json) oluşturur.

.DESCRIPTION
    1. scripts\mcp_check.py ile sunucuyu stdio üzerinden gerçek modelle test eder
    2. Proje kökünde .mcp.json oluşturur (bu bilgisayardaki mutlak yollarla; git'e girmez)
       Var olan .mcp.json'ın üzerine yazmadan önce sorar.
    Claude Code bu klasörde açıldığında kayaai sunucusunu kullanmak için onay ister.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\windows\mcp_setup.ps1
#>
[CmdletBinding()]
param([switch]$SkipCheck)

$ErrorActionPreference = "Continue"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $ProjectRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$env:PYTHONUTF8 = "1"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Önce kurulum: powershell -ExecutionPolicy Bypass -File scripts\windows\setup.ps1" -ForegroundColor Red
    exit 1
}

# mcp paketi kurulu mu? (setup.ps1 eski sürümle çalıştıysa eksik olabilir)
& $VenvPython -c "import mcp" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "==> mcp paketi kuruluyor" -ForegroundColor Cyan
    & $VenvPython -m pip install -e ".[dev]" --quiet
    if ($LASTEXITCODE -ne 0) { Write-Host "pip install başarısız" -ForegroundColor Red; exit 1 }
}

if (-not $SkipCheck) {
    Write-Host "==> MCP sunucusu gerçek modelle test ediliyor (stdio)" -ForegroundColor Cyan
    & $VenvPython scripts\mcp_check.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "MCP kontrolü başarısız; .mcp.json oluşturulmadı. data\mcp_check.json dosyasını paylaşın." -ForegroundColor Red
        exit 1
    }
}

$McpFile = Join-Path $ProjectRoot ".mcp.json"
if (Test-Path $McpFile) {
    Write-Host "`nMevcut .mcp.json:" -ForegroundColor Yellow
    Get-Content $McpFile | Write-Host
    $a = Read-Host "Üzerine yazılsın mı? (öncekinin yedeği .mcp.json.bak olarak saklanır) [e/H]"
    if ($a -notmatch '^(e|evet|y|yes)$') { Write-Host "Değiştirilmedi."; exit 0 }
    Copy-Item $McpFile "$McpFile.bak" -Force
}

$config = [ordered]@{
    mcpServers = [ordered]@{
        kayaai = [ordered]@{
            type    = "stdio"
            command = $VenvPython
            args    = @("-m", "kayaai.mcp_server")
            env     = [ordered]@{ PYTHONUTF8 = "1" }
        }
    }
}
$json = $config | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText($McpFile, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "`n[OK] .mcp.json oluşturuldu: $McpFile" -ForegroundColor Green
Get-Content $McpFile | Write-Host

Write-Host "`nSonraki adım:" -ForegroundColor Cyan
Write-Host "  1. Bu klasörde Claude Code'u başlatın:  claude"
Write-Host "  2. 'kayaai' MCP sunucusunu kullanma onayı sorulursa kabul edin"
Write-Host "  3. /mcp yazın: kayaai 'connected' görünmeli"
Write-Host "  4. Deneyin: kayaai_ask aracıyla yerel modele sor: Türkiye'nin başkenti neresi?"
