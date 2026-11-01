"""İsteğe bağlı dış veri kaynakları (Adım 14c; referans incelemesi: public-apis). Varsayılan KAPALI.

- Döviz kurları — Frankfurter (Avrupa Merkez Bankası referans kurları; anahtar yok). Gönderilen: yalnız para birimi kodları.
- Resmi tatiller — Nager.Date (anahtar yok). Gönderilen: yıl ve ülke kodu.

Yerel-öncelik ilkesi: her çağrı bilgisayardan veri çıkarır → açmak **R2 sahip onayı** (önizlemede hangi siteye ne gittiği),
kapatmak R1. Yalnız bu iki ana makineye istek yapılır; her çağrı `integration.call` olayına yazılır; sonuçlar önbellekte
(kurlar günde bir, tatiller yılda bir) tutulur. Kişisel veri, sohbet ya da dosya içeriği hiçbir zaman gönderilmez.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from .core.permissions import Risk, SubmitResult, ToolAction

if TYPE_CHECKING:
    from .runtime import Runtime

META_KEY = "integrations"
CURRENCIES = ("USD", "EUR", "GBP", "CHF", "JPY")
SOURCES: dict[str, dict[str, str]] = {
    "exchange_rates": {"label": "Döviz kurları", "provider": "Frankfurter (Avrupa Merkez Bankası referans kurları)",
                       "host": "api.frankfurter.dev", "sends": "yalnız para birimi kodları (EUR, TRY, USD…)",
                       "use": "sohbette kur/döviz soruları, satış raporunda kur notu"},
    "holidays": {"label": "Resmi tatiller", "provider": "Nager.Date", "host": "date.nager.at",
                 "sends": "yıl ve ülke kodu (TR)", "use": "zamanlanmış görevlerde 'resmi tatilde çalışma'"},
}
CURRENCY_RE = re.compile(r"\b(dolar\w*|euro\w*|avro\w*|sterlin\w*|pound\w*|usd|eur|gbp|chf|jpy|döviz\w*|kur(?:u|unu|lar|ları|ların|da)?\b|"
                         r"exchange\s+rate\w*|currency|€|\$|£)", re.IGNORECASE)


class IntegrationError(ValueError):
    pass


class IntegrationDisabled(IntegrationError):
    pass


def enabled(rt: "Runtime") -> dict[str, bool]:
    raw = rt.store.get_meta(META_KEY)
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        data = {}
    return {k: bool(data.get(k)) for k in SOURCES}


def is_enabled(rt: "Runtime", name: str) -> bool:
    return enabled(rt).get(name, False)


def _set(rt: "Runtime", name: str, value: bool) -> None:
    data = enabled(rt)
    data[name] = value
    rt.store.set_meta(META_KEY, json.dumps(data))


def status(rt: "Runtime") -> list[dict[str, Any]]:
    on = enabled(rt)
    return [{"name": k, **v, "enabled": on[k]} for k, v in SOURCES.items()]


def request_enable(rt: "Runtime", name: str, requested_by: str = "user") -> SubmitResult:
    if name not in SOURCES:
        raise IntegrationError(f"Bilinmeyen kaynak: {name} ({', '.join(SOURCES)})")
    if is_enabled(rt, name):
        raise IntegrationError(f"Zaten açık: {SOURCES[name]['label']}")
    src = SOURCES[name]
    assert rt.permissions is not None
    return rt.permissions.submit(ToolAction(
        tool="integration.enable", params={"name": name}, risk=Risk.R2,
        summary=f"Dış veri kaynağını aç: {src['label']} ({src['provider']})",
        reason="kayaAI bu siteye internet üzerinden istek yapacak (yerel-öncelik ilkesinin istisnası).",
        preview={"new_head": f"Site: https://{src['host']}\nGönderilen: {src['sends']}\nKullanım: {src['use']}\n"
                             "Kişisel veri, sohbet ya da dosya içeriği gönderilmez. Her istek kayda geçer."},
        undo=f"kayaai integrations disable {name}", requested_by=requested_by))


def request_disable(rt: "Runtime", name: str, requested_by: str = "user") -> SubmitResult:
    if name not in SOURCES:
        raise IntegrationError(f"Bilinmeyen kaynak: {name}")
    assert rt.permissions is not None
    return rt.permissions.submit(ToolAction(
        tool="integration.disable", params={"name": name}, risk=Risk.R1,
        summary=f"Dış veri kaynağını kapat: {SOURCES[name]['label']}", requested_by=requested_by))


def executors(rt: "Runtime") -> dict[str, Any]:
    def enable(p: dict[str, Any]) -> dict[str, Any]:
        _set(rt, p["name"], True)
        rt.store.emit("integration.enabled", {"name": p["name"]})
        return {"name": p["name"], "enabled": True}

    def disable(p: dict[str, Any]) -> dict[str, Any]:
        _set(rt, p["name"], False)
        rt.store.emit("integration.disabled", {"name": p["name"]})
        return {"name": p["name"], "enabled": False}

    return {"integration.enable": enable, "integration.disable": disable}


# ---------------------------------------------------------------------------- ağ (yalnız izinli iki ana makine)


def _fetch_json(url: str, timeout: float = 10) -> Any:
    import httpx

    with httpx.Client(timeout=timeout, follow_redirects=False, headers={"User-Agent": "kayaAI (yerel asistan)"}) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.json()


def _get(rt: "Runtime", name: str, url: str) -> Any:
    if not is_enabled(rt, name):
        raise IntegrationDisabled(f"{SOURCES[name]['label']} kapalı (açmak için: kayaai integrations enable {name})")
    host = urlparse(url).hostname
    if host != SOURCES[name]["host"]:
        raise IntegrationError(f"İzin verilmeyen adres: {host}")
    try:
        data = _fetch_json(url)
        rt.store.emit("integration.call", {"name": name, "host": host, "ok": True})
        return data
    except Exception as exc:  # noqa: BLE001
        rt.store.emit("integration.call", {"name": name, "host": host, "ok": False, "error": str(exc)[:200]})
        raise IntegrationError(f"{SOURCES[name]['provider']} isteği başarısız: {exc}") from exc


def _cache(rt: "Runtime") -> Path:
    d = rt.settings.data_dir / "integrations"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------- döviz kurları


def rates(rt: "Runtime", today: date | None = None) -> dict[str, Any]:
    """1 birim yabancı para = kaç TL (ECB referans kuru, Frankfurter). Günde bir istek; aynı gün önbellekten."""
    today = today or date.today()
    path = _cache(rt) / f"rates-{today.isoformat()}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    data = _get(rt, "exchange_rates",
                f"https://api.frankfurter.dev/v1/latest?base=EUR&symbols=TRY,{','.join(c for c in CURRENCIES if c != 'EUR')}")
    eur = data.get("rates") or {}
    if "TRY" not in eur:
        raise IntegrationError("Kur cevabında TRY yok")
    per_try = {"EUR": round(float(eur["TRY"]), 4)}
    for c in CURRENCIES:
        if c != "EUR" and eur.get(c):
            per_try[c] = round(float(eur["TRY"]) / float(eur[c]), 4)
    out = {"date": data.get("date"), "source": "Avrupa Merkez Bankası (Frankfurter)", "unit": "1 birim = TL",
           "per_try": per_try, "fetched": datetime.now().isoformat(timespec="seconds")}
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def wants_rates(text: str) -> bool:
    return bool(CURRENCY_RE.search(text or ""))


def rates_note(r: dict[str, Any]) -> str:
    parts = [f"1 {c} = {v:.4f}".replace(".", ",") + " TL" for c, v in r["per_try"].items() if c in ("USD", "EUR", "GBP")]
    return f"Kurlar ({r['source']}, {r['date']}): " + " · ".join(parts)


# ---------------------------------------------------------------------------- resmi tatiller


def holidays(rt: "Runtime", year: int, country: str = "TR") -> list[dict[str, str]]:
    path = _cache(rt) / f"holidays-{country}-{year}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    data = _get(rt, "holidays", f"https://date.nager.at/api/v3/PublicHolidays/{int(year)}/{country}")
    if not isinstance(data, list):
        raise IntegrationError("Tatil cevabı beklenen biçimde değil")
    out = [{"date": h["date"], "name": h.get("localName") or h.get("name") or ""} for h in data if h.get("date")]
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def holiday_on(rt: "Runtime", day: date, country: str = "TR") -> str | None:
    """Gün resmi tatilse adı, değilse None."""
    for h in holidays(rt, day.year, country):
        if h["date"] == day.isoformat():
            return h["name"] or "resmi tatil"
    return None
