"""Excel/CSV analizi (Adım 10, kabul #7) — "sayıları kod hesaplar".

1. Kod tabloyu profiller (sütunlar, türler, boşlar, toplam/ortalama/min/maks, örnek satırlar).
2. Yerel model (data ajanının modeli) soruya göre bir **AnalysisPlan** yazar: yalnızca sabit işlem kümesi
   (süz, grupla, topla/ortalama/say/min/maks, sırala, ilk N, dönem). Plan şema + KODLA doğrulanır (sütunlar var mı,
   sayısal mı) — geçersizse model geri bildirimle yeniden yazar.
3. Kod planı yürütür. Hiçbir kod/formül çalıştırılmaz; model hiçbir sayıyı kendisi üretmez.
4. Model sonuç tablolarından kısa yorum yazar; yorumdaki her sayı hesaplanan değerlerde var mı KODLA denetlenir
   (Adım 7'deki "kanıt" fikri) — yoksa model düzeltir; yine de kalırsa uyarı olarak gösterilir.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from pydantic import BaseModel, Field

from ..core.task import Permission, Task, ValidationResult
from ..llm.registry import ModelRegistry
from ..workers.base import LLMWorker
from ..workers.general import GeneralWorker
from .numbers import fmt, numbers_in_text, parse_number
from .readers import Table

if TYPE_CHECKING:
    from ..runtime import Runtime

Agg = Literal["sum", "mean", "count", "min", "max"]
AGG_LABEL = {"sum": "Toplam", "mean": "Ortalama", "count": "Adet", "min": "En düşük", "max": "En yüksek"}
MAX_RESULT_ROWS = 50


class AnalysisError(ValueError):
    pass


# ---------------------------------------------------------------------------- profil


def profile(t: Table, sample_rows: int = 5) -> dict[str, Any]:
    cols = []
    for j, (name, typ) in enumerate(zip(t.columns, t.types)):
        vals = [r[j] for r in t.rows if r[j] is not None]
        c: dict[str, Any] = {"name": name, "type": typ, "non_empty": len(vals), "empty": len(t.rows) - len(vals)}
        if typ == "number" and vals:
            nums = [float(v) for v in vals if isinstance(v, (int, float))]
            if nums:
                c.update(sum=round(sum(nums), 4), mean=round(sum(nums) / len(nums), 4), min=min(nums), max=max(nums))
        elif typ == "date" and vals:
            c.update(first=min(map(str, vals)), last=max(map(str, vals)))
        elif typ == "text" and vals:
            counts: dict[str, int] = defaultdict(int)
            for v in vals:
                counts[str(v)] += 1
            c["distinct"] = len(counts)
            c["top_values"] = sorted(counts.items(), key=lambda kv: -kv[1])[:5]
        cols.append(c)
    return {"sheet": t.name, "rows": len(t.rows), "truncated": t.truncated, "columns": cols,
            "sample_rows": [dict(zip(t.columns, r)) for r in t.rows[:sample_rows]]}


# ---------------------------------------------------------------------------- plan şeması


class Filter(BaseModel):
    column: str = Field(description="Exact column name")
    op: Literal["=", "!=", ">", ">=", "<", "<=", "contains"]
    value: str = Field(description="Value to compare with (as text)")


class Metric(BaseModel):
    agg: Agg
    column: str | None = Field(None, description="Numeric column to aggregate; null only for agg 'count'")


class Operation(BaseModel):
    title: str = Field(description="Short title of this result table, in the user's language")
    filters: list[Filter] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list, description="0-2 column names to group by")
    period: Literal["day", "month", "quarter", "year"] | None = Field(
        None, description="If a group_by column is a date column: group dates by this period")
    metrics: list[Metric] = Field(description="1-4 aggregations")
    sort: Literal["metric_desc", "metric_asc", "group_asc"] = "metric_desc"
    limit: int | None = Field(None, description="Top N rows (1-50), null for all")


class AnalysisPlan(BaseModel):
    sheet: str | None = Field(None, description="Sheet name to use (null = first sheet)")
    operations: list[Operation] = Field(description="1-4 operations that answer the question")


class ResultTable(BaseModel):
    title: str
    columns: list[str]
    rows: list[list[Any]]
    total_rows: int


def validate_plan(plan: AnalysisPlan, tables: list[Table]) -> list[str]:
    errors: list[str] = []
    t = pick_table(plan, tables, strict=False)
    if t is None:
        return [f"bilinmeyen sayfa: {plan.sheet!r}; sayfalar: {[x.name for x in tables]}"]
    if not 1 <= len(plan.operations) <= 4:
        errors.append("1-4 işlem olmalı")
    cols = {c: typ for c, typ in zip(t.columns, t.types)}

    def check_col(name: str | None, where: str) -> str | None:
        if name is None:
            return None
        j = t.column_index(name)
        if j is None:
            errors.append(f"{where}: bilinmeyen sütun {name!r}; sütunlar: {t.columns}")
            return None
        return t.types[j]

    for i, op in enumerate(plan.operations, 1):
        if not 1 <= len(op.metrics) <= 4:
            errors.append(f"işlem {i}: 1-4 metrik olmalı")
        if len(op.group_by) > 2:
            errors.append(f"işlem {i}: en fazla 2 gruplama sütunu")
        if op.limit is not None and not 1 <= op.limit <= MAX_RESULT_ROWS:
            errors.append(f"işlem {i}: limit 1-{MAX_RESULT_ROWS} olmalı")
        for f in op.filters:
            typ = check_col(f.column, f"işlem {i} süzgeç")
            if typ == "number" and f.op != "contains" and parse_number(f.value) is None:
                errors.append(f"işlem {i}: {f.column!r} sayısal; süzgeç değeri sayı olmalı ({f.value!r})")
        gtypes = [check_col(g, f"işlem {i} gruplama") for g in op.group_by]
        if op.period and "date" not in gtypes:
            errors.append(f"işlem {i}: 'period' yalnızca tarih sütunuyla gruplarken kullanılır")
        for m in op.metrics:
            if m.agg == "count":
                check_col(m.column, f"işlem {i} metrik")
                continue
            if m.column is None:
                errors.append(f"işlem {i}: {m.agg} için sütun gerekli")
                continue
            typ = check_col(m.column, f"işlem {i} metrik")
            if typ is not None and typ != "number":
                errors.append(f"işlem {i}: {m.agg} için {m.column!r} sayısal değil (türü: {typ}); sayısal sütunlar: "
                              f"{[c for c, ty in cols.items() if ty == 'number']}")
    return errors


def pick_table(plan: AnalysisPlan, tables: list[Table], strict: bool = True) -> Table | None:
    if not plan.sheet:
        return tables[0]
    for t in tables:
        if t.name.strip().lower() == plan.sheet.strip().lower():
            return t
    if strict:
        raise AnalysisError(f"Sayfa bulunamadı: {plan.sheet}")
    return None


# ---------------------------------------------------------------------------- yürütme


def _period(v: Any, period: str | None) -> Any:
    if not period or not isinstance(v, str) or len(v) < 7:
        return v
    try:
        d = date.fromisoformat(v[:10])
    except ValueError:
        return v
    if period == "year":
        return str(d.year)
    if period == "quarter":
        return f"{d.year}-Ç{(d.month - 1) // 3 + 1}"
    if period == "month":
        return f"{d.year}-{d.month:02d}"
    return d.isoformat()


def _match(cell: Any, f: Filter, typ: str) -> bool:
    if cell is None:
        return False
    if f.op == "contains":
        return str(f.value).casefold() in str(cell).casefold()
    if typ == "number":
        a, b = float(cell), parse_number(f.value)
        if b is None:
            return False
    elif typ == "date":
        a, b = str(cell)[:10], str(f.value)[:10]
    else:
        a, b = str(cell).casefold().strip(), str(f.value).casefold().strip()
    return {"=": a == b, "!=": a != b, ">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b}[f.op]  # type: ignore[operator]


def _agg(values: list[float], agg: str, n_rows: int) -> float | None:
    if agg == "count":
        return float(len(values))
    if not values:
        return None
    if agg == "sum":
        return round(sum(values), 6)
    if agg == "mean":
        return round(sum(values) / len(values), 6)
    return min(values) if agg == "min" else max(values)


def execute(plan: AnalysisPlan, tables: list[Table]) -> list[ResultTable]:
    errors = validate_plan(plan, tables)
    if errors:
        raise AnalysisError("; ".join(errors))
    t = pick_table(plan, tables)
    assert t is not None
    results = []
    for op in plan.operations:
        rows = t.rows
        for f in op.filters:
            j = t.column_index(f.column)
            assert j is not None
            rows = [r for r in rows if _match(r[j], f, t.types[j])]
        gidx = [t.column_index(g) for g in op.group_by]
        groups: dict[tuple, list[list[Any]]] = defaultdict(list)
        for r in rows:
            key = tuple(_period(r[j], op.period if t.types[j] == "date" else None) for j in gidx if j is not None)
            groups[key].append(r)
        if not gidx:
            groups = {(): rows}
        metric_names = []
        for m in op.metrics:
            name = AGG_LABEL[m.agg] + (f" ({t.columns[t.column_index(m.column)]})" if m.column else "")  # type: ignore[index]
            metric_names.append(name)
        out_rows = []
        for key, grp in groups.items():
            vals = []
            for m in op.metrics:
                if m.agg == "count" and m.column is None:
                    vals.append(float(len(grp)))
                    continue
                j = t.column_index(m.column or "")
                col = [r[j] for r in grp if j is not None and r[j] is not None]
                nums = [float(v) for v in col if isinstance(v, (int, float))]
                vals.append(float(len(col)) if m.agg == "count" else _agg(nums, m.agg, len(grp)))
            out_rows.append([*["(boş)" if k is None else k for k in key], *vals])
        ng = len(gidx)
        if op.sort == "group_asc":
            out_rows.sort(key=lambda r: tuple(str(x) for x in r[:ng]))
        elif ng:
            out_rows.sort(key=lambda r: (r[ng] is None, (r[ng] or 0) * (-1 if op.sort == "metric_desc" else 1)))
        columns = [t.columns[j] for j in gidx if j is not None] + metric_names
        # Tek toplam metrikli gruplamada payı (yüzde) da ver: iş raporlarında en çok sorulan şey
        if ng and len(op.metrics) == 1 and op.metrics[0].agg in ("sum", "count"):
            total = sum(r[ng] or 0 for r in out_rows)
            if total:
                columns.append("Pay (%)")
                for r in out_rows:
                    r.append(round(100 * (r[ng] or 0) / total, 2))
        total_rows = len(out_rows)
        limit = min(op.limit or MAX_RESULT_ROWS, MAX_RESULT_ROWS)
        results.append(ResultTable(title=op.title, columns=columns, rows=out_rows[:limit], total_rows=total_rows))
    return results


def result_markdown(r: ResultTable) -> str:
    head = "| " + " | ".join(r.columns) + " |\n|" + "---|" * len(r.columns) + "\n"
    body = "\n".join("| " + " | ".join(fmt(v) if isinstance(v, float) else str(v) for v in row) + " |" for row in r.rows)
    more = f"\n\n_(ilk {len(r.rows)} / {r.total_rows} satır)_" if r.total_rows > len(r.rows) else ""
    return f"**{r.title}**\n\n{head}{body}{more}"


# ---------------------------------------------------------------------------- sayı denetimi


def allowed_numbers(results: list[ResultTable], prof: dict[str, Any], question: str) -> list[float]:
    vals: list[float] = list(numbers_in_text(question))
    for r in results:
        vals.append(float(r.total_rows))
        for row in r.rows:
            vals += [float(v) for v in row if isinstance(v, (int, float)) and not isinstance(v, bool)]
            vals += [x for v in row if isinstance(v, str) for x in numbers_in_text(v)]
    vals.append(float(prof.get("rows", 0)))
    for c in prof.get("columns", []):
        vals += [float(c[k]) for k in ("sum", "mean", "min", "max", "non_empty", "empty", "distinct") if k in c]
    return vals


def unverified_numbers(text: str, allowed: list[float]) -> list[float]:
    """Metinde geçen ama hesaplanan değerlerde olmayan sayılar. Küçük tam sayılar (≤31: sıra, ay, gün) ve yıllar muaf;
    yuvarlama payı: %0.6 ya da 0.01."""
    bad = []
    for v in numbers_in_text(text):
        if float(v).is_integer() and (abs(v) <= 31 or 1900 <= v <= 2100):
            continue
        if any(math.isclose(v, a, rel_tol=0.006, abs_tol=0.011) or math.isclose(v, round(a, 1), abs_tol=0.051)
               or math.isclose(v, round(a), abs_tol=0.51) for a in allowed):
            continue
        bad.append(v)
    return list(dict.fromkeys(bad))


# ---------------------------------------------------------------------------- iç worker'lar


# Gerçek ölçüm (Windows, business_check 2026-10-31): "En çok satış getiren ürün hangisi?" → model ürün başına max(Tutar)
# planladı (tek satışın en büyüğü). "En çok satan/getiren/toplam/ciro" toplam ister; tek kayıt ifadesi yoksa max/min hatadır.
_TOTAL_HINTS = ("getir", "satan", "satıl", "toplam", "ciro", "gelir", "kazandır", "most sold", "top-selling", "top selling",
                "best-selling", "best selling", "revenue", "total", "sales by", "in total")
_SINGLE_HINTS = ("tek ", "tek satış", "tek işlem", "en pahalı", "en ucuz", "en büyük tek", "en küçük tek", "birim fiyat",
                 "single", "largest single", "most expensive", "cheapest", "highest price", "lowest price")


def total_intent_errors(question: str, plan: AnalysisPlan) -> list[str]:
    """Soru toplam istiyorsa gruplu işlemde max/min kullanılmasını yakalar (kodla, dil bağımsız ek köklerle)."""
    q = question.casefold()
    if not any(h in q for h in _TOTAL_HINTS) or any(h in q for h in _SINGLE_HINTS):
        return []
    errors = []
    for i, op in enumerate(plan.operations, 1):
        if op.group_by and op.metrics and all(m.agg in ("max", "min") for m in op.metrics):
            errors.append(f"işlem {i}: soru grup başına TOPLAMI soruyor ('en çok satan/getiren', 'toplam'); "
                          "max/min tek bir kaydın değerini verir — agg 'sum' kullan")
    return errors


class PlanWorker(LLMWorker):
    name: ClassVar[str] = "business.plan"
    description: ClassVar[str] = "Tablo sorusunu sabit işlem kümesiyle bir analiz planına çevirir"
    required_permissions: ClassVar[tuple[Permission, ...]] = (Permission.LLM_INFERENCE,)
    output_model: ClassVar[type[BaseModel]] = AnalysisPlan
    system_prompt: ClassVar[str] = (
        "You are the data analyst planner of kayaAI. The input data contains a table profile (sheets, columns with "
        "types, statistics, sample rows). Turn the user's question into an analysis plan using ONLY the allowed "
        "operations: filters, group_by (max 2 columns; for date columns choose a period), metrics (sum, mean, count, "
        "min, max over NUMERIC columns; count may have column null), sort and limit. Use exact column names from "
        "the profile. You do not compute anything yourself — the program executes the plan. If the question is "
        "general ('analyse this', 'özetle'), give 2-3 useful operations (e.g. totals by the main category, by month). "
        "IMPORTANT: 'en çok satan / en çok getiren / en fazla gelir / toplam / ciro / most sold / top-selling / revenue' "
        "means the TOTAL per group: use agg 'sum' with group_by and sort metric_desc. Use 'max'/'min' only when the "
        "question asks for a single record (e.g. 'en büyük tek satış', 'en pahalı', 'single largest'). "
        "Write titles in the user's language."
    )

    def model_spec(self, registry: ModelRegistry):  # -> ModelSpec
        return registry.model_for_worker("general")

    def validate(self, task: Task, output: BaseModel) -> ValidationResult:
        assert isinstance(output, AnalysisPlan)
        tables = [Table.model_validate(t) for t in task.input.get("_tables", [])]
        errors = validate_plan(output, tables) if tables else []
        errors += total_intent_errors(task.objective, output)
        return ValidationResult(passed=not errors, validator="business.plan", errors=errors)

    def build_messages(self, task: Task) -> list[dict[str, str]]:
        # Tablo verisinin tamamı doğrulama için girdide; modele yalnızca profil gider (bağlam ve gizlilik)
        visible = Task(**{**task.model_dump(), "input": {k: v for k, v in task.input.items() if not k.startswith("_")}})
        return super().build_messages(visible)


class NarrateWorker(GeneralWorker):
    name: ClassVar[str] = "business.narrate"
    description: ClassVar[str] = "Hesaplanmış sonuç tablolarını yorumlar (sayı uydurmaz)"
    system_prompt: ClassVar[str] = (
        "You are the data analyst of kayaAI. The input data contains RESULT TABLES computed by the program from the "
        "user's file. Answer the user's question in 3-6 short sentences or bullet points, in the user's language: the "
        "main findings, the largest/smallest items, notable shares or changes. Use ONLY numbers that appear in the "
        "result tables (you may round them). Never compute new numbers yourself and never invent data. Do not repeat "
        "the tables; they are shown to the user separately."
    )

    def model_spec(self, registry: ModelRegistry):  # -> ModelSpec
        return registry.model_for_worker("general")

    def validate(self, task: Task, output: BaseModel) -> ValidationResult:
        base = super().validate(task, output)
        allowed = [float(x) for x in task.input.get("_allowed_numbers", [])]
        bad = unverified_numbers(getattr(output, "answer", ""), allowed) if allowed else []
        errors = list(base.errors)
        if bad:
            errors.append("cevapta sonuç tablolarında OLMAYAN sayılar var: " + ", ".join(fmt(b) for b in bad[:6])
                          + ". Yalnızca tablolardaki sayıları kullan.")
        return ValidationResult(passed=not errors, validator="business.narrate", errors=errors)

    def build_messages(self, task: Task) -> list[dict[str, str]]:
        visible = Task(**{**task.model_dump(), "input": {k: v for k, v in task.input.items() if not k.startswith("_")}})
        return super().build_messages(visible)


# ---------------------------------------------------------------------------- uçtan uca


class AnalysisResult(BaseModel):
    kind: Literal["analysis"] = "analysis"
    source: str
    question: str
    sheet: str
    profile: dict[str, Any]
    plan: AnalysisPlan | None = None
    results: list[ResultTable] = Field(default_factory=list)
    narrative: str = ""
    unverified_numbers: list[float] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def markdown(self) -> str:
        parts = [self.narrative.strip()] if self.narrative.strip() else []
        parts += [result_markdown(r) for r in self.results]
        if not self.results:
            parts.append(profile_markdown(self.profile))
        parts.append(f"_Kaynak: {self.source} · sayfa {self.sheet} · {self.profile.get('rows', 0)} satır — "
                     "tüm sayılar programla hesaplandı._")
        return "\n\n".join(parts)


def profile_markdown(prof: dict[str, Any]) -> str:
    lines = ["| Sütun | Tür | Dolu | Toplam | Ortalama | En düşük | En yüksek |", "|---|---|---|---|---|---|---|"]
    tr = {"number": "sayı", "date": "tarih", "text": "metin", "empty": "boş"}
    for c in prof.get("columns", []):
        lines.append(f"| {c['name']} | {tr.get(c['type'], c['type'])} | {c['non_empty']} | {fmt(c.get('sum'))} | "
                     f"{fmt(c.get('mean'))} | {fmt(c.get('min'))} | {fmt(c.get('max'))} |")
    return "**Tablo profili**\n\n" + "\n".join(lines)


def analyze(rt: "Runtime", tables: list[Table], question: str, source: str) -> AnalysisResult:
    """Plan (model) → yürütme (kod) → yorum (model, sayı denetimli). Model başarısız olursa profil + uyarı döner."""
    if not tables:
        raise AnalysisError("Tablo yok")
    question = question.strip() or "Bu tabloyu analiz et ve öne çıkanları özetle."
    profiles = [profile(t) for t in tables[:5]]
    res = AnalysisResult(source=source, question=question, sheet=tables[0].name, profile=profiles[0])
    plan_task = rt.orchestrator.ask(question, worker="business.plan", input={
        "tables": profiles, "_tables": [t.model_dump() for t in tables[:5]]})
    if plan_task.status.value != "succeeded" or not plan_task.result:
        res.warnings.append("Analiz planı oluşturulamadı; tablonun genel profili gösteriliyor.")
        return res
    plan = AnalysisPlan.model_validate(plan_task.result)
    try:
        results = execute(plan, tables)
    except AnalysisError as exc:
        res.warnings.append(f"Plan yürütülemedi: {exc}")
        return res
    table = pick_table(plan, tables)
    assert table is not None
    res.plan, res.results, res.sheet = plan, results, table.name
    res.profile = profile(table)
    allowed = allowed_numbers(results, res.profile, question)
    narr = rt.orchestrator.ask(question, worker="business.narrate", input={
        "result_tables": [{"title": r.title, "columns": r.columns,
                           "rows": [[fmt(v) if isinstance(v, float) else v for v in row] for row in r.rows]}
                          for r in results],
        "_allowed_numbers": allowed})
    if narr.status.value == "succeeded" and narr.result:
        res.narrative = str(narr.result.get("answer", ""))
    else:
        # Son denemede de uydurma sayı kaldıysa: metni yine göster ama sayıları işaretle
        last = narr.result or {}
        text = str(last.get("answer", "")) if isinstance(last, dict) else ""
        if text:
            res.narrative = text
        res.warnings.append("Yorum doğrulanamadı; tablolar programla hesaplandı, yorumu dikkatle oku.")
    res.unverified_numbers = unverified_numbers(res.narrative, allowed)
    if res.unverified_numbers:
        res.warnings.append("Yorumda tablolarda olmayan sayı(lar) var: " + ", ".join(fmt(v) for v in res.unverified_numbers[:5]))
    return res


def plan_json(plan: AnalysisPlan | None) -> str:
    return json.dumps(plan.model_dump() if plan else {}, ensure_ascii=False)
