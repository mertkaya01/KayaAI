"""Tarayıcı sürücüsü (Adım 12d): Playwright + kurulu Edge (sahip kararı), AYRI ve boş profil (`data/browser_profile`).

Playwright'ın senkron API'si tek iş parçacığına bağlıdır: tüm komutlar sürücünün kendi iş parçacığında sırayla çalışır
(onay merkezinden gelen "onayla" isteği başka iş parçacığında olsa da). İndirme kapalı; `file://` ve yerel ağ istekleri
ağ katmanında engellenir.
"""

from __future__ import annotations

import base64
import io
import queue
import threading
from concurrent.futures import Future
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from .risk import Element, is_local_host

if TYPE_CHECKING:
    from ..config import Settings


class BrowserError(RuntimeError):
    pass


class PageState(BaseModel):
    url: str = ""
    title: str = ""
    text: str = ""
    elements: list[Element] = Field(default_factory=list)


class Driver(Protocol):
    def open(self, url: str) -> None: ...
    def snapshot(self) -> PageState: ...
    def screenshot(self, element_id: int | None = None) -> bytes: ...
    def act(self, action: str, element_id: int | None, value: str) -> None: ...
    def close(self) -> None: ...


SNAPSHOT_JS = r"""
() => {
  const sel = 'a[href], button, input, select, textarea, summary, [role=button], [role=link], [role=checkbox], [role=tab], [role=menuitem], [onclick]';
  document.querySelectorAll('[data-kaya-id]').forEach((e) => e.removeAttribute('data-kaya-id'));
  const out = [];
  let id = 0;
  for (const e of document.querySelectorAll(sel)) {
    const r = e.getBoundingClientRect();
    const st = getComputedStyle(e);
    if (r.width < 2 || r.height < 2 || st.visibility === 'hidden' || st.display === 'none' || e.type === 'hidden' || e.disabled) continue;
    id += 1;
    e.setAttribute('data-kaya-id', String(id));
    const tag = e.tagName.toLowerCase();
    const type = (tag === 'input' || tag === 'button') ? (e.getAttribute('type') || (tag === 'button' ? 'submit' : 'text')).toLowerCase() : '';
    const label = (e.labels && e.labels[0] && e.labels[0].innerText) || '';
    const img = e.querySelector && e.querySelector('img[alt]');
    const btnValue = (type === 'submit' || type === 'button') ? (e.value || '') : '';
    const name = (e.getAttribute('aria-label') || e.innerText || label || e.getAttribute('placeholder') || e.title || btnValue || (img && img.alt) || '').replace(/\s+/g, ' ').trim();
    const form = e.form || e.closest('form');
    const sens = form && form.querySelector('input[type=password], [autocomplete^="cc-"], input[name*=card i], input[name*=cvv i], input[name*=iban i]');
    out.push({ id, tag, role: e.getAttribute('role') || '', name: name.slice(0, 120), type,
      href: tag === 'a' ? (e.href || '') : '', autocomplete: (e.getAttribute('autocomplete') || '').toLowerCase(),
      field: [e.getAttribute('name'), e.id, e.getAttribute('placeholder')].filter(Boolean).join(' ').slice(0, 80),
      in_form: !!form, form_sensitive: !!sens, download: e.hasAttribute('download') });
    if (out.length >= 120) break;
  }
  return { elements: out, text: (document.body ? document.body.innerText : '').replace(/\n{3,}/g, '\n\n').slice(0, 6000) };
}
"""

HIGHLIGHT_JS = """(id) => { const e = document.querySelector(`[data-kaya-id="${id}"]`); if (!e) return false;
  e.scrollIntoView({block: 'center'}); e.dataset.kayaOutline = e.style.outline; e.style.outline = '4px solid #ff3b30';
  e.style.outlineOffset = '2px'; return true; }"""
UNHIGHLIGHT_JS = """(id) => { const e = document.querySelector(`[data-kaya-id="${id}"]`); if (e) { e.style.outline = e.dataset.kayaOutline || ''; e.style.outlineOffset = ''; } }"""


