# Faz 0 — Ortam Denetimi ve Teknik Rapor

> Durum: **Hedef makinede doğrulama bekliyor.**
> Bu rapor MASTER_PROMPT'taki donanım bilgilerine dayanır. kayaAI bulut ortamında geliştirildiği için
> Windows makinesi doğrudan denetlenemedi. Gerçek değerler `scripts\audit\audit_windows.ps1`
> çıktısıyla (`data\audit_windows.json`) doğrulanınca bu rapor güncellenecek.

## 1. Donanım (beyan edilen)

| Bileşen | Değer | kayaAI için anlamı |
|---|---|---|
| GPU | NVIDIA RTX 5070 Ti, 16 GB GDDR7 | 8B–14B modeller tamamen VRAM'de, hızlı |
| CPU | Intel Core i7-14700K (20 çekirdek / 28 iş parçacığı) | OCR, ses ön işleme, VRAM'e sığmayan katmanlar |
| RAM | 32 GB | VRAM'e sığmayan modellerde kısmi CPU offload mümkün ama yavaş |
| Disk | 2 TB SSD | Model deposu için bol yer |
| OS | Windows (10/11 doğrulanacak) | Yerel Windows desteği zorunlu |
| Bütçe | 0 TL/ay | Sadece ücretsiz, yerel araçlar |

**Kullanılabilir VRAM gerçekçi olarak ~14–15 GB'tır.** Windows masaüstü, tarayıcı ve diğer uygulamalar
0.8–1.5 GB VRAM kullanır. Bu yüzden plan, "her şey aynı anda yüklü" yerine **tek büyük model yüklü**
politikasına dayanır (Ollama `keep_alive` ile otomatik boşaltma).

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

| Kalem | Disk | VRAM (yüklüyken) |
|---|---|---|
| Ollama uygulaması | ~1 GB | — |
| qwen3:8b | 5.2 GB | ~6–6.5 GB |
| (sonra) qwen3:14b | 9.3 GB | ~10–11 GB |
| (Faz 5) qwen2.5vl:7b | ~6 GB | ~7–8 GB |
| (Faz 6) whisper large-v3-turbo | ~1.6 GB | ~1.5–2.5 GB |
| Python ortamı + bağımlılıklar | 0.2 GB (Faz 1) → ~5 GB (Faz 5–6, PyTorch vb.) | — |
| **Faz 1 toplam** | **~7 GB** | **~6.5 GB** |
| Faz 6 sonu tahmini | ~30–40 GB | tek seferde en fazla ~12 GB |

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
| 0 | Ortam denetimi, mimari, rapor | Kod hazır, **Windows'ta çalıştırılması bekleniyor** |
| 1 | Ollama + Python çekirdeği, görev yöneticisi, worker registry | Kod + birim testleri hazır, **gerçek model testi bekleniyor** |
| 2 | MCP sunucusu: Claude Code yerel worker'ları çağırır | Sonraki adım |
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
