"""Canlı ilerleme (Adım 15): ajan çalışırken üretilen metinden okunur kısa bir "kuyruk" ve seyrek olay.

Ajanlar JSON şemasıyla cevap verir; yarım JSON'u balonda göstermek anlamsız olur. `readable_tail` yazılmakta olan son
metin değerini (ör. `"answer": "Ankara bölgesinde sat…`) çıkarır. `ProgressSink` olayları en çok `interval_s`'de bir
gönderir (SQLite olay tablosu şişmesin); görev bitince bu olaylar silinir (yalnız canlı izleme içindir).
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

_KEY_RE = re.compile(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*:\s*"')
TAIL_CHARS = 140


TEXT_CHARS = 4000


def readable_tail(partial: str, limit: int = TAIL_CHARS) -> tuple[str | None, str]:
    """Yarım JSON metninde yazılmakta olan son metin değeri: (alan adı, okunur kuyruk). JSON değilse metnin sonu."""
    field, text = readable_value(partial)
    return field, _clip(text, limit)


def readable_value(partial: str) -> tuple[str | None, str]:
    """Yazılmakta olan son metin değerinin tamamı (satır sonları korunur) — sohbette cevabın akması için (Adım 18)."""
    s = partial.lstrip()
    if not s.startswith(("{", "[")):
        return None, s
    last = None
    for m in _KEY_RE.finditer(s):
        last = m
    if last is None:
        return None, ""
    raw = s[last.end():]
    # Değer kapanmışsa kapanış tırnağına kadar al (kaçışlı tırnaklar hariç)
    end = None
    i = 0
    while i < len(raw):
        if raw[i] == "\\":
            i += 2
            continue
        if raw[i] == '"':
            end = i
            break
        i += 1
    body = raw[:end] if end is not None else raw
    if body.endswith("\\"):
        body = body[:-1]
    try:
        text = json.loads(f'"{body}"')
    except ValueError:
        text = body.replace("\\n", "\n").replace('\\"', '"')
    return last.group(1), text


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else "…" + text[-(limit - 1):]


class ProgressSink:
    """Bir görevin akan çıktısını biriktirir; en çok `interval_s` aralıkla `emit(data)` çağırır."""

    def __init__(self, emit: Callable[[dict[str, Any]], None], interval_s: float = 0.4,
                 clock: Callable[[], float] = time.monotonic):
        self._emit = emit
        self._interval = interval_s
        self._clock = clock
        self._buf: list[str] = []
        self._chars = 0
        self._last = -1e9
        self.attempt = 1
        self.sent = 0

    def reset(self, attempt: int) -> None:
        self._buf, self._chars, self.attempt = [], 0, attempt
        self.flush(force=True)

    def feed(self, chunk: str) -> None:
        self._buf.append(chunk)
        self._chars += len(chunk)
        if self._clock() - self._last >= self._interval:
            self.flush()

    def flush(self, force: bool = False) -> None:
        if not force and not self._buf:
            return
        field, text = readable_value("".join(self._buf))
        self._last = self._clock()
        self.sent += 1
        self._emit({"chars": self._chars, "field": field, "tail": _clip(text, TAIL_CHARS), "attempt": self.attempt,
                    "text": text[:TEXT_CHARS]})
