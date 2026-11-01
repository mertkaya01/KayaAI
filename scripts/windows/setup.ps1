<#
.SYNOPSIS
    kayaAI - Windows kurulum scripti (Faz 1).

.DESCRIPTION
    Adım adım ve her adımı doğrulayarak:
      1. Python 3.11+ bulur (yoksa winget ile kurmayı SORAR)
      2. Proje içinde .venv sanal ortamı oluşturur
      3. kayaAI'yi ve test bağımlılıklarını kurar
      4. Çevrimdışı birim testlerini çalıştırır
      5. Node.js varsa Control Center arayüzünü derler (yoksa uyarır, kurulum durmaz)
      6. Ollama'yı bulur (yoksa winget ile kurmayı SORAR) ve servisin çalıştığını doğrular
      7. config\models.yaml'daki modeli indirmeyi SORAR
      8. kayaai doctor ile son kontrolü yapar
    Yönetici (admin) yetkisi gerektirmez. Sistem ayarlarını değiştirmez.

.PARAMETER Yes
    Tüm sorulara otomatik "evet" der (kurulum ve model indirme dahil).

.PARAMETER SkipModel
    Model indirme adımını atlar.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\windows\setup.ps1
#>
[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$SkipModel
)

# "Stop" kullanılmaz: PS 5.1'de stderr'e yazan harici komutlar (ollama, pip) istisna fırlatır.
# Her adım $LASTEXITCODE ile açıkça kontrol edilir.
$ErrorActionPreference = "Continue"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $ProjectRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$env:PYTHONUTF8 = "1"

function Write-Step([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "    [OK] $Text" -ForegroundColor Green }
function Write-Warn2([string]$Text) { Write-Host "    [UYARI] $Text" -ForegroundColor Yellow }
function Fail([string]$Text) {
    Write-Host "    [HATA] $Text" -ForegroundColor Red
    Write-Host "`nKurulum durdu. Yukarıdaki hatayı geliştirme oturumuna yapıştırabilirsiniz." -ForegroundColor Red
    exit 1
}
function Confirm-Action([string]$Question) {
    if ($Yes) { return $true }
    $a = Read-Host "    $Question [e/H]"
    return ($a -match '^(e|evet|y|yes)$')
}
function Update-SessionPath {
    # winget kurulumundan sonra yeni PATH'i bu oturuma al
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}
function Test-Python([string]$Exe, [string[]]$PreArgs) {
    try {
        $out = & $Exe @PreArgs -c "import sys; print('%d.%d.%d' % sys.version_info[:3]); print(sys.version_info >= (3, 11))" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out.Count -ge 2 -and $out[1] -eq "True") { return $out[0] }
    } catch {}
    return $null
}
function Find-Python {
    $candidates = @(
        @{ exe = "py"; args = @("-3.12") },
        @{ exe = "py"; args = @("-3.13") },
        @{ exe = "py"; args = @("-3.11") },
        @{ exe = "py"; args = @("-3") },
        @{ exe = "python"; args = @() }
    )
    foreach ($c in $candidates) {
        $cmd = Get-Command $c.exe -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $cmd) { continue }
        if ($cmd.Source -like "*\WindowsApps\*") { continue }  # Microsoft Store yönlendiricisi
        $ver = Test-Python $cmd.Source $c.args
        if ($ver) { return @{ exe = $cmd.Source; args = $c.args; version = $ver } }
    }
    return $null
}
function Test-OllamaService {
    try {
        $v = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 3
        return $v.version
    } catch { return $null }
}

Write-Host "kayaAI kurulumu - proje: $ProjectRoot" -ForegroundColor Cyan

# ---------------------------------------------------------------- 1. Python
Write-Step "1/8 Python 3.11+ aranıyor"
$py = Find-Python
if (-not $py) {
    Write-Warn2 "Python 3.11+ bulunamadı."
    if ((Get-Command winget -ErrorAction SilentlyContinue) -and (Confirm-Action "Python 3.12 winget ile kurulsun mu? (~30 MB)")) {
        winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
        Update-SessionPath
        $py = Find-Python
    }
    if (-not $py) { Fail "Python 3.11+ gerekli. https://www.python.org/downloads/ adresinden kurun ('Add python.exe to PATH' işaretleyin) ve scripti tekrar çalıştırın." }
}
Write-Ok "Python $($py.version): $($py.exe) $($py.args -join ' ')"

