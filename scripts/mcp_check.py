"""kayaAI MCP sunucusu doğrulaması - GERÇEK Ollama ile, stdio üzerinden (Claude Code'un yaptığı gibi).

Kullanım (proje klasöründe, venv etkin):
    python scripts/mcp_check.py
Sonuç: data/mcp_check.json
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp import Client, StdioServerParameters  # noqa: E402

from kayaai.config import load_settings  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

QUESTIONS = [
    "Merhaba! Kendini tek cümleyle tanıtır mısın?",
    "In one sentence, what is the Model Context Protocol used for?",
]


async def check() -> dict:
    # SDK alt sürece güvenlik için kısıtlı bir ortam verir (ör. Windows'ta ProgramFiles/windir yok).
    # Sunucu bizim kendi kodumuz ve bu bizim kendi kontrol scriptimiz: tam ortamı aktarmak güvenli.
    env = dict(os.environ) | {"PYTHONUTF8": "1"}
    params = StdioServerParameters(command=sys.executable, args=["-m", "kayaai.mcp_server"], cwd=str(ROOT), env=env)
    report: dict = {"steps": {}}
    async with Client(params) as c:
        report["server_info"] = c.server_info.model_dump() if c.server_info else None
        report["protocol_version"] = c.protocol_version
        tools = [t.name for t in (await c.list_tools()).tools]
        report["steps"]["list_tools"] = {"passed": "kayaai_ask" in tools, "tools": tools}
        print(f"[OK] El sıkışma: protokol {c.protocol_version}, {len(tools)} araç: {', '.join(tools)}")

        h = await c.call_tool("kayaai_health", {})
        health = h.structured_content or {}
        ok = not h.is_error and health.get("ollama_reachable") and all(health.get("worker_models_installed", {}).values())
        report["steps"]["health"] = {"passed": bool(ok), **health}
        print(f"[{'OK' if ok else 'HATA'}] kayaai_health: Ollama {health.get('ollama_version')}, sorunlar: {health.get('problems')}")
        gpus = health.get("gpus") or []
        print(f"     GPU: {', '.join(g.get('name', '?') for g in gpus) or 'yok'} | notlar: {health.get('gpu_notes')}")
        if not ok:
            return report

        for q in QUESTIONS:
            r = await c.call_tool("kayaai_ask", {"question": q})
            sc = r.structured_content or {}
            passed = not r.is_error and bool(sc.get("answer"))
            report["steps"].setdefault("ask", []).append(
                {"question": q, "passed": passed, "is_error": r.is_error,
                 "answer": sc.get("answer") or (r.content[0].text if r.content else None),
                 "language": sc.get("language"), "duration_s": sc.get("duration_s"),
                 "tokens_per_second": sc.get("tokens_per_second")}
            )
            print(f"[{'OK' if passed else 'HATA'}] kayaai_ask: {q[:50]!r} -> {str(sc.get('answer') or r.content[0].text)[:120]!r}")
    return report


def main() -> int:
    settings = load_settings()
    try:
        report = asyncio.run(asyncio.wait_for(check(), timeout=600))
    except Exception as exc:  # noqa: BLE001
        report = {"steps": {}, "exception": f"{type(exc).__name__}: {exc}"}
        print(f"[HATA] {report['exception']}")
    steps = report["steps"]
    all_ok = (
        steps.get("list_tools", {}).get("passed")
        and steps.get("health", {}).get("passed")
        and steps.get("ask")
        and all(a["passed"] for a in steps["ask"])
    )
    report["all_passed"] = bool(all_ok)
    out = settings.data_dir / "mcp_check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print("\nSONUÇ:", "MCP SUNUCUSU HAZIR" if all_ok else "SORUN VAR", f"- rapor: {out}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
