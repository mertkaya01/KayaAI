"""PDF ve tablo (Excel/CSV) okuyucular (Adım 10). Yerel kütüphaneler: pypdf (BSD-3), openpyxl (MIT).

Hiçbir dosya içeriği çalıştırılmaz: Excel formülleri hesaplanmaz, dosyada kayıtlı son değerler okunur (data_only);
makrolar yok sayılır. Taranmış (görüntü) PDF metin içermez → açık hata; OCR Adım 12'de.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .numbers import parse_number

MAX_ROWS = 50_000
PDF_SUFFIXES = {".pdf"}
TABLE_SUFFIXES = {".xlsx", ".xlsm", ".csv", ".tsv"}
BINARY_SUFFIXES = PDF_SUFFIXES | {".xlsx", ".xlsm"}
ColumnType = Literal["number", "date", "text", "empty"]


class ReadError(ValueError):
    pass


class PdfDoc(BaseModel):
    name: str
    pages: list[str]
    ocr: bool = False  # Adım 12a: taranmış PDF, sayfalar OCR ile okundu

    @property
    def text(self) -> str:
        return "\n\n".join(f"[s.{i}]\n{t}" for i, t in enumerate(self.pages, 1) if t.strip())


class Table(BaseModel):
    name: str                       # sayfa adı (CSV'de dosya adı)
    columns: list[str]
    types: list[ColumnType] = Field(default_factory=list)
    rows: list[list[Any]]          # sayı sütunları float, tarih sütunları ISO tarih (str), metin str, boş None
    truncated: bool = False

    def column_index(self, name: str) -> int | None:
        key = _norm(name)
        for i, c in enumerate(self.columns):
            if _norm(c) == key:
                return i
        return None


def _norm(s: str) -> str:
    return " ".join(str(s).replace("İ", "i").replace("I", "ı").lower().split())


# ---------------------------------------------------------------------------- PDF


def read_pdf(data: bytes, name: str = "belge.pdf") -> PdfDoc:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                if not reader.decrypt(""):
                    raise ReadError(f"{name} parola korumalı; parolasız bir kopyasını ekle.")
            except Exception as exc:  # noqa: BLE001 - pypdf şifre çözme hataları çeşitli
                raise ReadError(f"{name} parola korumalı; parolasız bir kopyasını ekle.") from exc
        pages = [(p.extract_text() or "").strip() for p in reader.pages]
    except ReadError:
        raise
    except (PdfReadError, ValueError, KeyError, OSError) as exc:
        raise ReadError(f"{name} okunamadı (bozuk ya da desteklenmeyen PDF): {exc}") from exc
    if not any(len(p) > 20 for p in pages):
        return _read_scanned_pdf(data, name)
    return PdfDoc(name=name, pages=pages)


def _read_scanned_pdf(data: bytes, name: str) -> PdfDoc:
    """Metinsiz (taranmış) PDF: sayfalar görüntüye çevrilip OCR'dan geçirilir (Adım 12a; Windows OCR)."""
    from ..perception.ocr import OcrUnavailable, available, ocr_pdf

    ok, why = available()
    if not ok:
        raise ReadError(f"{name} metin içermiyor (taranmış/görüntü PDF). Görüntüden okuma için OCR gerekli: {why}")
    try:
        pages = ocr_pdf(data)
    except OcrUnavailable as exc:
        raise ReadError(f"{name} metin içermiyor (taranmış PDF); OCR çalışmadı: {exc}") from exc
    except ValueError as exc:
        raise ReadError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - pypdfium2 hataları çeşitli
        raise ReadError(f"{name} sayfaları görüntüye çevrilemedi: {exc}") from exc
    if not any(len(p) > 20 for p in pages):
        raise ReadError(f"{name} metin içermiyor (taranmış PDF); OCR da okunabilir yazı bulamadı "
                        "(boş sayfa ya da çözünürlük düşük olabilir)")
    return PdfDoc(name=name, pages=pages, ocr=True)


# ---------------------------------------------------------------------------- tablolar


