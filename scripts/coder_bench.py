"""Kod ajanı için model karşılaştırması: qwen3:8b (general-8b) vs qwen2.5-coder:7b (coder-7b).

Kullanım (proje klasöründe, venv etkin):
    python scripts/coder_bench.py              # güvenli mod: kod ÇALIŞTIRILMAZ, söz dizimi + yapı kontrolü
    python scripts/coder_bench.py --execute    # üretilen kodu testlerle çalıştırır (onay ister)

--execute modunda model tarafından üretilen kod bu bilgisayarda çalışır. Önlemler: ayrı geçici klasör,
`python -I` (kullanıcı site-packages/ortam yok), 10 sn zaman aşımı, kısıtlı ortam değişkenleri.
Bu gerçek bir sandbox DEĞİLDİR; kod yalnızca basit saf fonksiyonlar istendiği için risk düşüktür.

Sonuç: data/coder_bench.json
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kayaai.config import load_settings  # noqa: E402
from kayaai.llm.ollama_client import OllamaClient, OllamaError  # noqa: E402
from kayaai.llm.registry import ModelRegistry  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

MODELS = ["general-8b", "coder-7b"]

# (fonksiyon adı, istek, test kodu)
TASKS = [
    ("is_palindrome",
     "Write a Python function is_palindrome(s: str) -> bool that ignores case, spaces and punctuation.",
     "assert is_palindrome('A man, a plan, a canal: Panama')\nassert not is_palindrome('kaya')\nassert is_palindrome('')"),
    ("fizzbuzz",
     "Write a Python function fizzbuzz(n: int) -> list[str] returning the FizzBuzz sequence from 1 to n.",
     "assert fizzbuzz(5) == ['1','2','Fizz','4','Buzz']\nassert fizzbuzz(15)[-1] == 'FizzBuzz'\nassert fizzbuzz(0) == []"),
    ("merge_intervals",
     "Write a Python function merge_intervals(intervals: list[list[int]]) -> list[list[int]] that merges "
     "overlapping intervals and returns them sorted.",
     "assert merge_intervals([[1,3],[2,6],[8,10]]) == [[1,6],[8,10]]\nassert merge_intervals([]) == []\n"
     "assert merge_intervals([[5,6],[1,2]]) == [[1,2],[5,6]]\nassert merge_intervals([[1,4],[4,5]]) == [[1,5]]"),
    ("word_count",
     "Türkçe: word_count(text: str) -> dict[str, int] adlı bir Python fonksiyonu yaz; kelimeleri küçük harfe "
     "çevirip noktalama işaretlerini yok sayarak sayar.",
     "assert word_count('Merhaba dünya, merhaba!') == {'merhaba': 2, 'dünya': 1}\nassert word_count('') == {}"),
    ("parse_duration",
     "Write a Python function parse_duration(s: str) -> int that converts strings like '1h30m', '45s', "
     "'2h', '1h2m3s' to total seconds. Raise ValueError for invalid input.",
     "assert parse_duration('1h30m') == 5400\nassert parse_duration('45s') == 45\nassert parse_duration('1h2m3s') == 3723\n"
     "try:\n    parse_duration('abc')\n    raise SystemExit('no ValueError')\nexcept ValueError:\n    pass"),
]

SYSTEM = "You are a precise Python programmer. Reply with ONLY one ```python code block containing the function. No tests, no prints."
CODE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


def extract_code(text: str) -> str:
    m = CODE_RE.search(text)
    return (m.group(1) if m else text).strip()


def static_check(code: str, func: str) -> tuple[bool, str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, f"SyntaxError: {exc}"
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    if func not in names:
        return False, f"'{func}' fonksiyonu yok (bulunan: {sorted(names)})"
    return True, "ok"


def run_tests(code: str, tests: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="kayaai_bench_") as d:
        path = Path(d) / "candidate.py"
        path.write_text(code + "\n\n" + tests + "\n", encoding="utf-8")
        env = {k: os.environ[k] for k in ("SYSTEMROOT", "PATH", "TEMP", "TMP") if k in os.environ}
        env["PYTHONUTF8"] = "1"
        try:
            r = subprocess.run([sys.executable, "-I", str(path)], cwd=d, env=env, capture_output=True,
                               text=True, timeout=10, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return False, "zaman aşımı (10 sn)"
        return r.returncode == 0, (r.stderr or r.stdout).strip()[-300:] or "ok"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="üretilen kodu testlerle çalıştır (onay ister)")
    ap.add_argument("--yes", action="store_true", help="--execute onayını sormadan kabul et")
    args = ap.parse_args()

    if args.execute and not args.yes:
        print("UYARI: --execute, modelin ürettiği Python kodunu bu bilgisayarda çalıştırır")
        print("(geçici klasör, python -I, 10 sn sınır; gerçek bir sandbox değildir).")
        if input("Devam edilsin mi? [e/H]: ").strip().lower() not in {"e", "evet", "y", "yes"}:
            print("İptal edildi. Güvenli modda çalıştırmak için --execute olmadan çalıştırın.")
            return 1

    settings = load_settings()
    registry = ModelRegistry.load_for(settings)
    client = OllamaClient(settings.ollama)
    report: dict = {"mode": "execute" if args.execute else "static", "models": {}}
    try:
        installed = {m.get("name") for m in client.list_models()}
    except OllamaError as exc:
        print(f"[HATA] Ollama'ya ulaşılamadı: {exc}")
        return 1

    for key in MODELS:
        spec = registry.get(key)
        if spec.name not in installed:
            print(f"[ATLANDI] {spec.name} kurulu değil (ollama pull {spec.name})")
            report["models"][key] = {"name": spec.name, "skipped": "not installed"}
            continue
        rows = []
        print(f"\n== {spec.name} ==")
        for func, prompt, tests in TASKS:
            t0 = time.perf_counter()
            try:
                res = client.chat(spec.name, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                                  options={**spec.ollama_options(), "temperature": 0.1}, think=spec.think,
                                  keep_alive=spec.keep_alive)
            except OllamaError as exc:
                rows.append({"task": func, "error": str(exc)})
                print(f"  {func:<16} HATA {exc}")
                continue
            code = extract_code(res.content)
            ok_static, static_msg = static_check(code, func)
            row = {"task": func, "static_ok": ok_static, "static_msg": static_msg,
                   "seconds": round(time.perf_counter() - t0, 2), "tokens_per_second": res.tokens_per_second}
            if args.execute and ok_static:
                row["tests_passed"], row["test_msg"] = run_tests(code, tests)
            rows.append(row)
            mark = row.get("tests_passed", ok_static)
            detail = static_msg if not ok_static else row.get("test_msg", "")
            detail = detail.strip().splitlines()[-1] if detail.strip() else ""
            print(f"  {func:<16} {'GEÇTİ' if mark else 'KALDI'}  {row['seconds']} sn  {detail[:90]}")
        scored = [r for r in rows if "error" not in r]
        key_field = "tests_passed" if args.execute else "static_ok"
        report["models"][key] = {
            "name": spec.name,
            "score": f"{sum(bool(r.get(key_field)) for r in scored)}/{len(TASKS)}",
            "avg_seconds": round(sum(r["seconds"] for r in scored) / len(scored), 2) if scored else None,
            "rows": rows,
        }
    client.close()

    out = settings.data_dir / "coder_bench.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nÖZET (" + ("testler çalıştırıldı" if args.execute else "yalnızca söz dizimi/yapı") + "):")
    for key, m in report["models"].items():
        print(f"  {m['name']:<18} {m.get('score', m.get('skipped'))}  ort. {m.get('avg_seconds')} sn")
    print(f"Rapor: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
