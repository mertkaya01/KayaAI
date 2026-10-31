# kayaAI

Yerel çalışan, çok-ajanlı kişisel yapay zeka sistemi. Windows + NVIDIA GPU üzerinde, ücretsiz ve
açık modellerle (Ollama) çalışır; verileriniz bilgisayarınızdan çıkmaz.

> Vizyon, kararlar ve yol haritası: [`MASTER_PROMPT.md`](MASTER_PROMPT.md) (v2).
> Claude isteğe bağlıdır: kayaAI tamamen yerel ve ücretsiz çalışır; Claude Pro varsa "Claude modu" ile takviye olarak eklenir.

## Durum

| Faz | İçerik | Durum |
|---|---|---|
| 0 | Ortam denetimi + mimari + teknik rapor | **Tamamlandı** (Windows 11, RTX 5070 Ti) |
| 1 | Yerel AI çekirdeği: Ollama istemcisi, orkestratör, görev geçmişi, genel worker, CLI | **Tamamlandı** — qwen3:8b ~138 token/sn, %100 GPU |
| 2 | MCP sunucusu: Claude Code yerel modeli araç olarak çağırır | **Tamamlandı** — Claude Code → `kayaai_ask` → qwen3:8b doğrulandı |
| 3+ | Çoklu worker, arayüz, ekran, ses, otomasyon, hafıza, iş ajanları | Planlandı |

Ayrıntılı iş listesi: [`TASKS.md`](TASKS.md)

## Gereksinimler (Faz 1)

