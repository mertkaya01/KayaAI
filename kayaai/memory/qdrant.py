"""Qdrant vektör deposu (Adım 19b): büyük belge havuzları için (sunucu kurulumu). Masaüstünde varsayılan SQLite kalır.

- Qdrant'ın REST arayüzü `httpx` ile (ek Python bağımlılığı yok). Yalnız yapılandırılan adrese gider (masaüstünde
  127.0.0.1, sunucuda iç Docker ağı `http://qdrant:6333`); internete çıkmaz.
- Koleksiyon: `kayaai_<boyut>` (bge-m3: 1024), kosinüs. Nokta kimliği `uuid5(kind:item_id)`; yük: kind, item_id, model.
- Arama `kind` ve `model` ile süzülür (hafıza ile belge parçaları karışmaz; model değişince eski vektörler gelmez).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx

log = logging.getLogger(__name__)
NS = uuid.UUID("6f1c3a52-6b0e-4d6a-9a52-6b61796161ff")  # sabit ad alanı (kimlikler kalıcı olsun)
PREFIX = "kayaai_"


class QdrantError(RuntimeError):
    pass


def point_id(kind: str, item_id: str) -> str:
    return str(uuid.uuid5(NS, f"{kind}:{item_id}"))


class QdrantStore:
    def __init__(self, url: str, api_key: str | None = None, timeout: float = 30,
                 transport: httpx.BaseTransport | None = None):
        headers = {"api-key": api_key} if api_key else {}
        self._http = httpx.Client(base_url=url.rstrip("/"), timeout=timeout, headers=headers, transport=transport)
        self._known: set[str] = set()

    def close(self) -> None:
        self._http.close()

    def _req(self, method: str, path: str, **kw: Any) -> Any:
        try:
            r = self._http.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise QdrantError(f"Qdrant'a ulaşılamadı ({self._http.base_url}): {exc}") from exc
        if r.status_code >= 400:
            raise QdrantError(f"Qdrant HTTP {r.status_code}: {r.text[:300]}")
        return r.json().get("result") if r.content else None

    # ------------------------------------------------------------------ koleksiyonlar

    def collections(self) -> list[str]:
        res = self._req("GET", "/collections") or {}
        return [c["name"] for c in res.get("collections", []) if str(c.get("name", "")).startswith(PREFIX)]

    def _ensure(self, dim: int) -> str:
        name = f"{PREFIX}{dim}"
        if name in self._known:
            return name
        if name not in self.collections():
            self._req("PUT", f"/collections/{name}", json={"vectors": {"size": dim, "distance": "Cosine"}})
            for field in ("kind", "model", "item_id"):
                self._req("PUT", f"/collections/{name}/index?wait=true", json={"field_name": field, "field_schema": "keyword"})
        self._known.add(name)
        return name

    # ------------------------------------------------------------------ vektörler

    def upsert(self, kind: str, items: list[tuple[str, str, list[float]]]) -> None:
        """items: (item_id, model, vektör). Boyuta göre koleksiyonlara gruplanır."""
        by_dim: dict[int, list[dict[str, Any]]] = {}
        for item_id, model, vec in items:
            by_dim.setdefault(len(vec), []).append(
                {"id": point_id(kind, item_id), "vector": [float(x) for x in vec],
                 "payload": {"kind": kind, "item_id": item_id, "model": model}})
        for dim, points in by_dim.items():
            name = self._ensure(dim)
            for i in range(0, len(points), 256):
                self._req("PUT", f"/collections/{name}/points?wait=true", json={"points": points[i:i + 256]})

    def delete(self, kind: str, ids: list[str]) -> None:
        if not ids:
            return
        pts = [point_id(kind, i) for i in ids]
        for name in self.collections():
            for i in range(0, len(pts), 500):
                self._req("POST", f"/collections/{name}/points/delete?wait=true", json={"points": pts[i:i + 500]})

    def search(self, kind: str, model: str, query: list[float], k: int) -> list[tuple[str, float]]:
        name = f"{PREFIX}{len(query)}"
        if name not in self._known and name not in self.collections():
            return []
        self._known.add(name)
        flt = {"must": [{"key": "kind", "match": {"value": kind}}, {"key": "model", "match": {"value": model}}]}
        res = self._req("POST", f"/collections/{name}/points/search",
                        json={"vector": [float(x) for x in query], "limit": k, "filter": flt, "with_payload": True}) or []
        return [(str(p["payload"]["item_id"]), float(p["score"])) for p in res]

    def count(self, kind: str | None = None) -> int:
        total = 0
        for name in self.collections():
            body: dict[str, Any] = {"exact": True}
            if kind:
                body["filter"] = {"must": [{"key": "kind", "match": {"value": kind}}]}
            total += int((self._req("POST", f"/collections/{name}/points/count", json=body) or {}).get("count", 0))
        return total

    def health(self) -> dict[str, Any]:
        try:
            r = self._http.get("/")
            info = r.json() if r.status_code == 200 else {}
            return {"ok": r.status_code == 200, "version": info.get("version"), "points": self.count()}
        except (httpx.HTTPError, QdrantError, ValueError) as exc:
            return {"ok": False, "error": str(exc)[:200]}
