# CHANGELOG

Biçim: [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/). Sürümleme: SemVer.

## [0.7.1] - 2026-10-31

### Düzeltildi (Windows'ta gerçek modelle görülenler)
- qwen3:8b Türkçe bir e-postanın içine Çince karakter yazdı ("…dolayı造成的 rahatsızlık…"): istekte/girdide olmayan
  Çince/Japonca/Korece karakter artık doğrulama hatası (tüm cevaplar ve revizyonlar); model geri bildirimle yeniden yazar
- Gözden geçirici, cevapta zaten olan bir ifadeyi tırnak içinde "eksik" diye bildirdi → böyle çelişkili eksikler kodla
  elenir (`dropped_issues`), gereksiz revizyon olmaz
- Kapsam kontrolü "e-posta yazma / email writing" gibi talimat/biçim konularını artık eksik saymaz
- `agents_check`: yalnızca koddan oluşan cevapta dil ölçülmez (önceden "dil yanlış" sayılıyordu); yabancı yazı sayacı

### Eklendi
- `kayaai api --open`: sunucu hazır olunca Control Center'ı anahtarlı adresle açar; `kayaai api` çıktısı `kayaai ui`'yi önerir

### Doğrulandı (Windows, v0.7.0)
- Control Center: canlı CPU/RAM/GPU/VRAM (RTX 5070 Ti), yüklü modeller, ajan kartları
- `agents_check` 6/6: doğru ajan 6/6, doğru hesap 6/6, gözden geçirme 6/6, uydurma not 0, anlaşmazlık 0, toplam 15.5 sn

## [0.7.0] - 2026-10-31

### Eklendi (Adım 7 — ajan sistemi)
- Uzman ajanlar `data` (tablo/sayı analizi) ve `document` (rapor, e-posta, özet, düzeltme)
- Üretici → gözden geçirici akışı: ajan tanımında `review: {required, reviewer, checks}`; coder/data/document cevapları
  incelenir; her sorun cevaptan birebir alıntı ister, alıntısı olmayan sorun kodla elenir; `code_syntax` kontrolü
  Python/JSON/YAML bloklarını ayrıştırır (çalıştırmaz); ciddi sorunda bir tur revizyon (kabul / gerekçeli itiraz)
- Anlaşmazlıklar: SQLite `disputes`; Claude modu açıksa iş taslak + iki görüşle Claude kutusuna, kapalıysa sahibe;
  `kayaai disputes [list|show|resolve]`, `GET /api/disputes`, `POST /api/disputes/{id}/resolve`, MCP `kayaai_disputes`
  (salt okunur), Control Center → Anlaşmazlıklar paneli; kutu öğelerinde `local_draft` + `disputes`
- Geçici ajanlar (`data/agents`): izin tavanı (base ∩ yaratıcı), yerel planlayıcı önerisi (`new_agent`), MCP
  `kayaai_agent_propose`, `kayaai agents new|promote|remove`, `/api/agents/{ad}/promote|remove`; kalıcı yapma =
  en az bir başarılı kullanım + R2 sahip onayı (YAML önizlemesi); arayüzde "geçici" rozeti, kullanım, düğmeler
- `conductor.disputes` (claude_first | owner), `conductor.time_budget_s`, `allow_temp_agents`, `max_temp_agents`
- Olaylar: `dispute.opened|resolved`, `agent.created|promoted|removed`, `decision.summary`
- `scripts/agents_check.py` (gerçek modelle ölçüm, ayrı veri klasöründe), `docs/REFERENCES.md`
- Claude çalışma alanı talimatları: kutudaki anlaşmazlıklar, geçici ajan önerme

### Değişti
- Dal `main`'e birleştirildi; README sıfırdan kurulum için `main` + taşıma notu
- İç yardımcı worker'lar planlayıcıya/arayüze/MCP'ye görünmez; MCP `kayaai_ask` yalnızca görünür ajanları kabul eder

## [0.6.0] - 2026-10-31

### Eklendi (Adım 6 — Control Center v1)
- `ui/`: React 18 + TypeScript + Vite arayüzü (ek UI kütüphanesi yok, koyu tema, dar ekranda tek sütun):
  üst çubuk (sürüm, canlı bağlantı, Ollama, Claude modu rozeti + aç/kapat), sistem izleme (CPU/RAM/GPU/VRAM, son 2 dk
  çizgi grafik, bellekteki modeller, aktif görev), ajan kartları (durum renkleri, şu anki/son görev), onay merkezi
  (bekleyen/geçmiş, eski/yeni içerik yan yana, geri alma bilgisi, Onayla/Reddet + not), canlı olaylar (son 50)
