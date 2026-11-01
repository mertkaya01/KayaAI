"""Ofis çizimleri (Adım 18d): sahibin çizdiği karakter / masa / zemin resimleri `data/ofis/` klasöründen.

Kurallar (Türkçe dosya adları, küçük harf):
- Karakter: `<ajan>.png` (genel, veri, belge, kod, gorsel, denetci, sef, sen, claude) — İngilizce adlar da olur
- Durum (isteğe bağlı): `<ajan>-calisiyor.png`, `-bekliyor`, `-hata`, `-yuruyor`, `-bitti`, `-bosta`
- Ortak: `masa.png`, `zemin.png` (izometrik karo), `ajan.png` (adı olmayan ajanlar için)
- Biçim: PNG, SVG, WEBP; en çok 5 MB. Yalnız bu klasördeki resimler sunulur (alt klasör, başka dosya türü yok).
Resimler arayüzde `/ofis/<dosya>` adresinden okunur (yalnız bu bilgisayar; resimde gizli bilgi olmamalı).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SUFFIXES = {".png": "image/png", ".svg": "image/svg+xml", ".webp": "image/webp"}
MAX_BYTES = 5 * 1024 * 1024
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,60}\.(png|svg|webp)$")
ACTORS = {"genel": "general", "veri": "data", "belge": "document", "kod": "coder", "gorsel": "vision",
          "denetci": "reviewer", "sef": "chef", "sen": "owner", "claude": "claude", "ajan": "default"}
STATES = {"calisiyor": "working", "bekliyor": "waiting", "hata": "error", "yuruyor": "walking", "bitti": "done",
          "bosta": "idle"}
SPECIAL = {"masa": "desk", "zemin": "floor"}


def folder(data_dir: Path) -> Path:
    return data_dir / "ofis"


def safe_file(data_dir: Path, name: str) -> Path | None:
    """Sunulabilecek resim yolu ya da None (kaçış, tür, boyut kontrolü)."""
    if not NAME_RE.match(name):
        return None
    d = folder(data_dir).resolve()
    p = (d / name).resolve()
    if p.parent != d or not p.is_file() or p.suffix.lower() not in SUFFIXES or p.stat().st_size > MAX_BYTES:
        return None
    return p


def scan(data_dir: Path) -> dict[str, Any]:
    """Klasördeki çizimler → arayüz eşlemesi: {actors: {id: {state|'base': url}}, desk, floor, unknown: [...]}."""
    d = folder(data_dir)
    out: dict[str, Any] = {"folder": str(d), "exists": d.is_dir(), "actors": {}, "desk": None, "floor": None,
                           "unknown": [], "skipped": []}
    if not d.is_dir():
        return out
    for p in sorted(d.iterdir()):
        if not p.is_file() or p.name.lower() in ("oku.txt", "readme.txt"):
            continue
        if safe_file(data_dir, p.name) is None:
            out["skipped"].append(p.name)
            continue
        stem = p.stem.lower()
        url = f"/ofis/{p.name}?v={int(p.stat().st_mtime)}"
        if stem in SPECIAL:
            out[SPECIAL[stem]] = url
            continue
        base, _, state = stem.partition("-")
        actor = ACTORS.get(base, base if base in ACTORS.values() else None)
        st = STATES.get(state, state if state in STATES.values() else None) if state else "base"
        if actor is None or st is None:
            out["unknown"].append(p.name)
            continue
        out["actors"].setdefault(actor, {})[st] = url
    return out
