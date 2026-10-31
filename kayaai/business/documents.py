"""PDF özeti (kabul #6) ve fatura çıkarma (Adım 10).

- Özet: kısa PDF tek adımda; uzun PDF sayfa gruplarına bölünür → her bölüm document ajanıyla özetlenir → birleştirilir.
  Kaynak sayfalar (s.N) korunur. Taranmış PDF → okuyucu açık hata verir (OCR Adım 12).
- Fatura: model alanları çıkarır (şema), KOD denetler: satır toplamı ≈ ara toplam, ara toplam + KDV ≈ toplam, KDV oranı
  makul, tarih biçimi, tutarların metinde gerçekten geçmesi. Tutarsızlıklar uyarı olur; model sayı uyduramaz.
"""

from __future__ import annotations

import math
from datetime import date
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from pydantic import BaseModel, Field

from ..core.task import Permission, Task, ValidationResult
from ..llm.registry import ModelRegistry
from ..workers.base import LLMWorker
from .numbers import fmt, numbers_in_text
from .readers import PdfDoc

if TYPE_CHECKING:
    from ..runtime import Runtime

SECTION_CHARS = 6000
INVOICE_CHARS = 12000
VAT_RATES = (0.0, 1.0, 8.0, 10.0, 18.0, 20.0)


# ---------------------------------------------------------------------------- özet


class SummaryResult(BaseModel):
    kind: Literal["summary"] = "summary"
    source: str
    pages: int
    summary: str
    sections: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def markdown(self) -> str:
        return f"{self.summary.strip()}\n\n_Kaynak: {self.source} · {self.pages} sayfa — yerel modelle özetlendi._"


def _sections(doc: PdfDoc) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []
    start, buf = 1, ""
    for i, page in enumerate(doc.pages, 1):
        piece = f"[s.{i}]\n{page}\n"
        if buf and len(buf) + len(piece) > SECTION_CHARS:
            out.append((start, i - 1, buf))
            start, buf = i, ""
        buf += piece[: SECTION_CHARS * 2]
    if buf.strip():
        out.append((start, len(doc.pages), buf))
    return out


def summarize_pdf(rt: "Runtime", doc: PdfDoc, question: str = "") -> SummaryResult:
    focus = question.strip() or "Bu belgeyi özetle."
    res = SummaryResult(source=doc.name, pages=len(doc.pages), summary="")
    parts = _sections(doc)
    if len(parts) == 1:
        t = rt.orchestrator.ask(
            f"{focus}\n\n(Not: Belge girdi verisinde. Ana noktaları madde madde ver; önemli tarih, tutar ve kararları koru; "
            "her maddenin sonunda kaynağı [s.N] biçiminde yaz.)", worker="document",
            input={"document": {"name": doc.name, "text": parts[0][2]}})
        if t.status.value != "succeeded" or not t.result:
            res.warnings.append(f"Özet oluşturulamadı: {t.error}")
            return res
        res.summary = str(t.result.get("answer", ""))
        return res
    notes = []
    for a, b, text in parts:
        t = rt.orchestrator.ask(
            f"{focus}\n\n(Not: Bu, belgenin {a}-{b}. sayfaları. Yalnızca bu bölümün ana noktalarını 3-6 madde olarak yaz; "
            "tarih, tutar ve kararları koru; her maddeye [s.N] kaynağı ekle.)", worker="document",
            input={"document_part": {"name": doc.name, "pages": f"{a}-{b}", "text": text}})
        if t.status.value == "succeeded" and t.result:
            notes.append({"pages": f"{a}-{b}", "summary": str(t.result.get("answer", ""))})
        else:
            res.warnings.append(f"{a}-{b}. sayfalar özetlenemedi.")
    res.sections = notes
    if not notes:
        res.warnings.append("Hiçbir bölüm özetlenemedi.")
        return res
    t = rt.orchestrator.ask(
        f"{focus}\n\n(Not: Girdi verisinde belgenin bölüm özetleri var. Bunlardan tek, tekrarsız bir özet yaz: önce 2-3 "
        "cümlelik genel bakış, sonra en önemli maddeler. [s.N] kaynaklarını koru; yeni bilgi ekleme.)",
        worker="document", input={"section_summaries": notes, "name": doc.name})
    if t.status.value == "succeeded" and t.result:
        res.summary = str(t.result.get("answer", ""))
    else:
        res.summary = "\n\n".join(f"**s.{n['pages']}**\n\n{n['summary']}" for n in notes)
        res.warnings.append("Bölüm özetleri birleştirilemedi; bölüm bölüm gösteriliyor.")
    return res


# ---------------------------------------------------------------------------- fatura


class InvoiceLine(BaseModel):
    description: str
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = Field(None, description="Line total without VAT")


class Invoice(BaseModel):
    seller: str | None = Field(None, description="Issuing company name")
    buyer: str | None = Field(None, description="Customer name")
    invoice_no: str | None = None
    date: str | None = Field(None, description="Invoice date as YYYY-MM-DD")
    due_date: str | None = Field(None, description="Due date as YYYY-MM-DD")
    currency: str | None = Field(None, description="e.g. TRY, USD, EUR")
    lines: list[InvoiceLine] = Field(default_factory=list)
    subtotal: float | None = Field(None, description="Total without VAT (matrah)")
    vat_rate: float | None = Field(None, description="VAT percentage, e.g. 20")
    vat: float | None = Field(None, description="VAT amount (KDV)")
    total: float | None = Field(None, description="Grand total including VAT (genel toplam / ödenecek)")


