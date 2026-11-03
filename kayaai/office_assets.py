"""Ofis çizimleri (Adım 18d, Adım 21'de pixel stile uyarlandı): sahibin çizdiği karakter / masa / zemin resimleri
`data/ofis/` klasöründen. Yoksa arayüzdeki hazır pixel çizimler (free-office-pixel-art) kullanılır.

Kurallar (Türkçe dosya adları, küçük harf):
- Karakter (masasında oturan, arkadan): `<ajan>.png` (genel, veri, belge, kod, gorsel, denetci, sef, sen, claude)
- Durum (isteğe bağlı): `<ajan>-calisiyor.png`, `-bekliyor`, `-hata`, `-bitti`, `-bosta`
- Yürüme: `<ajan>-yuruyor.png` (aşağı doğru; sola/sağa yansıtılır) ya da yönlü `-yuruyor-asagi`, `-yuruyor-yukari`,
  `-yuruyor-sol`, `-yuruyor-sag`
- Animasyon: kareler YAN YANA, kare kare (64×64 önerilir) — kare sayısı genişlik/yükseklikten anlaşılır
- Ortak: `masa.png` (masa; oturan kişi üstüne çizilir), `zemin.png` (16×16 karo, döşenir), `ajan.png` (adı olmayan
  ajanlar için)
- Eşyalar: `su.png`, `dolap.png`, `kahve.png`, `yazici.png`, `bitki.png`, `cop.png`, `lavabo.png` (hazırın yerine)
- Büyük/yapay zekâ çizimlerini çevirmek için: `kayaai ofis ice-aktar <resim> <ad>` (kayaai/office_import.py)
- Biçim: PNG, SVG, WEBP; en çok 5 MB. Yalnız bu klasördeki resimler sunulur (alt klasör, başka dosya türü yok).
Resimler arayüzde `/ofis/<dosya>` adresinden okunur (yalnız bu bilgisayar; resimde gizli bilgi olmamalı).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SUFFIXES = {".png": "image/png", ".svg": "image/svg+xml", ".webp": "image/webp", ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg"}  # jpg yalnız fotoğraf kartı için anlamlı (saydamlık yok)
MAX_BYTES = 5 * 1024 * 1024
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,60}\.(png|svg|webp|jpg|jpeg)$")
ACTORS = {"genel": "general", "veri": "data", "belge": "document", "kod": "coder", "gorsel": "vision",
          "denetci": "reviewer", "sef": "chef", "sen": "owner", "claude": "claude", "ajan": "default"}
STATES = {"calisiyor": "working", "bekliyor": "waiting", "hata": "error", "yuruyor": "walking", "bitti": "done",
          "bosta": "idle", "foto": "photo", "yuruyor-asagi": "walk_down", "yuruyor-yukari": "walk_up", "yuruyor-sol": "walk_left",
          "yuruyor-sag": "walk_right"}
SPECIAL = {"masa": "desk", "zemin": "floor"}
# Eşyalar (Adım 21b): ad → (sahnedeki yer, en çok yükseklik px). Hazır eşyanın yerine geçer.
PROPS = {"su": ("water", 34), "dolap": ("cabinet", 46), "kahve": ("coffee", 44), "yazici": ("printer", 32),
         "bitki": ("plant", 28), "cop": ("trash", 14), "lavabo": ("sink", 30)}


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
                           "unknown": [], "skipped": [], "sizes": {}, "props": {}}
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
        size = png_size(p)
        if size:
            out["sizes"][url] = size  # kare sayısı = genişlik / yükseklik (yan yana kareler)
        if stem in SPECIAL:
            out[SPECIAL[stem]] = url
            continue
        if stem in PROPS:
            out["props"][PROPS[stem][0]] = url
            continue
        base, _, state = stem.partition("-")
        actor = ACTORS.get(base, base if base in ACTORS.values() else None)
        st = STATES.get(state, state if state in STATES.values() else None) if state else "base"
        if actor is None or st is None:
            out["unknown"].append(p.name)
            continue
        out["actors"].setdefault(actor, {})[st] = url
    return out


def png_size(p: Path) -> list[int] | None:
    """PNG başlığından genişlik/yükseklik (yalnız ilk 24 bayt okunur); PNG değilse None."""
    if p.suffix.lower() != ".png":
        return None
    try:
        with p.open("rb") as f:
            head = f.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    w, h = int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    return [w, h] if 0 < w <= 16384 and 0 < h <= 16384 else None
