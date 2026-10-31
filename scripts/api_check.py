"""kayaAI yerel API doğrulaması — çalışan bir `kayaai api` sunucusuna karşı, GERÇEK modelle.

Kullanım:
    1. terminal:  kayaai api
    2. terminal:  python scripts/api_check.py
Sonuç: data/api_check.json
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from websockets.sync.client import connect  # noqa: E402

from kayaai.api.app import load_or_create_token  # noqa: E402
from kayaai.config import load_settings  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass


def main() -> int:
    settings = load_settings()
    base = f"http://{settings.api.host}:{settings.api.port}"
    token = load_or_create_token(settings)
    report: dict = {"base": base, "checks": {}}
    ok_all = True

    def check(name: str, passed: bool, detail: object = None) -> None:
        nonlocal ok_all
        ok_all &= passed
        report["checks"][name] = {"passed": passed, "detail": detail}
        print(f"[{'OK' if passed else 'HATA'}] {name}" + (f" — {str(detail)[:160]}" if detail is not None else ""))

    c = httpx.Client(base_url=base, headers={"Authorization": f"Bearer {token}"}, timeout=30, trust_env=False)
    try:
        c.get("/api/health")
    except httpx.HTTPError as exc:
        print(f"[HATA] API'ye ulaşılamadı ({base}). Önce başka bir terminalde `kayaai api` çalıştırın. {exc}")
        return 1

    r = httpx.get(base + "/api/health", timeout=10, trust_env=False)
    check("anahtarsız istek reddediliyor", r.status_code == 401, r.status_code)
    h = c.get("/api/health").json()
    check("sağlık", h["ollama"]["reachable"], {"ollama": h["ollama"].get("version"), "claude": h["claude"]["state"]})
    s = c.get("/api/system").json()
    check("sistem ölçümleri", bool(s.get("gpus")), {"cpu": s["cpu_pct"], "ram%": s["ram_used_pct"],
                                                   "gpu": s["gpus"][0] if s.get("gpus") else None})
    agents = c.get("/api/agents").json()
    check("ajanlar", len(agents) >= 3, [f"{a['name']}:{a['status']['state']}" for a in agents])

    # Olay akışını dinle, aynı anda bir görev çalıştır
    events: list[dict] = []
    stop = threading.Event()

    def listen() -> None:
        url = base.replace("http", "ws") + f"/api/events?token={token}"
        with connect(url, open_timeout=10) as ws:
            while not stop.is_set():
                try:
                    events.append(json.loads(ws.recv(timeout=0.5)))
                except TimeoutError:
                    continue

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    time.sleep(1.0)
    t0 = time.perf_counter()
    task_id = c.post("/api/ask", json={"question": "kayaAI API testinden merhaba! Tek cümleyle cevap ver."}).json()["id"]
    task = {}
    for _ in range(600):
        task = c.get(f"/api/tasks/{task_id}").json()["task"]
        if task["status"] not in ("pending", "running"):
            break
        time.sleep(0.2)
    secs = round(time.perf_counter() - t0, 2)
    check("arka plan görevi (ask)", task.get("status") == "succeeded",
          {"süre_sn": secs, "cevap": (task.get("result") or {}).get("answer")})
    time.sleep(1.0)
    stop.set()
    mine = [e for e in events if e.get("task_id") == task_id]
    check("canlı olay akışı (WebSocket)", [e["data"]["status"] for e in mine][-1:] == ["succeeded"],
          [e["data"]["status"] for e in mine])

    report["all_passed"] = ok_all
    out = settings.data_dir / "api_check.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print("\nSONUÇ:", "API HAZIR" if ok_all else "SORUN VAR", f"- rapor: {out}")
    print(f"Tarayıcıdan deneme sayfası: {base}/docs  (Authorize → anahtar: kayaai api token)")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
