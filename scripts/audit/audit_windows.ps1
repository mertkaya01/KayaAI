<#
.SYNOPSIS
    kayaAI - Windows ortam denetimi (Faz 0). SALT OKUNUR: hiçbir şey kurmaz/değiştirmez.

.DESCRIPTION
    Python kurulu olmasa bile çalışır. İşletim sistemi, CPU, RAM, disk, NVIDIA GPU/sürücü/CUDA,
    geliştirme araçları ve Ollama durumunu toplar; data\audit_windows.json dosyasına yazar.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\audit\audit_windows.ps1
#>
[CmdletBinding()]
param(
    [string]$OutFile = ""
)

$ErrorActionPreference = "Continue"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $OutFile) { $OutFile = Join-Path $ProjectRoot "data\audit_windows.json" }

function Get-ToolVersion {
    param([string]$Name, [string[]]$VersionArgs = @("--version"))
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $cmd) { return [ordered]@{ installed = $false } }
    try {
        $out = & $cmd.Source @VersionArgs 2>&1 | Select-Object -First 1
        return [ordered]@{ installed = $true; version = "$out".Trim(); path = $cmd.Source }
    } catch {
        return [ordered]@{ installed = $true; version = "sürüm okunamadı: $($_.Exception.Message)"; path = $cmd.Source }
    }
}

Write-Host "=== kayaAI Windows Ortam Denetimi ===" -ForegroundColor Cyan

# --- İşletim sistemi
$os = Get-CimInstance Win32_OperatingSystem
$osInfo = [ordered]@{
    caption      = $os.Caption
    version      = $os.Version
    build        = $os.BuildNumber
    architecture = $os.OSArchitecture
    is_windows_11 = ([int]$os.BuildNumber -ge 22000)
}

# --- CPU
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$cpuInfo = [ordered]@{
    name          = $cpu.Name.Trim()
    cores         = $cpu.NumberOfCores
    logical_cores = $cpu.NumberOfLogicalProcessors
    max_clock_mhz = $cpu.MaxClockSpeed
}

# --- RAM
$ramInfo = [ordered]@{
    total_gb     = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
    available_gb = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
}

# --- Diskler
$disks = @()
Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
    $disks += [ordered]@{
        drive    = $_.DeviceID
        total_gb = [math]::Round($_.Size / 1GB, 2)
        free_gb  = [math]::Round($_.FreeSpace / 1GB, 2)
    }
}
$projectDrive = (Split-Path -Qualifier $ProjectRoot)

# --- GPU (Win32_VideoController 4 GB üstü VRAM'i yanlış raporlar; doğru değer nvidia-smi'den)
$videoControllers = @()
Get-CimInstance Win32_VideoController | ForEach-Object {
    $videoControllers += [ordered]@{ name = $_.Name; driver_version = $_.DriverVersion }
}
$gpuInfo = [ordered]@{ nvidia_smi_found = $false; gpus = @(); cuda_driver_version = $null; notes = @() }
$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($smi) {
    $gpuInfo.nvidia_smi_found = $true
    $q = "name,driver_version,memory.total,memory.used,memory.free,compute_cap"
    $rows = & $smi.Source "--query-gpu=$q" "--format=csv,noheader,nounits" 2>&1
    if ($LASTEXITCODE -ne 0) {
        $q = "name,driver_version,memory.total,memory.used,memory.free"
        $rows = & $smi.Source "--query-gpu=$q" "--format=csv,noheader,nounits" 2>&1
    }
    $fields = $q.Split(",")
    foreach ($row in $rows) {
        $parts = "$row".Split(",") | ForEach-Object { $_.Trim() }
        if ($parts.Count -ne $fields.Count) { continue }
        $g = [ordered]@{}
        for ($i = 0; $i -lt $fields.Count; $i++) { $g[$fields[$i]] = $parts[$i] }
        $gpuInfo.gpus += $g
        if (("$($g['compute_cap'])").StartsWith("12") -or $g['name'] -match "RTX 50") {
            $gpuInfo.notes += "$($g['name']): Blackwell (sm_120). CUDA 12.8+ destekli sürücü ve güncel Ollama gerekir."
        }
    }
    $header = (& $smi.Source 2>&1) -join "`n"
    if ($header -match "CUDA Version:\s*([\d\.]+)") {
        $gpuInfo.cuda_driver_version = $Matches[1]
        if ([version]$Matches[1] -lt [version]"12.8") {
            $gpuInfo.notes += "UYARI: Sürücünün CUDA sürümü $($Matches[1]) < 12.8. NVIDIA sürücüsünü güncelleyin."
        }
    }
} else {
    $gpuInfo.notes += "nvidia-smi bulunamadı: NVIDIA sürücüsü kurulu değil veya PATH'te yok."
}

