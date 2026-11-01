# TASKS

Durum işaretleri: `[x]` yapıldı ve test edildi · `[~]` kod hazır, hedef makinede doğrulama bekliyor · `[ ]` yapılmadı

> Kural: Bir özellik, testi **hedef makinede** geçmeden "tamamlandı" sayılmaz.

## Faz 0 — Ortam denetimi
- [x] Çapraz-platform denetim modülü (`kayaai/system/audit.py`) — geliştirme ortamında çalıştırıldı
- [x] Windows denetim scripti (`scripts/audit/audit_windows.ps1`) — Windows 11'de çalıştı (CUDA satırı okuma hatası düzeltildi, tekrar doğrulanacak)
- [x] Teknik rapor (`docs/PHASE0_REPORT.md`) — gerçek ölçümlerle güncellendi
- [x] Mimari ve zorunlu dokümanlar

## Faz 1 — Yerel AI çekirdeği
- [x] Ollama kurulumu (setup.ps1) — Windows'ta çalıştı
- [x] İlk model seçimi: qwen3:8b — ~138 tok/sn, 5.86 GB VRAM, %100 GPU
- [x] Python ↔ Ollama istemcisi (sahte sunucuyla test edildi)
- [x] Görev nesnesi + SQLite görev geçmişi + yeniden başlatmada kurtarma
- [x] Worker registry + model registry
- [x] Orkestratör: delegasyon, doğrulama, retry, timeout, iptal, onay, bağımlılıklar
- [x] CLI: doctor / ask / tasks / task / models / audit
- [x] Gerçek yerel çıkarım testi (`scripts/smoke_ollama.py`)
- [x] Dil tutarlılığı düzeltmesi (v0.1.1) — Windows'ta dil eşleşmesi 6/6 (önce 3/5)

## Kabul testleri (MASTER_PROMPT §20)
| # | Test | Durum |
|---|---|---|
| 1 | Yerel LLM yanıt veriyor | [x] 2026-10-31, RTX 5070 Ti |
| 2 | Python ↔ Ollama | [x] Ollama 0.33.3 |
| 3 | Orkestratör görevi worker'a delege ediyor | [x] |
| 4 | Worker doğrulanmış yapılandırılmış çıktı döndürüyor | [x] |
| 5 | Claude Code MCP ile yerel araçlara erişiyor | [x] 2026-10-31 — Claude Code `kayaai_ask` → qwen3:8b, görev geçmişinde doğrulandı |
| 6 | PDF okunup özetleniyor | [x] 2026-10-31 — 3 sayfalık rapor, 4/4 anahtar bilgi, sayfa kaynaklı |
| 7 | Excel analiz ediliyor | [x] 2026-10-31 — sayıları program hesaplar, uydurma sayı 0 (v0.10.2: toplam/maks yorumu düzeltildi) |
| 8 | Ekran görüntüsü yakalanıp analiz ediliyor | [~] 12a kodlandı (v0.12.0), Windows doğrulaması bekliyor |
| 9 | Seçilen ses kaynağı yazıya dökülüyor | [~] mikrofon (12b) + sistem sesi (12c) kodlandı, Windows doğrulaması bekliyor |
| 10 | Çeviri altyazı olarak gösteriliyor | [~] 12c kodlandı (v0.12.2), Windows doğrulaması bekliyor |
| 11 | Masaüstü otomasyonu önizlenip onaylanıyor | [~] tarayıcı otomasyonu (12d, v0.12.3) kodlandı, Windows doğrulaması bekliyor |
| 12 | İş raporu üretiliyor | [x] 2026-10-31 — xlsx / md / docx / pdf |
| 13 | Yeniden başlatmada görev geçmişi geri yükleniyor | [x] |

## Faz 2 — Claude Code ve MCP entegrasyonu
- [x] Yerel MCP sunucusu (stdio) — SDK istemcisiyle gerçek alt süreç testi geçti (sahte Ollama)
- [x] Güvenli görev araçları (yalnızca llm.inference, girdi sınırları, hata = is_error)
- [x] Yapılandırılmış iletişim (outputSchema + structuredContent) testli
- [x] `scripts/mcp_check.py` gerçek modelle — Windows'ta geçti (GPU tespiti v0.2.1'de düzeltildi)
- [x] `mcp_setup.ps1` (.mcp.json üretimi) — Windows'ta çalıştı
- [x] Claude Code yerel worker'ları çağırabiliyor (kabul testi #5)
- [ ] Claude'un yerel modeli ne zaman kendiliğinden kullanacağı (yönlendirme kuralları, `CLAUDE.md`) — mimari raporda