def _cell(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date().isoformat() if v.time() == datetime.min.time() else v.isoformat(sep=" ", timespec="minutes")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def _parse_date(s: Any) -> str | None:
    if not isinstance(s, str):
        return None
    for f in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M", "%Y-%m"):
        try:
            return datetime.strptime(s, f).date().isoformat()
        except ValueError:
            continue
    return None


def _finish(name: str, raw: list[list[Any]], truncated: bool) -> Table:
    raw = [r for r in raw if any(c is not None and str(c).strip() for c in r)]
    if not raw:
        raise ReadError(f"{name}: boş tablo")
    width = max(len(r) for r in raw)
    header = [str(c).strip() if c is not None and str(c).strip() else f"Sütun {i + 1}" for i, c in
              enumerate(raw[0] + [None] * (width - len(raw[0])))]
    seen: dict[str, int] = {}
    for i, h in enumerate(header):
        k = _norm(h)
        if k in seen:
            seen[k] += 1
            header[i] = f"{h} ({seen[k]})"
        else:
            seen[k] = 1
    body = [list(r) + [None] * (width - len(r)) for r in raw[1:]]
    types: list[ColumnType] = []
    for j in range(width):
        vals = [r[j] for r in body if r[j] is not None]
        if not vals:
            types.append("empty")
            continue
        nums = sum(1 for v in vals if parse_number(v) is not None)
        dates = sum(1 for v in vals if _parse_date(v))
        if nums >= 0.8 * len(vals):
            types.append("number")
        elif dates >= 0.8 * len(vals):
            types.append("date")
        else:
            types.append("text")
    for r in body:
        for j, t in enumerate(types):
            if r[j] is None:
                continue
            if t == "number":
                r[j] = parse_number(r[j])
            elif t == "date":
                r[j] = _parse_date(r[j]) or r[j]
            else:
                r[j] = str(r[j])
    return Table(name=name, columns=header, types=types, rows=body, truncated=truncated)


def read_xlsx(data: bytes, name: str = "tablo.xlsx") -> list[Table]:
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - openpyxl çeşitli hata türleri fırlatır
        raise ReadError(f"{name} okunamadı (bozuk ya da eski .xls olabilir; Excel'de .xlsx olarak kaydet): {exc}") from exc
    tables = []
    try:
        for ws in wb.worksheets:
            raw: list[list[Any]] = []
            truncated = False
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i > MAX_ROWS:
                    truncated = True
                    break
                raw.append([_cell(v) for v in row])
            try:
                tables.append(_finish(ws.title, raw, truncated))
            except ReadError:
                continue  # boş sayfa
    finally:
        wb.close()
    if not tables:
        raise ReadError(f"{name}: içinde veri olan sayfa yok")
    return tables


def read_csv(data: bytes, name: str = "tablo.csv") -> list[Table]:
    for enc in ("utf-8-sig", "cp1254", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:5000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delim = dialect.delimiter
    except csv.Error:
        delim = ";" if sample.count(";") > sample.count(",") else ","
    raw: list[list[Any]] = []
    truncated = False
    for i, row in enumerate(csv.reader(io.StringIO(text), delimiter=delim)):
        if i > MAX_ROWS:
            truncated = True
            break
        raw.append([_cell(c) for c in row])
    return [_finish(Path(name).stem, raw, truncated)]


def read_table(data: bytes, name: str) -> list[Table]:
    suffix = Path(name).suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        return read_xlsx(data, name)
    if suffix in (".csv", ".tsv"):
        return read_csv(data, name)
    if suffix == ".xls":
        raise ReadError("Eski .xls biçimi okunamıyor; Excel'de 'Farklı kaydet → .xlsx' yap.")
    raise ReadError(f"Tablo değil: {name}")


def table_to_text(t: Table, max_rows: int = 200) -> str:
    """Bağlam/dizin için düz metin (noktalı virgülle ayrılmış)."""
    from .numbers import fmt

    lines = [f"[{t.name}] " + " ; ".join(t.columns)]
    for r in t.rows[:max_rows]:
        lines.append(" ; ".join("" if v is None else fmt(v) if isinstance(v, float) else str(v) for v in r))
    if len(t.rows) > max_rows:
        lines.append(f"… ({len(t.rows) - max_rows} satır daha)")
    return "\n".join(lines)


def extract_text(data: bytes, name: str) -> tuple[str, Literal["pdf", "table"]]:
    """Ek/dizin için metin: PDF sayfa işaretli, tablo satır satır."""
    suffix = Path(name).suffix.lower()
    if suffix in PDF_SUFFIXES:
        return read_pdf(data, name).text, "pdf"
    return "\n\n".join(table_to_text(t) for t in read_table(data, name)), "table"
