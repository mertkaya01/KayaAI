"""Sayı ayrıştırma ve biçimlendirme (Türkçe ve İngilizce biçimler, para birimleri)."""

from __future__ import annotations

import math
import re
from typing import Any

_CURRENCY = re.compile(r"(₺|\bTL\b|\bTRY\b|\$|€|£|\bUSD\b|\bEUR\b|\bGBP\b)", re.IGNORECASE)
_NUM_IN_TEXT = re.compile(r"(?<![\w.,])[-+]?\d[\d.,]*\d(?![\w])|(?<![\w.,])[-+]?\d(?![\w.,]*\d)")


def parse_number(value: Any) -> float | None:
    """'1.234,56 ₺' → 1234.56 · '1,234.56' → 1234.56 · '%18' → 18 · '12' → 12. Sayı değilse None.

    Tek ayraç belirsizse Türkçe kural uygulanır: '1.234' binlik (1234), '12,5' ondalık (12.5).
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None if isinstance(value, float) and math.isnan(value) else float(value)
    s = _CURRENCY.sub("", str(value)).replace("%", "").replace(" ", "").replace(" ", "").strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if not s or not re.fullmatch(r"[-+]?[\d.,]+", s) or not re.search(r"\d", s):
        return None
    sign = -1.0 if (s.startswith("-") or neg) else 1.0
    s = s.lstrip("+-")
    if "." in s and "," in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        thou = "." if dec == "," else ","
        s = s.replace(thou, "").replace(dec, ".")
    elif "," in s:
        # 1,234,567 → binlik; tek virgül Türkçe ondalık sayılır (12,5)
        s = s.replace(",", "") if s.count(",") > 1 else s.replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    elif "." in s:
        head, tail = s.split(".")
        if len(tail) == 3 and 1 <= len(head) <= 3:  # Türkçe binlik: 1.234
            s = head + tail
    try:
        return sign * float(s)
    except ValueError:
        return None


def numbers_in_text(text: str) -> list[float]:
    """Metindeki sayılar (tarih/saat parçaları dahil ham olarak)."""
    out = []
    for m in _NUM_IN_TEXT.finditer(text):
        v = parse_number(m.group().rstrip(".,"))
        if v is not None:
            out.append(v)
    return out


def fmt(value: Any, decimals: int = 2) -> str:
    """Türkçe sayı biçimi: 1234.5 → '1.234,50'; tam sayılar ondalıksız."""
    if value is None:
        return ""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return str(value)
    if float(value).is_integer() and abs(value) < 1e15:
        return f"{int(value):,}".replace(",", ".")
    s = f"{value:,.{decimals}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")
