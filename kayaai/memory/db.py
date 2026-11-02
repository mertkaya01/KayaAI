"""Hafıza veritabanı (Adım 9): aynı `kayaai.db` dosyası, ayrı bağlantı (WAL — süreçler arası güvenli).

- `memories`: kişisel hafıza öğeleri (JSON `data`).
- `documents` / `chunks`: dizinlenen belgeler ve parçaları.
- `vectors`: (kind, item_id) → float32 vektör (bge-m3, normalize). Arama numpy ile bellekte (kişisel ölçek: on binlerce
  parça); vektörler yalnızca değiştiğinde yeniden yüklenir.
- `mem_fts`: SQLite FTS5 kelime araması (anlam aramasını tamamlar; embedding modeli yoksa tek başına çalışır).
- Adım 19b: `vectors` yerine **Qdrant** (büyük havuzlar, sunucu). Vektörler işlem boyunca biriktirilir, SQLite işlemi
  başarıyla bitince toplu gönderilir (geri alınan işlem Qdrant'a hiç gitmez). Qdrant'a ulaşılamazsa anlam araması boş
  döner, kelime araması (FTS) çalışmaya devam eder.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import logging

import numpy as np

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    status      TEXT NOT NULL,
    data        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,
    path        TEXT NOT NULL UNIQUE,
    data        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id          TEXT PRIMARY KEY,
    doc_id      TEXT NOT NULL,
    data        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
CREATE TABLE IF NOT EXISTS vectors (
    kind        TEXT NOT NULL,
    item_id     TEXT NOT NULL,
    model       TEXT NOT NULL,
    dim         INTEGER NOT NULL,
    vec         BLOB NOT NULL,
    PRIMARY KEY (kind, item_id)
);
"""
FTS_SCHEMA = ("CREATE VIRTUAL TABLE IF NOT EXISTS mem_fts USING fts5("
              "text, kind UNINDEXED, item_id UNINDEXED, tokenize='unicode61 remove_diacritics 2')")
_WORD = re.compile(r"\w{3,}", re.UNICODE)
_STOP = {"ve", "ile", "için", "bir", "bu", "şu", "the", "and", "for", "with", "what", "nedir", "nasıl", "neden",
         "hangi", "gibi", "daha", "çok", "olan", "olarak", "ama", "veya", "how", "why", "this", "that", "are", "is"}


