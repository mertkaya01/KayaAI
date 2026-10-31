# Model Kayıt Defteri

Kaynak gerçek: [`config/models.yaml`](config/models.yaml). Bu dosya gerekçeleri ve benchmark sonuçlarını tutar.

## Etkin modeller

| Anahtar | Ollama etiketi | Worker'lar | Bağlam | think | Lisans | Durum |
|---|---|---|---|---|---|---|
| `general-8b` | `qwen3:8b` | general | 8192 | false | Apache-2.0 | **Aktif** — RTX 5070 Ti'de doğrulandı |
| `coder-7b` | `qwen2.5-coder:7b` | coder (config/agents) | 8192 | — | Apache-2.0 | **Aktif** — kod benchmark'ında 4/5 |
| `llama31-8b` | `llama3.1:8b` | — | 8192 | — | Llama 3.1 Community License | Aday (kurulu), karşılaştırma için |

## Seçim gerekçesi — qwen3:8b

- **Donanım:** Q4_K_M ~5.2 GB; 8K bağlamla ~6–6.5 GB VRAM. 16 GB'ta görsel model veya whisper için yer kalır.
- **Türkçe:** Qwen3 çok dilli eğitimli; Türkçe sohbet ve çeviride bu boyuttaki en güçlü açık modeller arasında.
  *Gerçek kalite smoke benchmark'ı ile ölçülecek.*
- **JSON:** Ollama structured outputs ile şema kısıtlı üretim; kayaAI ayrıca Pydantic ile doğrular.
- **Esneklik:** `think` aç/kapa — hızlı yanıt veya derin akıl yürütme aynı modelde.
- **Lisans:** Apache-2.0, ticari kullanım serbest.

## Aday modeller (benchmark sonrası)

| Ollama etiketi | Boyut* | Rol | Not |
|---|---|---|---|
| `qwen3:14b` | ~9.3 GB | Daha güçlü genel model | 16 GB'a sığar; 8b yetersiz kalırsa |
| `qwen3:4b` | ~2.5 GB | Hızlı yönlendirici/sınıflandırıcı | Faz 3 |
| `gemma3:12b` | ~8.1 GB | Genel + görsel | Gemma Terms of Use |
| `qwen2.5-coder:14b` | ~9 GB | Yazılım worker'ı | Faz 3 |
| `qwen2.5vl:7b` | ~6 GB | Ekran/görsel anlama | Faz 5 |
| `qwen3:30b` (MoE, 3B aktif) | ~19 GB | Yüksek kalite | VRAM'e sığmaz, kısmi CPU offload; yavaş |

\* Q4_K_M yaklaşık değerler. Yeni sürümler çıktıkça bu tablo güncellenecek.

## Benchmark ölçütleri

`scripts/smoke_ollama.py` şu an ölçer: yanıt doğruluğu (Türkçe olgu, aritmetik), ilk denemede geçerli
JSON oranı, dil eşleşmesi, token/sn, yükleme süresi, VRAM (`/api/ps` → `size_vram`, `nvidia-smi`).

Faz 10'da genişletilecek: kodlama, uzun bağlam, Türkçe-İngilizce çeviri kalitesi, RAM kullanımı.

## Benchmark sonuçları

| Tarih | Model | Donanım | tok/sn | İlk denemede geçerli JSON | Dil eşleşmesi | VRAM | Not |
|---|---|---|---|---|---|---|---|
| 2026-10-31 | qwen3:8b (Ollama 0.33.3) | RTX 5070 Ti, sürücü 621.01 | **~138** | 5/5 | 3/5 (gerçek hata: 2/2 İngilizce soruya Türkçe cevap) | 5.86 GB, %100 GPU | Soğuk başlangıç 47.8 sn (22.1 sn yükleme); sıcak yanıt 0.4–1.1 sn; 17×23 doğru |

### Bulgular ve yapılan düzeltmeler (v0.1.1)

1. **İngilizce sorulara Türkçe cevap.** "Give three short tips…" ve "Summarize in one sentence…" sorularına
   Türkçe cevap geldi; birinde `language: "en"` etiketi yazılıp cevap Türkçeydi. Sebep: Türkçe sistem promptu
   ve "varsayılan Türkçe" ifadesi. Düzeltme: sistem promptu İngilizce yazıldı, kullanıcının dili koddan tespit
   edilip modele açıkça söyleniyor (`kayaai/core/lang.py`), cevap dili doğrulanıyor; yanlışsa geri bildirimle
   tekrar deneniyor, yanlış dil etiketi deterministik olarak düzeltilip kayda geçiriliyor.
2. **Ölçüm hatası (benchmark kodu):** çeviri sorusunun beklenen dili hedef dil (İngilizce) olmalıydı; 3/5'in
   biri aslında doğru cevaptı. Düzeltildi. Gerçek dil hatası oranı 2/5.
3. **0.63 tok/sn yanıltıcıydı:** ilk (soğuk) çağrı ve sadece 4 token. Artık 16 token altındaki çıktılarda
   tok/sn raporlanmıyor, soğuk ve sıcak gecikme ayrı ölçülüyor.
4. `confidence` her cevapta 0.9–1.0: modelin öz-güven değeri kalibre değil, karar verirken kullanılmamalı.

| 2026-10-31 | qwen3:8b (v0.2.1 kodu) | RTX 5070 Ti | **~137** | 6/6 | **6/6** | 5.86 GB, %100 GPU | Dil düzeltmesi doğrulandı; doğrulama tekrarı gerekmedi |

### Kod modeli karşılaştırması (`scripts/coder_bench.py --execute`, 2026-10-31)

| Model | Geçen test | tok/sn | Not |
|---|---|---|---|
| qwen2.5-coder:7b | **4/5** | ~152 | `parse_duration` başarısız |
| qwen3:8b | 3/5 | ~137 | `word_count` (Türkçe karakter/noktalama) ve `parse_duration` başarısız |

Karar: `coder` ajanı → `coder-7b`. Örneklem küçük (5 görev); ajanın JSON çıktı uyumu `scripts/conductor_check.py`
ile ayrıca doğrulanacak. VRAM: iki model birlikte ~10.6 GB (+ masaüstü) — 16 GB'a sığar.

## Model değiştirme

1. `ollama pull <etiket>`
2. `config/models.yaml` → `models:` altına ekle, `workers:` altında ata
3. `kayaai doctor` → `scripts\windows\smoke.ps1`
4. Sonucu bu dosyaya yaz. Benchmark geçmeden varsayılan yapma.
