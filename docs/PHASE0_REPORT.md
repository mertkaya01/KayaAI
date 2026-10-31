# Faz 0 — Ortam Denetimi ve Teknik Rapor

> Durum: **Hedef makinede doğrulandı (2026-10-31).** Kaynak: kullanıcının `data\audit_windows.json` ve
> `data\smoke_report.json` çıktıları.

## 1. Donanım (ölçülen)

| Bileşen | Ölçülen değer | kayaAI için anlamı |
|---|---|---|
| OS | Windows 11 Pro, build 26200, 64 bit, PowerShell 5.1 | Yerel Windows desteği zorunlu |
| CPU | Intel Core i7-14700K — 20 çekirdek / 28 iş parçacığı | OCR, ses ön işleme, kısmi offload |
| RAM | 31.8 GB (ölçüm anında 16.2 GB boş) | VRAM'e sığmayan modellerde kısmi offload mümkün ama yavaş |
| Disk | C: 1862 GB, **521.9 GB boş** | Model deposu için bol yer |
| GPU | NVIDIA GeForce RTX 5070 Ti — **16303 MB VRAM**, compute 12.0 (Blackwell) | 8B–14B modeller tamamen VRAM'de |
| Ek GPU | Intel UHD 770 (iGPU) | Masaüstü bu karta taşınırsa NVIDIA'da VRAM boşalır (opsiyonel) |
| NVIDIA sürücüsü | 621.01 | Blackwell ve CUDA 12.8+ destekli (ilk denetimde CUDA satırı okunamadı, regex düzeltildi) |
| Bütçe | 0 TL/ay | Sadece ücretsiz, yerel araçlar |

**Boşta VRAM kullanımı 1.3–1.6 GB** (masaüstü + uygulamalar). Bu yüzden plan, "her şey aynı anda
yüklü" yerine **tek büyük model yüklü** politikasına dayanır (Ollama `keep_alive` ile otomatik boşaltma).

### Kurulu yazılımlar (ölçülen)

| Araç | Sürüm | Not |
|---|---|---|
| Python | 3.11.9 (Microsoft Store) + 3.12.10 (kayaAI .venv bununla kuruldu) | OK |
| Git | 2.51.2 | OK |
| Node.js / npm | 24.15.0 / 12.0.2 | Faz 4 arayüz için hazır |
| Docker | 29.6.1 | Gerekmiyor, kullanılmayacak |
| Ollama | 0.33.3 | OK, GPU'yu tam kullanıyor |
| ffmpeg | 9.0.1 (gyan.dev full build) | Faz 6 için hazır |
| Tesseract | yok | Faz 5'te kurulacak |
| winget | 1.29 | OK |
| Kurulu modeller | qwen3:8b, llama3.1:8b, qwen2.5-coder:7b, qwen2:7b | qwen2:7b eski; silinirse ~4.4 GB yer açılır (`ollama rm qwen2:7b`) |

## 2. GPU uyumluluğu — RTX 50 (Blackwell) notları

- RTX 5070 Ti, Blackwell mimarisi, compute capability **12.0 (sm_120)**.
- **CUDA 12.8 veya üstünü destekleyen NVIDIA sürücüsü gerekir.** `nvidia-smi` başlığındaki
  "CUDA Version" ≥ 12.8 olmalı. Denetim scripti bunu otomatik kontrol eder.
- **Ollama:** güncel Windows sürümü Blackwell'i destekler; eski sürümler GPU'yu görmeyip CPU'ya düşebilir.
  Doğrulama: model yüklüyken `ollama ps` çıktısında `100% GPU` görülmeli.
- **Faz 5–6 için uyarı:** PyTorch, CTranslate2 (faster-whisper) gibi kütüphanelerin eski wheel'leri
  sm_120 içermez. O fazlarda CUDA 12.8+ ile derlenmiş sürümler seçilecek ve GPU'da gerçekten
  çalıştıkları test edilecek. CUDA Toolkit kurmak **gerekmez**; sürücü yeterlidir.

## 3. Yazılım denetimi

Kontrol edilecekler (scriptler otomatik yapar): Python 3.11+, Git, Node.js/npm (Faz 4 arayüz),
Docker (zorunlu değil), Ollama, Tesseract (Faz 5), ffmpeg (Faz 6), winget.

Faz 1 için **zorunlu olanlar yalnızca: Python 3.11+, Ollama, Git.**

## 4. Önerilen model seçimi

