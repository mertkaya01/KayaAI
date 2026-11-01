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
| 8 | Ekran görüntüsü yakalanıp analiz ediliyor | [x] 2026-11-01 — qwen2.5vl:7b 3/3, sayılar Windows OCR ile doğrulandı; gerçek ekran yorumlandı |
| 9 | Seçilen ses kaynağı yazıya dökülüyor | [x] 2026-11-01 — Whisper large-v3-turbo CUDA'da, WER 0.0 (en); mikrofon + sistem sesi arayüzde |
| 10 | Çeviri altyazı olarak gösteriliyor | [x] 2026-11-01 — canlı altyazı gecikmesi 0,55 sn; çeviri arayüzde |
| 11 | Masaüstü otomasyonu önizlenip onaylanıyor | [x] 2026-11-01 — Edge ile tarayıcı görevi, R2/R3 önizlemeli onay (v0.12.4: istenmeyen R3 kodla reddedilir) |
| 12 | İş raporu üretiliyor | [x] 2026-10-31 — xlsx / md / docx / pdf |
| 13 | Yeniden başlatmada görev geçmişi geri yükleniyor | [x] |

## Faz 2 — Claude Code ve MCP entegrasyonu
- [x] Yerel MCP sunucusu (stdio) — SDK istemcisiyle gerçek alt süreç testi geçti (sahte Ollama)
- [x] Güvenli görev araçları (yalnızca llm.inference, girdi sınırları, hata = is_error)
- [x] Yapılandırılmış iletişim (outputSchema + structuredContent) testli
- [x] `scripts/mcp_check.py` gerçek modelle — Windows'ta geçti (GPU tespiti v0.2.1'de düzeltildi)
- [x] `mcp_setup.ps1` (.mcp.json üretimi) — Windows'ta çalıştı
- [x] Claude Code yerel worker'ları çağırabiliyor (kabul testi #5)
- [x] Claude'un yerel modeli ne zaman kullanacağı (`CLAUDE.md`): sahip kararı (2026-11-01) "Ekleme, benimki yeter" —
  depoya kural eklenmez, sahibin kendi `CLAUDE.md`'si geçerli

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
  Playwright (tarayıcı 10 kontrol)
