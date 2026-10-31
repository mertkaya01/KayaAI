"""kayaAI ortam denetimi - bağımlılık kurmadan çalışır.

Kullanım (proje klasöründen):
    python scripts/audit/audit_env.py
Rapor: data/audit_report.json
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kayaai.system.audit import main  # noqa: E402  (stdlib-only modül)

if __name__ == "__main__":
    raise SystemExit(main(["--project-dir", str(ROOT), "--out", str(ROOT / "data" / "audit_report.json")]))
