# kayaAI Mimarisi

## Katmanlar

```
                ┌──────────────────────────────────────────────┐
  Geliştirme    │ Claude Code (geliştirme orkestratörü)        │  Faz 2: MCP ile yerel worker'ları çağırır
                └──────────────────────┬───────────────────────┘
                                       │ (Faz 2: MCP stdio)
                ┌──────────────────────▼───────────────────────┐
  Arayüzler     │ CLI (kayaai) │ MCP sunucusu │ FastAPI + Web UI│  Faz 1 / Faz 2 / Faz 4
                └──────────────────────┬───────────────────────┘
                                       │ Runtime (kayaai/runtime.py)
                ┌──────────────────────▼───────────────────────┐
  Çekirdek      │ Orchestrator  (kayaai/core/orchestrator.py)  │
                │  submit → bağımlılık → izin/onay → çalıştır   │
                │  → timeout/iptal → doğrula → kaydet           │
                ├───────────────┬───────────────┬──────────────┤
                │ TaskStore     │ WorkerRegistry│ ModelRegistry │
                │ SQLite        │ general, ...  │ models.yaml   │
                └───────────────┴───────┬───────┴──────────────┘
                                        │
                ┌───────────────────────▼──────────────────────┐
  Modeller      │ OllamaClient → Ollama (127.0.0.1:11434) → GPU │
                └──────────────────────────────────────────────┘
```

- **Geliştirme orkestratörü (Claude Code):** sistemi yazar, test eder, geliştirir.
- **Çalışma zamanı orkestratörü (kayaAI çekirdeği):** Claude Code kapalıyken de bağımsız çalışır.

## Modüller (Faz 1)

| Dosya | Sorumluluk |
|---|---|
| `kayaai/config.py` | `settings.yaml` + `settings.local.yaml` + ortam değişkenleri → `Settings` |
| `kayaai/core/task.py` | `Task` nesnesi: id, worker, objective, input, expected_output, timeout, permissions, depends_on, status, result, validation, metrics, zaman damgaları |
| `kayaai/core/store.py` | SQLite görev geçmişi + olay günlüğü (`task_events`); yeniden başlatmada yarım kalanları `failed (interrupted)` yapar |
| `kayaai/core/orchestrator.py` | Görev yaşam döngüsü, onay, timeout, iptal, bağımlılık sıralı paralel yürütme |
| `kayaai/llm/ollama_client.py` | Ollama REST istemcisi: retry (bağlantı/5xx), 4xx'te tekrar yok, structured output, iptal |
| `kayaai/llm/registry.py` | `models.yaml` → worker başına model; referans bütünlüğü kontrolü |
| `kayaai/workers/base.py` | `Worker` arayüzü, `LLMWorker`: JSON şemalı çağrı, şemaya uymazsa geri bildirimle tekrar |
| `kayaai/workers/general.py` | Genel zeka worker'ı + `GeneralAnswer` çıktı şeması + anlamsal doğrulama |
| `kayaai/system/audit.py` | Salt okunur ortam denetimi (sadece stdlib) |
| `kayaai/cli.py` | `doctor`, `ask`, `tasks`, `task`, `models`, `audit` |

## Görev yaşam döngüsü

```
pending ──► awaiting_approval ──► rejected
   │              │
   │              ▼
   └────────► running ──► succeeded   (yalnızca şema + anlamsal doğrulama geçerse)
                 │──────► failed      (geçersiz çıktı, Ollama hatası, bağımlılık başarısız, yeniden başlatma)
                 │──────► timed_out
                 └──────► cancelled
```

Kurallar:
1. **Doğrulanmamış çıktı asla `succeeded` olmaz.** Önce Pydantic şeması, sonra worker'ın `validate()` kontrolü.
2. Şemaya uymayan çıktı, hata mesajı modele geri verilerek `max_output_attempts` kez denenir.
3. `auto_approve` listesinde olmayan her izin (dosya yazma, ağ, komut çalıştırma, ekran, ses, masaüstü
   kontrolü) **onaylayıcı** ister. Onaylayıcı yoksa görev `rejected` olur.
