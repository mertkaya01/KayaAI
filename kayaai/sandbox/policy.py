"""Kum havuzu politikası (Adım 19c): çalıştırmadan önce kodda yasak işler. Asıl güvenlik sınırı konteynerdir; bu ek
katman ajanın ağa/alt sürece/sisteme uzanma girişimini erkenden yakalar ve ona açık bir sebep söyler."""

from __future__ import annotations

import ast
import re
from typing import Any

FORBIDDEN_MODULES = {
    "socket": "ağ", "ssl": "ağ", "http": "ağ", "urllib": "ağ", "requests": "ağ", "httpx": "ağ", "ftplib": "ağ",
    "smtplib": "ağ", "telnetlib": "ağ", "subprocess": "alt süreç", "multiprocessing": "alt süreç",
    "ctypes": "sistem çağrısı", "cffi": "sistem çağrısı", "pty": "terminal", "importlib": "dinamik içe aktarma",
}
# os.system(...), os.popen(...) gibi: nesne üzerinden de çağrılsa yasak
FORBIDDEN_ATTR_CALLS = {"system", "popen", "spawnl", "spawnv", "spawnve", "execv", "execve", "execl", "execvp",
                        "fork", "forkpty", "kill", "killpg"}
# eval(...) gibi: yalnız çıplak çağrı (pandas df.eval(...) zararsız)
FORBIDDEN_NAME_CALLS = {"__import__", "eval", "exec", "compile"}
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,80}$")


def safe_name(name: str) -> str | None:
    """Ek dosya adı: yalnız düz ad (klasör, '..' yok); uymuyorsa None."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return base if NAME_RE.match(base) and base != "main.py" and ".." not in base else None


def check(code: str, cfg: Any) -> list[str]:
    """Boş liste: çalıştırılabilir. Aksi halde Türkçe sebepler."""
    reasons: list[str] = []
    if len(code.encode("utf-8")) > cfg.max_code_kb * 1024:
        return [f"kod çok uzun (>{cfg.max_code_kb} KB)"]
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"sözdizimi hatası: satır {exc.lineno}: {exc.msg}"]
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for n in names:
                root = n.split(".")[0]
                if root in FORBIDDEN_MODULES:
                    reasons.append(f"'{root}' kullanılamaz ({FORBIDDEN_MODULES[root]})")
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr in FORBIDDEN_ATTR_CALLS:
                reasons.append(f"'{fn.attr}(...)' çağrısı kullanılamaz (alt süreç/sistem)")
            elif isinstance(fn, ast.Name) and fn.id in FORBIDDEN_NAME_CALLS:
                reasons.append(f"'{fn.id}(...)' çağrısı kullanılamaz")
    return sorted(set(reasons))
