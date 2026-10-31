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

## Yerel şef (Adım 3c)

`kayaai/conductor/conductor.py` — `kayaai do` ve MCP `kayaai_do`:

```
istek → planner (RoutePlan: direct | 2-4 adım, needs_claude)  ── geçersiz plan: geri bildirim → yine geçersiz: general
      → yönlendirme (D15/D16): local | local_with_warning | claude_inbox(waiting_claude)
      → adımlar sırayla (önceki sonuçlar <input_data> olarak)
      → birleştirme: merge=assemble (varsayılan; adım cevapları başlıklarla, LLM'siz) | merge=llm
      → reviewer (review=plan): YALNIZCA eksiklik + dil → missing_parts varsa general yazar, "Ek" olarak eklenir
        (≤ max_revisions); diğer notlar "doğrulanmadı" uyarısı
```
- Claude ihtiyacı = planlayıcının görüşü **veya** `complexity_signals` skoru ≥ `claude_threshold`
  (`kayaai/conductor/complexity.py`: adım sayısı, mimari/tasarım/ödünleşim/ölçekleme… ifadeleri, uzunluk).
  Gerekçe: 8B planlayıcı kendi sınırını bilemiyor (gerçek ölçüm).
- İş kaydı: `worker="conductor"` üst görev; tüm adımlar `parent_id` ile alt görev.
- `origin="claude"` (MCP): Claude zaten şef olduğu için kutuya gönderilmez; planlayıcının görüşü uyarı olur.
- Yerel sonuç üretilemezse: Claude açık → kutu, kapalı → `failed` (asla sahte başarı).

## Claude kutusu (Adım 3d)

```
kayaai do (Claude gerekli + Claude modu açık) ──► iş: waiting_claude  ◄── kayaai_claude_inbox (Claude Code)
                                                     │                    kayaai_claude_complete → succeeded, model=claude
                                                     │                    kayaai_claude_release  → yerel ekip (aynı iş)
kayaai claude off ──► bekleyenler yerelde (D16 uyarısı) | --keep: bekler
kayaai inbox run <id> / cancel <id>
```
kayaAI Claude'a iş gönderemez; Claude Code kutuyu okur. Kutu SQLite'ta, yeniden başlatmada korunur.

## Claude çalışma alanı (Adım 3e)

