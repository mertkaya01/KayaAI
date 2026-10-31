# CHANGELOG

Biçim: [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/). Sürümleme: SemVer.

## [0.4.0] - 2026-10-31

### Eklendi (Adım 4 — yerel API + olay akışı)
- `kayaai api` (FastAPI + Uvicorn): yalnızca 127.0.0.1 (başka adres reddedilir), her istek `data/api_token`
  erişim anahtarı ister (`kayaai api token`), CORS yalnızca localhost; `/docs` deneme sayfası
- Uç noktalar: `/api/health`, `/api/system` (CPU/RAM/GPU/VRAM, psutil + nvidia-smi), `/api/agents` (ajan + durum:
  idle/running/waiting/completed/failed), `/api/models`, `/api/tasks` (+ ayrıntı/olaylar/alt görevler, iptal),
  `POST /api/ask` ve `/api/do` (arka planda, hemen iş numarası döner), `/api/claude` (aç/kapat + kutuyu geri verme),
  `/api/inbox` (+ run/cancel)
- Süreçler arası olay akışı: SQLite `events` tablosu (görev durum değişiklikleri, Claude modu); CLI, MCP sunucusu ve
  API aynı akışı yazar; `WS /api/events` canlı aktarır (`after=` ile geçmiş)
- `scripts/api_check.py`: çalışan sunucuya karşı gerçek modelle uçtan uca kontrol
- Bağımlılıklar: `fastapi`, `websockets`, `psutil`

### Düzeltildi
- Kopan WebSocket bağlantısı açık kalıyor, `kayaai api` kapatılamıyordu (geliştirme sırasında yakalandı;
  gerçek sunucuyla regresyon testi)

### Eklendi
- **Kapsam kontrolü** (Opus'un gerçek gözlemi: "çok kiracılı SaaS" isteğine yerel cevap çok kiracılılığa hiç
  değinmedi, gözden geçirici yine "ok" dedi): planlayıcı `key_topics` (2–5 ana konu) çıkarır — ek model çağrısı yok;
  konuların cevapta geçip geçmediğine `kayaai/conductor/coverage.py` KODLA karar verir (Türkçe eklere dayanıklı
  kök eşleşmesi, "A / B" alternatifleri). Eksik konu gözden geçirmede "Ek" ile tamamlanır; yine eksikse tek uyarı.

### Düzeltildi
- Dil tespiti tek kelimelik metinde karar veriyordu (`"a"` → İngilizce); çok kısa metinde en az iki sinyal gerekir

## [0.3.0] - 2026-10-31

Adım 3 (iki mod + şef) kod olarak tamamlandı.

### Eklendi (Adım 3e — Claude çalışma alanı)
- `kayaai claude on` (aç + üret) / `kayaai claude sync [--workspace]`: şef (Opus) oturumu için ayrı klasör
  (varsayılan `~/kayaAI-workspace`, `claude.workspace_dir`). Üretilenler: `CLAUDE.md` (önce yerel, kutu işleme,
  "her mesajı araca yollama", dürüstlük/onay kuralları), `.claude/agents/kayaai-<ajan>.md` (claude_tier'a göre
  haiku/sonnet/opus; biçim resmi Claude Code dokümanından doğrulandı), `.mcp.json`, `README.md`
- Güvenlik: yalnızca `kayaai-generated` işaretli dosyalar güncellenir; kullanıcı dosyaları atlanır ve raporlanır;
  artık Claude karşılığı olmayan ajanın üretilmiş dosyası kaldırılır; repo içine üretim reddedilir