## Adım 3 — İki mod + şef ([plan](docs/STEP3_PLAN.md))
- [x] 3a Claude modu: `claude.enabled` ayarı, SQLite'ta kalıcı aç/kapa, "son temas" (MCP çağrılarından),
  `waiting_claude` görev durumu, `kayaai claude status|on|off` — Windows'ta `claude on/off` ve kutu sayacı çalıştı
- [x] 3b Ajan tanımları (`config/agents/*.yaml`): general, reviewer, coder; `kayaai agents`; MCP `kayaai_list_agents`;
  kod benchmark'ı Windows'ta: qwen2.5-coder:7b 4/5 vs qwen3:8b 3/5 → coder ajanı coder-7b
- [x] 3c Yerel şef (`kayaai do`, MCP `kayaai_do`) — Windows `conductor_check`: 6/6 başarılı, mod/ajan/dil 6/6
- [x] 3c düzeltmeleri — Windows `conductor_check` 2. tur: 6/6 (Claude önerisi dahil); CSV 3 bölüm, 4.5 sn (önce 9.4 sn)
- [~] 3c ince ayar: bağımlı adımlara "tekrarlama" notu (gerçek çıktıda bölümler aynı içeriği tekrarlıyordu), başlıklar kelime sınırında
- [x] 3d Claude kutusu — Windows'ta: `claude on` → SaaS isteği kutuya (skor 3) → `inbox` → `claude off` → yerelde + uyarı
  - [x] Claude Code tarafı: Opus 5.5 (Pro) `kayaAI-workspace`'te kutudaki işi aldı ve `kayaai_claude_complete` ile yazdı (kullanıcı bildirdi, 2026-10-31)
