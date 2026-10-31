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
| 3–5 | Ajan ekibi + yerel şef, Claude modu, yerel API, izin motoru + dosya araçları | **Tamamlandı** (Windows'ta doğrulandı) |
| 6 | Control Center v1: sistem izleme, ajan kartları, onay merkezi (React + TypeScript) | **Tamamlandı** (Windows'ta doğrulandı) |
| 7 | Ajan sistemi: uzmanlar (coder, data, document), gözden geçirme, anlaşmazlık yükseltme, geçici ajanlar | **Tamamlandı** (Windows'ta doğrulandı) |
| 8 | Asistan çalışma alanı: kalıcı sohbet, ekler, ajan seçimi, Claude'a devretme | **Tamamlandı** (Windows'ta doğrulandı) |
| 9 | Hafıza: kişisel hafıza + belge araması (RAG), yerel bge-m3, gizlilik sınıfları | **Tamamlandı** (Windows'ta doğrulandı) |
| 10 | İş modülleri: Excel/CSV analizi (sayıları program hesaplar), PDF özeti, fatura, rapor (xlsx/md/docx/pdf) | **Yeni** — Windows'ta doğrulama bekleniyor |
| 11+ | Görsel iş akışı + model yönetimi, ekran/ses, zamanlama | Planlandı |

Ayrıntılı iş listesi: [`TASKS.md`](TASKS.md)

## Gereksinimler (Faz 1)

- Windows 10/11, NVIDIA sürücüsü (CUDA 12.8+ destekli — RTX 50 serisi için zorunlu)
- Python 3.11+ ([python.org](https://www.python.org/downloads/), kurulumda **"Add python.exe to PATH"** işaretli)
- Git
- Ollama (kurulum scripti sorarak kurar)
- ~7 GB boş disk (model dahil)

## Windows'ta kurulum

PowerShell açın (Başlat → "PowerShell"). Yönetici yetkisi gerekmez.

**1. Projeyi indirin** (Git ve isteğe bağlı olarak Node.js LTS kurulu olmalı — Node yoksa arayüz derlenmez, gerisi çalışır)

```powershell
cd $HOME\Documents
git clone https://github.com/mertkaya01/KayaAI.git
cd KayaAI
```

`main` dalı Windows'ta doğrulanmış son sürümdür. Geliştirme sürümü `claude/eloquent-goldberg-co7wjy` dalındadır
(`git checkout claude/eloquent-goldberg-co7wjy`).

> **Sıfırdan kurulum / başka klasöre taşıma:** görev geçmişi, onaylar, erişim anahtarı ve sonradan oluşturulan
> ajanlar `data\` klasöründedir ve git'e girmez. Eskisini korumak için eski kurulumun `data\` klasörünü yenisine
> kopyalayın. Claude modu kullanıyorsanız kurulumdan sonra `scripts\windows\mcp_setup.ps1` ve
> `.venv\Scripts\kayaai claude sync` çalıştırın (çalışma alanı yeni klasörün Python'unu göstermeli).
> `~\kayaAI-files` (ajanların dosya klasörü) repodan bağımsızdır, etkilenmez.

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

## Dosya araçları ve onaylar

Ajanlar yalnızca izinli klasörlerde çalışır: `C:\Users\<kullanıcı>\kayaAI-files` (okuma+yazma) ve
`config/settings.yaml` → `files.allowed_dirs` içinde listelediğin klasörler (`read` ya da `read_write`).

```powershell
kayaai files roots                       # izinli klasörler
kayaai files write notlar.md --text "..." # yeni dosya: hemen (R1)
kayaai files write notlar.md --text "..." # var olan dosya: ONAY BEKLER (R2), önce yedek alınır
kayaai approvals                         # bekleyen onaylar
kayaai approvals show <id>               # önizleme (eski/yeni içerik, geri alma)
kayaai approvals approve <id>            # ya da: reject <id>
```

Onayı yalnızca sen verirsin (CLI ya da anahtarlı API). Claude Code'un MCP üzerinden onay verme aracı yoktur.

## Yerel API (arayüzler için)

```powershell
kayaai api            # http://127.0.0.1:8765  — yalnızca bu bilgisayar; Ctrl+C ile durur
kayaai api token      # erişim anahtarı (data\api_token)
```

Tarayıcıda `http://127.0.0.1:8765/docs` → **Authorize** → anahtarı yapıştır → uç noktaları dene.
Kontrol: ikinci terminalde `python scripts\api_check.py`.

## Control Center (arayüz)

Koyu temalı yerel web arayüzü: CPU/RAM/GPU/VRAM canlı grafikleri, ajan kartları (boşta/çalışıyor/bekliyor/tamamlandı/
başarısız), **onay merkezi** (eski/yeni içerik yan yana → Onayla/Reddet), Claude modu aç/kapat düğmesi, canlı olaylar.

```powershell
# 1. terminal
.venv\Scripts\kayaai api
# 2. terminal
.venv\Scripts\kayaai ui          # tarayıcıyı anahtarlı adresle açar
```

- Arayüz `setup.ps1` tarafından derlenir (Node.js 18+ gerekir; yoksa API/CLI yine çalışır). Elle: `cd ui; npm ci; npm run build`.
- Adres yalnızca `http://127.0.0.1:8765`. `kayaai ui` anahtarı adresin `#token=` kısmında verir (sunucuya gitmez);
  arayüz onu sekmeye alıp adres çubuğundan siler. `kayaai ui --print` adresi yazar — **paylaşmayın**.
- Geliştirme: `cd ui; npm run dev` (Vite, http://127.0.0.1:5173, `/api` → 8765'e yönlendirilir) · `npm test`.

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
kayaai agents                         # ajanlar (config/agents + data/agents), geçici olanlar ve kullanımları
kayaai do "istek"                     # şef: planla → ajanlara dağıt → gözden geçir → birleştir
kayaai disputes                       # ajan anlaşmazlıkları; show <id> / resolve <id> --side producer|reviewer
kayaai inbox                          # Claude kutusu (Claude gerektiren işler); run <id> → yerelde yap
kayaai ask --worker coder "..."       # belirli bir ajana sor (general / coder / data / document)
```

`Activate.ps1` "running scripts is disabled" hatası verirse, sanal ortamı etkinleştirmeden:
`powershell -ExecutionPolicy Bypass -File scripts\windows\run.ps1 ask "Merhaba"`

## Asistan (Adım 8)

Control Center'da üstteki **Asistan** sekmesi (`http://127.0.0.1:8765/asistan`): yerel modellerle sohbet.

- **Kalıcı sohbetler:** solda liste; yeniden adlandır / sil. Sunucu kapanıp açılsa da geçmiş durur (`data\kayaai.db`).
- **Ajan seçimi:** "Otomatik" → şef isteği uygun uzmana verir ve uzman cevaplarını gözden geçirtir; ya da doğrudan
  `general` / `coder` / `data` / `document` / geçici ajanlar.
- **Bağlam:** son 8 mesaj ve bu mesajın ekleri modele veri olarak gider (sınırı aşan ek kısaltılır, uyarı gösterilir).
- **Ekler:** metin dosyaları (txt, md, csv, json, py, …; en fazla 2 MB) — "Dosya ekle" ya da izinli klasörden
  "Klasörden ekle" (`~\kayaAI-files` ve `files.allowed_dirs`). PDF/Excel Adım 10'da.
- **Claude'a devret:** Claude modu açıkken bir cevabın altındaki düğme, soruyu (sohbet geçmişi ve ekleriyle, senin
  onayınla) Claude kutusuna bırakır. Claude Code oturumunda Opus kutuyu işleyince cevap sohbete kendiliğinden düşer.
  kayaAI Claude'u kendisi çağırmaz (sahip kararı). Claude kapalıysa düğme pasiftir.
- Cevaplar güvenli bir Markdown görüntüleyiciyle gösterilir (kod bloğu + kopyala, tablo, liste); HTML/betik çalışmaz.
- Hafıza paneli Adım 9'da dolacak; sesli giriş sonraki adımlarda.

## Hafıza (Adım 9)

Üstteki **Hafıza** sekmesi (`/hafiza`). Sahip kararı: SQLite + yerel `bge-m3` (kurulum `setup.ps1` sorar ya da
`ollama pull bge-m3`, ~1.2 GB). Model yoksa hafıza kelime aramasıyla yine çalışır.

- **Kişisel hafıza:** sohbette `hatırla: kahvemi şekersiz içerim` ya da mesajdaki **Hafızaya ekle** → yerel model kısa
  bir nota çevirip sınıflandırır (tercih, proje, karar, talimat, dosya, not). Hafıza sekmesinde gör, düzenle, sil,
  JSON olarak dışa aktar. Claude yalnızca **öneri** ekleyebilir; sen onaylamadan kullanılmaz.
- **Hassasiyet:** herkese açık · kişisel · **özel** (Claude'a hiç gönderilmez) · **gizli** (parola/anahtar/IBAN/kart gibi
  kalıplar kodla tespit edilir; açık izin olmadan saklanmaz, saklansa da hiçbir sohbete otomatik girmez, listede maskeli).
- **Belge araması (RAG):** `~\kayaAI-files` ve izin verdiğin klasörlerdeki metin dosyaları **Şimdi dizinle** ile parçalanıp
  dizinlenir (artımlı). `.env`, anahtar dosyaları, `node_modules` vb. ve parola geçen parçalar atlanır.
- **Sohbette:** her soruda ilgili hafıza öğeleri ve belge parçaları otomatik bulunur; cevabın altında **Kaynaklar**
  (`dosya.md:12`) ve "Hafızadan N bilgi kullanıldı" görünür. Claude'a devrederken yalnızca kişisel/herkese açık notlar
  gider; özel notlar ve yerel belgeler gitmez.
- CLI: `kayaai memory [list|add|rm|approve|search|index|status|export]`. Ölçüm: `python scripts\memory_check.py`
  (ayrı klasörde; gerçek bge-m3 ile benzerlik eşiğini önerir).

## İş modülleri (Adım 10)

Asistan'da bir **Excel/CSV** ya da **PDF** ekle (dosya seçici ya da "Klasörden ekle"; en fazla 10 MB):

- **Analiz et** (Excel/CSV): yerel model soruyu bir hesap planına çevirir (süz, grupla, topla/ortalama/say/en düşük/en
  yüksek, aylık/çeyreklik, ilk N); **tüm sayıları program hesaplar**; model kısa bir yorum yazar ve yorumdaki her sayı
  hesaplanan değerlerle **kodla** karşılaştırılır (uydurma sayı → model düzeltir, düzeltmezse uyarı). Türkçe sayı
  biçimleri (`1.234,56 ₺`) anlaşılır; formüller/makrolar çalıştırılmaz.
- **Özetle** (PDF): uzun belgeler bölüm bölüm özetlenip birleştirilir; maddelerde kaynak sayfa `[s.3]`.
- **Fatura olarak oku** (PDF): satıcı, alıcı, no, tarih, kalemler, ara toplam, KDV, toplam; **kod denetimi**: satırlar ≈ ara
  toplam, ara toplam + KDV ≈ toplam, KDV oranı, tutarlar belgede gerçekten var mı.
- **Rapor oluştur** (her cevabın altında): **Excel**, **PDF**, **Word**, **Markdown** → `~\kayaAI-files\raporlar\`.
  Yeni dosya otomatik; aynı adlı dosyanın üzerine yazmak onay ister (yedek alınır).
- Taranmış (görüntü) PDF'ler henüz okunamaz — OCR Adım 12'de. Eski `.xls` → Excel'de `.xlsx` olarak kaydet.
- Belge araması (Hafıza) PDF ve Excel dosyalarını da dizinler (kaynak: `rapor.pdf:s.3`).
- CLI: `kayaai analyze satis.xlsx "bölgelere göre toplam" --report pdf` · `kayaai summarize rapor.pdf` ·
  `kayaai invoice fatura.pdf --report xlsx`. Ölçüm: `python scripts\business_check.py`.

## Ajan ekibi (Adım 7)

| Ajan | İş | Yerel model | Gözden geçirme |
|---|---|---|---|
| `general` | sohbet, soru-cevap, özet, çeviri | qwen3:8b | — (hızlı kalsın) |
| `coder` | kod yazma/açıklama | qwen2.5-coder:7b | reviewer + kod sözdizimi kontrolü (kod **çalıştırılmaz**) |
| `data` | tablo/sayı analizi, hesap adımlarıyla | qwen3:8b | reviewer |
| `document` | rapor, e-posta, özet, metin düzeltme | qwen3:8b | reviewer |

- **Üretici → gözden geçirici:** uzman ajanın cevabını `reviewer` inceler. Her sorun için cevaptan birebir alıntı
  ister; alıntısı cevapta olmayan (uydurma) sorunlar kodla elenir. Python/JSON/YAML blokları ayrıştırılır.
  Ciddi sorun varsa üretici **bir tur** düzeltir ya da gerekçesiyle itiraz eder.
- **Anlaşmazlık:** itiraz edilen sorun kayda geçer. Claude modu açıksa iş iki görüşle Claude kutusuna gider (Opus
  karar verir); kapalıysa karar senin: `kayaai disputes` ya da Control Center → **Anlaşmazlıklar**.
- **Geçici ajanlar:** uygun ajan yoksa yerel planlayıcı (ya da Claude şef, ya da sen: `kayaai agents new`) mevcut bir
  ajana dayanan geçici bir ajan oluşturur (`data\agents\`). Dayandığı ajandan fazla izin alamaz, cevapları hep
  gözden geçirilir. En az bir başarılı kullanımdan sonra `kayaai agents promote <ad>` (ya da kartındaki **Kalıcı yap**)
  → onay merkezinde senin onayınla kalıcı olur. `kayaai agents remove <ad>` geçici ajanı siler.
- Gerçek modelle ölçüm: `python scripts\agents_check.py` → `data\agents_check.json` (ayrı veri klasöründe çalışır).

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
  api/             yerel API (FastAPI) + Control Center sunumu
  assistant/       sohbet: konuşmalar, mesajlar, ekler, Claude'a devretme (Adım 8)
  memory/          hafıza: kişisel notlar, belge dizini (RAG), gizli bilgi tespiti, yerel vektörler (Adım 9)
  business/        iş modülleri: PDF/Excel okuma, analiz, fatura, rapor yazıcıları (Adım 10)
  mcp_server.py    MCP sunucusu (Faz 2)
ui/                Control Center (React + TypeScript + Vite); derleme çıktısı ui/dist (git'e girmez)
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