- API `/` altında `ui/dist`'i sunar (SPA yolları → index.html; derlenmemişse yardım sayfası); güvenlik başlıkları
  (CSP `default-src 'self'`, `frame-ancestors 'none'`, nosniff, no-referrer)
- `WS /api/events?backlog=N` (en fazla 200): ilk bağlantıda son N olay
- CLI: `kayaai ui` (sunucuyu yoklar, tarayıcıyı `#token=` ile açar; `--print`)
- `setup.ps1`: Node.js 18+ varsa arayüzü derler ve testlerini çalıştırır (yoksa uyarır, kurulum durmaz)
- Testler: Python (sunum, CSP, yol kaçışı, `kayaai ui`, backlog), Vitest (biçimlendirme, anahtar alma)

## [0.5.0] - 2026-10-31

### Eklendi (Adım 5 — izin motoru v2 + ilk gerçek araçlar)
- `kayaai/core/permissions.py`: risk sınıfları R0 (otomatik) · R1 (otomatik + kayıt) · R2 (önizleme + sahip onayı) ·
  R3 (her seferinde sahip onayı, toplu onay yok); kalıcı onay kuyruğu (SQLite `approvals`, yeniden başlatmada korunur,
  `approvals.expire_hours` sonra `expired`); onaylanınca kayıtlı işlem çalıştırılır, sonucu talebe yazılır;
  olaylar: `approval.requested`, `approval.decided`, `tool.used`, `tool.failed`
- `kayaai/tools/files.py` (sahip kararı: kayaAI klasörü + seçilen klasörler): `files.home_dir`
  (varsayılan `~/kayaAI-files`, okuma+yazma) + `files.allowed_dirs` (`read` | `read_write`); `..`, mutlak yol ve
  sembolik bağlantı kaçışları yol çözümlendikten sonra reddedilir; okuma/listeleme R0, yeni dosya R1, var olan dosyanın
  üzerine yazma R2 (önizleme + otomatik yedek `data/backups`); silme yok; metin dosyaları (PDF/Excel Adım 9)
- CLI: `kayaai files roots|ls|read|write`, `kayaai approvals [list|show|approve|reject] [id]`
- API: `/api/files/roots|/api/files|/api/files/read|/api/files/write`, `/api/approvals` (+ `/{id}`, `/approve`, `/reject`)
- MCP: `kayaai_files_list|read|write`, `kayaai_approvals_pending` — **onay aracı yok** (ajan kendi isteğini onaylayamaz)
- `KAYAAI_FILES_DIR` ortam değişkeni

## [0.4.3] - 2026-10-31

### Düzeltildi
- Kapsam kontrolü kod bloklarını siliyordu (dil tespitinin normalleştirmesini paylaşıyordu): yalnızca koddan oluşan
  `function debounce(...)` cevabında "debounce" eksik sayıldı (Windows conductor_check). Artık kod korunur,
  `snake_case` adlar kelimelere bölünür.

### Doğrulandı (Windows, v0.4.2)
- `conductor_check` 6/6 (mod/ajan/Claude kararı/dil 6/6); SaaS cevabı yerelde çok kiracılılığı kapsadı

## [0.4.2] - 2026-10-31

### Düzeltildi
- `scripts/conductor_check.py` Claude modu açıkken ağır isteği Claude kutusuna bırakıp "başarısız" sayıyordu
  (Windows'ta: 5/6, hata kodu). Ölçüm artık her zaman yerel ekiple (`force="local"`); Claude ihtiyacı yine
  hesaplanıp raporlanır. Özete `uncovered_topics_total` eklendi. Regresyon testi: Claude modu açıkken 6/6.

### Doğrulandı (Windows, v0.4.1)
- `api_check`: tüm kontroller geçti; smoke: kabul testleri geçti, dil 6/6, ~136 tok/s

## [0.4.1] - 2026-10-31

### Düzeltildi
- Claude çalışma alanı raporu Windows'ta dosya yollarını `\` ile yazıyordu (`.claude\agents\...`); artık her
  platformda `/`. Dosyalar zaten doğru yere yazılıyordu; Windows'ta 3 test bu yüzden düşüyor, `setup.ps1` duruyordu.

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
