"""İş modülleri (Adım 10): PDF özeti, Excel/CSV analizi, fatura çıkarma, iş raporu (md/xlsx/docx/pdf)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .analysis import AnalysisError, AnalysisResult, analyze
from .documents import InvoiceResult, SummaryResult, extract_invoice, summarize_pdf
from .readers import BINARY_SUFFIXES, PDF_SUFFIXES, TABLE_SUFFIXES, ReadError, read_pdf, read_table
from .report import FORMATS, Report, ReportError, from_markdown, from_result, render, save

if TYPE_CHECKING:
    from ..runtime import Runtime


def register_workers(workers: Any) -> None:
    """İç worker'lar (planlayıcıya/arayüze görünmez)."""
    from .analysis import NarrateWorker, PlanWorker
    from .documents import InvoiceWorker

    for w in (PlanWorker(), NarrateWorker(), InvoiceWorker()):
        if w.name not in workers:
            workers.register(w, internal=True)


def run_mode(rt: "Runtime", mode: str, data: bytes, name: str, question: str = "") -> AnalysisResult | SummaryResult | InvoiceResult:
    """Bir dosya üzerinde iş modülü: analyze (tablo) | summarize (PDF) | invoice (PDF)."""
    from pathlib import Path

    suffix = Path(name).suffix.lower()
    if mode == "analyze":
        if suffix not in TABLE_SUFFIXES:
            raise ReadError(f"Analiz için Excel/CSV dosyası gerekli ({name})")
        return analyze(rt, read_table(data, name), question, name)
    if suffix not in PDF_SUFFIXES:
        raise ReadError(f"Bu işlem için PDF gerekli ({name})")
    doc = read_pdf(data, name)
    if mode == "summarize":
        return summarize_pdf(rt, doc, question)
    if mode == "invoice":
        return extract_invoice(rt, doc)
    raise ValueError(f"Bilinmeyen işlem: {mode}")


__all__ = [
    "BINARY_SUFFIXES", "FORMATS", "PDF_SUFFIXES", "TABLE_SUFFIXES", "AnalysisError", "AnalysisResult", "InvoiceResult",
    "ReadError", "Report", "ReportError", "SummaryResult", "analyze", "extract_invoice", "from_markdown", "from_result",
    "read_pdf", "read_table", "register_workers", "render", "run_mode", "save", "summarize_pdf",
]
