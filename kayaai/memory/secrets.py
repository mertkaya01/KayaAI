"""Gizli bilgi tespiti (Adım 9, MASTER_PROMPT v2 §7: "secret" öğeler açık izin olmadan SAKLANMAZ).

Kaba ama temkinli kalıplar: anahtar/parola/token gibi görünen her şey "secret" sayılır. Yanlış alarm, yanlışlıkla bir
parolayı vektör dizinine yazmaktan iyidir; sahip gerekirse öğeyi Hafıza ekranından açık onayla yine ekleyebilir.
"""

from __future__ import annotations

import re

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("özel anahtar", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("API anahtarı", re.compile(r"\b(sk-[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|"
                                r"github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|xox[abposr]-[A-Za-z0-9-]{10,}|"
                                r"AIza[0-9A-Za-z_-]{30,})")),
    ("parola", re.compile(r"(?i)\b(şifre(?:m|si|miz)?|parola(?:m|sı)?|password|passwd|pwd|pin(?:\s*kodu)?)\b"
                          r"\s*(?:[:=]|\bis\b|\bşu\b|\bolarak\b)?\s*\S{3,}")),
    ("erişim anahtarı", re.compile(r"(?i)\b(token|api[_ -]?key|secret|bearer)\b\s*[:=]\s*\S{8,}")),
    ("IBAN", re.compile(r"\bTR\d{2}\s?(?:\d{4}\s?){5}\d{2}\b")),
]
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_LONG_TOKEN = re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def detect_secrets(text: str, *, strict: bool = True) -> list[str]:
    """Metinde gizli bilgi türleri (boşsa yok). strict=False: "uzun anahtar/token" sezgisi atlanır (belgelerde kod
    özetleri/sürüm karmaları çok sık; belge parçalarında yalnızca açık kalıplar aranır)."""
    found: list[str] = [name for name, rx in _PATTERNS if rx.search(text)]
    for m in _CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            found.append("kart numarası")
            break
    for m in (_LONG_TOKEN.finditer(text) if strict else ()):
        tok = m.group()
        # uzun, harf+rakam karışık, düz kelime olmayan dizgiler (ör. anahtar/özet) — kod adları elenir
        if sum(c.isdigit() for c in tok) >= 6 and sum(c.isalpha() for c in tok) >= 6 and "_" not in tok[:3]:
            found.append("uzun anahtar/token")
            break
    return list(dict.fromkeys(found))