# ---------------------------------------------------------------- 2. venv
Write-Step "2/8 Sanal ortam (.venv)"
if (Test-Path $VenvPython) {
    Write-Ok ".venv zaten var, yeniden kullanılıyor"
} else {
    & $py.exe @($py.args) -m venv .venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPython)) { Fail ".venv oluşturulamadı" }
    Write-Ok ".venv oluşturuldu"
}

# ---------------------------------------------------------------- 3. paketler
Write-Step "3/8 kayaAI ve bağımlılıklar kuruluyor"
& $VenvPython -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) { Fail "pip güncellenemedi" }
# Bilinen iyi sürümler (sahibin çalışan kurulumundan; docs/DEPLOYMENT.md). Yoksa pyproject aralıkları kullanılır.
$Constraints = Join-Path $ProjectRoot "constraints\windows.txt"
if (Test-Path $Constraints) {
    & $VenvPython -m pip install -e ".[dev]" -c $Constraints --quiet
    if ($LASTEXITCODE -ne 0) { Fail "pip install başarısız (constraints\windows.txt ile)" }
    Write-Ok "Bilinen iyi sürümler kullanıldı (constraints\windows.txt)"
} else {
    & $VenvPython -m pip install -e ".[dev]" --quiet
    if ($LASTEXITCODE -ne 0) { Fail "pip install başarısız" }
}
& $VenvPython -c "import kayaai, httpx, pydantic, yaml; print(kayaai.__version__)"
if ($LASTEXITCODE -ne 0) { Fail "kayaai içe aktarılamadı" }
Write-Ok "Paketler kuruldu ve doğrulandı"

# ---------------------------------------------------------------- 4. testler
Write-Step "4/8 Çevrimdışı birim testleri (sahte Ollama ile)"
& $VenvPython -m pytest -q
if ($LASTEXITCODE -ne 0) { Fail "Birim testleri başarısız" }
Write-Ok "Birim testleri geçti"

# ---------------------------------------------------------------- 5. Control Center arayüzü
Write-Step "5/8 Control Center arayüzü (React)"
$UiDir = Join-Path $ProjectRoot "ui"
$node = Get-Command node -ErrorAction SilentlyContinue
$npm = Get-Command npm -ErrorAction SilentlyContinue
if (-not $node -or -not $npm) {
    Write-Warn2 "Node.js bulunamadı; arayüz derlenmedi (API ve komut satırı yine çalışır)."
    Write-Warn2 "Kurmak için: https://nodejs.org (LTS) - sonra bu scripti tekrar çalıştırın."
} else {
    $nodeVer = (& $node.Source --version 2>$null) -replace '^v', ''
    $nodeMajor = 0
    [void][int]::TryParse(($nodeVer -split '\.')[0], [ref]$nodeMajor)
    if ($nodeMajor -lt 18) {
        Write-Warn2 "Node.js $nodeVer çok eski (18+ gerekli); arayüz derlenmedi."
    } else {
        Push-Location $UiDir
        & $npm.Source ci --no-audit --no-fund --loglevel=error
        $npmOk = ($LASTEXITCODE -eq 0)
        if ($npmOk) { & $npm.Source run build --silent; $npmOk = ($LASTEXITCODE -eq 0) }
        if ($npmOk) { & $npm.Source test --silent; $npmOk = ($LASTEXITCODE -eq 0) }
        Pop-Location
        if ($npmOk -and (Test-Path (Join-Path $UiDir "dist\index.html"))) {
            Write-Ok "Arayüz derlendi ve testleri geçti (Node $nodeVer) -> ui\dist"
        } else {
            Write-Warn2 "Arayüz derlenemedi (yukarıdaki npm çıktısına bakın). API ve komut satırı yine çalışır."
        }
    }
}