- Ajan tanımlarına `claude_role` (Claude alt ajanının talimatı; yerel talimat Claude'a taşınmaz)

### Düzeltildi
- Bağımlı adımlar önceki sonuçları tekrar yazıyordu (gerçek çıktıda 3 bölüm aynı içerik) → "tekrarlama" notu
- Kutu uyarı metni eskimişti ("Adım 3d"); başlıklar artık kelime sınırında kesiliyor


### Eklendi (Adım 3a — Claude modu)
- `claude` ayarı (`config/settings.yaml`, varsayılan kapalı) ve `kayaai/core/claude_mode.py`:
  aç/kapa durumu SQLite `meta` tablosunda kalıcı; "son temas" = Claude Code'un MCP sunucusunu en son kullanması
- `kayaai claude status|on|off [--json]`; `kayaai doctor` ve MCP `kayaai_health.claude_mode` modu gösterir
- `waiting_claude` görev durumu (Claude kutusu için; yeniden başlatmada korunur, iptal edilebilir)
- Onaylanan Adım 3 planı: `docs/STEP3_PLAN.md`

### Eklendi (Adım 3d — Claude kutusu)
- `kayaai/conductor/inbox.py`: Claude gerektiren işler `waiting_claude` olarak bekler; Claude Code MCP ile alır
- MCP: `kayaai_claude_inbox` (bekleyenler + sebep + yerel plan önerisi), `kayaai_claude_complete` (Claude'un
  cevabını görev geçmişine yazar; `model: claude (Claude Code)`), `kayaai_claude_release` (yerel ekibe geri ver)
- `Conductor.resume_local`: bekleyen iş aynı kayıtta yerelde tamamlanır (D16 uyarısıyla)
- CLI: `kayaai inbox [list|run <id>|run all|cancel <id>]`; `kayaai claude off` kutudaki işleri yerelde yapmayı
  sorar (varsayılan evet, `--keep` bekletir, `--yes` sormaz)

### Düzeltildi (3c — RTX 5070 Ti'deki `conductor_check` sonuçlarına göre)
- **Birleştirme bilgi kaybediyordu:** 3 adımlı işte (kod → açıklama → commit mesajı) LLM birleştirmesi sadece kodu
  döndürdü. Varsayılan artık `merge: assemble` — adım cevapları başlıklarla sırayla, LLM'siz; `llm` seçenek olarak kaldı.
- **Gözden geçirici yanlış alarm veriyordu:** 8B model, kodda olmayan hatalar buldu (kullanılan parametreye
  "kullanılmıyor" dedi). Reviewer artık yalnızca eksiklik + dil kontrol eder (`missing_parts`); eksik kısımlar
  yazılıp cevaba "Ek" olarak eklenir, mevcut cevap ezilmez; diğer notlar "doğrulanmadı" uyarısı olur.
- **Claude ihtiyacı hiç tetiklenmiyordu:** planlayıcıya ek olarak kodla karmaşıklık skoru (adım sayısı,
  mimari/tasarım/ödünleşim/ölçekleme gibi ifadeler, uzunluk); skor ≥ `claude_threshold` (3) → Claude önerilir.

### Eklendi (Adım 3c — yerel şef)
- `kayaai do "istek" [--local|--claude] [--json]` ve MCP `kayaai_do`: planla → yürüt → birleştir → gözden geçir
- `planner` ajanı (`RoutePlan`: direct/plan, adımlar, needs_claude); plan geçerliliği kodla kontrol edilir,
  geçersizse geri bildirimle tekrar, yine geçersizse genel ajana düşer
- Claude yönlendirmesi: gerekmiyorsa yerel; gerekli + kapalı → yerelde + uyarı (D16); gerekli + açık →
  `waiting_claude` (Claude kutusu); yerel başarısız + açık → kutuya; her karar `routing.decision` olayıyla kayıtlı
- `reviewer` ile gözden geçirme (`conductor.review: never|plan|always`) ve en fazla `max_revisions` düzeltme
- İşler `conductor` üst görevi + alt görevler (`parent_id`) olarak görev geçmişinde
- `scripts/conductor_check.py`: gerçek modellerle 6 örnek istek

### Değişti
- `coder` ajanı → `qwen2.5-coder:7b` (kod benchmark'ı 4/5, qwen3:8b 3/5)

### Eklendi (Adım 3b — ajan tanımları)
- `config/agents/*.yaml` tek kaynak ajan tanımları: `general`, `reviewer`, `coder`; kod yazmadan yeni ajan
- `kayaai/agents/definitions.py`: doğrulamalı yükleyici (dosya adı, bilinmeyen/aday model, izinler, çıktı türü)
- `reviewer` worker (`ReviewResult`: verdict / issues / suggestion)
- Ajan başına zaman aşımı (`limits.timeout_s`), `kayaai agents`, MCP `kayaai_list_agents`
- `scripts/coder_bench.py`: kod modeli karşılaştırması; varsayılan kod çalıştırmaz, `--execute` onay ister

### Değişti
- `MASTER_PROMPT.md` v2: ilk MASTER_PROMPT + "Architecture & UI Design" prompt'u + sahibinin kararları
  (D1–D16) tek belgede. Claude isteğe bağlı bir "Claude modu" (aç/kapa); kayaAI onsuz tam çalışır;
  her iki modda da önce yerel. v1 `docs/archive/MASTER_PROMPT_v1.md` altında.

## [0.2.2] - 2026-10-31

### Doğrulandı (Windows, gerçek model)
- Kabul testi #5: Claude Code → MCP `kayaai_ask` → qwen3:8b; görevler `kayaai tasks` geçmişinde
- Dil eşleşmesi 6/6 (v0.1.1 düzeltmesi), MCP sağlık kontrolünde GPU görünüyor

### Düzeltildi
- Smoke: model zaten VRAM'deyse ilk çağrı artık "soğuk başlangıç" olarak etiketlenmiyor

## [0.2.1] - 2026-10-31

Windows'taki gerçek test çalıştırmasında bulunan hatalar.

### Düzeltildi
- **Orkestratör `run_all` yarış durumu:** bağımlılık *başlatıldığında* hazır sayılıyordu; bağımlı görev,
  bağımlılığı hâlâ çalışırken başlayıp "bağımlılık başarısız (running)" ile düşebiliyordu. Artık bağımlılık
  *bittiğinde* hazır sayılıyor. Windows'ta `test_dependencies_run_in_order_and_failure_propagates` ile
  yakalandı; deterministik regresyon testi eklendi.
- **MCP `kayaai_health` GPU'yu göremiyordu:** MCP SDK alt sürece kısıtlı ortam veriyor. `nvidia-smi` için
  Windows'ta bilinen konumlara yedek arama, `stdin` devralınmıyor, `mcp_check.py` tam ortamı aktarıyor;
  GPU okunamazsa sebebi `gpu_notes` alanında raporlanıyor.

### Doğrulandı (Windows)
- CUDA sürücü sürümü artık okunuyor: 13.5
- `mcp_check.py`: 8 araç, gerçek modelle TR/EN cevaplar doğru dilde (~138 tok/sn)

## [0.2.0] - 2026-10-31

### Eklendi (Faz 2 — MCP)
- `kayaai/mcp_server.py`: resmi `mcp` SDK 2.x ile stdio MCP sunucusu; 8 araç (`kayaai_ask`,
  `kayaai_submit_task`, `kayaai_run_task`, `kayaai_task_status`, `kayaai_cancel_task`,
  `kayaai_list_tasks`, `kayaai_list_models`, `kayaai_health`), şemalı yapılandırılmış çıktı
- `kayaai mcp` CLI komutu
- `scripts/mcp_check.py`: sunucuyu stdio üzerinden gerçek modelle doğrular → `data/mcp_check.json`
- `scripts/windows/mcp_setup.ps1`: doğrulama + Claude Code için `.mcp.json` üretimi
- MCP testleri: süreç içi ve gerçek stdio alt süreci

## [0.1.1] - 2026-10-31

Gerçek donanımdaki (RTX 5070 Ti) ilk smoke/benchmark sonuçlarına göre düzeltmeler.

### Düzeltildi
- İngilizce sorulara Türkçe cevap verme hatası: İngilizce sistem promptu, koddan dil tespiti
  (`kayaai/core/lang.py`), cevap dili doğrulaması ve geri bildirimle tekrar deneme
- Yanlış `language` etiketi artık deterministik olarak düzeltilip `metrics.corrections`'a yazılıyor
- Anlamsal doğrulama hataları da artık modele geri bildirilip tekrar deneniyor (önce yalnızca şema hataları)
- Denetimde CUDA sürümü okunamıyordu (`null`): esnek regex + `nvidia-smi -q` yedeği + teşhis örneği
- Benchmark: çeviri sorusunun beklenen dili hedef dil; soğuk/sıcak gecikme ayrı; 16 token altı çıktıda tok/sn yok

### Eklendi
- `config/models.yaml`: kurulu `qwen2.5-coder:7b` ve `llama3.1:8b` aday (`status: candidate`) olarak
- Dokümanlar gerçek ölçümlerle güncellendi (PHASE0_REPORT, MODEL_REGISTRY, TASKS)

## [0.1.0] - 2026-10-31

### Eklendi
- Faz 0: salt okunur ortam denetimi — `kayaai/system/audit.py` (Python stdlib), `scripts/audit/audit_windows.ps1`
- Faz 0: teknik rapor `docs/PHASE0_REPORT.md`, mimari ve zorunlu dokümanlar
- Faz 1: Ollama REST istemcisi (retry, timeout, structured output, iptal)
- Faz 1: YAML model kayıt defteri (`config/models.yaml`) ve ayarlar (`config/settings.yaml`)
- Faz 1: `Task` nesnesi, SQLite görev geçmişi + olay günlüğü, yeniden başlatmada kurtarma
- Faz 1: Orkestratör — izin/onay, timeout, iptal, bağımlılık sıralı paralel yürütme, çıktı doğrulama
- Faz 1: Genel worker (JSON şemalı `GeneralAnswer`)
- Faz 1: CLI `kayaai` — doctor, ask, tasks, task, models, audit
- Windows scriptleri: `setup.ps1`, `smoke.ps1`, `run.ps1`
- Gerçek model kabul testleri + benchmark: `scripts/smoke_ollama.py`
- Sahte Ollama HTTP sunucusuyla birim testleri

### Düzeltildi
- `README.md` UTF-16 kodlamalıydı (GitHub'da bozuk görünüyordu); UTF-8 olarak yeniden yazıldı.
