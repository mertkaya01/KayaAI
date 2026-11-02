"""`kayaai sandbox test` (Adım 19c): kum havuzu yalıtımını GERÇEK Docker'da denetler. Politika katmanı bilerek
atlanır (sabit deneme kodları doğrudan konteynerde çalışır) ki konteynerin kendisinin koruduğu görülsün.

Beklenen: hesap ve pandas çalışır; ağ yok; kök dosya sistemi salt-okunur; root değil; bellek ve süre sınırı işler;
yalnız verilen dosyalar görünür. Sonuç: data/sandbox_check.json
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from . import runner

CASES: list[tuple[str, str, str, dict[str, str]]] = [
    ("hesap", "print(2 + 2)", "stdout=4", {}),
    ("pandas", "import pandas as pd\ndf = pd.read_csv('satis.csv')\nprint(int(df['tutar'].sum()))", "stdout=300",
     {"satis.csv": "ay,tutar\nOcak,120\nŞubat,180\n"}),
    ("ağ_yok", "import socket\ntry:\n    socket.create_connection(('1.1.1.1', 53), timeout=3)\n    print('AG_ACIK')\n"
               "except OSError as e:\n    print('AG_YOK', type(e).__name__)", "contains=AG_YOK", {}),
    ("salt_okunur", "try:\n    open('/etc/kayaai_test', 'w').write('x')\n    print('YAZDI')\nexcept OSError:\n    print('YAZAMADI')",
     "contains=YAZAMADI", {}),
    ("root_değil", "import os\nprint(os.getuid())", "stdout=10001", {}),
    ("yalnız_verilen_dosyalar", "import os\nprint(sorted(os.listdir('/in')))", "stdout=['main.py']", {}),
    ("out_yazılır", "open('/out/sonuc.txt', 'w').write('ok')\nprint('YAZILDI')", "contains=YAZILDI", {}),
    ("bellek_sınırı", "x = bytearray(2 * 1024 ** 3)\nprint('AYRILDI')", "not_contains=AYRILDI", {}),
    ("süre_sınırı", "while True:\n    pass", "timed_out", {}),
]


def _passed(expect: str, out: dict[str, Any]) -> bool:
    if expect == "timed_out":
        return bool(out["timed_out"])
    kind, _, val = expect.partition("=")
    s = out["stdout"].strip()
    return {"stdout": s == val, "contains": val in s, "not_contains": val not in s and not out["timed_out"]}[kind]


def run_checks(cfg: Any, work: Path, exec_fn: runner.ExecFn | None = None) -> dict[str, Any]:
    ok, why = runner.image_ready(cfg, exec_fn)
    report: dict[str, Any] = {"image": cfg.image, "ready": ok, "reason": why, "cases": [], "ok": False}
    if not ok:
        return report
    for name, code, expect, files in CASES:
        rdir = work / f"check-{uuid.uuid4().hex[:8]}"
        (rdir / "in").mkdir(parents=True)
        (rdir / "out").mkdir()
        (rdir / "out").chmod(0o777)
        (rdir / "in" / "main.py").write_text(code, encoding="utf-8")
        for fn, content in files.items():
            (rdir / "in" / fn).write_text(content, encoding="utf-8")
        short = cfg.model_copy(update={"timeout_s": min(cfg.timeout_s, 8)}) if name == "süre_sınırı" else cfg
        out = runner.run_container(short, rdir, exec_fn)
        report["cases"].append({"name": name, "passed": _passed(expect, out), "expect": expect,
                                "stdout": out["stdout"][-300:], "stderr": out["stderr"][-300:],
                                "exit_code": out["exit_code"], "timed_out": out["timed_out"], "seconds": out["seconds"]})
        shutil.rmtree(rdir, ignore_errors=True)
    report["ok"] = all(c["passed"] for c in report["cases"])
    return report


def write_report(report: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
