"""Kişisel hafıza (Adım 9, MASTER_PROMPT v2 §7).

- Her öğenin bir kategorisi (preference, project, decision, instruction, file, note) ve hassasiyeti
  (public, personal, private, secret) vardır.
- **secret**: açık izin (`allow_secret=True`, yalnızca sahip — Hafıza ekranı/CLI) olmadan SAKLANMAZ; gizli bilgi
  kalıbı görülen metin otomatik "secret" sayılır. Secret öğeler hiçbir bağlama otomatik girmez.
- **private**: yerel ajanların bağlamına girer, Claude'a giden bağlama (devretme, MCP) GİRMEZ.
- Claude ya da bir ajan yalnızca **öneri** (status=proposed) ekleyebilir; sahip onaylayınca etkinleşir.
- Vektörler yerelde (Ollama, bge-m3). Model yoksa öğe yine kaydedilir, kelime aramasıyla bulunur; model kurulunca
  `reindex()` eksik vektörleri tamamlar.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from ..core.task import utcnow
from ..llm.ollama_client import OllamaError, OllamaModelNotFound
from .db import MemoryDB
from .secrets import detect_secrets

if TYPE_CHECKING:
    from ..runtime import Runtime

Category = Literal["preference", "project", "decision", "instruction", "file", "note"]
Sensitivity = Literal["public", "personal", "private", "secret"]
MAX_TEXT = 1000
CATEGORY_LABELS = {"preference": "tercih", "project": "proje", "decision": "karar", "instruction": "talimat",
                   "file": "dosya", "note": "not"}
SENSITIVITY_LABELS = {"public": "herkese açık", "personal": "kişisel", "private": "özel", "secret": "gizli"}


class MemoryError(ValueError):  # noqa: A001 - modül içi ad
    pass


class SecretRefused(MemoryError):
    def __init__(self, kinds: list[str]):
        super().__init__(
            "Bu metin gizli bilgi içeriyor gibi görünüyor (" + ", ".join(kinds) + "). Gizli bilgiler açık izin olmadan "
            "saklanmaz; gerçekten saklamak istiyorsan Hafıza ekranından 'gizli olarak kaydet' ile ekle.")
        self.kinds = kinds


class EmbedUnavailable(MemoryError):
    pass


class MemoryItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    text: str
    category: Category = "note"
    sensitivity: Sensitivity = "personal"
    status: Literal["active", "proposed"] = "active"
    source: str = "owner"                 # owner | chat | claude | agent:<ad>
    conv_id: str | None = None
    embedded: bool = False
    secret_kinds: list[str] = Field(default_factory=list)


class Embedder:
    """Ollama embedding sarmalayıcısı (model: settings.memory.embed_model → config/models.yaml)."""

    def __init__(self, rt: "Runtime"):
        self.rt = rt
        self.spec = rt.registry.get(rt.settings.memory.embed_model)

    @property
    def model(self) -> str:
        return self.spec.name

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            return self.rt.llm.embed(self.spec.name, texts, keep_alive=self.spec.keep_alive, timeout=120)
        except OllamaModelNotFound as exc:
            raise EmbedUnavailable(f"'{self.spec.name}' kurulu değil — kurmak için: ollama pull {self.spec.name}") from exc
        except OllamaError as exc:
            raise EmbedUnavailable(f"Vektör hesaplanamadı: {exc}") from exc


class MemoryBook:
    def __init__(self, rt: "Runtime", db: MemoryDB | None = None):
        self.rt = rt
        self.db = db or MemoryDB(rt.settings.db_path)
        self.embedder = Embedder(rt)

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------------ kayıt

    def _save(self, m: MemoryItem) -> None:
        with self.db.tx() as c:
            c.execute("INSERT OR REPLACE INTO memories(id, created_at, status, data) VALUES (?, ?, ?, ?)",
                      (m.id, m.created_at.isoformat(), m.status, self.db.dumps(m.model_dump(mode="json"))))

    def _index(self, m: MemoryItem) -> list[str]:
        """Kelime + vektör dizini. Vektör hatası kaydı engellemez (uyarı döner)."""
        warnings: list[str] = []
        with self.db.tx() as c:
            self.db.put_text(c, "memory", m.id, m.text)
        try:
            [vec] = self.embedder.embed([m.text])
            with self.db.tx() as c:
                self.db.put_vector(c, "memory", m.id, self.embedder.model, vec)
            m.embedded = True
        except EmbedUnavailable as exc:
            m.embedded = False
            warnings.append(f"Anlam araması için vektör hesaplanamadı ({exc}); kelime aramasıyla bulunur.")
        self._save(m)
        return warnings

    def add(self, text: str, *, category: Category = "note", sensitivity: Sensitivity = "personal",
            source: str = "owner", conv_id: str | None = None, allow_secret: bool = False,
            status: Literal["active", "proposed"] = "active") -> tuple[MemoryItem, list[str]]:
        text = (text or "").strip()
        if not text:
            raise MemoryError("Hafıza metni boş olamaz")
        if len(text) > MAX_TEXT:
            raise MemoryError(f"Hafıza öğesi en fazla {MAX_TEXT} karakter olabilir (uzun metinleri dosya olarak ekle)")
        kinds = detect_secrets(text)
        if kinds:
            sensitivity = "secret"
        if sensitivity == "secret" and not allow_secret:
            raise SecretRefused(kinds or ["gizli olarak işaretlendi"])
        m = MemoryItem(text=text, category=category, sensitivity=sensitivity, source=source, conv_id=conv_id,
                       status=status, secret_kinds=kinds)
        warnings = self._index(m)
        self.rt.store.emit("memory.added", {"id": m.id, "category": m.category, "sensitivity": m.sensitivity,
                                            "status": m.status, "source": source})
        return m, warnings

    def propose(self, text: str, *, category: Category = "note", sensitivity: Sensitivity = "personal",
                source: str = "claude", conv_id: str | None = None) -> tuple[MemoryItem, list[str]]:
        """Claude/ajan önerisi: sahip onaylayana kadar hiçbir bağlama girmez. Gizli bilgi önerilemez."""
        if sensitivity == "secret" or detect_secrets(text):
            raise SecretRefused(detect_secrets(text) or ["gizli"])
        return self.add(text, category=category, sensitivity=sensitivity, source=source, conv_id=conv_id,
                        status="proposed")

    def get(self, mem_id: str) -> MemoryItem:
        rows = self.db.query("SELECT data FROM memories WHERE id = ?", (mem_id,))
        if not rows:
            raise MemoryError(f"Hafıza öğesi bulunamadı: {mem_id}")
        return MemoryItem.model_validate_json(rows[0]["data"])

    def list(self, status: str | None = None) -> list[MemoryItem]:
        sql, args = "SELECT data FROM memories", ()
        if status:
            sql, args = sql + " WHERE status = ?", (status,)
        items = [MemoryItem.model_validate_json(r["data"]) for r in self.db.query(sql + " ORDER BY created_at DESC", args)]
        return items

    def update(self, mem_id: str, *, text: str | None = None, category: Category | None = None,
               sensitivity: Sensitivity | None = None, allow_secret: bool = False) -> tuple[MemoryItem, list[str]]:
        m = self.get(mem_id)
        if text is not None:
            text = text.strip()
            if not text or len(text) > MAX_TEXT:
                raise MemoryError(f"Metin 1-{MAX_TEXT} karakter olmalı")
            m.text = text
        if category is not None:
            m.category = category
        if sensitivity is not None:
            m.sensitivity = sensitivity
        kinds = detect_secrets(m.text)
        if kinds:
            m.sensitivity = "secret"
        if m.sensitivity == "secret" and not allow_secret:
            raise SecretRefused(kinds or ["gizli olarak işaretlendi"])
        m.secret_kinds, m.updated_at = kinds, utcnow()
        warnings = self._index(m)
        self.rt.store.emit("memory.updated", {"id": m.id})
        return m, warnings

    def approve(self, mem_id: str) -> MemoryItem:
        m = self.get(mem_id)
        if m.status != "proposed":
            raise MemoryError("Bu öğe zaten etkin")
        m.status, m.updated_at = "active", utcnow()
        self._save(m)
        self.rt.store.emit("memory.updated", {"id": m.id, "status": "active"})
        return m

    def delete(self, mem_id: str) -> None:
        self.get(mem_id)
        with self.db.tx() as c:
            c.execute("DELETE FROM memories WHERE id = ?", (mem_id,))
            self.db.delete_vectors(c, "memory", [mem_id])
            self.db.delete_texts(c, "memory", [mem_id])
        self.rt.store.emit("memory.deleted", {"id": mem_id})

    def export(self) -> list[dict[str, Any]]:
        return [m.model_dump(mode="json") for m in self.list()]

    def reindex(self) -> int:
        """Vektörü eksik öğeleri tamamlar (ör. bge-m3 sonradan kuruldu). Tamamlanan öğe sayısı."""
        missing = [m for m in self.list() if not m.embedded]
        if not missing:
            return 0
        vecs = self.embedder.embed([m.text for m in missing])
        with self.db.tx() as c:
            for m, v in zip(missing, vecs):
                self.db.put_vector(c, "memory", m.id, self.embedder.model, v)
        for m in missing:
            m.embedded = True
            self._save(m)
        return len(missing)

    # ------------------------------------------------------------------ arama

    def search(self, query: str, *, k: int = 5, query_vec: list[float] | None = None, min_score: float | None = None,
               allowed: frozenset[str] = frozenset({"public", "personal", "private"}),
               include_proposed: bool = False) -> list[tuple[MemoryItem, float]]:
        """Anlam (vektör) + kelime araması. Secret öğeler `allowed` içinde verilmedikçe dönmez."""
        threshold = self.rt.settings.memory.min_score_memory if min_score is None else min_score
        scores: dict[str, float] = {}
        if query_vec is not None:
            for mid, s in self.db.nearest("memory", self.embedder.model, query_vec, 50):
                scores[mid] = s
        keyword = set(self.db.keyword("memory", query, 50))
        out: list[tuple[MemoryItem, float]] = []
        for mid in set(scores) | keyword:
            s = scores.get(mid)
            if s is None:
                s = 0.5 if query_vec is None else threshold  # yalnızca kelime eşleşmesi: eşik düzeyinde say
            elif mid in keyword:
                s += 0.05
            if s < threshold:
                continue
            try:
                m = self.get(mid)
            except MemoryError:
                continue
            if m.sensitivity not in allowed or (m.status != "active" and not include_proposed):
                continue
            out.append((m, round(s, 4)))
        out.sort(key=lambda x: -x[1])
        return out[:k]
