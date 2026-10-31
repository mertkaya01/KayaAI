"""Dosya araçları (Adım 5) — yalnızca izin verilen klasörlerde.

Sahip kararı: kayaAI'nin kendi klasörü (`files.home_dir`, varsayılan ~/kayaAI-files, okuma+yazma) +
`files.allowed_dirs` listesindeki klasörler (her biri `read` ya da `read_write`). Listede olmayan hiçbir
yere erişilmez; `..`, mutlak yol ve sembolik bağlantı (symlink/junction) ile kaçış denemeleri, yol çözümlendikten
SONRA kontrol edildiği için reddedilir.

Risk:
  file.list / file.read          R0 (okuma)
  file.write (yeni dosya)        R1 (otomatik, kayda geçer)
  file.write (var olan dosya)    R2 (önizleme + sahip onayı; üzerine yazmadan önce otomatik yedek)
Silme bu adımda yok.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import Settings
from ..core.permissions import PermissionEngine, Risk, SubmitResult, ToolAction

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".yaml", ".yml", ".xml", ".html", ".htm",
                 ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".sql", ".css", ".ini", ".toml", ".log", ".ps1", ".sh"}
MAX_LIST = 500


class PathNotAllowed(PermissionError):
    pass


@dataclass(frozen=True)
class Root:
    path: Path
    writable: bool


def _norm(p: Path) -> str:
    return os.path.normcase(str(p))  # Windows'ta büyük/küçük harf duyarsız karşılaştırma


def home_dir(settings: Settings) -> Path:
    raw = settings.files.home_dir
    base = Path(os.path.expandvars(os.path.expanduser(raw))) if raw else Path.home() / "kayaAI-files"
    return base.resolve()


def roots(settings: Settings) -> list[Root]:
    out = [Root(home_dir(settings), True)]
    for d in settings.files.allowed_dirs:
        p = Path(os.path.expandvars(os.path.expanduser(d.path))).resolve()
        out.append(Root(p, d.access == "read_write"))
    return out


class FileTools:
    def __init__(self, settings: Settings, engine: PermissionEngine | None = None):
        self.settings = settings
        self.engine = engine
        self.backup_dir = settings.data_dir / "backups"  # klasörler yalnızca gerçekten kullanılınca oluşturulur

    # ------------------------------------------------------------------ yol güvenliği

    def resolve(self, user_path: str, *, write: bool = False) -> tuple[Path, Root]:
        if not user_path or "\x00" in user_path:
            raise PathNotAllowed("Geçersiz yol")
        raw = Path(os.path.expandvars(os.path.expanduser(user_path)))
        candidate = raw if raw.is_absolute() else home_dir(self.settings) / raw
        resolved = candidate.resolve()  # .. ve sembolik bağlantılar burada çözülür
        for root in sorted(roots(self.settings), key=lambda r: len(str(r.path)), reverse=True):
            r = _norm(root.path)
            if _norm(resolved) == r or _norm(resolved).startswith(r + os.sep):
                if write and not root.writable:
                    raise PathNotAllowed(f"Bu klasör yalnızca okunabilir: {root.path}")
                return resolved, root
        allowed = ", ".join(str(r.path) for r in roots(self.settings))
        raise PathNotAllowed(f"İzin verilen klasörlerin dışında: {resolved}. İzinli: {allowed}")

    def display(self, p: Path) -> str:
        return str(p)

    # ------------------------------------------------------------------ çalıştırıcılar (izin motoru çağırır)

    def exec_list(self, params: dict[str, Any]) -> dict[str, Any]:
        path, _ = self.resolve(params.get("path") or ".")
        if path == home_dir(self.settings):
            path.mkdir(parents=True, exist_ok=True)  # kayaAI klasörü ilk kullanımda oluşturulur
        if not path.is_dir():
            raise FileNotFoundError(f"Klasör yok: {path}")
        entries = []
        for i, child in enumerate(sorted(path.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower()))):
            if i >= MAX_LIST:
                break
            st = child.stat()
            entries.append({"name": child.name, "type": "dir" if child.is_dir() else "file",
                            "size": st.st_size if child.is_file() else None,
                            "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")})
        return {"path": str(path), "entries": entries, "truncated": len(entries) >= MAX_LIST}

    def exec_read(self, params: dict[str, Any]) -> dict[str, Any]:
        path, _ = self.resolve(params["path"])
        if not path.is_file():
            raise FileNotFoundError(f"Dosya yok: {path}")
        if path.suffix.lower() not in TEXT_SUFFIXES:
            raise ValueError(f"Bu dosya türü henüz okunamıyor ({path.suffix or 'uzantısız'}); PDF/Excel desteği Adım 9'da")
        size = path.stat().st_size
        limit = int(self.settings.files.max_read_mb * 1024 * 1024)
        if size > limit:
            raise ValueError(f"Dosya çok büyük ({size / 1e6:.1f} MB > {self.settings.files.max_read_mb} MB)")
        return {"path": str(path), "size": size, "content": path.read_text(encoding="utf-8", errors="replace")}

    def exec_write(self, params: dict[str, Any]) -> dict[str, Any]:
        path, _ = self.resolve(params["path"], write=True)
        content: str = params["content"]
        backup = None
        if path.exists():
            if not path.is_file():
                raise IsADirectoryError(f"Bu bir klasör: {path}")
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            backup = self.backup_dir / f"{datetime.now():%Y%m%d-%H%M%S}_{path.name}"
            shutil.copy2(path, backup)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="")
        return {"path": str(path), "bytes": len(content.encode("utf-8")), "overwritten": backup is not None,
                "backup": str(backup) if backup else None}

    def executors(self) -> dict[str, Any]:
        return {"file.list": self.exec_list, "file.read": self.exec_read, "file.write": self.exec_write}

    # ------------------------------------------------------------------ talep oluşturma (risk + önizleme)

    def list_dir(self, path: str = ".", requested_by: str = "user") -> SubmitResult:
        resolved, _ = self.resolve(path or ".")
        return self._submit(ToolAction(tool="file.list", params={"path": str(resolved)}, risk=Risk.R0,
                                       summary=f"Klasörü listele: {resolved}", requested_by=requested_by))

    def read(self, path: str, requested_by: str = "user") -> SubmitResult:
        resolved, _ = self.resolve(path)
        return self._submit(ToolAction(tool="file.read", params={"path": str(resolved)}, risk=Risk.R0,
                                       summary=f"Dosyayı oku: {resolved}", requested_by=requested_by))

    def write(self, path: str, content: str, requested_by: str = "user") -> SubmitResult:
        resolved, _ = self.resolve(path, write=True)  # salt-okunur klasör: onay bile istenmez, reddedilir
        size = len(content.encode("utf-8"))
        if size > self.settings.files.max_write_mb * 1024 * 1024:
            raise ValueError(f"İçerik çok büyük ({size / 1e6:.1f} MB > {self.settings.files.max_write_mb} MB)")
        params = {"path": str(resolved), "content": content}
        if not resolved.exists():
            return self._submit(ToolAction(tool="file.write", params=params, risk=Risk.R1,
                                           summary=f"Yeni dosya oluştur: {resolved}", requested_by=requested_by,
                                           preview={"new_size": size, "head": content[:500]},
                                           undo="Dosyayı silmek yeterli."))
        old = resolved.read_text(encoding="utf-8", errors="replace") if resolved.is_file() else ""
        return self._submit(ToolAction(
            tool="file.write", params=params, risk=Risk.R2,
            summary=f"Var olan dosyanın ÜZERİNE YAZ: {resolved}",
            reason="Mevcut içerik değişecek.",
            preview={"old_size": len(old.encode('utf-8')), "new_size": size,
                     "old_head": old[:400], "new_head": content[:400]},
            undo=f"Üzerine yazmadan önce otomatik yedek alınır: {self.backup_dir}",
            requested_by=requested_by))

    def _submit(self, action: ToolAction) -> SubmitResult:
        if self.engine is None:
            raise RuntimeError("İzin motoru bağlı değil")
        return self.engine.submit(action)