`kayaai/claude_workspace.py` — `kayaai claude on|sync`. Geliştirme repo'sundan ayrı klasör (repo içi reddedilir):
`CLAUDE.md` (şef kuralları) · `.claude/agents/kayaai-<ajan>.md` (`claude_tier` → `model`, `claude_role` → talimat) ·
`.mcp.json` (bu bilgisayardaki `.venv` Python'u ile `kayaai.mcp_server`) · `README.md`.
Hepsi `config/agents` ve ayarlardan türetilir (D14); yalnızca `kayaai-generated` işaretli dosyalar güncellenir.

## Yerel API ve olay akışı (Adım 4)

`kayaai/api/app.py` (FastAPI) — `kayaai api` ile 127.0.0.1:8765. Anahtar: `data/api_token` (Bearer).

```
CLI ─┐                      ┌─ GET /api/health|system|agents|models|tasks|claude|inbox
MCP ─┼─► SQLite (tasks, events) ◄─┤  POST /api/ask|do|claude|inbox/{id}/run|tasks/{id}/cancel  → 202 + id
API ─┘        ▲                   └─ WS  /api/events  (events tablosunu izler, 0.5 sn)
              └── TaskStore.save(): durum değişince events'e "task.status"; ClaudeMode: "claude.mode"
```
- Neden SQLite olay tablosu: kayaAI aynı anda birden çok süreçte çalışır (CLI, Claude Code'un başlattığı MCP sunucusu,
  API); bellek içi olay yolu diğer süreçleri göremez.
- Uzun işler tek iş parçacıklı kuyrukta (tek GPU); ajan durumu görev geçmişinden türetilir (`core/agent_status.py`).

## İzin motoru v2 ve dosya araçları (Adım 5)

```
araç (FileTools.write …) → ToolAction{tool, params, risk, summary, preview, undo, requested_by}
   → PermissionEngine.submit:  R0/R1 → çalıştır → "tool.used"
                               R2/R3 → approvals tablosu (pending) → "approval.requested" → çağırana approval_id
   sahip: kayaai approvals approve | POST /api/approvals/{id}/approve → kayıtlı işlem çalışır → "approval.decided"
```
- Dosya kökleri: `files.home_dir` (rw) + `files.allowed_dirs`; yol `resolve()` sonrası köklere göre denetlenir
  (Windows'ta `normcase`); salt-okunur köke yazma onaysız reddedilir.
- Onay yalnızca sahipten: CLI ve anahtarlı API. MCP yalnızca bekleyenleri okuyabilir.

## Control Center v1 (Adım 6)

```
tarayıcı (http://127.0.0.1:8765/#token=…)          kayaai api (FastAPI)
  ui/dist  ◄──── GET /, /assets/*  (anahtarsız, CSP) ──┤
  fetch    ───── GET/POST /api/*   (Bearer anahtar) ───┤──► Runtime (store, conductor, permissions, files)
  WebSocket ──── /api/events?token=…&backlog=50 ───────┘    SQLite events tablosu
```
- `ui/` — Vite + React 18 + TypeScript, ek UI kütüphanesi yok (CSS değişkenleri + elle yazılmış SVG çizgi grafikler).
  Bileşenler: `TopBar` (sürüm, canlı/Ollama/Claude rozetleri, Claude aç/kapat), `SystemPanel` (2 sn'de bir `/api/system`,
  son 2 dk grafik), `AgentsPanel` (`task.status` olayında yenilenir), `ApprovalsPanel` (bekleyen/geçmiş, önizleme,
  onay/ret + not), `EventsPanel` (son 50 olay).
- Veri akışı: periyodik çekme + olay geldiğinde ilgili paneli hemen yenileme (`usePolling(path, ms, refreshKey)`);
  WS koparsa 2 sn sonra kaldığı olaydan (`after`) devam eder; ilk bağlantıda `backlog=50` ile son olaylar gelir.
- Sunum: `ui/dist` varsa FastAPI `/` altında sunar (bilinmeyen yollar → `index.html`; `/api/*` hiçbir zaman arayüze
  düşmez); yoksa "arayüz derlenmemiş" yardım sayfası. `kayaai ui` sunucuyu yoklar ve tarayıcıyı anahtarlı adresle açar.

## Ajan sistemi (Adım 7)

```
şef: plan → adım (uzman ajan) ──► kontroller (checks.py: ast/json/yaml ayrıştırma, çalıştırma YOK)
                                 └► <gözden geçirici>.check: StepReview {missing_parts, issues[severity, claim, evidence]}
                                      evidence cevapta yoksa → sorun KODLA elenir (dropped_issues)
          blocker/major/eksik/kontrol hatası varsa ──► <ajan>.revise: Revision {answer, accepted[], disputed[{id, reason}]}
                                      c* (kontrol hatası) itiraz edilemez → doğrulama hatası
          disputed ──► disputes tablosu (dispute.opened) ──► Claude açık + claude_first: iş Claude kutusuna (taslak + iki görüş)
                                                          └► değilse: sahip (CLI/API/arayüz) ── dispute.resolved
```
- İç yardımcılar (`coder.revise`, `reviewer.check`) ajan tanımından türetilir; `WorkerRegistry` onları planlayıcıya,
  arayüze ve MCP'ye göstermez. Ajan durumu hesabında ana ajana sayılır.
- Ajan yaşam döngüsü (`kayaai/agents/lifecycle.py`): `config/agents` (repo) + `data/agents` (sonradan oluşturulan).
  Geçici ajan = base ajanın modeli/izinleri ∩ yaratıcının izinleri, her zaman gözden geçirilir; kalıcı yapma =
  başarılı kullanım + `agent.promote` R2 onayı (PermissionEngine). Süreçler arası eşitleme: `sync_user_agents`.
- Olaylar: `dispute.opened|resolved`, `agent.created|promoted|removed`, `decision.summary`.

## Asistan çalışma alanı (Adım 8)

```
arayüz /asistan ── POST /api/chat/{id}/messages {text, agent, attachments}
   ChatBook.send: kullanıcı mesajı + bekleyen asistan mesajı (job_id) ── arka plan kuyruğu
      agent=auto → Conductor.run(request, context)      agent=<ad> → orchestrator (tek ajan)
      context = {conversation: son 8 mesaj (≤2000 kr), attachments: [{name, content}] (≤12 000 kr)} → <input_data>
   ChatBook.refresh: mesaj durumu İŞ KAYDINDAN türetilir (pending/running/waiting_claude/done/failed)
   Claude'a devret → Conductor(force="claude", context) → Claude kutusu (InboxItem.context)
      → Claude Code: kayaai_claude_complete → iş SUCCEEDED → sohbet görüntülenince/olayla mesaj güncellenir
```
- Tablolar: `conversations`, `messages`, `attachments` (+ dosyalar `data/attachments/<id>.txt`). Olay: `chat.message`.
- Arayüz: History API ile `/` (Kontrol Merkezi) ve `/asistan/<id>`; Kontrol Merkezi'nin metrik yoklaması yalnızca o sayfa
  açıkken çalışır. Markdown görüntüleyici (`ui/src/markdown.tsx`) yalnızca React öğesi üretir.

## Hafıza (Adım 9)

```
kayaai.db (aynı dosya, ayrı bağlantı)       Ollama /api/embed (bge-m3, yerel)
  memories ─┐                                         │
  documents ├─ vectors (kind,item_id → float32) ◄─────┘   arama: numpy (mat @ q) + FTS5 (mem_fts, 5 harf önek)
  chunks ───┘  mem_fts (FTS5)
Memory.recall(query, for_claude) → {memory: [...], documents: [{source: "ad:satır", excerpt}]} → sohbet bağlamı
```
- `MemoryBook`: öğe (kategori, hassasiyet, durum active|proposed, kaynak). `secrets.detect_secrets` gizli bilgiyi
  kodla bulur → `SecretRefused` (açık izin hariç). Arama izinli hassasiyetlerle süzülür: yerel {public, personal,
  private}, Claude {public, personal}; secret hiçbir zaman otomatik dönmez.
- `DocumentIndex`: kökler = dosya araçlarının kökleri; her yol `FileTools.resolve` ile doğrulanır; satır sınırında
  parçalama (900 kr, 120 örtüşme), açık gizli kalıp geçen parça atlanır, artımlı (boyut+zaman+sha1).
- Sohbet: `ChatBook._recall` iş başlamadan bağlamı zenginleştirir, mesaja `recall` (kaynaklar, kullanılan öğeler) yazar.
  `hatırla: …` → `memory.classify` (iç worker) → `MemoryBook.add`.
- Eşikler `memory.min_score_memory` (0.60) ve `memory.min_score_docs` (0.50) — bge-m3 kosinüs, `scripts/memory_check.py` ile gerçek modelde tür başına ölçülerek ayarlandı.

## İş modülleri (Adım 10)

```
ek / izinli dosya ──► readers (pypdf, openpyxl, csv; Türkçe sayılar) ──► Table | PdfDoc
analiz:  profile (kod) → business.plan (model, AnalysisPlan şeması, sütunlar KODLA doğrulanır) → execute (kod: süz,
         grupla, topla…, pay %) → business.narrate (model; yorumdaki sayılar hesaplanan değerlerle KODLA karşılaştırılır)
özet:    sayfa grupları → document ajanı bölüm özetleri → birleştirme ([s.N] kaynakları)
fatura:  business.invoice (model, Invoice şeması) → check_invoice (kod: toplamlar, KDV oranı, metinde var mı)
rapor:   Report → md | xlsx (openpyxl) | docx (python-docx) | pdf (reportlab + sistem fontu) → FileTools.write_bytes
         (yeni dosya R1, üzerine yazma R2 + yedek) → ~/kayaAI-files/raporlar
```
- Sohbet: `ChatBook._business` (mod: analyze | summarize | invoice; tablo eki + otomatik/data → analyze), sonuç JSON'u
  mesajda (`meta.business`) saklanır → `ChatBook.report` aynı veriden dört biçimde rapor üretir.
- Belge dizini PDF/Excel'i metne çevirip dizinler (`Chunk.loc` = `s.N`).

## Akış grafiği ve model yönetimi (Adım 11)

```
şef işi + alt görevler (parent_id) + olaylar (plan.created) ──► conductor/graph.build_graph ──► JobGraph (düğüm/kenar)
   (grafik saklanmaz, TÜRETİLİR: iş sürerken ve başka süreçte başlatılan işlerde de doğru)   GET /api/jobs/{id}/graph
arayüz: dag.ts (en uzun yol = sütun, döngüye dayanıklı) → elle yazılmış SVG; iş sürerken 1,5 sn'de bir yenilenir

config/models.yaml + data/models.local.yaml (indirilen / aktif yapılan) ──► ModelRegistry.load_for(settings)
config/agents/*.yaml + data/agent_overrides.yaml (repo ajanları) | data/agents/<ad>.yaml (kullanıcı ajanları)
   ──► lifecycle.sync_agents: kayıt dosyası değiştiyse yeniden yükler, geçersiz kılmaları uygular (süreçler arası)
llm/manager.py: overview (kayıt + /api/tags + /api/ps) · talepler → PermissionEngine
   model.load / model.unload (R1, /api/generate|/api/embed keep_alive) · agent.model, model.pull, model.activate (R2)
llm/compare.py: ajan tanımı × {mevcut, aday} → ayrı TaskStore'da Orchestrator.ask → kodla puanlama →
   data/model_compare/<id>.json; tek kilit (tek GPU); ilerleme `model.compare` olayları
```
- API sunucusunda (`rt.background_ok`) indirme ve karşılaştırma arka plan iş parçacığında sürer; CLI'da bitene kadar bekler.
- Aday model kuralı korunur: aday modeller ajan tanımına ve geçersiz kılmaya atanamaz (yalnız karşılaştırmada, ayrı
  kayıtta çalışır); aktif yapmak için karşılaştırma sonucu + sahip onayı gerekir.

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