- [x] 3e Claude çalışma alanı: `kayaai claude on|sync` → `~/kayaAI-workspace` içinde `CLAUDE.md` (şef kuralları),
  `.claude/agents/kayaai-*.md` (alt ajan biçimi resmi dokümandan doğrulandı), `.mcp.json`; yabancı dosyalara dokunmaz,
  repo içine üretmez — 10 test; Windows'ta üretildi, Claude Code v2.1.316 **Opus 5.5 (Pro)** ile açıldı;
  "kutuyu işle" uçtan uca geçti. Gözlem: Opus oturum başında `CLAUDE.md` kuralına uyup kutuyu kontrol etti, onaysız işe girişmedi. Not: bu sürümde `/agents` komutu kaldırılmış; alt ajanlar
  doğrudan `.claude/agents/` klasöründen okunur (Claude'a "hangi alt ajanların var?" diye sorarak doğrulanır)

## Adım 4 — Yerel API + olay akışı
- [x] `kayaai api` (127.0.0.1, erişim anahtarı, CORS localhost), sistem/ajan/model/görev/Claude/kutu uç noktaları,
  arka plan işleri, SQLite `events` + `WS /api/events` — Windows `api_check` (2026-10-31): tüm kontroller geçti
  (401, RTX 5070 Ti metrikleri, arka plan görevi 0.86 sn, WebSocket pending→running→succeeded)

## Adım 5 — İzin motoru v2 + dosya araçları
- [x] Risk sınıfları R0–R3, kalıcı onay kuyruğu (CLI/API ile sahip onayı; MCP'de onay yok), izinli klasörlerle sınırlı
  dosya araçları (sahip kararı: `~/kayaAI-files` + `files.allowed_dirs`), üzerine yazma R2 + yedek — 17 test;
  Windows'ta doğrulandı (2026-10-31)

## Adım 6 — Control Center v1
- [x] `ui/` React + TypeScript (Vite, ek UI kütüphanesi yok): üst çubuk (Claude aç/kapat), sistem izleme (CPU/RAM/GPU/VRAM
  grafikleri), ajan kartları, onay merkezi (önizleme + onay/ret), canlı olaylar; FastAPI `/` sunumu + CSP; `kayaai ui`;
  `setup.ps1` derleme adımı — Python 199 test, Vitest 7 test, Playwright uçtan uca 23 kontrol (konteyner);
  Windows'ta doğrulandı (2026-10-31): canlı GPU/VRAM, yüklü modeller, ajan kartları, `kayaai ui` ile anahtarlı giriş

## Adım 7 — Ajan sistemi ([referans inceleme](docs/REFERENCES.md))
Hedef (MASTER_PROMPT §13): yerel uzmanlar, gözden geçirici, anlaşmazlık yükseltme, geçici ajanlar.
Kabul: üretici → gözden geçirici akışı çalışır; anlaşmazlık yükseltilir.
- [x] 0 — Dal `main`'e birleştirildi (mertkaya01/KayaAI#2); referans repolar incelendi, lisansları kontrol edildi
- [x] 7a — `data` ve `document` uzmanları; ajan başına `review` (gözden geçirici + `code_syntax` kontrolü); kanıtlı
  gözden geçirme (alıntısız sorun kodla elenir); bir tur revizyon (kabul/itiraz); zaman bütçesi; `decision.summary`
- [x] 7b — `disputes` tablosu; Claude açık → kutu (taslak + iki görüş), kapalı → sahip; `kayaai disputes`,
  `/api/disputes`, MCP salt-okunur `kayaai_disputes`, arayüzde Anlaşmazlıklar paneli
- [x] 7c — geçici ajanlar (`data/agents`): izin tavanı, planlayıcı önerisi (`new_agent`), MCP `kayaai_agent_propose`,
  `kayaai agents new|promote|remove`, kalıcı yapma = başarılı kullanım + R2 sahip onayı; arayüzde rozet ve düğmeler
- Testler: Python 241, Vitest 7, Playwright (Adım 7 akışı 17 kontrol); Windows `agents_check` (2026-10-31): 6/6 başarılı,
  doğru ajan ve hesap 6/6, gözden geçirme 6/6, uydurma not 0, anlaşmazlık 0, 15.5 sn — bulunan 3 kusur v0.7.1'de düzeltildi
  (Çince karakter sızıntısı, çelişkili "eksik", talimat konusunda kapsam yanlış alarmı)
- Riskler: 8B gözden geçiricinin yanlış alarmı (alıntı şartı + itiraz hakkıyla sınırlandı; ölçülecek); ek GPU süresi
  (zaman bütçesi, yalnızca uzmanlar gözden geçirilir)

## Adım 8 — Asistan çalışma alanı v1
Hedef (MASTER_PROMPT §9A, §13): gerçek sohbet; yeniden başlatınca geçmiş geri gelir. Sahip kararı (§14): Claude'a
sohbetten devretme Claude kutusu üzerinden (arka planda `claude -p` yok).
- [x] v0.7.1 — Windows bulguları: Çince karakter koruması, çelişkili "eksik" ayıklama, talimat konusu kapsam dışı,
  `kayaai api --open`; PR mertkaya01/KayaAI#3 ile `main`'e birleştirildi
- [x] Kalıcı sohbetler (SQLite), bağlam (son 8 mesaj + ekler, sınırlı), otomatik/ajan seçimi, metin ekleri (yükleme +
  izinli klasör), Claude'a devretme (onaylı, kutu üzerinden, cevap sohbete döner), güvenli Markdown, Asistan sekmesi
- Testler: Python 271, Vitest 12, Playwright (Adım 8 akışı 23 kontrol: geçmiş bağlamı, ek → data, yeniden başlatma
  sonrası geçmiş, Claude'a devret → başka süreçten tamamlama → sohbette, dar ekran); Windows (2026-10-31): gerçek
  sohbet, otomatik yönlendirme (general / data), data cevabı gözden geçirildi + düzeltildi, doğru hesap

## Adım 9 — Hafıza (kişisel hafıza + belge araması)
Sahip kararları (2026-10-31): SQLite + bge-m3 (Ollama, MIT); v1 kapsamı kişisel hafıza + belge araması (RAG).
- [x] Kişisel hafıza: kategori + hassasiyet, gizli bilgi tespiti (açık izinsiz saklanmaz), Claude önerileri onaylı,
  `hatırla:` komutu + "Hafızaya ekle", düzenle/sil/dışa aktar; anlam (numpy) + kelime (FTS5) araması
- [x] Belge araması: izinli klasörler, artımlı dizin, gizli dosya/parça atlama, kaynak gösterme (`dosya:satır`)
- [x] Sohbette otomatik hatırlama (yerel: özel dahil; Claude'a: yalnız kişisel/herkese açık, belge yok);
  Hafıza sekmesi; `kayaai memory`; MCP `kayaai_memory_search` / `kayaai_memory_propose`; doctor + setup bge-m3
- Testler: Python 297, Vitest 12, Playwright (Adım 9 akışı 15 kontrol); Windows `memory_check` (2026-10-31, gerçek bge-m3):
  hafıza 10/10, belge 10/10; hafıza ilgili 0.655–0.831 / ilgisiz ≤0.541, belge ilgili 0.553–0.679 / ilgisiz ≤0.389 →
  v0.9.1'de tür başına eşik (hafıza 0.60, belge 0.50); betiğin tek eşik önerisi yanlış etiketliyordu, düzeltildi
- Riskler: benzerlik eşiği (gerçek bge-m3 ile ölçülecek); büyük klasörlerde ilk dizinleme süresi (artımlı, sınırlı)

## Adım 10 — İş modülleri (kabul #6, #7, #12)
Sahip kararı (2026-10-31): rapor biçimleri Excel, Markdown, Word, PDF.
- [x] v0.9.1 — hafıza/belge için ayrı eşikler (0.60 / 0.50, Windows ölçümü); PR mertkaya01/KayaAI#5 ile `main`'e
- [x] Okuyucular: PDF (pypdf), Excel/CSV (openpyxl/csv; Türkçe sayı biçimi, tür çıkarımı); ikili ekler; belge dizininde PDF/Excel
- [x] Analiz: profil → model planı (şema + kod doğrulaması) → kodla yürütme → sayı denetimli yorum
- [x] PDF özeti (bölümlü, sayfa kaynaklı) ve fatura çıkarma (kodla tutar denetimi)
- [x] Rapor: md / xlsx / docx / pdf, `~/kayaAI-files/raporlar` (R1 / R2); sohbette "Rapor oluştur", CLI `--report`
- [x] Arayüz: PDF/Excel ekleme, "Analiz et / Özetle / Fatura olarak oku"; API `/api/business/run`, `.../report`;
  CLI `kayaai analyze|summarize|invoice`; MCP `kayaai_analyze_table`, `kayaai_read_pdf`
- Testler: Python (iş modülleri 38 + betik), Vitest 12, Playwright (Adım 10 akışı 8 kontrol); Windows `business_check`
  (2026-10-31, v0.10.1): analiz 2/3, uydurma sayı 0, fatura ✓, PDF özeti ✓, 4 rapor ✓, 13,8 sn. Tek hata: "en çok getiren
  ürün" sorusu max(tek satış) olarak planlandı → v0.10.2'de kodla denetim (toplam ifadesi + max/min → yeniden plan)

## Adım 11 — Görsel iş akışı + model yönetimi ([plan kararları](MASTER_PROMPT.md))
Sahip kararları (2026-10-31): LM Studio / llama.cpp şimdilik yok; Modeller sayfasında ajan modeli değiştirme,
yükle/boşalt, yeni model indirme, karşılaştırma testi.
- [x] 11a — Canlı iş akışı grafiği (`conductor/graph.py`, `/api/jobs`, Akış sekmesi, "Akışı göster"); zaman
  gruplamasında takvim sırası (business_check gözlemi)
- [x] 11b — Yerel model kaydı (`data/models.local.yaml`), ajan model geçersiz kılmaları (`data/agent_overrides.yaml`),
  yükle/boşalt (R1), ajan modeli değiştirme (R2), `/api/model-admin`
- [x] 11c — İndirme (R2, arka plan, ilerleme), karşılaştırma (`llm/compare.py`, kodla puanlama), adayı aktif yapma (R2)
- [x] CLI `kayaai models load|unload|assign|pull|compare|activate`; Modeller sekmesi
- Testler: Python (model yönetimi 28 + akış grafiği; tüm paket), Vitest 15, Playwright (akış canlı + Modeller 19 kontrol, mobil taşma yok)
- [x] Windows CLI (2026-11-01, v0.11.1): llama3.1:8b, qwen2:7b (kayıtsız → aday), qwen3:4b (indir → onay →
  karşılaştır) hepsi çalıştı; v0.11.2 ısınma + think düzeltmesi + daha zor vakalar
- [ ] Windows arayüz: Akış'ta gerçek çok adımlı iş; Modeller'de yükle/boşalt

## Adım 12 — Algı ve eylem (kabul #8–#11)
Sahip kararları (2026-11-01): dördü de; görsel model qwen2.5vl:7b; ses tanıma faster-whisper large-v3-turbo (GPU → CPU);
tarayıcı kurulu Edge (ayrı boş profil); sesli okuma Windows yerel sesleri.
- [x] 12a — Ekranı oku: 📷 Ekran (tek kare, alan seçimi), görüntü eki, Windows OCR, vision ajanı (qwen2.5vl:7b),
  sayı denetimi, devam soruları, Claude'a gitmez; taranmış PDF (pypdfium2 + OCR); CLI `kayaai screen`; API
- Testler: Python (algı 18), Playwright (ekran akışı 12 kontrol); Windows `perception_check` bekliyor
- [x] 12b — Bas-konuş (🎤 basılı tut / tıkla, MediaRecorder → yerel faster-whisper, GPU → işlemci, model indirme R2,
  ses saklanmaz) + 🔊 Oku (yalnız yerel Windows sesleri); CLI `kayaai speech`; setup.ps1 model + GPU kütüphaneleri
- Testler: Python (ses 15; webm/wav gerçek çözme), Vitest 18, Playwright (bas-konuş 9 kontrol); Windows `perception_check` bekliyor
- [x] 12c — Canlı çeviri altyazı: sistem sesi / mikrofon → AudioWorklet → WS → bölütleyici + Whisper + yerel çeviri;
  küçük pencere (Document PiP); döküm .txt/.srt yalnız istenince; görsel model boşaltılır
- Testler: Python (canlı 12: bölütleyici sentetik ses, oturum, WS), Playwright (altyazı 13 kontrol; sahte mikrofon dosyası
  + sesli paylaşım); Windows `perception_check` (canlı altyazı gecikmesi) bekliyor
- [x] 12d — Tarayıcı otomasyonu: Playwright + kurulu Edge (ayrı profil), kodla risk sınıfı (R0–R3 + reddedilenler),
  hedef öğesi çerçeveli önizlemeyle onay, Tarayıcı sayfası (adımlar, satır içi onay, sayfa görüntüsü), CLI `kayaai browse`
- Testler: Python (tarayıcı 42: risk tablosu, sahte sürücüyle onay/ret/kural/durdur/tekrar, gerçek Chromium sürücüsü, API),
  Playwright (tarayıcı 10 kontrol); Windows `perception_check --browser` bekliyor

## Sıradaki adımlar
Yol haritası: [`MASTER_PROMPT.md`](MASTER_PROMPT.md) v2 §13. Adım 3 tamamlandı (2026-10-31). Adım 4 tamamlandı (2026-10-31). Adım 10 tamamlandı (2026-10-31). Adım 11 tamamlandı (2026-11-01). Adım 12 kodlandı (12a–d, v0.12.3), Windows doğrulaması bekliyor. Sıradaki: Adım 13 (zamanlama).

- [~] Kapsam kontrolü (Opus'un gözlemi): planlayıcı `key_topics` + kodla kapsam; eksik konu "Ek" ile tamamlanır — Windows'ta
  2. tur (v0.4.2): 6/6, SaaS cevabı çok kiracılılığı kapsıyor (eksik konu yok) + Claude uyarısı; 1 yanlış alarm:
  yalnızca koddan oluşan debounce cevabında 'debounce' eksik sayıldı (kod blokları siliniyordu) → v0.4.3'te düzeltildi

## Sonraya not (kullanıcı isteği: "her şey bitince")
Referans repolardan faydalanılacak; içerikleri henüz incelenmedi, her biri alınmadan önce lisansı kontrol edilecek:
sindresorhus/awesome · public-apis/public-apis · donnemartin/system-design-primer · cobusgreyling/loop-engineering ·
SeloGPT/selogpt-prompt-labs · arturitu/the-delegation · ripienaar/free-for-dev · sdmg15/Best-websites-a-programmer-should-visit ·
Donchitos/Claude-Code-Game-Studios · microsoft/Web-Dev-For-Beginners