"En popüler" değil, donanıma ve göreve göre seçildi. İlk adımda **tek model** indirilir, benchmark
edilir, sonra diğerlerine karar verilir (MASTER_PROMPT kural: "ilk modeli benchmark etmeden birden çok
büyük model indirme").

| Rol | İlk seçim | Yaklaşık boyut* | Neden | Alternatif |
|---|---|---|---|---|
| Genel / Türkçe-İngilizce | **qwen3:8b** | 5.2 GB disk, ~6–6.5 GB VRAM (8K bağlam) | Apache-2.0, güçlü çok dillilik, JSON çıktıda iyi, `think` aç/kapa | qwen3:14b (~9.3 GB), gemma3:12b (~8.1 GB) |
| Hızlı sınıflandırıcı | (Faz 3) qwen3:4b | 2.5 GB | Yönlendirme/sınıflandırma için düşük gecikme | gemma3:4b |
| Yazılım | (Faz 3) qwen2.5-coder:14b | ~9 GB | Kod odaklı | qwen3-coder (30B MoE, VRAM'e sığmaz → kısmi offload) |
| Görsel (ekran) | (Faz 5) qwen2.5vl:7b | ~6 GB | Ekran görüntüsü/UI anlama, OCR destekli | gemma3:12b (görsel destekli) |
| Konuşma→metin | (Faz 6) faster-whisper large-v3-turbo | ~1.6 GB | Türkçe dahil çok dilli, hızlı | whisper small/medium |

\* Boyutlar Ollama kütüphanesindeki Q4_K_M sürümlerine göre yaklaşıktır. Ekim 2026 itibarıyla bu
ailelerin daha yeni sürümleri çıkmış olabilir; `config/models.yaml` sayesinde değişiklik tek satırdır.
Yeni bir model **benchmark'tan geçmeden** varsayılan yapılmaz.

`qwen3` için `think: false` varsayılandır: düşünme modu gecikmeyi 3–10 kat artırır ve yapılandırılmış
JSON çıktısıyla bazen çakışır. Karmaşık akıl yürütme gerektiren worker'larda ileride açılabilir.

## 5. Disk ve VRAM bütçesi

**Ölçülen (qwen3:8b, 8K bağlam):** model belleği 5.86 GB, **tamamı VRAM'de** (`size_vram = size`).
Toplam GPU belleği yüklemeden önce 1587 MB → yükledikten sonra 7726 MB; **~8.3 GB boş kalıyor.**

| Kalem | Disk | VRAM (yüklüyken) |
|---|---|---|
| Ollama uygulaması | ~1 GB | — |
| qwen3:8b | 5.2 GB | **5.86 GB (ölçüldü)** |
| (sonra) qwen3:14b | 9.3 GB | ~10–11 GB (tahmin) |
| (Faz 5) qwen2.5vl:7b | ~6 GB | ~7–8 GB (tahmin) |
| (Faz 6) whisper large-v3-turbo | ~1.6 GB | ~1.5–2.5 GB (tahmin) |
| Python ortamı + bağımlılıklar | 0.2 GB (Faz 1) → ~5 GB (Faz 5–6, PyTorch vb.) | — |

Sonuç: qwen3:8b + whisper birlikte rahat sığar; qwen3:8b + görsel model (~13.5 GB + masaüstü) sınırda →
görsel model kullanılırken LLM boşaltılacak.

### Hız (ölçülen)

| Ölçüm | Değer |
|---|---|
| Soğuk başlangıç (ilk istek) | 47.8 sn toplam, bunun 22.1 sn'si model yükleme |
| Sıcak yanıt (model yüklü) | 0.36–1.1 sn |
| Üretim hızı | **~138 token/sn** (132–139) |

Soğuk başlangıç yüksek: 22 sn yükleme + ~25 sn ilk hesaplama (muhtemelen ilk çalıştırmada GPU çekirdek
derlemesi/ısınma; sürücü bunu önbelleğe alır). Bir sonraki smoke çalıştırmasında `latency` alanı soğuk ve
sıcak süreyi ayrı raporlar. Model `keep_alive: 10m` boyunca VRAM'de kalır.

Ollama modelleri varsayılan olarak `C:\Users\<kullanıcı>\.ollama\models` altına iner. C: dolu ise
`OLLAMA_MODELS` kullanıcı ortam değişkeniyle başka sürücüye taşınabilir.

## 6. Ücretsiz araç ve lisans değerlendirmesi

> Ticari kullanım öncesi her lisans resmi kaynağından tekrar doğrulanmalıdır (kural 18).

| Araç / model | Lisans | Ticari kullanım |
|---|---|---|
| Ollama | MIT | Serbest |
| Qwen3 modelleri | Apache-2.0 | Serbest |
| Gemma 3 | Gemma Terms of Use | İzinli, kullanım kısıtlamaları politikasına uyulmalı |
| Llama 3.x | Llama Community License | İzinli; atıf zorunlu, 700M+ MAU kısıtı |
| DeepSeek-R1 distill | MIT (+ taban modelin lisansı: Qwen→Apache, Llama→Llama lisansı) | Taban modele göre |
| httpx / pydantic / PyYAML / pytest | BSD / MIT / MIT / MIT | Serbest |
| SQLite | Public domain | Serbest |
| Tesseract | Apache-2.0 | Serbest |
| OpenCV (4.5+) | Apache-2.0 | Serbest |
| MSS, Pillow | MIT, HPND (MIT benzeri) | Serbest |
| faster-whisper, Whisper modelleri | MIT | Serbest |
| Piper TTS | Güncel geliştirme GPL-3.0 (piper1-gpl); her sesin ayrı lisansı var | Dikkat: GPL ve ses lisansları kontrol edilmeli |
| MarianMT (Helsinki-NLP opus-mt) | Çoğunlukla CC-BY-4.0 | Atıf ile serbest |
| Playwright | Apache-2.0 | Serbest |
| pywinauto | BSD-3 | Serbest |
| ChromaDB / Qdrant | Apache-2.0 | Serbest |
| **PyMuPDF** | **AGPL-3.0** | **Dikkat:** satılan üründe kaynak açma yükümlülüğü → yerine pypdf (BSD) / pdfplumber (MIT) tercih edilecek |

## 7. Mimari özeti

Ayrıntı: [`ARCHITECTURE.md`](../ARCHITECTURE.md). Kısaca: Python çekirdeği (orkestratör + worker'lar +
SQLite görev geçmişi) → Ollama (localhost) üzerinden yerel modeller. Faz 2'de aynı çekirdek MCP
sunucusu olarak Claude Code'a açılır, Faz 4'te FastAPI + web arayüzü eklenir.

## 8. Adım adım uygulama planı

| Faz | İçerik | Durum |
|---|---|---|
| 0 | Ortam denetimi, mimari, rapor | **Tamamlandı** — Windows'ta doğrulandı |
| 1 | Ollama + Python çekirdeği, görev yöneticisi, worker registry | **Tamamlandı** — kabul testleri #1-4, #13 geçti |
| 2 | MCP sunucusu: Claude Code yerel worker'ları çağırır | **Tamamlandı** — kabul testi #5 geçti |
| 3 | Uzman worker'lar, delegasyon, doğrulama | |
| 4 | Masaüstü/web arayüzü | |
| 5 | Ekran zekası (yakalama, OCR, görsel model) | |
| 6 | Ses ve canlı çeviri | |
| 7 | Masaüstü/tarayıcı otomasyonu + onay sistemi | |
| 8 | Hafıza ve bilgi tabanı (RAG) | |
| 9 | İş ajanları (Excel, PDF, rapor, teklif) | |
| 10 | Optimizasyon | |

**Öneri:** İlk gelir potansiyeli Faz 9'dadır (Excel/CSV otomasyonu, PDF/fatura çıkarımı). Faz 3
bittikten sonra Faz 9'un ilk modülüne erken geçip satılabilir bir demo çıkarmak mantıklıdır;
ekran/ses fazları teknik olarak daha riskli ve uzun sürer.

## 9. Gerçekçi sınırlar

- **Canlı çeviri eşzamanlı olmaz.** Parça bazlı (chunk) transkripsiyon + çeviri ile 1.5–4 sn gecikme
  hedeflenir.
- **Windows sistem sesi yakalama** (WASAPI loopback) mümkündür ama bazı cihaz/sürücülerde kırılgandır;
  mikrofon yolu yedek olarak hep tutulacak.
- **16 GB VRAM'de** büyük LLM + görsel model + whisper aynı anda tam hızda çalışmaz; modeller sırayla
  yüklenir. 30B+ modeller kısmi CPU offload ile çalışır ama belirgin şekilde yavaşlar.
- Yerel 8–14B modeller GPT-4 sınıfı bulut modellerin kalitesine her görevde ulaşmaz; kritik çıktılar
  doğrulayıcı worker'larla ve insan onayıyla kontrol edilecek.
