# CHANGELOG

Biçim: [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/). Sürümleme: SemVer.

## [0.12.3] - 2026-11-01

### Eklendi (Adım 12d — tarayıcı otomasyonu; kabul #11)
- **Tarayıcı** sekmesi ve `kayaai browse "hedef" --url`: Playwright + kurulu Edge, ayrı boş profil, görünür pencere
- Ajan her adımda bir eylem önerir (`browser.step`, şema + kod doğrulaması); risk sınıfını kod belirler: R0 okuma,
  R1 aynı sitede tıklama, R2 form/yeni site, R3 gönder/öde/satın al/sil/yayınla/kaydol; parola-kart-kimlik alanı,
  indirme/yükleme, `file://` ve yerel ağ reddedilir
- Onay talebinde hedef öğe kırmızı çerçeveli ekran görüntüsü (Onay merkezi de gösterir); sayfada satır içi onay/ret;
  durdurma, 20 adım, tekrar ve onay zaman aşımı korumaları; her adım görev geçmişinde
- API `/api/browser/run|jobs|jobs/{id}|jobs/{id}/stop`; `doctor` satırı; `perception_check --browser`
- Bağımlılık: playwright (Edge'i kullanır, tarayıcı indirmez)

### Düzeltildi
- Windows kurulumunda 2 birim testi düşüyordu: testler OCR olmayan ortamı varsayıyordu, sahibin bilgisayarında Windows OCR
  çalıştı ve boş taranmış sayfada doğru biçimde "yazı bulamadı" dedi. Hata mesajları tutarlı ("metin içermiyor …"),
  testler OCR'dan bağımsız; "OCR yazı bulamadı" durumu için ayrı test; tüm paket "OCR var" koşulunda da doğrulandı
- Tarayıcı işinde `file:///…` gibi şemalı adreslerin önüne `https://` eklenip kabul edilmesi (artık reddedilir)

## [0.12.2] - 2026-11-01

### Eklendi (Adım 12c — canlı çeviri altyazı; kabul #9, #10)
- **Altyazı** sekmesi: sistem sesi (paylaşımla) ya da mikrofon → AudioWorklet 16 kHz PCM → `WS /api/speech/live` →
  enerji tabanlı bölütleyici (uyarlanır gürültü tabanı) → Whisper → gerekirse yerel qwen3:8b çevirisi; ara/kesin
  altyazı, gecikme göstergesi, her zaman üstte **küçük pencere** (Document PiP)
- Döküm yalnız istenince `POST /api/speech/transcript` → `~/kayaAI-files/altyazilar/*.txt|srt`
- Altyazı başlarken görsel model GPU'dan boşaltılır; `perception_check` canlı altyazı gecikmesini ölçer

## [0.12.1] - 2026-11-01

### Eklendi (Adım 12b — bas-konuş ve sesli okuma)
- Asistan'da **🎤** (basılı tut ya da tıkla-başlat/bitir): MediaRecorder → yerel **faster-whisper large-v3-turbo** →
  metin yazı kutusuna; GPU (CUDA float16) → olmazsa işlemci (int8), nedeni raporlanır; 10 dk boşta kalınca bellekten çıkar
- Model indirme sahip onayıyla (`speech.download`, R2) ya da setup.ps1'de; setup.ps1 GPU için NVIDIA cuBLAS + cuDNN'i
  isteğe bağlı kurar; `kayaai doctor` ses durumunu gösterir
- Cevaplarda **🔊 Oku**: yalnızca yerel Windows sesleri (çevrim içi sesler kullanılmaz)
- API `GET /api/speech/status`, `POST /api/speech/transcribe`, `POST /api/speech/download`; CLI
  `kayaai speech status|download|transcribe`; `perception_check` Windows sesiyle sentezlenen cümlelerle WER ölçer
- Bağımlılıklar: faster-whisper, av (<19)

### Düzeltildi
- PyAV 19 faster-whisper 1.2.1'in ses çözmesini bozuyor (`metadata_errors` kaldırılmış): `av<19` sınırı

## [0.12.0] - 2026-11-01

### Eklendi (Adım 12a — ekranı okuma; kabul #8)
- Asistan'da **📷 Ekran**: `getDisplayMedia` ile tek kare (paylaşım hemen kapanır), alan seçmeli önizleme, görüntü eki;
  görüntü dosyaları (PNG/JPEG/WebP/BMP) da eklenebilir
- `vision` ajanı (yerel **qwen2.5vl:7b**, kullanılmayınca 2 dk'da boşalır); Windows yerleşik OCR (pywinrt) ile yazı okuma;
  cevaptaki sayılar OCR metnine karşı kodla denetlenir; devam soruları aynı görüntüyle; "Ekranda okunan yazı" bölümü
- Taranmış PDF: metinsiz sayfalar pypdfium2 ile görüntüye çevrilip OCR'dan geçirilir (özet / fatura)
- CLI `kayaai screen [soru] [--file] [--monitor] [--save]`; API `POST /api/perception/image`, `GET /api/perception/status`;
  `kayaai doctor` görsel model ve OCR durumunu gösterir; setup.ps1 görsel modeli isteğe bağlı indirir
- `scripts/perception_check.py` (gerçek modelle; örnek görüntüler + taranmış PDF + isteğe bağlı gerçek ekran)
- Bağımlılıklar: pillow, pypdfium2, mss; Windows'ta pywinrt OCR paketleri

### Güvenlik
- Ekran görüntüleri Claude'a gitmez (Claude karşılığı yok, MCP aracı yok, devirde çıkarılır); planlayıcı vision ajanını
  metin işlerine atamaz

## [0.11.3] - 2026-11-01

### Düzeltildi (Windows karşılaştırması, v0.11.2)
- Puanlama fazla cömertti: qwen3:4b "Artış yüzde kaç?" sorusuna "120 + 80 = 200" dedi ve "20" metin olarak "200"ün içinde
  geçtiği için doğru sayıldı; başka bir vakada soruyu aynen geri yazdı ve sorudaki sayılar yüzünden doğru sayıldı
  (gerçek sonuç 2/5, rapor 4/5). Artık beklenen sayılar **sayı olarak** aranır (20 ≠ 200; Türkçe/İngilizce biçimler:
  1.234,56 · 1,234.56 · %25 · 60.0), istekte geçen sayılar sayılmaz, soruyu tekrarlayan cevap başarısız ("soruyu
  tekrarladı"); metin beklentileri kelime olarak aranır. Vaka sayıları beklenen sonuçlarla çakışmayacak şekilde seçildi.
- Isınma modeli varsayılan bağlam uzunluğuyla yüklüyordu; ilk sohbet 8192 bağlamla gelince Ollama yeniden yüklüyordu
  (ısınmadan sonra ilk cevap yine ~4 sn). Isınma ve Modeller → Yükle artık sohbetle aynı seçeneklerle (num_ctx) yükler.

### Doğrulandı (Windows, v0.11.2)
- think düzeltmesi: qwen3:4b cevap başına ~6 sn → 0,43 sn (163 token/sn); yükleme süresi ayrı (3,9 / 2,1 sn)
- Yeni zor vaka ayırt edici: indirim + vergi sorusunu iki model de yanlış yaptı (qwen3:8b "90", qwen3:4b "68"; doğru 66)

## [0.11.2] - 2026-11-01

### Düzeltildi (Windows karşılaştırma ölçümleri)
- Karşılaştırmada ilk vakanın süresine modelin belleğe yüklenmesi karışıyordu (qwen2:7b ilk cevap 13,5 sn, diğerleri
  ~0,5 sn). Artık her model vakalardan önce **ısıtılır**; yükleme süresi ayrı gösterilir, ortalamaya girmez. Aday
  karşılaştırmadan önce bellekte değildiyse sonunda boşaltılır (VRAM geri verilir).
- Sonradan eklenen düşünen modeller (Ollama yeteneği `thinking`, ör. qwen3:4b) gizli düşünme açık kaydediliyordu: 161
  token/sn'ye rağmen cevap başına ~6 sn. Artık genel modelle aynı politika (`think: false`) yazılır; eski kayıtlar ilk
  karşılaştırmada düzeltilir.
- Vakalar çok kolaydı (her model 3/3): data ve general setlerine ikişer çok adımlı / kesin cevaplı vaka eklendi (5 vaka).

### Doğrulandı (Windows, v0.11.1)
- `kayaai models compare data llama3.1:8b` 3/3 ↔ 3/3; `general qwen2:7b` (kayıtsız → otomatik aday) 3/3 ↔ 3/3;
  `pull qwen3:4b` → onay → indirme → `compare data qwen3:4b` 3/3 ↔ 3/3

## [0.11.1] - 2026-10-31

### Düzeltildi (Windows geri bildirimi)
- `kayaai models compare data qwen3-4b` → "Kayıtlı model değil" hatası. Model `ollama pull` ile kayaAI dışında
  indirildiyse (Ollama'da kurulu, kayaAI kaydında yok) karşılaştırma artık onu **aday** olarak kaydedip çalışır
  (indirme yok; aday ajana atanamaz kuralı aynı).
- Model komutları anahtar **ya da** Ollama adı kabul eder (`qwen3-4b` ≡ `qwen3:4b`): compare, assign, activate.
- Anlaşılır hatalar: indirme onay bekliyorsa `kayaai approvals approve <id>`; hiç kurulu değilse `kayaai models pull …`;
  `kayaai models` listesi kayıtsız modeller için karşılaştırma komutunu gösterir.
- Modeller → Karşılaştır: kurulu kayıtsız modeller de aday olarak seçilebilir.

## [0.11.0] - 2026-10-31

### Eklendi (Adım 11 — görsel iş akışı + model yönetimi)
- **Akış** sekmesi: şef işlerinin canlı düğüm grafiği (İstek → Planlayıcı → ajanlar → gözden geçirme/düzeltme → son
  kontrol → Sonuç / Claude kutusu); grafik iş kaydı + alt görevler + olaylardan türetilir; `GET /api/jobs`,
  `GET /api/jobs/{id}/graph`; Asistan'da "Akışı göster / izle"
- **Modeller** sekmesi ve `kayaai models load|unload|assign|pull|compare|activate`:
  model tablosu (boyut, nicemleme, VRAM, bellekte, kullanan ajanlar), yükle/boşalt (R1), ajan modeli değiştirme (R2),
  Ollama'dan indirme (R2, arka planda, ilerleme), karşılaştırma testi (kodla puanlama, ayrı kayıt), adayı aktif yapma (R2)
- Yerel model kaydı `data/models.local.yaml` ve ajan model atamaları `data/agent_overrides.yaml` (repo dosyaları
  değişmez; süreçler arası eşitlenir)
- API: `GET /api/model-admin`, `POST /api/models/load|unload|pull`, `POST /api/models/{anahtar}/activate`,
  `POST /api/agents/{ad}/model`, `POST /api/model-compare`, `GET /api/model-compare/{id}`

### Düzeltildi
- Aylara/çeyreklere göre gruplamada sonuç takvim sırasıyla verilir (önceden tutara göre sıralanabiliyordu)
- Dar ekranda üst sekmeler yatay kayar (5. sekme eklenince taşma olmasın)

### Ertelendi
- LM Studio / llama.cpp bağdaştırıcısı (sahip kararı: şimdilik yalnız Ollama)

## [0.10.2] - 2026-10-31

### Düzeltildi
- Analiz planı: "En çok satış getiren ürün hangisi?" sorusunu model ürün başına `max` (tek satışın en büyüğü) olarak
  planlamıştı (Windows, gerçek model). Artık soru "en çok satan/getiren, toplam, ciro, revenue…" içeriyor ve tek kayıt
  ifadesi ("en pahalı", "tek satış"…) içermiyorsa gruplu işlemde `max`/`min` KODLA reddedilir → model `sum` ile yeniden
  planlar; planlayıcı talimatına da kural eklendi.

### Doğrulandı (Windows, v0.10.1)
- `business_check`: analiz 2/3 (yukarıdaki hata), uydurma sayı 0, fatura tüm alanlar + kalemler ✓, PDF özeti 4/4 anahtar
  bilgi + sayfa kaynakları ✓, dört rapor biçimi ✓, toplam 13,8 sn
- `memory_check`: hafıza 10/10, belge 10/10; embedding ~51 ms, arama ~1 ms (önceki ~2 sn ilk model yüklemesiydi);
  eşikler 0.60 / 0.50 ayrışmayı koruyor
- smoke: tüm kabul testleri ✓ (qwen3:8b + bge-m3 birlikte 9,1 GB VRAM)

## [0.10.1] - 2026-10-31

### Düzeltildi
- Windows'ta `setup.ps1` birim testlerinde 7 test düşüyordu: test yardımcısı örnek PDF üretirken Linux'a özgü DejaVu
  yazı tipi yolunu sabit kullanıyordu. Artık üretim kodundaki sistem fontu araması kullanılır (Windows: Segoe UI /
  Arial). Üretim kodu etkilenmemişti.

## [0.10.0] - 2026-10-31

### Eklendi (Adım 10 — iş modülleri; kabul #6, #7, #12)
- `kayaai/business/`: okuyucular (PDF: pypdf; Excel/CSV: openpyxl/csv, Türkçe sayı biçimleri, sütun türü çıkarımı),
  analiz (profil → `AnalysisPlan` → kodla yürütme → sayı denetimli yorum; pay %, dönem gruplama), PDF özeti
  (bölümlü, `[s.N]`), fatura çıkarma + kodla tutar denetimi, rapor (Markdown, Excel, Word, PDF — sahip kararı)
- Sohbet: PDF/Excel ekleri (base64, ≤10 MB), "Analiz et / Özetle / Fatura olarak oku", her cevapta "Rapor oluştur";
  tablo eki + otomatik/data ajanı → analiz
- Raporlar `~/kayaAI-files/raporlar` altına (`FileTools.write_bytes`: yeni R1, üzerine yazma R2 + yedek)
- Belge araması PDF ve Excel'i de dizinler (kaynak `dosya.pdf:s.3`)
- API `/api/business/run`, `/api/chat/{id}/messages/{mid}/report`, `/api/attachments` (`data_b64`); CLI
  `kayaai analyze|summarize|invoice <dosya> [soru] [--report biçim]`; MCP `kayaai_analyze_table`, `kayaai_read_pdf`
- `scripts/business_check.py` (gerçek modelle; ayrı klasör, örnek dosyalar üretir)
- Bağımlılıklar: pypdf, openpyxl, python-docx, reportlab

## [0.9.1] - 2026-10-31

### Değişti
- Tek benzerlik eşiği yerine tür başına eşik: `memory.min_score_memory: 0.60`, `memory.min_score_docs: 0.50`
  (Windows ölçümü, gerçek bge-m3: hafıza ilgili ≥0.655 / ilgisiz ≤0.541; belge ilgili ≥0.553 / ilgisiz ≤0.389).
  Eski `min_score` ayarı okunursa ikisine uygulanır.

### Düzeltildi
- `memory_check` eşik önerisi yanlış etiketliyordu (hafıza sorusunda dönen ilgili belge parçasını "ilgisiz" sayıyordu →
  0.62 önerdi). Artık yalnızca beklenen öğe ilgili; tür başına öneri; süre embedding / arama olarak ayrı ölçülür.

### Doğrulandı (Windows, v0.9.0)
- `memory_check`: hafıza 10/10, belge 10/10, ortalama 910 ms (bazı sorgular ~2 sn — v0.9.1 ölçümü kaynağını gösterecek)

## [0.9.0] - 2026-10-31

### Eklendi (Adım 9 — hafıza; sahip kararı: SQLite + bge-m3)
- `kayaai/memory/`: kişisel hafıza (`MemoryBook`: kategori, hassasiyet, öneri/onay), belge dizini (`DocumentIndex`:
  izinli klasörler, artımlı, satır sınırında parçalama), gizli bilgi tespiti (`secrets.py`), yerel vektörler
  (Ollama `/api/embed`, numpy) + FTS5 kelime araması; `Memory.recall(query, for_claude)`
- Sohbette: `hatırla: …` komutu, mesajda "Hafızaya ekle", her soruda ilgili hafıza + belge parçaları bağlama eklenir,
  cevapta Kaynaklar (`dosya:satır`) ve kullanılan hafıza; Claude'a devretmede özel öğeler ve belgeler gitmez
- Arayüzde **Hafıza** sekmesi: ekle (elle / otomatik sınıflandır / gizli olarak), öneriler (onayla), liste (süz, düzenle,
  sil, gizliyi tek tek göster), JSON dışa aktarma, belge dizini (Şimdi dizinle, durum), hafızada ara
- API: `/api/memory` (+ `from-text`, `{id}`, `approve`, `reveal`), `/api/memory-export`, `/api/memory-search`,
  `/api/documents`, `/api/documents/index`; olaylar `memory.added|updated|deleted|indexed|revealed`
- CLI `kayaai memory [list|add|rm|approve|search|index|status|export]`; MCP `kayaai_memory_search` (özel/gizli/belge
  yok), `kayaai_memory_propose` (öneri); `config/models.yaml` → `embed-m3: bge-m3`; `memory:` ayarları
- `kayaai doctor` ve `setup.ps1` bge-m3'ü kontrol eder / indirmeyi sorar; `scripts/memory_check.py` (eşik ölçümü)
- Bağımlılık: `numpy` (vektör araması)

## [0.8.0] - 2026-10-31

### Eklendi (Adım 8 — Asistan çalışma alanı v1)
- Arayüzde **Asistan** sekmesi (`/asistan`): kalıcı sohbetler (liste, yeniden adlandır, sil), yazma alanı (Enter gönderir),
  ajan seçici (otomatik / uzmanlar / geçici ajanlar), metin ekleri (yükleme ya da izinli klasörden), cevaplarda ajan adı,
  gözden geçirme/düzeltme/anlaşmazlık rozetleri, uyarılar, kopyala; güvenli Markdown görüntüleyici (kod, tablo, liste)
- **Claude'a devret** (sahip kararı: Claude kutusu üzerinden): onay penceresi → kutuya iş (sohbet geçmişi + ekler
  `InboxItem.context`) → Claude Code'da tamamlanınca cevap sohbete düşer; Claude kapalıyken pasif
- `kayaai/assistant/chat.py` (`ChatBook`), SQLite `conversations` / `messages` / `attachments`, `data/attachments/`
- API: `/api/chat` (liste/oluştur/görüntüle/adlandır/sil), `/api/chat/{id}/messages`, `.../handoff`,
  `/api/attachments`, `/api/attachments/from-path`; olay `chat.message`
- Şef işine sohbet bağlamı (`context`): adımlar, gözden geçirici ve revizyon aynı veriyi görür; planlayıcı kısa geçmişi görür
- Claude çalışma alanı talimatı: sohbetten devredilen işlerde bağlamın kullanımı

### Değişti
- Kontrol Merkezi metrikleri yalnızca o sayfa açıkken yoklanır

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
