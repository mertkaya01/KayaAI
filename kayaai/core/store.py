"""SQLite tabanlı kalıcı görev geçmişi ve olay günlüğü.

Yeniden başlatmada geçmiş korunur. Süreç çökerken "running" kalmış görevler
`recover_interrupted()` ile dürüstçe "failed (interrupted)" olarak işaretlenir;
asla başarılı sayılmaz.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .task import Task, TaskStatus, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    worker      TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    data        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

CREATE TABLE IF NOT EXISTS task_events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id  TEXT NOT NULL,
    ts       TEXT NOT NULL,
    event    TEXT NOT NULL,
    detail   TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_task ON task_events(task_id);

CREATE TABLE IF NOT EXISTS events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL,
    type     TEXT NOT NULL,
    task_id  TEXT,
    data     TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    status      TEXT NOT NULL,
    risk        TEXT NOT NULL,
    tool        TEXT NOT NULL,
    data        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);

CREATE TABLE IF NOT EXISTS disputes (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    status      TEXT NOT NULL,
    job_id      TEXT,
    data        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_disputes_status ON disputes(status);
CREATE INDEX IF NOT EXISTS idx_disputes_job ON disputes(job_id);

CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    data        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at);

CREATE TABLE IF NOT EXISTS messages (
    id          TEXT PRIMARY KEY,
    conv_id     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    status      TEXT NOT NULL,
    data        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conv_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status);

CREATE TABLE IF NOT EXISTS attachments (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    data        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""
SCHEMA_VERSION = "1"


class TaskStore:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        if str(db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,)
        )

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ meta (anahtar/değer)

    def get_meta(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    # ------------------------------------------------------------------ onay kuyruğu (Adım 5)

    def save_approval(self, approval_id: str, created_at: str, status: str, risk: str, tool: str,
                      data: dict[str, Any]) -> None:
        with self._tx() as c:
            c.execute(
                """INSERT INTO approvals(id, created_at, status, risk, tool, data) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET status=excluded.status, data=excluded.data""",
                (approval_id, created_at, status, risk, tool, json.dumps(data, ensure_ascii=False, default=str)),
            )

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT data FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        return json.loads(row["data"]) if row else None

    def list_approvals(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql, args = "SELECT data FROM approvals", ()
        if status:
            sql, args = sql + " WHERE status = ?", (status,)
        with self._lock:
            rows = self._conn.execute(sql + " ORDER BY created_at DESC LIMIT ?", (*args, limit)).fetchall()
        return [json.loads(r["data"]) for r in rows]

    # ------------------------------------------------------------------ anlaşmazlıklar (Adım 7)

    def save_dispute(self, dispute_id: str, created_at: str, status: str, job_id: str | None,
                     data: dict[str, Any]) -> None:
        with self._tx() as c:
            c.execute(
                """INSERT INTO disputes(id, created_at, status, job_id, data) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET status=excluded.status, data=excluded.data""",
                (dispute_id, created_at, status, job_id, json.dumps(data, ensure_ascii=False, default=str)),
            )

    def get_dispute(self, dispute_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT data FROM disputes WHERE id = ?", (dispute_id,)).fetchone()
        return json.loads(row["data"]) if row else None

    def list_disputes(self, status: str | None = None, job_id: str | None = None,
                      limit: int = 100) -> list[dict[str, Any]]:
        where, args = [], []
        if status:
            where.append("status = ?"); args.append(status)
        if job_id:
            where.append("job_id = ?"); args.append(job_id)
        sql = "SELECT data FROM disputes" + (" WHERE " + " AND ".join(where) if where else "")
        with self._lock:
            rows = self._conn.execute(sql + " ORDER BY created_at DESC LIMIT ?", (*args, limit)).fetchall()
        return [json.loads(r["data"]) for r in rows]

    # ------------------------------------------------------------------ sohbet (Adım 8)

    def save_conversation(self, conv_id: str, created_at: str, updated_at: str, data: dict[str, Any]) -> None:
        with self._tx() as c:
            c.execute(
                """INSERT INTO conversations(id, created_at, updated_at, data) VALUES (?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at, data=excluded.data""",
                (conv_id, created_at, updated_at, json.dumps(data, ensure_ascii=False, default=str)),
            )

    def get_conversation(self, conv_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT data FROM conversations WHERE id = ?", (conv_id,)).fetchone()
        return json.loads(row["data"]) if row else None

    def list_conversations(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT data FROM conversations ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [json.loads(r["data"]) for r in rows]

    def delete_conversation(self, conv_id: str) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM messages WHERE conv_id = ?", (conv_id,))
            c.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))

    def save_message(self, msg_id: str, conv_id: str, created_at: str, status: str, data: dict[str, Any]) -> None:
        with self._tx() as c:
            c.execute(
                """INSERT INTO messages(id, conv_id, created_at, status, data) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET status=excluded.status, data=excluded.data""",
                (msg_id, conv_id, created_at, status, json.dumps(data, ensure_ascii=False, default=str)),
            )

    def get_message(self, msg_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT data FROM messages WHERE id = ?", (msg_id,)).fetchone()
        return json.loads(row["data"]) if row else None

    def list_messages(self, conv_id: str, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT data FROM messages WHERE conv_id = ? ORDER BY created_at, rowid LIMIT ?", (conv_id, limit)
            ).fetchall()
        return [json.loads(r["data"]) for r in rows]

    def list_messages_by_status(self, statuses: tuple[str, ...], limit: int = 200) -> list[dict[str, Any]]:
        marks = ",".join("?" * len(statuses))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT data FROM messages WHERE status IN ({marks}) ORDER BY created_at LIMIT ?", (*statuses, limit)
            ).fetchall()
        return [json.loads(r["data"]) for r in rows]

    def save_attachment(self, att_id: str, created_at: str, data: dict[str, Any]) -> None:
        with self._tx() as c:
            c.execute("INSERT OR REPLACE INTO attachments(id, created_at, data) VALUES (?, ?, ?)",
                      (att_id, created_at, json.dumps(data, ensure_ascii=False, default=str)))

    def get_attachment(self, att_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT data FROM attachments WHERE id = ?", (att_id,)).fetchone()
        return json.loads(row["data"]) if row else None

    def count_worker_results(self, worker: str) -> tuple[int, int]:
        """(biten, başarılı) görev sayısı — bir ajanın kullanım geçmişi (Adım 7c)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT SUM(status IN ('succeeded', 'failed', 'cancelled', 'timed_out', 'rejected')), "
                "SUM(status = 'succeeded') FROM tasks WHERE worker = ?", (worker,)
            ).fetchone()
        return int(row[0] or 0), int(row[1] or 0)

    def count_by_status(self, status: TaskStatus) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM tasks WHERE status = ?", (status.value,)).fetchone()[0]

    # ------------------------------------------------------------------ görevler

    def save(self, task: Task) -> None:
        now = utcnow().isoformat()
        with self._tx() as c:
            prev = c.execute("SELECT status FROM tasks WHERE id = ?", (task.id,)).fetchone()
            if prev is None or prev["status"] != task.status.value:
                # Süreçler arası olay akışı (Adım 4): API sunucusu bu tabloyu izleyip arayüze aktarır.
                self._insert_event(c, "task.status", task.id, {
                    "worker": task.worker, "status": task.status.value,
                    "previous": prev["status"] if prev else None, "parent_id": task.parent_id,
                    "objective": task.objective[:160], "model": task.model,
                })
            c.execute(
                """INSERT INTO tasks(id, worker, status, created_at, updated_at, data)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     worker=excluded.worker, status=excluded.status,
                     updated_at=excluded.updated_at, data=excluded.data""",
                (task.id, task.worker, task.status.value, task.created_at.isoformat(), now,
                 task.model_dump_json()),
            )

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            row = self._conn.execute("SELECT data FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return Task.model_validate_json(row["data"]) if row else None

    def list_tasks(self, limit: int = 50, status: TaskStatus | None = None) -> list[Task]:
        sql = "SELECT data FROM tasks"
        args: tuple[Any, ...] = ()
        if status:
            sql += " WHERE status = ?"
            args = (status.value,)
        sql += " ORDER BY created_at DESC LIMIT ?"
        with self._lock:
            rows = self._conn.execute(sql, (*args, limit)).fetchall()
        return [Task.model_validate_json(r["data"]) for r in rows]

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

    def list_children(self, parent_id: str, limit: int = 500) -> list[Task]:
        """Bir işin alt görevleri, oluşturulma sırasıyla (Adım 11: iş akışı grafiği)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT data FROM tasks WHERE json_extract(data, '$.parent_id') = ? ORDER BY created_at, rowid LIMIT ?",
                (parent_id, limit)).fetchall()
        return [Task.model_validate_json(r["data"]) for r in rows]

    def list_by_worker(self, worker: str, limit: int = 50) -> list[Task]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT data FROM tasks WHERE worker = ? ORDER BY created_at DESC LIMIT ?", (worker, limit)).fetchall()
        return [Task.model_validate_json(r["data"]) for r in rows]

    # ------------------------------------------------------------------ olaylar

    def log_event(self, task_id: str, event: str, detail: dict[str, Any] | str | None = None) -> None:
        if detail is not None and not isinstance(detail, str):
            detail = json.dumps(detail, ensure_ascii=False, default=str)
        with self._tx() as c:
            c.execute(
                "INSERT INTO task_events(task_id, ts, event, detail) VALUES (?, ?, ?, ?)",
                (task_id, utcnow().isoformat(), event, detail),
            )

    def events(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, event, detail FROM task_events WHERE task_id = ? ORDER BY id", (task_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ kurtarma

    # ------------------------------------------------------------------ olay akışı (süreçler arası)

    @staticmethod
    def _insert_event(c: sqlite3.Connection, type_: str, task_id: str | None, data: dict[str, Any] | None) -> None:
        c.execute(
            "INSERT INTO events(ts, type, task_id, data) VALUES (?, ?, ?, ?)",
            (utcnow().isoformat(), type_, task_id, json.dumps(data or {}, ensure_ascii=False, default=str)),
        )

    def emit(self, type_: str, data: dict[str, Any] | None = None, task_id: str | None = None) -> None:
        with self._tx() as c:
            self._insert_event(c, type_, task_id, data)

    def events_since(self, after_id: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, type, task_id, data FROM events WHERE id > ? ORDER BY id LIMIT ?", (after_id, limit)
            ).fetchall()
        return [{**dict(r), "data": json.loads(r["data"] or "{}")} for r in rows]

    def last_event_id(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT MAX(id) FROM events").fetchone()
        return int(row[0] or 0)

    def recover_interrupted(self) -> list[str]:
        """Önceki süreçte yarım kalmış görevleri 'failed' olarak işaretler. ID listesini döner."""
        recovered: list[str] = []
        open_states = (TaskStatus.RUNNING, TaskStatus.AWAITING_APPROVAL)
        for status in open_states:
            for task in self.list_tasks(limit=10_000, status=status):
                task.status = TaskStatus.FAILED
                task.error = f"interrupted: süreç yeniden başlatıldı (önceki durum: {status.value})"
                task.finished_at = utcnow()
                self.save(task)
                self.log_event(task.id, "recovered_as_failed", {"previous_status": status.value})
                recovered.append(task.id)
        return recovered