# ---------------------------------------------------------------- 6. Ollama
Write-Step "6/8 Ollama"
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
    $default = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (Test-Path $default) { $env:Path += ";" + (Split-Path $default); $ollama = Get-Command ollama -ErrorAction SilentlyContinue }
}
if (-not $ollama) {
    Write-Warn2 "Ollama kurulu değil."
    if ((Get-Command winget -ErrorAction SilentlyContinue) -and (Confirm-Action "Ollama winget ile kurulsun mu? (~1 GB, ücretsiz, MIT lisanslı)")) {
        winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
        Update-SessionPath
        $default = Join-Path $env:LOCALAPPDATA "Programs\Ollama"
        if (Test-Path $default) { $env:Path += ";$default" }
        $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    }
    if (-not $ollama) { Fail "Ollama gerekli: https://ollama.com/download/windows adresinden kurun ve scripti tekrar çalıştırın." }
}
Write-Ok "Ollama: $($ollama.Source) ($((& $ollama.Source --version 2>&1 | Select-Object -First 1)))"

$ver = Test-OllamaService
if (-not $ver) {
    Write-Warn2 "Ollama servisi yanıt vermiyor, başlatılıyor (sadece 127.0.0.1)..."
    Start-Process -FilePath $ollama.Source -ArgumentList "serve" -WindowStyle Hidden
    for ($i = 0; $i -lt 20 -and -not $ver; $i++) { Start-Sleep -Seconds 1; $ver = Test-OllamaService }
    if (-not $ver) { Fail "Ollama servisi başlatılamadı. Başlat menüsünden 'Ollama' uygulamasını açıp tekrar deneyin." }
}
Write-Ok "Ollama servisi çalışıyor: v$ver (http://127.0.0.1:11434)"
$ollamaHost = [Environment]::GetEnvironmentVariable("OLLAMA_HOST", "User")
if ($ollamaHost -match "0\.0\.0\.0") { Write-Warn2 "OLLAMA_HOST=$ollamaHost -> Ollama ağa açık! Güvenlik için bu değişkeni kaldırın." }