class MemoryDB:
    def __init__(self, db_path: Path | str, vectors: Any = None):
        self.path = str(db_path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        try:
            self._conn.execute(FTS_SCHEMA)
            self.fts = True
        except sqlite3.OperationalError:  # FTS5'siz SQLite: yalnızca anlam araması
            self.fts = False
        self._cache: dict[str, tuple[int, list[str], np.ndarray]] = {}
        self.vectors = vectors            # Adım 19b: QdrantStore | None (None: SQLite + numpy)
        self._pending: list[tuple[str, str, Any]] | None = None  # (işlem, kind, veri) — commit sonrası Qdrant'a
        self.last_vector_error: str | None = None

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            self._pending = [] if self.vectors is not None else None
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                self._pending = None
                raise
            else:
                self._conn.execute("COMMIT")
                pending, self._pending = self._pending, None
                if pending:
                    self._flush(pending)

    def _flush(self, pending: list[tuple[str, str, Any]]) -> None:
        """İşlem sırasıyla Qdrant'a: ardışık ekleme/silmeler türüne göre toplanır."""
        batch: list[tuple[str, str, list[Any]]] = []
        for op, kind, data in pending:
            if batch and batch[-1][0] == op and batch[-1][1] == kind:
                batch[-1][2].extend(data)
            else:
                batch.append((op, kind, list(data)))
        try:
            for op, kind, data in batch:
                if op == "put":
                    self.vectors.upsert(kind, data)
                else:
                    self.vectors.delete(kind, data)
            self.last_vector_error = None
        except Exception as exc:
            self.last_vector_error = str(exc)[:300]
            raise

    def query(self, sql: str, args: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    # ------------------------------------------------------------------ JSON kayıtlar

    @staticmethod
    def dumps(data: dict[str, Any]) -> str:
        return json.dumps(data, ensure_ascii=False, default=str)

    # ------------------------------------------------------------------ vektörler

    def put_vector(self, c: sqlite3.Connection, kind: str, item_id: str, model: str, vec: list[float]) -> None:
        arr = np.asarray(vec, dtype=np.float32)
        n = float(np.linalg.norm(arr)) or 1.0
        arr = arr / n
        if self.vectors is not None:
            if self._pending is None:
                raise RuntimeError("put_vector yalnız tx() içinde")
            self._pending.append(("put", kind, [(item_id, model, arr.tolist())]))
            return
        c.execute("INSERT OR REPLACE INTO vectors(kind, item_id, model, dim, vec) VALUES (?, ?, ?, ?, ?)",
                  (kind, item_id, model, int(arr.shape[0]), arr.tobytes()))

    def delete_vectors(self, c: sqlite3.Connection, kind: str, ids: list[str]) -> None:
        if self.vectors is not None:
            if ids and self._pending is not None:
                self._pending.append(("delete", kind, list(ids)))
            return
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            c.execute(f"DELETE FROM vectors WHERE kind = ? AND item_id IN ({','.join('?' * len(part))})", (kind, *part))

    def _matrix(self, kind: str, model: str) -> tuple[list[str], np.ndarray]:
        with self._lock:
            stamp = self._conn.execute(
                "SELECT COUNT(*), COALESCE(MAX(rowid), 0), COALESCE(SUM(length(item_id)), 0) FROM vectors "
                "WHERE kind = ? AND model = ?", (kind, model)).fetchone()
            key = hash(tuple(stamp))
            cached = self._cache.get(f"{kind}:{model}")
            if cached and cached[0] == key:
                return cached[1], cached[2]
            rows = self._conn.execute("SELECT item_id, dim, vec FROM vectors WHERE kind = ? AND model = ?",
                                      (kind, model)).fetchall()
        if not rows:
            mat = np.zeros((0, 1), dtype=np.float32)
            ids: list[str] = []
        else:
            dim = rows[0]["dim"]
            rows = [r for r in rows if r["dim"] == dim]
            ids = [r["item_id"] for r in rows]
            mat = np.frombuffer(b"".join(r["vec"] for r in rows), dtype=np.float32).reshape(len(rows), dim)
        self._cache[f"{kind}:{model}"] = (key, ids, mat)
        return ids, mat

    def nearest(self, kind: str, model: str, query: list[float], k: int) -> list[tuple[str, float]]:
        if self.vectors is not None:
            try:
                out = self.vectors.search(kind, model, query, k)
                self.last_vector_error = None
                return out
            except Exception as exc:  # noqa: BLE001 - Qdrant kapalıysa kelime araması yine çalışır
                self.last_vector_error = str(exc)[:300]
                log.warning("Qdrant araması başarısız (kelime aramasıyla devam): %s", exc)
                return []
        ids, mat = self._matrix(kind, model)
        if not ids:
            return []
        q = np.asarray(query, dtype=np.float32)
        if q.shape[0] != mat.shape[1]:
            return []  # model/boyut değişti: yeniden dizinlenmeli
        q = q / (float(np.linalg.norm(q)) or 1.0)
        scores = mat @ q
        top = np.argsort(-scores)[:k]
        return [(ids[i], float(scores[i])) for i in top]

    def sqlite_vectors(self, batch: int = 500) -> Iterator[list[tuple[str, str, str, list[float]]]]:
        """SQLite'taki vektörler (kind, item_id, model, vektör) — Qdrant'a taşımak için, parça parça."""
        last = 0
        while True:
            rows = self.query("SELECT rowid, kind, item_id, model, dim, vec FROM vectors WHERE rowid > ? ORDER BY rowid LIMIT ?",
                              (last, batch))
            if not rows:
                return
            last = rows[-1]["rowid"]
            yield [(r["kind"], r["item_id"], r["model"], np.frombuffer(r["vec"], dtype=np.float32).tolist()) for r in rows]

    def vector_ids(self, kind: str, model: str) -> set[str]:
        return {r["item_id"] for r in self.query("SELECT item_id FROM vectors WHERE kind = ? AND model = ?", (kind, model))}

    # ------------------------------------------------------------------ kelime araması

    def put_text(self, c: sqlite3.Connection, kind: str, item_id: str, text: str) -> None:
        if not self.fts:
            return
        c.execute("DELETE FROM mem_fts WHERE kind = ? AND item_id = ?", (kind, item_id))
        c.execute("INSERT INTO mem_fts(text, kind, item_id) VALUES (?, ?, ?)", (text, kind, item_id))

    def delete_texts(self, c: sqlite3.Connection, kind: str, ids: list[str]) -> None:
        if not self.fts:
            return
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            c.execute(f"DELETE FROM mem_fts WHERE kind = ? AND item_id IN ({','.join('?' * len(part))})", (kind, *part))

    def keyword(self, kind: str, query: str, k: int) -> list[str]:
        """Kelime araması: Türkçe ekler için 5 harflik önek eşleşmesi (ör. 'toplantı' → 'toplantılar')."""
        if not self.fts:
            return []
        words = [w.lower() for w in _WORD.findall(query) if w.lower() not in _STOP]
        terms = list(dict.fromkeys(f'"{w[:5]}"*' for w in words if '"' not in w))[:12]
        if not terms:
            return []
        try:
            rows = self.query("SELECT item_id FROM mem_fts WHERE mem_fts MATCH ? AND kind = ? ORDER BY rank LIMIT ?",
                              (" OR ".join(terms), kind, k))
        except sqlite3.OperationalError:
            return []
        return [r["item_id"] for r in rows]
