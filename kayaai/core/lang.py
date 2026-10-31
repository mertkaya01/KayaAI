"""Hafif Türkçe/İngilizce dil tespiti (yalnızca stdlib).

Amaç model çıktısını DOĞRULAMAK: "İngilizce soruya Türkçe cevap" gibi hataları yakalamak.
Genel amaçlı bir dil tanıyıcı değildir; emin olmadığında "other" döner ve o durumda
doğrulama hata vermez (yanlış alarm yerine sessiz kalmak tercih edilir).
"""

from __future__ import annotations

import re
from typing import Literal

Lang = Literal["tr", "en", "other"]

_TR_CHARS = set("çğıöşü")
_TR_STOP = {
    "ve", "bir", "bu", "şu", "için", "ile", "de", "da", "mi", "mı", "mu", "mü", "ne", "nasıl",
    "neden", "nedir", "hangi", "değil", "çok", "daha", "gibi", "olarak", "var", "yok", "ama",
    "en", "ben", "sen", "biz", "siz", "onlar", "kadar", "sonra", "önce", "her", "ki", "veya",
    "ya", "ise", "olan", "olur", "iki", "üç", "bana", "sana", "şey", "artık", "hem", "yani",
}
_EN_STOP = {
    "the", "and", "is", "are", "was", "were", "of", "to", "in", "for", "with", "what", "how",
    "why", "this", "that", "it", "you", "your", "a", "an", "be", "on", "as", "by", "can", "do",
    "does", "from", "or", "not", "will", "would", "should", "my", "i", "we", "they", "their",
    "have", "has", "if", "about", "into", "only", "please", "which", "when", "there", "these",
}
# Kullanıcı açıkça bir hedef dil / çeviri istiyorsa beklenen dil soru dili DEĞİLDİR.
_TARGET_LANG_RE = re.compile(
    r"(çevir|tercüme|translat|ingilizce|türkçe|almanca|fransızca|ispanyolca|rusça|arapça|"
    r"\benglish\b|\bturkish\b|\bgerman\b|\bfrench\b|\bspanish\b|\bin\s+\w+\s+language\b)",
    re.IGNORECASE,
)
_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_WORD_RE = re.compile(r"[a-zçğıöşüâîû']+")


def _normalize(text: str) -> str:
    text = _CODE_BLOCK_RE.sub(" ", text)
    text = _INLINE_CODE_RE.sub(" ", text)
    # Türkçe büyük harfleri doğru küçült ("İ"->"i", "I"->"ı" yapılmaz: İngilizce "I" bozulur).
    return text.replace("İ", "i").lower().replace("̇", "")


def language_scores(text: str) -> dict[str, int]:
    words = _WORD_RE.findall(_normalize(text))
    tr = sum(1 for w in words if w in _TR_STOP) + sum(1 for w in words if _TR_CHARS & set(w))
    en = sum(1 for w in words if w in _EN_STOP)
    return {"tr": tr, "en": en, "words": len(words)}


def detect_language(text: str) -> Lang:
    s = language_scores(text)
    tr, en = s["tr"], s["en"]
    if tr == en:  # 0-0 dahil: belirsiz
        return "other"
    if s["words"] < 3 and max(tr, en) < 2:
        return "other"  # çok kısa metin: tek bir sinyal yetmez (ör. tek harf "a" İngilizce sayılıyordu)
    winner, loser = (("tr", tr), en) if tr > en else (("en", en), tr)
    # Karışık metinde açık bir üstünlük iste.
    if loser and winner[1] < 2 * loser:
        return "other"
    return winner[0]  # type: ignore[return-value]


def mentions_target_language(text: str) -> bool:
    return bool(_TARGET_LANG_RE.search(text))


def expected_answer_language(question: str) -> Lang:
    """Cevabın hangi dilde olması gerektiği; çeviri/hedef dil istenmişse 'other' (kontrol yok)."""
    if mentions_target_language(question):
        return "other"
    return detect_language(question)


LANGUAGE_NAMES = {"tr": "Turkish", "en": "English"}

# Çince/Japonca/Korece yazı. Gerçek gözlem (Windows, 2026-10-31): qwen3:8b Türkçe bir e-postanın ortasına
# "造成的" yazdı. İstekte (ve girdide) bu yazı yoksa cevapta da olamaz.
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff]")
_CJK_LANG_RE = re.compile(r"(çince|japonca|korece|chinese|japanese|korean|mandarin|kanji)", re.IGNORECASE)


def foreign_script(answer: str, request: str) -> str:
    """İstekte olmayan Çince/Japonca/Korece karakterler (cevapta geçtikleri sırayla, tekrarsız). Boşsa sorun yok."""
    if _CJK_RE.search(request) or _CJK_LANG_RE.search(request):
        return ""  # kullanıcı bu yazıyı kendisi kullandı ya da o dili istedi
    return "".join(dict.fromkeys(_CJK_RE.findall(answer)))


def strip_code(text: str) -> str:
    """Kod bloklarını ve satır içi kodu çıkarır (düzyazının dilini ölçmek için)."""
    return _INLINE_CODE_RE.sub(" ", _CODE_BLOCK_RE.sub(" ", text))