# ---------------------------------------------------------------- 7. model
Write-Step "7/8 Model"
$model = (& $VenvPython -c "from kayaai.config import load_settings; from kayaai.llm.registry import ModelRegistry; print(ModelRegistry.load(load_settings().models_file).model_for_worker('general').name)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $model) { Fail "config\models.yaml okunamadı" }
$installed = (& $ollama.Source list 2>&1) -join "`n"
if ($installed -match [regex]::Escape($model)) {
    Write-Ok "Model zaten kurulu: $model"
} elseif ($SkipModel) {
    Write-Warn2 "Model indirme atlandı. Sonra: ollama pull $model"
} else {
    if (Confirm-Action "'$model' indirilsin mi? (qwen3:8b ~5.2 GB disk)") {
        & $ollama.Source pull $model
        if ($LASTEXITCODE -ne 0) { Fail "Model indirilemedi: $model" }
        Write-Ok "Model indirildi: $model"
    } else {
        Write-Warn2 "Model indirilmedi. Sonra: ollama pull $model"
    }
}

# Adım 9 — hafıza modeli (anlam araması). Zorunlu değil: yoksa hafıza kelime aramasıyla çalışır.
$embed = (& $VenvPython -c "from kayaai.config import load_settings; from kayaai.llm.registry import ModelRegistry; s=load_settings(); print(ModelRegistry.load(s.models_file).get(s.memory.embed_model).name)").Trim()
if ($LASTEXITCODE -eq 0 -and $embed) {
    if ($installed -match [regex]::Escape($embed)) {
        Write-Ok "Hafıza modeli zaten kurulu: $embed"
    } elseif ($SkipModel) {
        Write-Warn2 "Hafıza modeli indirme atlandı. Sonra: ollama pull $embed"
    } elseif (Confirm-Action "Hafıza modeli '$embed' indirilsin mi? (~1.2 GB, MIT lisanslı; hafıza ve belge araması için)") {
        & $ollama.Source pull $embed
        if ($LASTEXITCODE -ne 0) { Write-Warn2 "Hafıza modeli indirilemedi; hafıza kelime aramasıyla çalışır." }
        else { Write-Ok "Hafıza modeli indirildi: $embed" }
    } else {
        Write-Warn2 "Hafıza modeli indirilmedi (hafıza kelime aramasıyla çalışır). Sonra: ollama pull $embed"
    }
}

# Adım 12a — görsel model (ekranı okuma). Zorunlu değil: yoksa ekran özelliği kurulum talimatı gösterir.
$vision = (& $VenvPython -c "from kayaai.config import load_settings; from kayaai.llm.registry import ModelRegistry; s=load_settings(); print(ModelRegistry.load(s.models_file).get('vision-7b').name)").Trim()
if ($LASTEXITCODE -eq 0 -and $vision) {
    if ($installed -match [regex]::Escape($vision)) {
        Write-Ok "Görsel model zaten kurulu: $vision"
    } elseif ($SkipModel) {
        Write-Warn2 "Görsel model indirme atlandı. Sonra: ollama pull $vision"
    } elseif (Confirm-Action "Görsel model '$vision' indirilsin mi? (~6 GB, Apache-2.0; ekranı okuma için)") {
        & $ollama.Source pull $vision
        if ($LASTEXITCODE -ne 0) { Write-Warn2 "Görsel model indirilemedi. Sonra: ollama pull $vision" }
        else { Write-Ok "Görsel model indirildi: $vision" }
    } else {
        Write-Warn2 "Görsel model indirilmedi (ekranı okuma kapalı). Sonra: ollama pull $vision"
    }
}

# Adım 12b — ses tanıma (bas-konuş, canlı altyazı). Zorunlu değil.
$speechOk = (& $VenvPython -c "from kayaai.config import load_settings; from kayaai.speech.stt import is_installed; print(is_installed(load_settings()))").Trim()
if ($speechOk -eq "True") {
    Write-Ok "Ses tanıma modeli zaten kurulu (whisper)"
} elseif ($SkipModel) {
    Write-Warn2 "Ses tanıma modeli atlandı. Sonra: kayaai speech download"
} elseif (Confirm-Action "Ses tanıma modeli (whisper large-v3-turbo, ~1.6 GB, MIT) indirilsin mi? (bas-konuş ve canlı altyazı için)") {
    & $VenvPython -c "from kayaai.config import load_settings; from kayaai.speech.stt import download; print(download(load_settings()))"
    if ($LASTEXITCODE -ne 0) { Write-Warn2 "Ses modeli indirilemedi. Sonra: kayaai speech download" }
    else { Write-Ok "Ses tanıma modeli indirildi" }
}
$gpuLibs = (& $VenvPython -c "import importlib.util as u; print(bool(u.find_spec('nvidia.cublas') and u.find_spec('nvidia.cudnn')))" 2>$null)
if ($gpuLibs -and $gpuLibs.Trim() -eq "True") {
    Write-Ok "Ses tanıma GPU kütüphaneleri kurulu (cuBLAS + cuDNN)"
} elseif (-not $SkipModel -and (Confirm-Action "Ses tanıma GPU'da çalışsın mı? NVIDIA cuBLAS + cuDNN kütüphaneleri pip ile kurulur (~1.3 GB). Hayır: işlemcide çalışır (daha yavaş)")) {
    & $VenvPython -m pip install "nvidia-cublas-cu12" "nvidia-cudnn-cu12>=9,<10"
    if ($LASTEXITCODE -ne 0) { Write-Warn2 "GPU kütüphaneleri kurulamadı; ses tanıma işlemcide çalışır." }
    else { Write-Ok "GPU kütüphaneleri kuruldu" }
}

# ---------------------------------------------------------------- 8. doctor
Write-Step "8/8 Son kontrol (kayaai doctor)"
& $VenvPython -m kayaai doctor
$doctorExit = $LASTEXITCODE

Write-Host ""
if ($doctorExit -eq 0) {
    Write-Host "Kurulum tamamlandı." -ForegroundColor Green
    Write-Host "Gerçek kabul testleri için:  powershell -ExecutionPolicy Bypass -File scripts\windows\smoke.ps1"
    Write-Host "Soru sormak için:            powershell -ExecutionPolicy Bypass -File scripts\windows\run.ps1 ask `"Merhaba`""
    Write-Host "Claude Code (MCP) için:      powershell -ExecutionPolicy Bypass -File scripts\windows\mcp_setup.ps1"
    Write-Host "Control Center için:         1. terminal: .venv\Scripts\kayaai api   2. terminal: .venv\Scripts\kayaai ui"
} else {
    Write-Host "Kurulum bitti ama doctor eksik buldu (yukarıdaki HATA satırları)." -ForegroundColor Yellow
}
exit $doctorExit
