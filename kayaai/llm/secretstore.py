"""Sağlayıcı API anahtarları (Adım 20, sahip kararı): Windows'ta **Kimlik Bilgisi Yöneticisi** (Credential Manager).

- Anahtar arayüzden bir kez girilir; API ve arayüz onu bir daha GÖSTERMEZ (yalnız "kayıtlı / yok"), kayıtlara yazılmaz.
- Windows: `advapi32` CredWriteW/CredReadW/CredDeleteW (ctypes; ek paket yok). Hedef adı `kayaAI/provider/<id>`;
  Denetim Masası → Kimlik Bilgisi Yöneticisi → Windows Kimlik Bilgileri'nde görünür, oradan da silinebilir.
- Linux (sunucu modu): `data/secrets/<id>.key`, yalnız sahibin okuyabildiği izinle (0600).
- Her iki durumda ortam değişkeni `KAYAAI_PROVIDER_KEY_<ID>` önce gelir (sunucu/otomasyon için).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

MAX_KEY_CHARS = 1000  # Kimlik Bilgisi Yöneticisi genel kayıt sınırı 2560 bayt (UTF-16)
TARGET_PREFIX = "kayaAI/provider/"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


class SecretStoreError(RuntimeError):
    pass


def env_name(provider_id: str) -> str:
    return "KAYAAI_PROVIDER_KEY_" + re.sub(r"[^A-Z0-9]", "_", provider_id.upper())


def _check(provider_id: str) -> None:
    if not ID_RE.match(provider_id):
        raise SecretStoreError(f"geçersiz sağlayıcı kimliği: {provider_id!r}")


def clean_key(key: str) -> str:
    key = (key or "").strip()
    if not key:
        raise SecretStoreError("anahtar boş")
    if len(key) > MAX_KEY_CHARS:
        raise SecretStoreError(f"anahtar çok uzun (en çok {MAX_KEY_CHARS} karakter)")
    if any(ch.isspace() for ch in key) or not key.isprintable():
        raise SecretStoreError("anahtarda boşluk ya da görünmez karakter olamaz")
    return key


class WindowsCredentialStore:
    """Windows Kimlik Bilgisi Yöneticisi (genel kimlik bilgisi, bu bilgisayara kalıcı)."""

    name = "Windows Kimlik Bilgisi Yöneticisi"

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class CREDENTIALW(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR),
            ]

        self._ct, self._CRED = ctypes, CREDENTIALW
        pcred = ctypes.POINTER(CREDENTIALW)
        adv = ctypes.WinDLL("advapi32", use_last_error=True)  # type: ignore[attr-defined]
        self._write = adv.CredWriteW
        self._write.argtypes, self._write.restype = [pcred, wintypes.DWORD], wintypes.BOOL
        self._read = adv.CredReadW
        self._read.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(pcred)]
        self._read.restype = wintypes.BOOL
        self._delete = adv.CredDeleteW
        self._delete.argtypes, self._delete.restype = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD], wintypes.BOOL
        self._free = adv.CredFree
        self._free.argtypes, self._free.restype = [ctypes.c_void_p], None
        self._pcred = pcred

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2
    ERROR_NOT_FOUND = 1168

    def set(self, provider_id: str, key: str) -> None:
        ct = self._ct
        blob = key.encode("utf-16-le")
        buf = (ct.c_ubyte * len(blob)).from_buffer_copy(blob)
        cred = self._CRED()
        cred.Type = self.CRED_TYPE_GENERIC
        cred.TargetName = TARGET_PREFIX + provider_id
        cred.Comment = "kayaAI dış sağlayıcı API anahtarı"
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ct.cast(buf, ct.POINTER(ct.c_ubyte))
        cred.Persist = self.CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = "kayaai"
        if not self._write(ct.byref(cred), 0):
            raise SecretStoreError(f"Kimlik Bilgisi Yöneticisi'ne yazılamadı (hata {ct.get_last_error()})")

    def get(self, provider_id: str) -> str | None:
        ct = self._ct
        p = self._pcred()
        if not self._read(TARGET_PREFIX + provider_id, self.CRED_TYPE_GENERIC, 0, ct.byref(p)):
            err = ct.get_last_error()
            if err == self.ERROR_NOT_FOUND:
                return None
            raise SecretStoreError(f"Kimlik Bilgisi Yöneticisi okunamadı (hata {err})")
        try:
            c = p.contents
            return ct.string_at(c.CredentialBlob, c.CredentialBlobSize).decode("utf-16-le") or None
        finally:
            self._free(p)

    def delete(self, provider_id: str) -> None:
        ct = self._ct
        if not self._delete(TARGET_PREFIX + provider_id, self.CRED_TYPE_GENERIC, 0):
            err = ct.get_last_error()
            if err != self.ERROR_NOT_FOUND:
                raise SecretStoreError(f"Kimlik Bilgisi Yöneticisi'nden silinemedi (hata {err})")


class FileStore:
    """Linux/sunucu: data/secrets/<id>.key (0600). Klasör de yalnız sahibin (0700)."""

    name = "dosya (data/secrets, yalnız sahip okur)"

    def __init__(self, root: Path):
        self.root = root

    def _path(self, provider_id: str) -> Path:
        return self.root / f"{provider_id}.key"

    def set(self, provider_id: str, key: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass
        p = self._path(provider_id)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(key)
        os.chmod(p, 0o600)

    def get(self, provider_id: str) -> str | None:
        p = self._path(provider_id)
        try:
            return p.read_text(encoding="utf-8").strip() or None if p.is_file() else None
        except OSError:
            return None

    def delete(self, provider_id: str) -> None:
        self._path(provider_id).unlink(missing_ok=True)


class SecretStore:
    """Ortam değişkeni → platform deposu. Testlerde `backend` yerine bellekte bir depo verilir."""

    def __init__(self, data_dir: Path, backend: object | None = None):
        if backend is None:
            backend = WindowsCredentialStore() if sys.platform == "win32" else FileStore(data_dir / "secrets")
        self.backend = backend

    @property
    def backend_name(self) -> str:
        return str(getattr(self.backend, "name", type(self.backend).__name__))

    def source(self, provider_id: str) -> str | None:
        """Anahtar nereden geliyor: 'env' | 'store' | None (değerin kendisi asla dönmez)."""
        _check(provider_id)
        if os.environ.get(env_name(provider_id), "").strip():
            return "env"
        return "store" if self.backend.get(provider_id) else None  # type: ignore[attr-defined]

    def get(self, provider_id: str) -> str | None:
        _check(provider_id)
        env = os.environ.get(env_name(provider_id), "").strip()
        return env or self.backend.get(provider_id)  # type: ignore[attr-defined]

    def set(self, provider_id: str, key: str) -> None:
        _check(provider_id)
        self.backend.set(provider_id, clean_key(key))  # type: ignore[attr-defined]

    def delete(self, provider_id: str) -> None:
        _check(provider_id)
        self.backend.delete(provider_id)  # type: ignore[attr-defined]


class MemoryStore:
    """Testler için (anahtar diske/Windows'a yazılmaz)."""

    name = "bellek (test)"

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def set(self, provider_id: str, key: str) -> None:
        self.data[provider_id] = key

    def get(self, provider_id: str) -> str | None:
        return self.data.get(provider_id)

    def delete(self, provider_id: str) -> None:
        self.data.pop(provider_id, None)
