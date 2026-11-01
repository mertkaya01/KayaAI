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


def scan_secrets(rt: "Runtime", *, fix: bool = False) -> dict[str, Any]:
    """Kayıtlı hafıza öğelerini ve belge parçalarını GÜNCEL gizli bilgi kurallarıyla yeniden tarar (kurallar
    genişleyince eski kayıtlar için). Metin döndürülmez, yalnız id/tür/dosya.

    fix=True: (1) eşleşen hafıza öğeleri "gizli" yapılır → hiçbir bağlama girmez (silinmez; silmek sahibin kararı);
    (2) eşleşen belge parçaları dizinden çıkarılır (yalnız türetilmiş dizin; dosyalara dokunulmaz).
    """
    from .documents import Chunk, DocInfo
    from .secrets import detect_secrets

    assert rt.memory is not None
    mem = rt.memory
    items = []
    for m in mem.book.list():
        if m.sensitivity == "secret":
            continue
        kinds = detect_secrets(m.text)
        if kinds:
            items.append({"id": m.id, "kinds": kinds, "status": m.status})
            if fix:
                m.sensitivity, m.secret_kinds = "secret", kinds
                mem.book._save(m)
    by_doc: dict[str, list[str]] = {}
    for r in mem.db.query("SELECT data FROM chunks"):
        ch = Chunk.model_validate_json(r["data"])
        if detect_secrets(ch.text, strict=False):
            by_doc.setdefault(ch.doc_id, []).append(ch.id)
    docs = []
    for doc_id, ids in by_doc.items():
        rows = mem.db.query("SELECT data FROM documents WHERE id = ?", (doc_id,))
        doc = DocInfo.model_validate_json(rows[0]["data"]) if rows else None
        docs.append({"path": doc.path if doc else doc_id, "chunks": len(ids)})
        if fix:
            with mem.db.tx() as c:
                mem.db.delete_vectors(c, "chunk", ids)
                mem.db.delete_texts(c, "chunk", ids)
                c.executemany("DELETE FROM chunks WHERE id = ?", [(i,) for i in ids])
                if doc:
                    doc.chunks = max(0, doc.chunks - len(ids))
                    doc.skipped_secret_chunks += len(ids)
                    c.execute("UPDATE documents SET data = ? WHERE id = ?",
                              (mem.db.dumps(doc.model_dump(mode="json")), doc.id))
    if fix and (items or docs):
        rt.store.emit("memory.secrets_fixed", {"items": len(items), "chunks": sum(d["chunks"] for d in docs)})
    return {"items": items, "documents": docs, "fixed": fix}
