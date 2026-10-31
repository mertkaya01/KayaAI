# CHANGELOG

Biçim: [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/). Sürümleme: SemVer.

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