- Windows `perception_check --screen --browser` (2026-11-01, v0.12.3): görsel 3/3 (OCR doğrulamalı, ort. 2,1 sn), OCR
  fatura 3/3 · hata penceresi 0/2 (`C:\` → `C:X`, l → I), gerçek ekran doğru özetlendi; Whisper CUDA'da, WER 0.0 (en;
  Türkçe SAPI sesi yok), canlı altyazı 0,55 sn; tarayıcı görevi bitti. Bulgular → v0.12.4: istenmeyen R3 ("Satın alma."
  hedefinde "Satın Al" önerildi) kodla reddedilir, aynı adım tekrarı atlanır; ses ölçümünde model yükleme ayrı; OCR küçük
  görüntüyü 2 kat büyütür; test PDF'i düzeltildi; Türkçe OneCore sesi (WinRT) ile ölçüm

## Adım 13 — Zamanlama, optimizasyon, kurulum belgeleri (son adım)
Sahip kararları (2026-11-01): Windows Görev Zamanlayıcı; hazır görevler: belge klasörü özeti, haftalık satış raporu,
belge dizini yenileme, serbest görev.
- [x] 13a — Zamanlanmış görevler: kayıt + sıklık, Görev Zamanlayıcı XML'i (schtasks), R2 onay, çalıştırıcı (kilit,
  Ollama bekleme, sonuç Asistan'a), 4 işleyici, API/CLI, Zamanlama sekmesi, `scripts/schedule_check.py`
- Testler: Python (zamanlama 36), Playwright (zamanlama 8 kontrol); Windows `schedule_check` bekliyor
- [x] 13b — VRAM bekçisi (görsel model / Whisper öncesi boştaki modelleri boşaltır) + `kayaai bench` (Windows'ta çalıştırılacak)
- [x] 13c — [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md): sıfırdan kurulum, güncelleme, yedekleme/geri yükleme, kaldırma,
  sorun giderme, güvenlik özeti; README hızlı başlangıç bağlantısı
- [x] Windows `kayaai bench` (2026-11-01): qwen3:8b soğuk 4,7 sn / sıcak 0,4 sn, 139 token/sn; bge-m3 7,8 ms/metin;
  qwen2.5vl soğuk 3,7 / sıcak 0,44 sn; Whisper yükleme 3,6 sn, gerçek zaman oranı 0,057 (CUDA), WER 0; VRAM tepe 16,1/16,3 GB
  → v0.13.3: bench de Whisper öncesi VRAM bekçisini çağırır, görsel doğrulama ayrıntısını kaydeder
- [x] Windows `schedule_check` (2026-11-01, v0.13.3): **kabul geçti** — kayaAI kapalıyken Görev Zamanlayıcı 16:12'de
  çalıştırdı (Last Result 0, `trigger: windows`, sonuç Asistan'da, günlük yazıldı); ilk deneme de çalışmıştı (15:54,
  Last Result 0) ama betik rapor yazmadan bitmişti → v0.13.3
- [x] Windows `kayaai bench` (v0.13.3): VRAM bekçisi Whisper öncesi 247 MB → 7,4 GB boşalttı; Whisper RTF 0,027.
  Görsel "doğrulanmadı": OCR ondalık virgülü "1" okuyor (1.680,00 → 1.680100) → v0.13.4: para tutarlarında bu okuma
  kabul edilir (yanlış sayı yine yakalanır)

## Sıradaki adımlar
Yol haritası: [`MASTER_PROMPT.md`](MASTER_PROMPT.md) v2 §13. Adım 3 tamamlandı (2026-10-31). Adım 4 tamamlandı (2026-10-31). Adım 10 tamamlandı (2026-10-31). Adım 11 tamamlandı (2026-11-01). Adım 12 tamamlandı (2026-11-01). Adım 13 tamamlandı (2026-11-01). **Yol haritası (Adım 0–13) tamamlandı.**

- [~] Kapsam kontrolü (Opus'un gözlemi): planlayıcı `key_topics` + kodla kapsam; eksik konu "Ek" ile tamamlanır — Windows'ta
  2. tur (v0.4.2): 6/6, SaaS cevabı çok kiracılılığı kapsıyor (eksik konu yok) + Claude uyarısı; 1 yanlış alarm:
  yalnızca koddan oluşan debounce cevabında 'debounce' eksik sayıldı (kod blokları siliniyordu) → v0.4.3'te düzeltildi

## Sonraya not (kullanıcı isteği: "her şey bitince")
- [x] Referans repolar incelendi (2026-11-01) — lisanslar, katkılar ve öneriler: [`docs/REFERENCES.md`](docs/REFERENCES.md).
  Öneriler: otomasyonu duraklat anahtarı, dosya yazma yasak listesi, isteğe bağlı dış veri (döviz/tatil), erişilebilirlik
## Adım 14 — Referans incelemesinden iyileştirmeler (sahip dördünü seçti, 2026-11-01)
- [x] 14a — Otomasyonu duraklat (üst çubuk, `kayaai pause|resume`, API) — Python 3 + Playwright 4 kontrol
- [x] 14b — Dosya yazma yasak listesi (talep + yürütme) — Python 23
- [x] 14c — Döviz kuru (Frankfurter) + resmi tatiller (Nager.Date): kapalı, R2 ile açılır, sohbet bağlamı, satış raporu
  notu, zamanlanmış görevde tatil atlama, `kayaai integrations` — Python 15 (sahte ağ; bu ortamdan siteler engelli)
- [x] 14d — Erişilebilirlik: axe (WCAG 2.1 AA) 8 sayfada 5 ihlal → 0; İçeriğe atla, görünür odak, aria-current,
  h1, landmark adları, kontrast, Escape/odak yönetimi — Playwright klavye 9 kontrol
- [x] Windows'ta sahip doğruladı (2026-11-01): duraklat/sürdür, yasak liste, gerçek kur/tatil bağlantısı, klavye

## Adım 15–17 — Sahip tasarımı (2026-11-01): canlı ofis → Bugün + sol menü + bildirim → bulut köprüsü
Sahip kararları: ofis 2B izometrik; Asistan'ın yanında + tam ekran; bildirim tarayıcı + Windows; bulutta "genel + seçtiğim
iş verisi" (özel/gizli asla). OmniRoute: resmî depo ve lisans kurulumdan önce doğrulanacak.
- [x] 15a — Canlı ilerleme: akışlı Ollama (`on_token`), yarım JSON'dan okunur kuyruk, `task.progress` (≤0,4 sn'de bir,
  iş bitince silinir), `orchestrator.live_progress` — Python 15
- [x] 15b — Ofis: `ui/src/office/scene.ts` (düğüm→karakter, masalar, yürüyüş farkları), `OfficeView` (SVG izometrik,
  derinlik sırası, balonlar üst katmanda, inceleme paneli, onay/durdur), Asistan yan paneli (Ofis | Hafıza) + `/ofis`
  (Ofis | Akış grafiği; eski `/akis` açılır) — Vitest 10, Playwright (canlı akış, teslim yürüyüşü, inceleme), axe 0 ihlal
  (+ eski iki ihlal: olay listesi klavye, mesaj başlık sırası), klavye, hareketi azalt
- [ ] Windows: Asistan'da "Otomatik" ile çok adımlı bir iş → ofiste izle; karaktere tıkla; Büyüt
- [x] 16a — Tasarım: açık/koyu/sistem tema (tüm renkler tek yerde), ferah boşluklar, yumuşak gölgeler; sol menü
  (daraltılabilir, dar ekranda çekmece); Kontrol Merkezi → Sistem (`/sistem`); eski üst çubuk kaldırıldı
- [x] 16b — Bugün (`/`, `/api/today`): onaylar (tek tık), çalışan işin ofisi, zamanlanmış görevler, son sohbetler,
  sistem, açıksa kur/tatil — Python 13
- [x] 16c — Bildirimler: tercihler + sessiz saatler (`/api/notifications`), tarayıcı (arka plandayken), Windows
  bildirimi (zamanlanmış görev; PowerShell, metin ortam değişkeniyle) — Vitest 33, Playwright (bildirim arka planda
  geliyor / önde gelmiyor, menü, tema, klavye), axe 9 sayfa × 2 tema 0 ihlal
- [ ] Windows: Sistem → Bildirimler → "Windows'u dene"; zamanlanmış görev kayaAI kapalıyken bildirim; açık tema
- [x] 17 — Bulut köprüsü: `llm/cloud.py` (ayarlar, yalnız yerel adres, R2 aç / R1 kapat, veri kapısı, gizli bilgi kapısı,
  günlük sınır, metinsiz kayıt, yerel yedek), işçi döngüsünde bulut → hata olursa yerel, şef her adıma izni geçirir,
  sohbet `cloud`, `kayaai do --cloud`, serbest zamanlanmış görev `cloud`, `kayaai cloud status|enable|disable|key|test`,
  `/api/cloud*`, Sistem → Bulut köprüsü paneli, sohbette ☁ Bulut, ofiste ☁ işareti; ofis tek ajanlı işleri de gösterir —
  Python 14, Vitest 35, Playwright (sahte OmniRoute: dene → aç → onay → ☁ ile cevap, hafıza gitmedi)
- [ ] Windows: OmniRoute kur → `kayaai cloud key` → `kayaai cloud test` → `kayaai cloud enable` → Asistan'da ☁ Bulut

- [x] Fine-tuning değerlendirmesi → `docs/FINETUNING.md`: şimdilik hayır, önce ölç; `kayaai quality` (ajan × model ilk
  deneme / geçersiz / zaman aşımı / kesilme → `data/quality.json`) — Python 5
- [x] Windows (sahip, 2026-11-01): `kayaai quality` — general 77 / planner 33 görev %100 ilk deneme, hiç geçersiz yok →
  fine-tuning gerekmiyor (ayrıntı `docs/FINETUNING.md`)
