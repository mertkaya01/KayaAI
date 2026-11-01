"""Tarayıcı eylemlerinin risk sınıfı — KODLA (model karar vermez). MASTER_PROMPT §8: form girişi R2; gönderme, ödeme,
satın alma, silme, yayınlama R3 (her seferinde sahip onayı). Parola/kart alanına yazma, dosya yükleme, yerel ağ ve
`file://` reddedilir.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel

Verdict = Literal["R0", "R1", "R2", "R3", "refuse"]

# Düğme/bağlantı metninde geri alınamaz eylem (R3)
R3_WORDS = re.compile(
    r"\b(gönder|gonder|öde|ode|ödeme|odeme|satın\s*al|satin\s*al|sipariş|siparis|siparişi\s*tamamla|alışverişi\s*tamamla|"
    r"onayla\s*ve\s*öde|hemen\s*al|sepeti\s*onayla|sil|kaldır|hesabı\s*kapat|yayınla|yayinla|paylaş|paylas|abone\s*ol|"
    r"bağış|transfer|havale|eft|send|submit|pay|payment|buy|purchase|order|checkout|place\s*order|delete|remove|"
    r"publish|post|tweet|share|subscribe|donate|confirm\s*payment|sign\s*up|register|kaydol|üye\s*ol)\b",
    re.IGNORECASE)
SENSITIVE_FIELD = re.compile(r"(pass(word)?|parola|şifre|sifre|card|kart|cvv|cvc|iban|ssn|tckn|tc\s*kimlik|"
                             r"kimlik\s*no|otp|2fa|pin\b|security\s*code|güvenlik\s*kodu)", re.IGNORECASE)
DOWNLOAD_EXT = re.compile(r"\.(exe|msi|bat|cmd|ps1|zip|rar|7z|dmg|apk|scr|jar|vbs)(\?|$)", re.IGNORECASE)


class Element(BaseModel):
    id: int
    tag: str
    role: str = ""
    name: str = ""                 # görünen metin / etiket
    type: str = ""                 # input türü
    href: str = ""
    autocomplete: str = ""
    field: str = ""                # name/id/placeholder (alan adı ipuçları)
    in_form: bool = False
    form_sensitive: bool = False   # aynı formda parola/kart alanı var
    download: bool = False


class Decision(BaseModel):
    verdict: Verdict
    reason: str


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def is_local_host(host: str) -> bool:
    if host in ("localhost", "") or host.endswith(".local") or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast


def site(host: str) -> str:
    """Kaba kayıtlı alan adı: son iki etiket (co.uk/com.tr gibi ikinci düzeyde üç)."""
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "gov", "edu", "ac") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def check_url(url: str, allow_local: bool = False) -> str | None:
    """Gidilemeyecek adres için neden; yoksa None."""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return f"yalnızca http/https adresleri ({p.scheme or 'şema yok'} reddedildi)"
    if not p.hostname:
        return "adres geçersiz"
    if not allow_local and is_local_host(p.hostname.lower()):
        return "yerel ağ / bu bilgisayar adresleri reddedilir"
    return None


def classify(action: str, current_url: str, el: Element | None = None, value: str = "",
             allow_local: bool = False) -> Decision:
    if action in ("scroll", "extract", "done", "back_to_list"):
        return Decision(verdict="R0", reason="yalnızca okuma")
    if action == "goto":
        why = check_url(value, allow_local)
        if why:
            return Decision(verdict="refuse", reason=why)
        if current_url and site(_host(value)) == site(_host(current_url)):
            return Decision(verdict="R1", reason="aynı sitede gezinme")
        return Decision(verdict="R2", reason=f"yeni siteye gitme: {_host(value)}")
    if el is None:
        return Decision(verdict="refuse", reason="öğe bulunamadı")
    hint = " ".join([el.name, el.field, el.autocomplete, el.type])
    if action == "type":
        if el.type == "file":
            return Decision(verdict="refuse", reason="dosya yükleme yapılmaz")
        if el.type == "password" or el.autocomplete.startswith("cc-") or SENSITIVE_FIELD.search(hint):
            return Decision(verdict="refuse", reason="parola / kart / kimlik alanına yazılmaz — bunu sen yapmalısın")
        return Decision(verdict="R2", reason="forma bilgi yazma")
    if action == "select":
        return Decision(verdict="R2", reason="formda seçim yapma")
    if action == "click":
        if el.download or DOWNLOAD_EXT.search(el.href):
            return Decision(verdict="refuse", reason="dosya indirme yapılmaz")
        if el.type == "file":
            return Decision(verdict="refuse", reason="dosya yükleme yapılmaz")
        if R3_WORDS.search(el.name) or (el.form_sensitive and (el.type == "submit" or el.tag == "button")):
            return Decision(verdict="R3", reason=f"geri alınamaz eylem olabilir: \"{el.name[:60]}\"")
        if el.href:
            why = check_url(el.href, allow_local) if el.href.startswith(("http:", "https:", "file:")) else None
            if why:
                return Decision(verdict="refuse", reason=why)
            if el.href.startswith(("http:", "https:")) and site(_host(el.href)) != site(_host(current_url)):
                return Decision(verdict="R2", reason=f"başka siteye bağlantı: {_host(el.href)}")
            return Decision(verdict="R1", reason="bağlantıya tıklama")
        if el.in_form and (el.type == "submit" or el.tag == "button"):
            return Decision(verdict="R2", reason="form gönderme düğmesi")
        return Decision(verdict="R1", reason="düğmeye tıklama")
    return Decision(verdict="refuse", reason=f"bilinmeyen eylem: {action}")


def describe(action: str, el: Element | None, value: str) -> str:
    target = f"\"{el.name[:60]}\" ({el.tag}{'/' + el.type if el.type else ''})" if el else ""
    return {
        "goto": f"Adrese git: {value}",
        "click": f"Tıkla: {target}",
        "type": f"Yaz: {target} ← \"{value[:80]}\"",
        "select": f"Seç: {target} → \"{value[:60]}\"",
        "scroll": f"Sayfayı kaydır ({value or 'aşağı'})",
        "extract": "Sayfadan bilgi oku",
        "done": "Bitir",
    }.get(action, action)


def element_from(raw: dict[str, Any]) -> Element:
    return Element.model_validate(raw)
