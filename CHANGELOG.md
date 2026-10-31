# CHANGELOG

Biçim: [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/). Sürümleme: SemVer.

## [0.2.0] - 2026-10-31

### Eklendi (Faz 2 — MCP)
- `kayaai/mcp_server.py`: resmi `mcp` SDK 2.x ile stdio MCP sunucusu; 8 araç (`kayaai_ask`,
  `kayaai_submit_task`, `kayaai_run_task`, `kayaai_task_status`, `kayaai_cancel_task`,
  `kayaai_list_tasks`, `kayaai_list_models`, `kayaai_health`), şemalı yapılandırılmış çıktı
- `kayaai mcp` CLI komutu
- `scripts/mcp_check.py`: sunucuyu stdio üzerinden gerçek modelle doğrular → `data/mcp_check.json`
- `scripts/windows/mcp_setup.ps1`: doğrulama + Claude Code için `.mcp.json` üretimi
- MCP testleri: süreç içi ve gerçek stdio alt süreci

## [0.1.1] - 2026-10-31

Gerçek donanımdaki (RTX 5070 Ti) ilk smoke/benchmark sonuçlarına göre düzeltmeler.

### Düzeltildi
- İngilizce sorulara Türkçe cevap verme hatası: İngilizce sistem promptu, koddan dil tespiti
  (`kayaai/core/lang.py`), cevap dili doğrulaması ve geri bildirimle tekrar deneme
- Yanlış `language` etiketi artık deterministik olarak düzeltilip `metrics.corrections`'a yazılıyor
- Anlamsal doğrulama hataları da artık modele geri bildirilip tekrar deneniyor (önce yalnızca şema hataları)
- Denetimde CUDA sürümü okunamıyordu (`null`): esnek regex + `nvidia-smi -q` yedeği + teşhis örneği
- Benchmark: çeviri sorusunun beklenen dili hedef dil; soğuk/sıcak gecikme ayrı; 16 token altı çıktıda tok/sn yok

### Eklendi
- `config/models.yaml`: kurulu `qwen2.5-coder:7b` ve `llama3.1:8b` aday (`status: candidate`) olarak
- Dokümanlar gerçek ölçümlerle güncellendi (PHASE0_REPORT, MODEL_REGISTRY, TASKS)

## [0.1.0] - 2026-10-31

### Eklendi
- Faz 0: salt okunur ortam denetimi — `kayaai/system/audit.py` (Python stdlib), `scripts/audit/audit_windows.ps1`
- Faz 0: teknik rapor `docs/PHASE0_REPORT.md`, mimari ve zorunlu dokümanlar
- Faz 1: Ollama REST istemcisi (retry, timeout, structured output, iptal)
- Faz 1: YAML model kayıt defteri (`config/models.yaml`) ve ayarlar (`config/settings.yaml`)
- Faz 1: `Task` nesnesi, SQLite görev geçmişi + olay günlüğü, yeniden başlatmada kurtarma
- Faz 1: Orkestratör — izin/onay, timeout, iptal, bağımlılık sıralı paralel yürütme, çıktı doğrulama
- Faz 1: Genel worker (JSON şemalı `GeneralAnswer`)
- Faz 1: CLI `kayaai` — doctor, ask, tasks, task, models, audit
- Windows scriptleri: `setup.ps1`, `smoke.ps1`, `run.ps1`
- Gerçek model kabul testleri + benchmark: `scripts/smoke_ollama.py`
- Sahte Ollama HTTP sunucusuyla birim testleri

### Düzeltildi
- `README.md` UTF-16 kodlamalıydı (GitHub'da bozuk görünüyordu); UTF-8 olarak yeniden yazıldı.
