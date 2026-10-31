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

## Sıradaki adımlar
Yol haritası: [`MASTER_PROMPT.md`](MASTER_PROMPT.md) v2 §13. Adım 3 tamamlandı (2026-10-31). Şu an: Adım 4 planı (yerel API + olay yolu) onay bekliyor.

Bekleyen iyileştirme (Opus'un gözlemi): yerel gözden geçirici, cevabın isteğin ana konusunu (ör. "çok kiracılı") yüzeysel geçtiğini
yakalayamıyor → isteğin anahtar kavramlarının cevapta geçip geçmediğini kodla kontrol (kapsam kontrolü).

## Sonraya not (kullanıcı isteği: "her şey bitince")
Referans repolardan faydalanılacak; içerikleri henüz incelenmedi, her biri alınmadan önce lisansı kontrol edilecek:
sindresorhus/awesome · public-apis/public-apis · donnemartin/system-design-primer · cobusgreyling/loop-engineering ·
SeloGPT/selogpt-prompt-labs · arturitu/the-delegation · ripienaar/free-for-dev · sdmg15/Best-websites-a-programmer-should-visit ·
Donchitos/Claude-Code-Game-Studios · microsoft/Web-Dev-For-Beginners
