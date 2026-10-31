"""Kapsam kontrolü: cevap, isteğin ana konularına gerçekten değiniyor mu? (kodla)

Neden: Opus'un gerçek gözlemi (2026-10-31) — "çok kiracılı SaaS" isteğine yerel ekip genel mikroservis
bilgisi verdi, çok kiracılılığa hiç değinmedi; yerel gözden geçirici yine de "ok" dedi.
Konuları planlayıcı çıkarır (RoutePlan.key_topics, ek model çağrısı yok); kapsanıp kapsanmadığına KOD karar verir.

Yöntem: her konunun ('A / B' alternatifleri) içerik kelimelerinin Türkçe eklere dayanıklı kökleri
(kelimenin ilk 4–7 harfi) cevapta bir kelimenin başı olarak aranır; bir alternatifin köklerinin en az
yarısı bulunursa konu kapsanmış sayılır. Bu kaba bir sinyaldir: yalnızca uyarı ve "eksik kısım" girdisi
olarak kullanılır, asla tek başına başarısızlık sebebi değildir.
"""

from __future__ import annotations

import math
import re

from ..core.lang import _EN_STOP, _TR_STOP, _WORD_RE

def _normalize(text: str) -> str:
    """Dil tespitindeki normalleştirmeden FARKLI: kod blokları SİLİNMEZ — konu çoğu zaman kodun içindedir
    (gerçek yanlış alarm, 2026-10-31: yalnızca koddan oluşan `function debounce(...)` cevabında 'debounce' eksik sayıldı)."""
    return text.replace("İ", "i").lower().replace("\u0307", "").replace("_", " ")

_SPLIT_ALTERNATIVES = re.compile(r"[/()|,;]+")
# Konu adında anlam taşımayan genel kelimeler
_GENERIC = {"için", "olan", "gibi", "ile", "and", "the", "for", "with", "nasıl", "how"}
MIN_ANSWER_CHARS = 150


def _stem(word: str) -> str:
    n = max(4, min(7, math.ceil(len(word) * 0.6)))
    return word[:n]


def _content_stems(text: str) -> list[str]:
    words = _WORD_RE.findall(_normalize(text.replace("-", " ")))
    out = []
    for w in words:
        w = w.strip("'")
        if len(w) < 4 or w in _TR_STOP or w in _EN_STOP or w in _GENERIC:
            continue
        out.append(_stem(w))
    return list(dict.fromkeys(out))


def topic_covered(topic: str, answer: str) -> bool:
    answer_words = set(_WORD_RE.findall(_normalize(answer.replace("-", " "))))
    alternatives = [a for a in _SPLIT_ALTERNATIVES.split(topic) if a.strip()]
    checked_any = False
    for alt in alternatives:
        stems = _content_stems(alt)
        if not stems:
            continue
        checked_any = True
        found = sum(1 for s in stems if any(w.startswith(s) for w in answer_words))
        if found >= math.ceil(len(stems) / 2):
            return True
    return not checked_any  # içerik kelimesi yoksa (ör. 'API') değerlendirilemez → kapsanmış say


def missing_topics(topics: list[str], answer: str) -> list[str]:
    if len(answer.strip()) < MIN_ANSWER_CHARS:
        return []  # kısa olgusal cevaplarda (ör. "Ankara") anlamsız
    return [t.strip() for t in topics if t.strip() and not topic_covered(t, answer)]
