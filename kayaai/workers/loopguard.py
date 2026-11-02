"""Tekrar döngüsü yakalayıcı (sahip videosu, 2026-11-02): küçük yerel modeller bazen aynı cümleyi durmadan yazar
("…eksik bilgilerin belirtilmesi istenen rapor kapsamında eksik bilgilerin belirtilmesi…") ve iş ancak süre sınırında
(120 sn) düşer. Model akışlı okunurken metnin sonu aynı parçanın art arda tekrarına dönüşürse akış hemen kesilir;
işçi daha sıkı ayarla (tekrar cezası) yeniden dener.

Yanlış alarmı önlemek için: parça en az 12 karakter, art arda en az 4 kez ve toplam en az 200 karakter tekrar
etmeli (kısa çizgiler, tablo ayraçları, birkaç benzer kod satırı yakalanmaz)."""

from __future__ import annotations

import math
from typing import Callable


class ModelLooping(RuntimeError):
    """Model aynı metni tekrar ediyor; akış kesildi."""

    def __init__(self, phrase: str, chars: int):
        super().__init__(f"model aynı metni tekrar etmeye başladı: “{phrase.strip()[:60]}”")
        self.phrase = phrase
        self.chars = chars


MIN_PERIOD = 12
MAX_PERIOD = 240
MIN_REPEATS = 4
MIN_SPAN = 200
CHECK_EVERY = 96


def find_loop(text: str) -> str | None:
    """Metnin SONU bir parçanın art arda tekrarıysa o parçayı döner, değilse None."""
    n = len(text)
    for p in range(MIN_PERIOD, MAX_PERIOD + 1):
        k = max(MIN_REPEATS, math.ceil(MIN_SPAN / p))
        if p * k > n:
            if p * MIN_REPEATS > n:
                break
            continue
        unit = text[n - p:]
        if all(text[n - (i + 1) * p:n - i * p] == unit for i in range(1, k)):
            return unit
    return None


class LoopGuard:
    """Akışlı model çıktısını izler; döngü görünce `ModelLooping` fırlatır (akış o an kesilir)."""

    def __init__(self, then: Callable[[str], None] | None = None):
        self.then = then
        self.parts: list[str] = []
        self.chars = 0
        self._since = 0

    def feed(self, chunk: str) -> None:
        if self.then is not None:
            self.then(chunk)
        self.parts.append(chunk)
        self.chars += len(chunk)
        self._since += len(chunk)
        if self._since >= CHECK_EVERY:
            self._since = 0
            text = "".join(self.parts)
            self.parts = [text[-(MAX_PERIOD * 20):]]  # bellekte yalnız kuyruk
            phrase = find_loop(self.parts[0])
            if phrase is not None:
                raise ModelLooping(phrase, self.chars)