- Windows 10/11, NVIDIA sürücüsü (CUDA 12.8+ destekli — RTX 50 serisi için zorunlu)
- Python 3.11+ ([python.org](https://www.python.org/downloads/), kurulumda **"Add python.exe to PATH"** işaretli)
- Git
- Ollama (kurulum scripti sorarak kurar)
- ~7 GB boş disk (model dahil)

## Windows'ta kurulum

PowerShell açın (Başlat → "PowerShell"). Yönetici yetkisi gerekmez.

**1. Projeyi indirin**

```powershell
cd $HOME\Documents
git clone https://github.com/mertkaya01/KayaAI.git
cd KayaAI
git checkout claude/eloquent-goldberg-co7wjy
```

**2. Ortam denetimi (salt okunur, hiçbir şey kurmaz)**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\audit\audit_windows.ps1
```

Sonuç `data\audit_windows.json` dosyasına yazılır.

**3. Kurulum (her adımı doğrular, kurulum/indirme öncesi sorar)**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\setup.ps1
```

Python sanal ortamı, bağımlılıklar, birim testleri, Ollama ve `qwen3:8b` modeli (~5.2 GB).

**4. Gerçek model kabul testleri + benchmark**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\smoke.ps1
```

Sonuç `data\smoke_report.json` dosyasına yazılır.

> `-ExecutionPolicy Bypass` yalnızca o komut için geçerlidir; sistem güvenlik ayarınızı değiştirmez.

**Güncelleme (sonraki sürümleri çekmek için)**

```powershell
git pull
powershell -ExecutionPolicy Bypass -File scripts\windows\setup.ps1
```

## Claude modu (isteğe bağlı)

kayaAI Claude olmadan tam çalışır. Claude Pro aboneliğin varken:

```powershell
kayaai claude on      # Claude modunu açar ve şef çalışma alanını üretir (~\kayaAI-workspace)
cd $HOME\kayaAI-workspace
claude                # Opus burada şef: CLAUDE.md kurallarını ve kayaai-* alt ajanlarını kullanır
```

Kurallar: her iki modda da önce yerel model; Claude yalnızca gerektiğinde. Claude gerektiren işler
`kayaai inbox`'ta bekler; Claude Code oturumunda "kutuyu işle" de. `kayaai claude off` bekleyenleri yerelde yapar.

Doğrulama: Claude Code'da `/mcp` → `kayaai` connected. Alt ajanlar (`kayaai-general`, `kayaai-coder`,
`kayaai-reviewer`) `.claude/agents/` klasöründen otomatik okunur; güncel Claude Code sürümlerinde `/agents` komutu
yok — Claude'a "hangi alt ajanların var?" diye sorabilirsin. Pro planında Opus 5.5 kullanılabildiği doğrulandı.

## Yerel API (arayüzler için)

```powershell
kayaai api            # http://127.0.0.1:8765  — yalnızca bu bilgisayar; Ctrl+C ile durur
kayaai api token      # erişim anahtarı (data\api_token)
```

Tarayıcıda `http://127.0.0.1:8765/docs` → **Authorize** → anahtarı yapıştır → uç noktaları dene.
Kontrol: ikinci terminalde `python scripts\api_check.py`.

## Claude Code ile kullanım (MCP, Faz 2)

kayaAI bir MCP sunucusu içerir: Claude Code, yerel modelinizi araç olarak çağırabilir. Sunucu yalnızca
stdio üzerinden konuşur, **ağ portu açmaz**; yalnızca yerel modele soru sorma ve görev yönetimi araçları
vardır (dosya yazma / komut çalıştırma yok).

**1. Claude Code'u kurun** (bir kez):

```powershell
irm https://claude.ai/install.ps1 | iex
```

**2. MCP sunucusunu test edip `.mcp.json` oluşturun:**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\mcp_setup.ps1
```

Gerçek modelle stdio üzerinden test eder (`data\mcp_check.json`), sonra proje kökünde bu bilgisayara
özgü `.mcp.json` yazar (git'e girmez).

**3. Claude Code'u proje klasöründe başlatın:**

```powershell
claude
```

`kayaai` sunucusunu kullanma onayı istenince kabul edin. `/mcp` yazınca `kayaai` **connected** görünmeli.
Örnek istek: *"kayaai_ask aracıyla yerel modele sor: Türkiye'nin başkenti neresi?"*

| Araç | Ne yapar |
|---|---|
| `kayaai_ask` | Yerel modele soru/metin görevi (isteğe bağlı `context` güvenilmez veri olarak) |
| `kayaai_submit_task` / `kayaai_run_task` | Görev oluştur / çalıştır (bağımlılıklarla) |
| `kayaai_task_status` / `kayaai_list_tasks` / `kayaai_cancel_task` | Görev takibi |
| `kayaai_list_models` / `kayaai_health` | Model kaydı, Ollama/GPU durumu |

## Kullanım

```powershell
.\.venv\Scripts\Activate.ps1          # sanal ortamı etkinleştir (her yeni pencerede bir kez)
kayaai doctor                         # sistem / GPU / Ollama / model kontrolü
kayaai ask "Merhaba, kendini tanıt"   # genel worker'a soru
kayaai ask --json "Bir cümleyle özetle: ..."   # tüm görev nesnesi (JSON)
kayaai tasks                          # görev geçmişi
kayaai task <görev-id>                # görev ayrıntısı + olay günlüğü
kayaai models                         # model kayıt defteri
kayaai audit                          # Python ile ortam denetimi
kayaai mcp                            # MCP sunucusu (stdio; Claude Code kendisi başlatır)
kayaai claude [on|off]                # Claude modu: durum / aç / kapat (varsayılan kapalı)
kayaai agents                         # tanımlı ajanlar (config/agents/*.yaml)
kayaai do "istek"                     # şef: planla → ajanlara dağıt → birleştir → gözden geçir
kayaai inbox                          # Claude kutusu (Claude gerektiren işler); run <id> → yerelde yap
kayaai ask --worker coder "..."       # belirli bir ajana sor (general / coder / reviewer)
```

`Activate.ps1` "running scripts is disabled" hatası verirse, sanal ortamı etkinleştirmeden:
`powershell -ExecutionPolicy Bypass -File scripts\windows\run.ps1 ask "Merhaba"`

## Yapılandırma

- `config/settings.yaml` — Ollama adresi, zaman aşımları, izinler, loglama
- `config/models.yaml` — hangi worker hangi modeli kullanır (model değiştirmek için sadece bu dosya)
- `config/settings.local.yaml` — kişisel değişiklikler (git'e girmez)
- Ortam değişkenleri: `KAYAAI_OLLAMA_URL`, `KAYAAI_DATA_DIR`, `KAYAAI_LOG_LEVEL`

Çalışma verisi (`data/`, git'e girmez): `kayaai.db` (görev geçmişi), `logs/kayaai.log`, denetim ve smoke raporları.

## Proje yapısı

```
kayaai/            Python paketi (çekirdek)
  core/            görev, SQLite deposu, orkestratör
  llm/             Ollama istemcisi, model kayıt defteri
  workers/         worker arayüzü + genel worker
  system/          ortam denetimi
  mcp_server.py    MCP sunucusu (Faz 2)
config/            settings.yaml, models.yaml
scripts/audit/     ortam denetim scriptleri
scripts/windows/   setup / smoke / run / mcp_setup
scripts/smoke_ollama.py   gerçek model kabul testleri
scripts/mcp_check.py      MCP sunucusu doğrulaması (stdio, gerçek model)
tests/             birim testleri (sahte Ollama HTTP sunucusu ile)
docs/              faz raporları
```

## Geliştirme

```powershell
.\.venv\Scripts\Activate.ps1
pytest
```

Birim testleri gerçek bir yerel HTTP sunucusu olarak çalışan **sahte Ollama** kullanır; istemci,
retry, doğrulama ve orkestratör mantığını test eder. Model kalitesini **ölçmez** — onun için
`scripts/smoke_ollama.py` gerçek Ollama ile çalıştırılır.

## Dokümanlar

[`ARCHITECTURE.md`](ARCHITECTURE.md) · [`MODEL_REGISTRY.md`](MODEL_REGISTRY.md) ·
[`SECURITY.md`](SECURITY.md) · [`TASKS.md`](TASKS.md) · [`CHANGELOG.md`](CHANGELOG.md) ·
[`docs/PHASE0_REPORT.md`](docs/PHASE0_REPORT.md)
