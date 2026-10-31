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
- [~] Dil tutarlılığı düzeltmesi (v0.1.1) — birim testli; smoke ile tekrar ölçülecek

## Kabul testleri (MASTER_PROMPT §20)
| # | Test | Durum |
|---|---|---|
| 1 | Yerel LLM yanıt veriyor | [x] 2026-10-31, RTX 5070 Ti |
| 2 | Python ↔ Ollama | [x] Ollama 0.33.3 |
| 3 | Orkestratör görevi worker'a delege ediyor | [x] |
| 4 | Worker doğrulanmış yapılandırılmış çıktı döndürüyor | [x] |
| 5 | Claude Code MCP ile yerel araçlara erişiyor | [ ] Faz 2 |
| 6 | PDF okunup özetleniyor | [ ] |
| 7 | Excel analiz ediliyor | [ ] |
| 8 | Ekran görüntüsü yakalanıp analiz ediliyor | [ ] Faz 5 |
| 9 | Seçilen ses kaynağı yazıya dökülüyor | [ ] Faz 6 |
| 10 | Çeviri altyazı olarak gösteriliyor | [ ] Faz 6 |
| 11 | Masaüstü otomasyonu önizlenip onaylanıyor | [ ] Faz 7 |
| 12 | İş raporu üretiliyor | [ ] Faz 9 |
| 13 | Yeniden başlatmada görev geçmişi geri yükleniyor | [x] |

## Faz 2 — Claude Code ve MCP entegrasyonu
- [ ] Yerel MCP sunucusu (stdio)
- [ ] Güvenli görev araçları (yalnızca llm.inference)
- [ ] Claude Code yerel worker'ları çağırabiliyor (kabul testi #5)
- [ ] Yapılandırılmış iletişimin doğrulanması

## Sıradaki adımlar
1. Faz 2: MCP sunucusu (bu oturumda).
2. Kullanıcı: `git pull` → `setup.ps1` → `smoke.ps1` (dil düzeltmesinin gerçek modelle ölçümü) → Claude Code ile MCP testi.
3. Faz 3: uzman worker'lar; qwen2.5-coder:7b ve llama3.1:8b benchmark.