class BrowserDriver:
    """Gerçek tarayıcı (Playwright). `settings.browser.channel` = msedge (Windows) · testlerde executable_path."""

    def __init__(self, settings: "Settings"):
        self.settings = settings
        self._q: queue.Queue[tuple[Any, tuple, Future] | None] = queue.Queue()
        self._ready: Future = Future()
        self._thread = threading.Thread(target=self._loop, name="kayaai-browser", daemon=True)
        self._thread.start()
        self._ready.result(timeout=90)  # tarayıcı açılamadıysa hatayı burada yükselt

    # -------------------------------------------------------------- iş parçacığı

    def _loop(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            self._ready.set_exception(BrowserError(f"Playwright kurulu değil (setup.ps1 yeniden çalıştırılmalı): {exc}"))
            return
        b = self.settings.browser
        try:
            pw = sync_playwright().start()
        except Exception as exc:  # noqa: BLE001
            self._ready.set_exception(BrowserError(f"Playwright başlatılamadı: {exc}"))
            return
        try:
            profile = self.settings.data_dir / b.profile_dir
            profile.mkdir(parents=True, exist_ok=True)
            kw: dict[str, Any] = {"headless": b.headless, "accept_downloads": False, "viewport": {"width": 1280, "height": 800},
                                  "locale": "tr-TR",
                                  # ajan profili kendi başına arka plan bağlantısı kurmasın (eşitleme, güncelleme, öneriler)
                                  "args": ["--no-first-run", "--no-default-browser-check", "--disable-background-networking",
                                           "--disable-sync", "--disable-component-update", "--disable-default-apps"]}
            if b.executable_path:
                kw["executable_path"] = b.executable_path
            elif b.channel:
                kw["channel"] = b.channel
            self.ctx = pw.chromium.launch_persistent_context(str(profile), **kw)
            self.ctx.route("**/*", self._guard)
            self.ctx.set_default_timeout(b.step_timeout_s * 1000)
            self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        except Exception as exc:  # noqa: BLE001
            pw.stop()
            hint = " (Edge kurulu mu? settings: browser.channel)" if b.channel == "msedge" else ""
            self._ready.set_exception(BrowserError(f"Tarayıcı açılamadı{hint}: {exc}"))
            return
        self._ready.set_result(True)
        while True:
            item = self._q.get()
            if item is None:
                break
            fn, args, fut = item
            try:
                fut.set_result(fn(*args))
            except Exception as exc:  # noqa: BLE001
                fut.set_exception(exc)
        try:
            self.ctx.close()
        finally:
            pw.stop()

    def _guard(self, route: Any) -> None:
        url = route.request.url
        p = urlparse(url)
        if p.scheme in ("data", "blob", "about"):
            return route.continue_()
        if p.scheme not in ("http", "https") or (not self.settings.browser.allow_local and is_local_host((p.hostname or "").lower())):
            return route.abort("blockedbyclient")
        return route.continue_()

    def _call(self, fn: Any, *args: Any, timeout: float = 60) -> Any:
        if not self._thread.is_alive():
            raise BrowserError("Tarayıcı kapalı")
        fut: Future = Future()
        self._q.put((fn, args, fut))
        return fut.result(timeout=timeout)

    # -------------------------------------------------------------- komutlar (sürücü iş parçacığında)

    def _settle(self) -> None:
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except Exception:  # noqa: BLE001 - yavaş sayfa: devam
            pass
        self.page.wait_for_timeout(400)

    def _open(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded")
        self._settle()

    def _snapshot(self) -> PageState:
        if len(self.ctx.pages) > 1 and self.page not in self.ctx.pages[-1:]:
            self.page = self.ctx.pages[-1]  # yeni sekme açıldıysa ona geç
        data = self.page.evaluate(SNAPSHOT_JS)
        return PageState(url=self.page.url, title=self.page.title(), text=data["text"],
                         elements=[Element.model_validate(e) for e in data["elements"]])

    def _screenshot(self, element_id: int | None) -> bytes:
        if element_id is not None:
            self.page.evaluate(HIGHLIGHT_JS, element_id)
        try:
            return self.page.screenshot(type="jpeg", quality=70)
        finally:
            if element_id is not None:
                self.page.evaluate(UNHIGHLIGHT_JS, element_id)

    def _act(self, action: str, element_id: int | None, value: str) -> None:
        sel = f'[data-kaya-id="{element_id}"]'
        if action == "goto":
            self.page.goto(value, wait_until="domcontentloaded")
        elif action == "click":
            self.page.click(sel)
        elif action == "type":
            self.page.fill(sel, value)
        elif action == "select":
            try:
                self.page.select_option(sel, label=value)
            except Exception:  # noqa: BLE001
                self.page.select_option(sel, value=value)
        elif action == "scroll":
            self.page.mouse.wheel(0, -700 if value in ("up", "yukarı") else 700)
        else:
            raise BrowserError(f"Bilinmeyen eylem: {action}")
        self._settle()

    # -------------------------------------------------------------- dış arayüz

    def open(self, url: str) -> None:
        self._call(self._open, url)

    def snapshot(self) -> PageState:
        return self._call(self._snapshot)

    def screenshot(self, element_id: int | None = None) -> bytes:
        return self._call(self._screenshot, element_id)

    def act(self, action: str, element_id: int | None, value: str) -> None:
        self._call(self._act, action, element_id, value, timeout=self.settings.browser.step_timeout_s + 20)

    def close(self) -> None:
        if self._thread.is_alive():
            self._q.put(None)
            self._thread.join(timeout=20)


def thumbnail(jpeg: bytes, width: int = 900) -> str:
    """Önizleme için küçük JPEG data URL (onay kaydına ve arayüze)."""
    from PIL import Image

    img = Image.open(io.BytesIO(jpeg)).convert("RGB")
    if img.width > width:
        img = img.resize((width, int(img.height * width / img.width)))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=65)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
