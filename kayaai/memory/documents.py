"""Belge araması / RAG (Adım 9): izinli klasörlerdeki metin dosyaları parçalanır, yerelde vektörlenir, aranır.

- Kökler: dosya araçlarının kökleri (`~/kayaAI-files` + `files.allowed_dirs`) — başka hiçbir yer dizinlenmez; her dosya
  yolu `FileTools.resolve` ile yeniden doğrulanır (köke dışarı çıkan sembolik bağlantılar atlanır).
- Gizli bilgi taşıyabilecek dosyalar (`.env`, `*.key`, `id_rsa*` …) ve açık gizli bilgi kalıbı geçen PARÇALAR dizine
  girmez. İkili dosyalar ve sınırı aşanlar atlanır. PDF/Word Adım 10'da.
- Artımlı: değişmeyen dosyalar (boyut + değişiklik zamanı + vektör var) yeniden işlenmez; silinen dosyalar dizinden çıkar.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from ..core.task import utcnow
from ..tools.files import TEXT_SUFFIXES, PathNotAllowed, roots
from .book import EmbedUnavailable, Embedder
from .db import MemoryDB
from .secrets import detect_secrets

if TYPE_CHECKING:
    from ..runtime import Runtime

EMBED_BATCH = 16


class DocInfo(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    path: str
    root: str
    size: int
    mtime: float
    sha1: str
    chunks: int = 0
    skipped_secret_chunks: int = 0
    embedded: bool = False
    indexed_at: datetime = Field(default_factory=utcnow)


class Chunk(BaseModel):
    id: str
    doc_id: str
    path: str
    line: int
    text: str


class IndexReport(BaseModel):
    roots: list[str]
    scanned: int = 0
    indexed: int = 0
    unchanged: int = 0
    removed: int = 0
    skipped: dict[str, int] = Field(default_factory=dict)
    chunks_total: int = 0
    secret_chunks_skipped: int = 0
    embed_available: bool = True
    errors: list[str] = Field(default_factory=list)
    duration_s: float = 0.0


def chunk_text(text: str, size: int, overlap: int) -> list[tuple[int, str]]:
    """Satır sınırında parçalar: (başlangıç satırı, metin). Çok uzun satırlar bölünür; bitişik parçalar `overlap`
    karakter kadar örtüşür (bağlam kopmasın)."""
    lines = text.replace("\r\n", "\n").split("\n")
    out: list[tuple[int, str]] = []
    buf: list[tuple[int, str]] = []
    length = 0

    def flush() -> None:
        nonlocal buf, length
        body = "\n".join(t for _, t in buf).strip()
        if body:
            out.append((buf[0][0], body))
        keep: list[tuple[int, str]] = []
        kept = 0
        for ln, t in reversed(buf):
            if kept + len(t) > overlap:
                break
            keep.insert(0, (ln, t))
            kept += len(t) + 1
        buf, length = keep, kept

    for no, line in enumerate(lines, 1):
        while len(line) > size:
            if buf:
                flush()
            out.append((no, line[:size]))
            line = line[size - overlap:] if overlap < size else line[size:]
        if length + len(line) + 1 > size and buf:
            flush()
        buf.append((no, line))
        length += len(line) + 1
    if buf and "\n".join(t for _, t in buf).strip():
        body = "\n".join(t for _, t in buf).strip()
        if not out or out[-1][1] != body:
            out.append((buf[0][0], body))
    return out


class DocumentIndex:
    def __init__(self, rt: "Runtime", db: MemoryDB | None = None):
        self.rt = rt
        self.settings = rt.settings.memory
        self.db = db or MemoryDB(rt.settings.db_path)
        self.embedder = Embedder(rt)

    # ------------------------------------------------------------------ tarama

    def _skip_file(self, name: str) -> bool:
        low = name.lower()
        return any(fnmatch.fnmatch(low, pat.lower()) for pat in self.settings.skip_files)

    def _walk(self, report: IndexReport) -> list[tuple[Path, str]]:
        found: list[tuple[Path, str]] = []
        skip_dirs = {d.lower() for d in self.settings.skip_dirs}
        limit = int(self.settings.max_file_mb * 1024 * 1024)

        def skip(reason: str) -> None:
            report.skipped[reason] = report.skipped.get(reason, 0) + 1

        for root in roots(self.rt.settings):
            if not root.path.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(root.path):
                dirnames[:] = [d for d in dirnames if d.lower() not in skip_dirs and not d.startswith(".")]
                for name in filenames:
                    p = Path(dirpath) / name
                    if self._skip_file(name):
                        skip("gizli bilgi taşıyabilir (dosya adı)")
                        continue
                    if p.suffix.lower() not in TEXT_SUFFIXES:
                        skip("desteklenmeyen tür")
                        continue
                    try:
                        resolved, _ = self.rt.files.resolve(str(p))  # type: ignore[union-attr]
                    except PathNotAllowed:
                        skip("izinli klasör dışına çıkıyor")
                        continue
                    try:
                        if resolved.stat().st_size > limit:
                            skip("çok büyük")
                            continue
                    except OSError:
                        continue
                    found.append((resolved, str(root.path)))
                    if len(found) >= self.settings.max_files:
                        report.errors.append(f"Dosya sınırına ulaşıldı ({self.settings.max_files}); kalanlar atlandı")
                        return found
        return found

    def _doc(self, path: str) -> DocInfo | None:
        rows = self.db.query("SELECT data FROM documents WHERE path = ?", (path,))
        return DocInfo.model_validate_json(rows[0]["data"]) if rows else None

    def _remove(self, doc: DocInfo) -> None:
        ids = [r["id"] for r in self.db.query("SELECT id FROM chunks WHERE doc_id = ?", (doc.id,))]
        with self.db.tx() as c:
            self.db.delete_vectors(c, "chunk", ids)
            self.db.delete_texts(c, "chunk", ids)
            c.execute("DELETE FROM chunks WHERE doc_id = ?", (doc.id,))
            c.execute("DELETE FROM documents WHERE id = ?", (doc.id,))

    # ------------------------------------------------------------------ dizinleme

    def index(self) -> IndexReport:
        t0 = time.perf_counter()
        report = IndexReport(roots=[str(r.path) for r in roots(self.rt.settings)])
        files = self._walk(report)
        report.scanned = len(files)
        seen: set[str] = set()
        embed_ok = True
        for path, root in files:
            key = str(path)
            seen.add(key)
            try:
                st = path.stat()
                old = self._doc(key)
                if old and old.size == st.st_size and old.mtime == st.st_mtime and (old.embedded or not embed_ok):
                    report.unchanged += 1
                    continue
                raw = path.read_bytes()
                if b"\x00" in raw[:4096]:
                    report.skipped["ikili içerik"] = report.skipped.get("ikili içerik", 0) + 1
                    continue
                sha1 = hashlib.sha1(raw).hexdigest()
                if old and old.sha1 == sha1 and (old.embedded or not embed_ok):
                    old.mtime, old.size = st.st_mtime, st.st_size
                    with self.db.tx() as c:
                        c.execute("UPDATE documents SET data = ? WHERE id = ?", (self.db.dumps(old.model_dump(mode="json")), old.id))
                    report.unchanged += 1
                    continue
                embed_ok = self._index_file(path, root, raw.decode("utf-8", errors="replace"), st, sha1, old, report) and embed_ok
                report.indexed += 1
            except OSError as exc:
                report.errors.append(f"{path}: {exc}")
        for row in self.db.query("SELECT data FROM documents"):
            doc = DocInfo.model_validate_json(row["data"])
            if doc.path not in seen:
                self._remove(doc)
                report.removed += 1
        report.chunks_total = int(self.db.query("SELECT COUNT(*) AS n FROM chunks")[0]["n"])
        report.embed_available = embed_ok
        report.duration_s = round(time.perf_counter() - t0, 2)
        self.rt.store.emit("memory.indexed", {"indexed": report.indexed, "removed": report.removed,
                                              "chunks": report.chunks_total, "embed_available": embed_ok})
        return report

    def _index_file(self, path: Path, root: str, text: str, st: os.stat_result, sha1: str, old: DocInfo | None,
                    report: IndexReport) -> bool:
        pieces = chunk_text(text, self.settings.chunk_chars, self.settings.chunk_overlap)
        kept: list[tuple[int, str]] = []
        secret = 0
        for line, body in pieces:
            if detect_secrets(body, strict=False):
                secret += 1
                continue
            kept.append((line, body))
        report.secret_chunks_skipped += secret
        doc = DocInfo(id=old.id if old else uuid.uuid4().hex[:12], path=str(path), root=root, size=st.st_size,
                      mtime=st.st_mtime, sha1=sha1, chunks=len(kept), skipped_secret_chunks=secret)
        if old:
            self._remove(old)
        chunks = [Chunk(id=f"{doc.id}-{i}", doc_id=doc.id, path=str(path), line=line, text=body)
                  for i, (line, body) in enumerate(kept)]
        vectors: list[list[float]] = []
        embedded = True
        try:
            for i in range(0, len(chunks), EMBED_BATCH):
                vectors += self.embedder.embed([f"{path.name}\n{c.text}" for c in chunks[i:i + EMBED_BATCH]])
        except EmbedUnavailable as exc:
            embedded = False
            if str(exc) not in report.errors:
                report.errors.append(str(exc))
        doc.embedded = embedded
        with self.db.tx() as c:
            c.execute("INSERT OR REPLACE INTO documents(id, path, data) VALUES (?, ?, ?)",
                      (doc.id, doc.path, self.db.dumps(doc.model_dump(mode="json"))))
            for i, ch in enumerate(chunks):
                c.execute("INSERT OR REPLACE INTO chunks(id, doc_id, data) VALUES (?, ?, ?)",
                          (ch.id, doc.id, self.db.dumps(ch.model_dump(mode="json"))))
                self.db.put_text(c, "chunk", ch.id, f"{path.name}\n{ch.text}")
                if embedded:
                    self.db.put_vector(c, "chunk", ch.id, self.embedder.model, vectors[i])
        return embedded

    # ------------------------------------------------------------------ arama / durum

    def chunk(self, chunk_id: str) -> Chunk | None:
        rows = self.db.query("SELECT data FROM chunks WHERE id = ?", (chunk_id,))
        return Chunk.model_validate_json(rows[0]["data"]) if rows else None

    def search(self, query: str, *, k: int = 4, query_vec: list[float] | None = None,
               min_score: float | None = None) -> list[tuple[Chunk, float]]:
        threshold = self.settings.min_score if min_score is None else min_score
        scores: dict[str, float] = {}
        if query_vec is not None:
            scores = dict(self.db.nearest("chunk", self.embedder.model, query_vec, 50))
        keyword = set(self.db.keyword("chunk", query, 50))
        out: list[tuple[Chunk, float]] = []
        for cid in set(scores) | keyword:
            s = scores.get(cid)
            if s is None:
                s = 0.5 if query_vec is None else threshold
            elif cid in keyword:
                s += 0.05
            if s < threshold:
                continue
            ch = self.chunk(cid)
            if ch is not None:
                out.append((ch, round(s, 4)))
        out.sort(key=lambda x: -x[1])
        return out[:k]

    def documents(self) -> list[DocInfo]:
        return sorted((DocInfo.model_validate_json(r["data"]) for r in self.db.query("SELECT data FROM documents")),
                      key=lambda d: d.path.lower())

    def status(self) -> dict[str, Any]:
        docs = self.documents()
        return {
            "roots": [str(r.path) for r in roots(self.rt.settings)],
            "documents": len(docs),
            "chunks": int(self.db.query("SELECT COUNT(*) AS n FROM chunks")[0]["n"]),
            "not_embedded": sum(1 for d in docs if not d.embedded),
            "last_indexed": max((d.indexed_at for d in docs), default=None),
            "embed_model": self.embedder.model,
        }