class InvoiceWorker(LLMWorker):
    name: ClassVar[str] = "business.invoice"
    description: ClassVar[str] = "Fatura metninden alanları çıkarır"
    required_permissions: ClassVar[tuple[Permission, ...]] = (Permission.LLM_INFERENCE,)
    output_model: ClassVar[type[BaseModel]] = Invoice
    system_prompt: ClassVar[str] = (
        "You extract fields from an invoice text (Turkish e-Fatura or other). Copy values exactly as they appear; "
        "convert numbers to plain numbers (1.234,56 → 1234.56) and dates to YYYY-MM-DD. Use null for anything that "
        "is not in the text — never guess. 'Mal Hizmet Toplam Tutarı'/'Matrah' is the subtotal, 'Hesaplanan KDV' is "
        "the VAT, 'Vergiler Dahil Toplam'/'Ödenecek Tutar' is the total."
    )

    def model_spec(self, registry: ModelRegistry):  # -> ModelSpec
        return registry.model_for_worker("general")

    def validate(self, task: Task, output: BaseModel) -> ValidationResult:
        assert isinstance(output, Invoice)
        errors = []
        if output.total is None and output.subtotal is None:
            errors.append("total ya da subtotal bulunamadı; metinde 'Toplam', 'Ödenecek', 'Matrah' satırlarına bak")
        for name in ("date", "due_date"):
            v = getattr(output, name)
            if v:
                try:
                    date.fromisoformat(v)
                except ValueError:
                    errors.append(f"{name} YYYY-MM-DD olmalı (gelen: {v!r})")
        return ValidationResult(passed=not errors, validator="business.invoice", errors=errors)


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=0.005, abs_tol=0.05)


def check_invoice(inv: Invoice, source_text: str) -> list[str]:
    """Kodla tutarlılık denetimi; boş liste = tutarlı."""
    warnings: list[str] = []
    amounts = [ln.amount for ln in inv.lines if ln.amount is not None]
    if amounts and inv.subtotal is not None and not _close(sum(amounts), inv.subtotal):
        warnings.append(f"Satır toplamı ({fmt(sum(amounts))}) ara toplamla ({fmt(inv.subtotal)}) uyuşmuyor.")
    for ln in inv.lines:
        if None not in (ln.quantity, ln.unit_price, ln.amount) and not _close(ln.quantity * ln.unit_price, ln.amount):  # type: ignore[operator]
            warnings.append(f"'{ln.description[:40]}': miktar × birim fiyat ≠ satır tutarı.")
    if None not in (inv.subtotal, inv.vat, inv.total) and not _close(inv.subtotal + inv.vat, inv.total):  # type: ignore[operator]
        warnings.append(f"Ara toplam + KDV ({fmt(inv.subtotal + inv.vat)}) toplamla ({fmt(inv.total)}) uyuşmuyor.")  # type: ignore[operator]
    if inv.subtotal and inv.vat is not None:
        rate = 100 * inv.vat / inv.subtotal
        if not any(abs(rate - r) < 0.6 for r in VAT_RATES):
            warnings.append(f"KDV oranı alışılmadık: %{fmt(round(rate, 2))}.")
    in_text = numbers_in_text(source_text)
    for label, v in (("toplam", inv.total), ("ara toplam", inv.subtotal), ("KDV", inv.vat)):
        if v is not None and not any(_close(v, x) for x in in_text):
            warnings.append(f"{label} ({fmt(v)}) belge metninde bulunamadı — doğrula.")
    return warnings


class InvoiceResult(BaseModel):
    kind: Literal["invoice"] = "invoice"
    source: str
    invoice: Invoice | None = None
    warnings: list[str] = Field(default_factory=list)

    def markdown(self) -> str:
        if self.invoice is None:
            return "Fatura alanları çıkarılamadı."
        inv = self.invoice
        rows = [("Satıcı", inv.seller), ("Alıcı", inv.buyer), ("Fatura no", inv.invoice_no), ("Tarih", inv.date),
                ("Vade", inv.due_date), ("Para birimi", inv.currency), ("Ara toplam", fmt(inv.subtotal)),
                ("KDV oranı", f"%{fmt(inv.vat_rate)}" if inv.vat_rate is not None else None), ("KDV", fmt(inv.vat)),
                ("Genel toplam", fmt(inv.total))]
        md = "**Fatura**\n\n| Alan | Değer |\n|---|---|\n" + "\n".join(f"| {k} | {v or '—'} |" for k, v in rows)
        if inv.lines:
            md += "\n\n**Kalemler**\n\n| Açıklama | Miktar | Birim fiyat | Tutar |\n|---|---|---|---|\n" + "\n".join(
                f"| {ln.description} | {fmt(ln.quantity)} | {fmt(ln.unit_price)} | {fmt(ln.amount)} |" for ln in inv.lines)
        verdict = "Tutarlar kodla denetlendi: tutarlı." if not self.warnings else "Denetim uyarıları aşağıda."
        return f"{md}\n\n_Kaynak: {self.source} — {verdict}_"


def extract_invoice(rt: "Runtime", doc: PdfDoc) -> InvoiceResult:
    text = doc.text[:INVOICE_CHARS]
    res = InvoiceResult(source=doc.name)
    t = rt.orchestrator.ask("Bu faturanın alanlarını çıkar.", worker="business.invoice", input={"invoice_text": text})
    if not t.result or "raw_output" in t.result:
        res.warnings.append(f"Fatura alanları çıkarılamadı: {t.error}")
        return res
    res.invoice = Invoice.model_validate(t.result)
    if t.status.value != "succeeded":
        res.warnings.append("Model çıktısı doğrulamadan tam geçmedi; alanları kontrol et.")
    res.warnings += check_invoice(res.invoice, doc.text)
    return res