4. Zaman aşımı/iptal: görev hemen sonuçlanır, iptal sinyali arka plandaki işe iletilir, geç gelen sonuç yok sayılır.
5. Görevin `input` verisi `<girdi_verisi>` etiketleri içinde **veri** olarak verilir (prompt injection'a karşı ilk savunma katmanı).

## Worker iletişimi

Worker'lar birbirine serbest metin değil **`Task` nesnesi** ile iş verir. Faz 3'te bir worker'ın
çıktısı başka bir görevin `input`'u olacak; alıcı worker bu veriyi de güvenilmez kabul eder
(MASTER_PROMPT: "Workers must not blindly trust each other's outputs").

## Tasarım kararları

| Karar | Gerekçe |
|---|---|
| **LangGraph yerine özel hafif task manager** | Faz 1 ihtiyaçları (DAG bağımlılık, timeout, onay, kalıcı geçmiş) ~300 satırla karşılanıyor. LangGraph ek bağımlılık ve soyutlama getirir; Faz 3'te çok adımlı ajan döngüleri karmaşıklaşırsa yeniden değerlendirilecek. |
| **Senkron httpx + iş parçacıkları** | Tek GPU'da LLM çağrıları zaten sıralı; asyncio karmaşıklığı gereksiz. Faz 4'te FastAPI gelirken çekirdek thread havuzunda çalıştırılabilir. |
| **SQLite (WAL)** | Sıfır kurulum, tek dosya, yedeklemesi kolay, Windows'ta sorunsuz. |
| **Ollama structured outputs (`format`=JSON Schema)** | Modelin geçerli JSON üretme oranını ciddi artırır; yine de Pydantic ile ikinci kez doğrulanır. |
| **`max_parallel: 1` varsayılan** | 16 GB VRAM'de paralel LLM çağrıları VRAM'i böler ve toplamda hızlandırmaz. |
| **Docker yok** | Windows'ta GPU geçişi ve ses/ekran erişimi Docker ile zorlaşır; şu an fayda sağlamıyor. |
| **Proje içi `data/`** | Taşınabilirlik; `KAYAAI_DATA_DIR` ile değiştirilebilir. |

## Claude modu (Adım 3a)

Claude isteğe bağlıdır (MASTER_PROMPT v2 D2). `kayaai/core/claude_mode.py`:
- Aç/kapa: `config/settings.yaml` → `claude.enabled` varsayılan; `kayaai claude on|off` ile değiştirilen
  durum SQLite `meta` tablosunda (`claude.enabled`) saklanır ve varsayılanı ezer.
- "Son temas": kayaAI Claude'u çağıramaz; Claude Code MCP sunucusunu kullandıkça `claude.last_contact`
  güncellenir. Durumlar: `off` / `on_no_contact` / `on_recent_contact` / `on_stale_contact`.
- `waiting_claude` görev durumu Claude kutusu (3d) içindir; terminal değildir, yeniden başlatmada korunur.

## Ajan tanımları (Adım 3b)

`config/agents/<ad>.yaml` → `kayaai/agents/definitions.py` → yerel worker. Alanlar: `name`, `description`,
`output` (`answer` → `GeneralAnswer`, `review` → `ReviewResult`), `role` (sistem talimatı), `local_model`
(models.yaml anahtarı; aday model reddedilir), `claude_tier` (Claude modunda karşılığı, 3e), `permissions`,
`limits.timeout_s`, `status`. Şema ve anlamsal doğrulama çıktı türünün worker sınıfından gelir.
Tanım klasörü yoksa yerleşik `general` worker kullanılır.

## MCP katmanı (Faz 2)

`kayaai/mcp_server.py` — resmi `mcp` Python SDK 2.x (`MCPServer`), **yalnızca stdio**. Claude Code
sunucuyu `.mcp.json`'daki komutla alt süreç olarak başlatır; ağ portu açılmaz.

```
Claude Code ──stdio(JSON-RPC)──► kayaai.mcp_server ──► Runtime/Orchestrator ──► Ollama ──► GPU
```

| Araç | Orkestratör karşılığı |
|---|---|
| `kayaai_ask(question, context?, worker?, timeout_s?)` | `submit` + `run`; `context` → `input` (güvenilmez veri) |
| `kayaai_submit_task` / `kayaai_run_task` | `submit` / `run` (bağımlılıklar korunur) |
| `kayaai_task_status` / `kayaai_list_tasks` / `kayaai_cancel_task` | `TaskStore` / `cancel` |
| `kayaai_list_models` / `kayaai_health` | `ModelRegistry` + Ollama + `nvidia-smi` |

Kurallar:
- Çıktılar Pydantic şemalı (`structuredContent` + MCP `outputSchema`).
- Görev `succeeded` değilse araç **`is_error`** döner; doğrulama hataları mesajda yer alır.
- Onaylayıcı yok → `llm.inference` dışı izin isteyen worker'lar otomatik reddedilir.
- Girdi sınırları: metin ≤ 20.000 karakter, `timeout_s` 1–600.
- Runtime ilk araç çağrısında kurulur; sunucu Ollama kapalıyken de başlar ve `kayaai_health` sorunu raporlar.
- stdout protokole ait; kayaAI logları yalnızca `data/logs/kayaai.log`.
- SDK alt sürece kısıtlı ortam verir; `scripts/mcp_check.py` `KAYAAI_*` değişkenlerini açıkça aktarır.

## Sonraki fazlarda eklenecek bileşenler
- **Faz 3:** worker'lar (software, research, data, document, qa), LLM tabanlı yönlendirici, doğrulayıcı worker.
- **Faz 4:** FastAPI (yalnızca 127.0.0.1, token kimlik doğrulama) + React arayüzü, GPU/VRAM izleme.