# --- Araçlar
$tools = [ordered]@{
    python    = Get-ToolVersion "python"
    py_launcher = Get-ToolVersion "py" @("--version")
    git       = Get-ToolVersion "git"
    node      = Get-ToolVersion "node"
    npm       = Get-ToolVersion "npm"
    docker    = Get-ToolVersion "docker"
    ollama    = Get-ToolVersion "ollama"
    tesseract = Get-ToolVersion "tesseract"
    ffmpeg    = Get-ToolVersion "ffmpeg" @("-version")
    nvcc      = Get-ToolVersion "nvcc"
    winget    = Get-ToolVersion "winget"
}
# Microsoft Store'un sahte "python" kısayolu: çalıştırınca Store'u açar, sürüm basmaz.
if ($tools.python.installed -and $tools.python.path -like "*WindowsApps*") {
    $tools.python.note = "Bu Microsoft Store yönlendiricisi olabilir; python.org'dan Python 3.11+ kurun."
}

# --- Ollama servisi
$ollama = [ordered]@{ base_url = "http://127.0.0.1:11434"; reachable = $false; models = @() }
try {
    $v = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 3
    $ollama.reachable = $true
    $ollama.version = $v.version
    $tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 5
    foreach ($m in $tags.models) {
        $ollama.models += [ordered]@{ name = $m.name; size_gb = [math]::Round($m.size / 1GB, 2) }
    }
} catch {
    $ollama.error = $_.Exception.Message
}
$ollamaEnvHost = [Environment]::GetEnvironmentVariable("OLLAMA_HOST")
if ($ollamaEnvHost -and $ollamaEnvHost -match "0\.0\.0\.0") {
    $ollama.security_warning = "OLLAMA_HOST=$ollamaEnvHost : Ollama ağa açık! Güvenlik için kaldırın."
}
$ollama.models_dir = [Environment]::GetEnvironmentVariable("OLLAMA_MODELS")

# --- Mevcut proje kontrolü (üzerine yazmamak için)
$existing = Get-ChildItem -Path $ProjectRoot -Force -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name

$report = [ordered]@{
    generated_at        = (Get-Date).ToUniversalTime().ToString("o")
    project_dir         = $ProjectRoot
    project_drive       = $projectDrive
    os                  = $osInfo
    cpu                 = $cpuInfo
    ram                 = $ramInfo
    disks               = $disks
    video_controllers   = $videoControllers
    gpu                 = $gpuInfo
    tools               = $tools
    ollama              = $ollama
    powershell_version  = $PSVersionTable.PSVersion.ToString()
    project_entries     = $existing
}

$outDir = Split-Path -Parent $OutFile
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }
$json = $report | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText($OutFile, $json, (New-Object System.Text.UTF8Encoding($false)))

# --- Özet
Write-Host ("İşletim sistemi : {0} (build {1})" -f $osInfo.caption, $osInfo.build)
Write-Host ("CPU             : {0} - {1} çekirdek / {2} iş parçacığı" -f $cpuInfo.name, $cpuInfo.cores, $cpuInfo.logical_cores)
Write-Host ("RAM             : toplam {0} GB, boş {1} GB" -f $ramInfo.total_gb, $ramInfo.available_gb)
foreach ($d in $disks) { Write-Host ("Disk {0}         : toplam {1} GB, boş {2} GB" -f $d.drive, $d.total_gb, $d.free_gb) }
if ($gpuInfo.gpus.Count -gt 0) {
    foreach ($g in $gpuInfo.gpus) {
        Write-Host ("GPU             : {0} | VRAM {1} MB (boş {2} MB) | sürücü {3} | CUDA {4}" -f `
            $g['name'], $g['memory.total'], $g['memory.free'], $g['driver_version'], $gpuInfo.cuda_driver_version)
    }
} else {
    Write-Host "GPU             : NVIDIA GPU algılanmadı" -ForegroundColor Yellow
}
Write-Host "Yazılımlar:"
foreach ($k in $tools.Keys) {
    $t = $tools[$k]
    if ($t.installed) { Write-Host ("  OK {0,-12} {1}" -f $k, $t.version) -ForegroundColor Green }
    else { Write-Host ("  -- {0,-12} kurulu değil" -f $k) -ForegroundColor DarkGray }
}
if ($ollama.reachable) {
    $names = ($ollama.models | ForEach-Object { $_.name }) -join ", "
    if (-not $names) { $names = "(model yok)" }
    Write-Host "Ollama servisi  : çalışıyor v$($ollama.version) - modeller: $names" -ForegroundColor Green
} else {
    Write-Host "Ollama servisi  : erişilemiyor" -ForegroundColor Yellow
}
foreach ($n in $gpuInfo.notes) { Write-Host "  * $n" -ForegroundColor Yellow }
if ($ollama.security_warning) { Write-Host "  * $($ollama.security_warning)" -ForegroundColor Red }
Write-Host ""
Write-Host "Rapor yazıldı: $OutFile" -ForegroundColor Cyan
Write-Host "Bu dosyanın içeriğini kayaAI geliştirme oturumuna yapıştırabilirsiniz."
