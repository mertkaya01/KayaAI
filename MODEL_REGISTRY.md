# Model Kayıt Defteri

Kaynak gerçek: [`config/models.yaml`](config/models.yaml). Bu dosya gerekçeleri ve benchmark sonuçlarını tutar.

## Etkin modeller

| Anahtar | Ollama etiketi | Worker'lar | Bağlam | think | Lisans | Durum |
|---|---|---|---|---|---|---|
| `general-8b` | `qwen3:8b` | general | 8192 | false | Apache-2.0 | Benchmark bekleniyor |

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

| Tarih | Model | Donanım | tok/sn | İlk denemede JSON | Dil eşleşmesi | VRAM | Not |
|---|---|---|---|---|---|---|---|
| — | qwen3:8b | RTX 5070 Ti | bekleniyor | bekleniyor | bekleniyor | bekleniyor | `data\smoke_report.json` gelince doldurulacak |

## Model değiştirme

1. `ollama pull <etiket>`
2. `config/models.yaml` → `models:` altına ekle, `workers:` altında ata
3. `kayaai doctor` → `scripts\windows\smoke.ps1`
4. Sonucu bu dosyaya yaz. Benchmark geçmeden varsayılan yapma.
