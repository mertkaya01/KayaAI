"""Deterministik cevap kontrolleri (Adım 7). Hiçbir kod ÇALIŞTIRILMAZ — yalnızca ayrıştırılır.

`code_syntax`: cevaptaki çitli kod bloklarından Python (`ast.parse`), JSON (`json.loads`) ve YAML (`yaml.safe_load`)
ayrıştırılır. Diğer diller atlanır ve "kontrol edilmedi" olarak sayılır. Bir kontrol hatası kanıttır: üretici ajan
buna itiraz edemez, düzeltmek zorundadır.
"""

from __future__ import annotations

import ast
import json
import re
from typing import Literal

import yaml
from pydantic import BaseModel, Field

CheckName = Literal["code_syntax"]

FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_+#.-]*)[^\n]*\n(.*?)```", re.DOTALL)
PYTHON = {"python", "py", "python3"}
JSON = {"json"}
YAML = {"yaml", "yml"}


class CheckFailure(BaseModel):
    check: str
    block: int
    language: str
    message: str


class CheckReport(BaseModel):
    checked_blocks: int = 0
    skipped_blocks: int = 0
    skipped_languages: list[str] = Field(default_factory=list)
    failures: list[CheckFailure] = Field(default_factory=list)


def code_blocks(text: str) -> list[tuple[str, str]]:
    return [(m.group(1).lower(), m.group(2)) for m in FENCE.finditer(text)]


def _syntax_error(lang: str, code: str) -> str | None | Literal[False]:
    """Hata mesajı; None = geçerli; False = bu dil kontrol edilmez."""
    if lang in PYTHON:
        if ">>>" in code:  # etkileşimli oturum dökümü, kaynak kod değil
            return False
        try:
            ast.parse(code)
        except SyntaxError as exc:
            return f"Python sözdizimi hatası, satır {exc.lineno}: {exc.msg}"
        return None
    if lang in JSON:
        try:
            json.loads(code)
        except json.JSONDecodeError as exc:
            return f"Geçersiz JSON, satır {exc.lineno}: {exc.msg}"
        return None
    if lang in YAML:
        try:
            yaml.safe_load(code)
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            where = f", satır {mark.line + 1}" if mark is not None else ""
            return f"Geçersiz YAML{where}: {getattr(exc, 'problem', None) or exc}"
        return None
    return False


def run_checks(answer: str, checks: list[str]) -> CheckReport:
    report = CheckReport()
    if "code_syntax" not in checks:
        return report
    for n, (lang, code) in enumerate(code_blocks(answer), 1):
        result = _syntax_error(lang, code)
        if result is False:
            report.skipped_blocks += 1
            if lang and lang not in report.skipped_languages:
                report.skipped_languages.append(lang)
            continue
        report.checked_blocks += 1
        if result:
            report.failures.append(CheckFailure(check="code_syntax", block=n, language=lang,
                                                message=f"{n}. kod bloğu: {result}"))
    return report
