# kayaAI — bilinen iyi paket sürümlerini kaydeder (docs/DEPLOYMENT.md §3).
# Her şey çalışırken çalıştır: .venv'deki sürümler constraints\windows.txt'ye UTF-8 olarak yazılır;
# setup.ps1 sonraki kurulumlarda bu sürümleri kullanır.

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "[HATA] .venv bulunamadı; önce scripts\windows\setup.ps1" -ForegroundColor Red
    exit 1
}
$Lines = & $VenvPython -m pip freeze --exclude-editable
if ($LASTEXITCODE -ne 0 -or -not $Lines) {
    Write-Host "[HATA] pip freeze başarısız" -ForegroundColor Red
    exit 1
}
$Dir = Join-Path $ProjectRoot "constraints"
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
$Out = Join-Path $Dir "windows.txt"
$Header = "# kayaAI bilinen iyi sürümler (Windows) — $(Get-Date -Format 'yyyy-MM-dd'); yenilemek: scripts\windows\freeze.ps1"
# UTF-8, BOM'suz (pip -c dosyasını böyle okur; PowerShell 5.1'de '>' UTF-16 yazar)
[System.IO.File]::WriteAllLines($Out, @($Header) + @($Lines | Where-Object { $_ -and ($_ -notmatch '^(-e |kayaai)') }),
    (New-Object System.Text.UTF8Encoding($false)))
Write-Host "[OK] $(@($Lines).Count) paket yazıldı: $Out" -ForegroundColor Green
