"""Hafıza (Adım 9): kişisel hafıza + belge araması, tamamen yerel (SQLite + Ollama bge-m3)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from .book import (
    CATEGORY_LABELS,
    SENSITIVITY_LABELS,
    EmbedUnavailable,
    MemoryBook,
    MemoryError,
    MemoryItem,
    SecretRefused,
)
from .db import MemoryDB
from .documents import DocumentIndex

if TYPE_CHECKING:
    from ..runtime import Runtime

REMEMBER_RE = re.compile(r"^\s*(?:/hatırla|hatırla|unutma|aklında tut|aklında bulunsun|remember)\b[\s:,\-–]*(.+)$",
                         re.IGNORECASE | re.DOTALL)


class RecallResult(BaseModel):
    memories: list[dict[str, Any]] = Field(default_factory=list)
    documents: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def context(self) -> dict[str, Any]:
        """Modele giden bağlam parçası (yalnızca metin ve kaynak; puanlar/kimlikler değil)."""
        out: dict[str, Any] = {}
        if self.memories:
            out["memory"] = [{"text": m["text"], "category": m["category"]} for m in self.memories]
        if self.documents:
            out["documents"] = [{"source": f"{d['name']}:{d.get('loc') or d['line']}", "excerpt": d["text"]}
                                for d in self.documents]
        return out


class Memory:
    """Kişisel hafıza + belge dizini için tek giriş noktası (aynı veritabanı bağlantısını paylaşırlar)."""

    def __init__(self, rt: "Runtime"):
        self.rt = rt
        self.db = MemoryDB(rt.settings.db_path)
        self.book = MemoryBook(rt, self.db)
        self.docs = DocumentIndex(rt, self.db)

    def close(self) -> None:
        self.db.close()

    def recall(self, query: str, *, for_claude: bool = False) -> RecallResult:
        """İlgili hafıza öğeleri ve belge parçaları. for_claude: özel/gizli öğeler ve yerel belgeler dahil edilmez."""
        cfg = self.rt.settings.memory
        res = RecallResult()
        if not cfg.enabled or not query.strip():
            return res
        try:
            [qvec] = self.book.embedder.embed([query[:2000]])
        except EmbedUnavailable as exc:
            qvec = None
            res.warnings.append(f"Hafıza yalnızca kelime aramasıyla kullanıldı: {exc}")
        allowed = frozenset({"public", "personal"} if for_claude else {"public", "personal", "private"})
        for m, score in self.book.search(query, k=cfg.top_memories, query_vec=qvec, allowed=allowed):
            res.memories.append({"id": m.id, "text": m.text, "category": m.category, "sensitivity": m.sensitivity,
                                 "score": score})
        if not for_claude and cfg.top_chunks:
            from pathlib import Path

            for ch, score in self.docs.search(query, k=cfg.top_chunks, query_vec=qvec):
                res.documents.append({"chunk_id": ch.id, "path": ch.path, "name": Path(ch.path).name, "line": ch.line,
                                      "loc": ch.where,
                                      "text": ch.text, "score": score})
        return res


def remember(rt: "Runtime", text: str, *, source: str = "chat", conv_id: str | None = None
             ) -> tuple[MemoryItem | None, str, list[str]]:
    """Sahibin "hatırla" isteği: gizli bilgi kodla reddedilir; metin yerel modelle kısa nota çevrilip sınıflandırılır
    (model başarısız olursa metin olduğu gibi 'not' olarak kaydedilir). Dönüş: (öğe | None, kullanıcıya mesaj, uyarılar)."""
    from .secrets import detect_secrets

    assert rt.memory is not None
    raw = text.strip()
    kinds = detect_secrets(raw)
    if kinds:
        return None, str(SecretRefused(kinds)), []
    warnings: list[str] = []
    note_text, category, sensitivity = raw[:1000], "note", "personal"
    task = rt.orchestrator.ask(raw[:2000], worker="memory.classify")
    if task.status.value == "succeeded" and task.result:
        note_text = str(task.result.get("text") or note_text)
        category = task.result.get("category", category)
        sensitivity = task.result.get("sensitivity", sensitivity)
    else:
        warnings.append("Not yerel modelle sınıflandırılamadı; olduğu gibi 'not' olarak kaydedildi.")
    try:
        item, w = rt.memory.book.add(note_text, category=category, sensitivity=sensitivity, source=source,
                                     conv_id=conv_id)
    except SecretRefused as exc:
        return None, str(exc), warnings
    msg = (f"Hafızaya kaydettim: “{item.text}”\n\n*{CATEGORY_LABELS[item.category]} · "
           f"{SENSITIVITY_LABELS[item.sensitivity]}* — Hafıza sekmesinden düzenleyebilir ya da silebilirsin.")
    return item, msg, warnings + w


__all__ = [
    "remember",
    "CATEGORY_LABELS", "REMEMBER_RE", "SENSITIVITY_LABELS", "DocumentIndex", "EmbedUnavailable", "Memory",
    "MemoryBook", "MemoryDB", "MemoryError", "MemoryItem", "RecallResult", "SecretRefused",
]
