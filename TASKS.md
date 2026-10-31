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
| 6 | PDF okunup özetleniyor | [ ] |
| 7 | Excel analiz ediliyor | [ ] |
| 8 | Ekran görüntüsü yakalanıp analiz ediliyor | [ ] Faz 5 |
| 9 | Seçilen ses kaynağı yazıya dökülüyor | [ ] Faz 6 |
| 10 | Çeviri altyazı olarak gösteriliyor | [ ] Faz 6 |
| 11 | Masaüstü otomasyonu önizlenip onaylanıyor | [ ] Faz 7 |
| 12 | İş raporu üretiliyor | [ ] Faz 9 |
| 13 | Yeniden başlatmada görev geçmişi geri yükleniyor | [x] |

## Faz 2 — Claude Code ve MCP entegrasyonu
- [x] Yerel MCP sunucusu (stdio) — SDK istemcisiyle gerçek alt süreç testi geçti (sahte Ollama)
- [x] Güvenli görev araçları (yalnızca llm.inference, girdi sınırları, hata = is_error)
- [x] Yapılandırılmış iletişim (outputSchema + structuredContent) testli
- [x] `scripts/mcp_check.py` gerçek modelle — Windows'ta geçti (GPU tespiti v0.2.1'de düzeltildi)
- [x] `mcp_setup.ps1` (.mcp.json üretimi) — Windows'ta çalıştı
- [x] Claude Code yerel worker'ları çağırabiliyor (kabul testi #5)
- [ ] Claude'un yerel modeli ne zaman kendiliğinden kullanacağı (yönlendirme kuralları, `CLAUDE.md`) — mimari raporda

## Sıradaki adımlar
1. "Architecture & UI Design" fazı: repo denetimi + mimari + UI önerisi + yol haritası (kod değişikliği yok).
   Alınan kararlar: Claude (Pro, Claude Code) en üstte — Opus şef, Sonnet/Haiku alt ajanlar; geri kalan her şey yerel ve 0 TL.
2. Karar soruları tek tek: sıradaki frontend teknolojisi.
