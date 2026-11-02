"""Adım 19b doğrulaması — GERÇEK Qdrant ile vektör deposu. Artık tek komut:

    kayaai qdrant start     # Qdrant'ı Docker'da başlatır (yalnız 127.0.0.1)
    kayaai qdrant test      # denetim → data/qdrant_check.json

Bu betik `kayaai qdrant test` ile aynıdır (eski komutla çalışmaya devam etsin diye).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kayaai.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["qdrant", "test"]))
