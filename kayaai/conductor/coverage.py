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
# Konu değil TALİMAT/BİÇİM bildiren kelimeler. Gerçek yanlış alarm (Windows, 2026-10-31): "e-posta yazma / email
# writing" konusu, cevabın kendisi bir e-posta olduğu hâlde "değinilmedi" sayıldı.
_INSTRUCTION = {
    "yaz", "yazma", "yazmak", "yazımı", "yazılması", "write", "writing", "written",
    "e", "posta", "eposta", "email", "mail", "mektup", "letter", "mesaj", "message",
    "açıkla", "açıklama", "açıklaması", "explain", "explanation", "özet", "özetle", "özetleme", "summary", "summarize",
    "çeviri", "çevir", "translate", "translation", "metin", "metni", "text", "kısa", "short", "resmi", "formal",
    "oluştur", "oluşturma", "create", "hazırla", "hazırlama", "prepare", "düzenle", "düzenleme", "edit",
    "yeniden", "rewrite", "cevap", "answer", "yanıt", "response",
}
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


def is_instruction_topic(topic: str) -> bool:
    """Konunun tüm alternatifleri yalnızca talimat/biçim kelimelerinden oluşuyorsa (ör. 'e-posta yazma') True."""
    for alt in (a for a in _SPLIT_ALTERNATIVES.split(topic) if a.strip()):
        words = [w.strip("'") for w in _WORD_RE.findall(_normalize(alt.replace("-", " ")))]
        content = [w for w in words if w and w not in _TR_STOP and w not in _EN_STOP and w not in _GENERIC]
        if any(w not in _INSTRUCTION for w in content):
            return False
    return True


def missing_topics(topics: list[str], answer: str) -> list[str]:
    if len(answer.strip()) < MIN_ANSWER_CHARS:
        return []  # kısa olgusal cevaplarda (ör. "Ankara") anlamsız
    return [t.strip() for t in topics
            if t.strip() and not is_instruction_topic(t) and not topic_covered(t, answer)]
