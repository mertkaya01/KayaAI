# TASKS

Durum işaretleri: `[x]` yapıldı ve test edildi · `[~]` kod hazır, hedef makinede doğrulama bekliyor · `[ ]` yapılmadı

> Kural: Bir özellik, testi **hedef makinede** geçmeden "tamamlandı" sayılmaz.

## Faz 0 — Ortam denetimi
- [x] Çapraz-platform denetim modülü (`kayaai/system/audit.py`) — geliştirme ortamında çalıştırıldı
- [~] Windows denetim scripti (`scripts/audit/audit_windows.ps1`) — Windows'ta çalıştırılmadı
- [~] Teknik rapor (`docs/PHASE0_REPORT.md`) — gerçek denetim çıktısıyla güncellenecek
- [x] Mimari ve zorunlu dokümanlar

## Faz 1 — Yerel AI çekirdeği
- [~] Ollama kurulumu (setup.ps1) — Windows'ta çalıştırılmadı
- [~] İlk model seçimi: qwen3:8b — benchmark bekleniyor
- [x] Python ↔ Ollama istemcisi (sahte sunucuyla test edildi)
- [x] Görev nesnesi + SQLite görev geçmişi + yeniden başlatmada kurtarma
- [x] Worker registry + model registry
- [x] Orkestratör: delegasyon, doğrulama, retry, timeout, iptal, onay, bağımlılıklar
- [x] CLI: doctor / ask / tasks / task / models / audit
- [~] Gerçek yerel çıkarım testi (`scripts/smoke_ollama.py`)

## Kabul testleri (MASTER_PROMPT §20)
| # | Test | Durum |
|---|---|---|
| 1 | Yerel LLM yanıt veriyor | [~] smoke_ollama.py hazır |
| 2 | Python ↔ Ollama | [~] smoke_ollama.py hazır (sahte sunucuyla [x]) |
| 3 | Orkestratör görevi worker'a delege ediyor | [~] (sahte LLM ile [x]) |
| 4 | Worker doğrulanmış yapılandırılmış çıktı döndürüyor | [~] (sahte LLM ile [x]) |
| 5 | Claude Code MCP ile yerel araçlara erişiyor | [ ] Faz 2 |
| 6 | PDF okunup özetleniyor | [ ] |
| 7 | Excel analiz ediliyor | [ ] |
| 8 | Ekran görüntüsü yakalanıp analiz ediliyor | [ ] Faz 5 |
| 9 | Seçilen ses kaynağı yazıya dökülüyor | [ ] Faz 6 |
| 10 | Çeviri altyazı olarak gösteriliyor | [ ] Faz 6 |
| 11 | Masaüstü otomasyonu önizlenip onaylanıyor | [ ] Faz 7 |
| 12 | İş raporu üretiliyor | [ ] Faz 9 |
| 13 | Yeniden başlatmada görev geçmişi geri yükleniyor | [~] (birim testi [x]) |

## Sıradaki adımlar
1. Kullanıcı: `audit_windows.ps1` → `setup.ps1` → `smoke.ps1`; `data\audit_windows.json` ve `data\smoke_report.json` paylaşılır.
2. Sonuçlara göre: model seçimi kesinleşir, PHASE0_REPORT güncellenir, gerekiyorsa qwen3:14b benchmark edilir.
3. Faz 2: MCP sunucusu.
