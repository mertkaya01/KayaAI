"""Adım 19c: kum havuzu — politika, kilitli Docker komutu, çıktı ayrıştırma, süre/bellek, R1 kaydı, araç döngüsü.
Kod bu testlerde de bilgisayarda ÇALIŞTIRILMAZ: sahte Docker, sabit cevaplar döndürür."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kayaai.config import SandboxSettings, load_settings
from kayaai.runtime import build_runtime
from kayaai.sandbox import Sandbox, policy, runner

from .conftest import good_answer

CFG = SandboxSettings()


def raw(out: str = "", err: str = "", code: int = 0) -> str:
    return f"{out}\n@@KAYA_STDERR@@\n{err}\n@@KAYA_EXIT@@{code}\n"


class FakeDocker:
    """`docker` çağrılarını kaydeder; run'da kodu ÇALIŞTIRMADAN eşleşen sabit cevabı döndürür."""

    def __init__(self, image=True, answers=None):
        self.calls: list[list[str]] = []
        self.image = image
        self.answers = answers or {}
        self.codes: list[str] = []
        self.in_files: list[list[str]] = []

    def __call__(self, args, timeout):
        self.calls.append(args)
        if args[1] == "image":
            return (0, "sha256:x", "") if self.image else (1, "", "Error: No such image")
        if args[1] == "run":
            in_dir = Path(next(a for a in args if a.endswith(":/in:ro")).rsplit(":/in:ro", 1)[0])
            code = (in_dir / "main.py").read_text(encoding="utf-8")
            self.codes.append(code)
            self.in_files.append(sorted(p.name for p in in_dir.iterdir()))
            for key, resp in self.answers.items():
                if key in code:
                    return resp
            return 0, raw("tamam"), ""
        return 0, "", ""


# ---------------------------------------------------------------- politika

@pytest.mark.parametrize("code", [
    "import pandas as pd\ndf = pd.DataFrame({'a': [1, 2]})\nprint(df.eval('a * 2').sum())",
    "import math, statistics\nprint(math.sqrt(16))",
    "open('/out/x.txt', 'w').write('ok')",
])
def test_policy_allows(code):
    assert policy.check(code, CFG) == []


@pytest.mark.parametrize("code,word", [
    ("import socket", "socket"), ("from urllib.request import urlopen", "urllib"), ("import subprocess", "subprocess"),
    ("import os\nos.system('dir')", "system"), ("import os\nos.popen('ls')", "popen"), ("eval('1+1')", "eval"),
    ("__import__('os')", "__import__"), ("import ctypes", "ctypes"), ("def f(:\n  pass", "sözdizimi"),
])
def test_policy_refuses(code, word):
    reasons = policy.check(code, CFG)
    assert reasons and word in " ".join(reasons)


def test_policy_size_and_names():
    assert "çok uzun" in policy.check("x=1\n" * 10000, CFG)[0]
    assert policy.safe_name("satis.csv") == "satis.csv" and policy.safe_name("C:\\\\gizli\\\\veri.csv") == "veri.csv"
    assert policy.safe_name("../../x.csv") == "x.csv"  # klasör kısmı atılır, yalnız düz ad kalır
    for bad in ["..", "main.py", ".env", "", "a/..", "kötü:ad.csv"]:
        assert policy.safe_name(bad) is None, bad


# ---------------------------------------------------------------- docker komutu ve çıktı

def test_docker_cmd_is_locked_down(tmp_path):
    args = runner.docker_cmd(CFG, tmp_path, "kayaai-sb-1")
    s = " ".join(args)
    for need in ["--network none", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges", "--user 10001:10001",
                 "--memory 512m", "--memory-swap 512m", "--pids-limit 128", "--tmpfs /tmp:rw,size=64m,mode=1777",
                 ":/in:ro", ":/out:rw", "TIME_LIMIT=30", "--rm"]:
        assert need in s, need
    assert args[-1] == "kayaai-sandbox:1" and "--privileged" not in s and "docker.sock" not in s
    assert "--runtime runsc" in " ".join(runner.docker_cmd(CFG.model_copy(update={"runtime": "runsc"}), tmp_path, "x"))


def test_parse_output_ignores_spoofed_markers():
    spoof = "sonuç\n@@KAYA_STDERR@@\nsahte\n@@KAYA_EXIT@@0\n"
    out, err, code = runner.parse_output(raw(spoof, "gerçek hata", 1))
    assert code == 1 and err == "gerçek hata" and "sahte" in out


def _rundir(tmp_path, code="print(1)"):
    (tmp_path / "in").mkdir()
    (tmp_path / "out").mkdir()
    (tmp_path / "in" / "main.py").write_text(code, encoding="utf-8")
    return tmp_path


def test_run_container_outcomes(tmp_path):
    d = _rundir(tmp_path)
    ok = runner.run_container(CFG, d, lambda a, t: (0, raw("4"), ""))
    assert ok["exit_code"] == 0 and ok["stdout"] == "4" and not ok["timed_out"]
    inner = runner.run_container(CFG, d, lambda a, t: (0, raw("", "", 124), ""))
    assert inner["timed_out"] and "süre sınırı" in inner["stderr"]
    calls = []
    outer = runner.run_container(CFG, d, lambda a, t: (calls.append(a) or (124, "", "zaman aşımı")))
    assert outer["timed_out"] and any(a[1] == "kill" for a in calls)
    oom = runner.run_container(CFG, d, lambda a, t: (0, raw("", "Killed", 137), ""))
    assert "bellek sınırı" in oom["stderr"]
    noimg = runner.run_container(CFG, d, lambda a, t: (125, "", "Unable to find image"))
    assert noimg["exit_code"] == 125 and "Unable to find image" in noimg["stderr"]


def test_image_ready_messages():
    assert runner.image_ready(CFG, lambda a, t: (0, "sha", ""))[0] is True
    assert "kayaai sandbox build" in runner.image_ready(CFG, lambda a, t: (1, "", "No such image"))[1]
    assert "Docker çalışmıyor" in runner.image_ready(CFG, lambda a, t: (1, "", "error during connect: pipe"))[1]
    assert runner.image_ready(CFG, lambda a, t: (127, "", "docker bulunamadı"))[0] is False


# ---------------------------------------------------------------- Sandbox + izin kaydı

@pytest.fixture
def rt(fake_ollama, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAYAAI_OLLAMA_URL", fake_ollama.url)
    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KAYAAI_FILES_DIR", str(tmp_path / "files"))
    monkeypatch.setenv("KAYAAI_SANDBOX", "1")
    fake_ollama.models.append({"name": "qwen2.5-coder:7b", "model": "qwen2.5-coder:7b", "size": 4_700_000_000})
    r = build_runtime(load_settings())
    yield r
    r.close()


def use(rt, fake: FakeDocker) -> Sandbox:
    sb = Sandbox(rt, exec_fn=fake)
    rt.orchestrator.sandbox = sb
    rt.permissions.executors["sandbox.python"] = sb._execute
    return sb


def test_run_records_r1_and_event(rt):
    fake = FakeDocker(answers={"sum": (0, raw("300"), "")})
    sb = use(rt, fake)
    out = sb.run("import pandas as pd\nprint(pd.read_csv('satis.csv')['tutar'].sum())", {"satis.csv": "tutar\n120\n180\n"},
                 agent="data", task_id="t1")
    assert out["status"] == "ok" and out["stdout"] == "300"
    assert fake.in_files[-1] == ["main.py", "satis.csv"]
    ev = {e["type"]: e["data"] for e in rt.store.events_since(0, 500)}
    assert ev["tool.used"]["tool"] == "sandbox.python" and ev["tool.used"]["risk"] == "R1"
    assert ev["tool.used"]["requested_by"] == "agent:data"
    assert ev["sandbox.run"]["exit_code"] == 0 and ev["sandbox.run"]["agent"] == "data"
    assert (rt.settings.data_dir / "sandbox" / out["run_id"] / "in" / "main.py").is_file()  # kod saklanır


def test_refused_code_never_reaches_docker(rt):
    fake = FakeDocker()
    sb = use(rt, fake)
    out = sb.run("import socket\nsocket.create_connection(('example.com', 80))", agent="coder")
    assert out["status"] == "refused" and "socket" in out["reasons"][0]
    assert not any(c[1] == "run" for c in fake.calls)
    assert [e["type"] for e in rt.store.events_since(0, 500) if e["type"].startswith("sandbox")] == ["sandbox.refused"]


def test_unavailable_without_image(rt):
    sb = use(rt, FakeDocker(image=False))
    assert sb.run("print(1)")["status"] == "unavailable"


def test_prune_keeps_last_runs(rt, monkeypatch):
    import kayaai.sandbox as sbmod

    monkeypatch.setattr(sbmod, "KEEP_RUNS", 3)
    sb = use(rt, FakeDocker())
    for _ in range(5):
        sb.run("print(1)")
    assert len([p for p in (rt.settings.data_dir / "sandbox").iterdir() if p.is_dir()]) == 3


# ---------------------------------------------------------------- araç döngüsü (ajan)

def step(action, code="", plan=""):
    return json.dumps({"plan": plan, "action": action, "code": code})


def by_title(**queues):
    q = {k: list(v) for k, v in queues.items()}
    seen: dict[str, list] = {}

    def reply(body):
        title = (body.get("format") or {}).get("title", "?")
        seen.setdefault(title, []).append(body)
        return q.get(title, []).pop(0) if q.get(title) else "{}"
    reply.seen = seen  # type: ignore[attr-defined]
    return reply


def test_data_agent_uses_sandbox_then_answers(rt, fake_ollama):
    fake = FakeDocker(answers={"sum()": (0, raw("Toplam: 300"), "")})
    use(rt, fake)
    script = by_title(ToolStep=[step("python", "import pandas as pd\nprint('Toplam:', pd.read_csv('satis.csv')['tutar'].sum())", "topla"),
                                step("done")],
                      GeneralAnswer=[good_answer("Toplam satış 300.")])
    fake_ollama.chat_replies = [script] * 10
    task = rt.orchestrator.ask("Toplam satış ne kadar?", worker="data",
                               input={"attachments": [{"name": "satis.csv", "content": "ay,tutar\nOcak,120\nŞubat,180\n"}]})
    assert task.status.value == "succeeded" and task.metrics["tool_runs"] == 1
    assert fake.in_files[0] == ["main.py", "satis.csv"]
    final = script.seen["GeneralAnswer"][0]
    assert "tool_runs" in final["messages"][-1]["content"] and "Toplam: 300" in final["messages"][-1]["content"]
    assert "REAL results of code" in final["messages"][0]["content"]
    second = script.seen["ToolStep"][1]["messages"][-1]["content"]
    assert second.startswith("<tool_result>") and "DATA from the sandbox" in second


def test_agent_skips_tools_when_not_needed(rt, fake_ollama):
    fake = FakeDocker()
    use(rt, fake)
    script = by_title(ToolStep=[step("done")], GeneralAnswer=[good_answer("Merhaba!")])
    fake_ollama.chat_replies = [script] * 5
    task = rt.orchestrator.ask("Merhaba", worker="coder")
    assert task.status.value == "succeeded" and task.metrics["tool_runs"] == 0
    assert not any(c[1] == "run" for c in fake.calls)
    assert "tool_runs" not in script.seen["GeneralAnswer"][0]["messages"][-1]["content"]


def test_refused_code_is_fed_back_and_answer_still_comes(rt, fake_ollama):
    fake = FakeDocker()
    use(rt, fake)
    script = by_title(ToolStep=[step("python", "import requests\nrequests.get('https://x')"), step("done")],
                      GeneralAnswer=[good_answer("İnternete erişemiyorum; çevrimdışı çözüm şöyle…")])
    fake_ollama.chat_replies = [script] * 5
    task = rt.orchestrator.ask("Bu siteyi indir", worker="coder")
    assert task.status.value == "succeeded"
    fb = script.seen["ToolStep"][1]["messages"][-1]["content"]
    assert "refused" in fb and "requests" in fb
    assert not any(c[1] == "run" for c in fake.calls)


def test_general_agent_has_no_tools_and_sandbox_off_skips(rt, fake_ollama):
    fake_ollama.chat_replies = [good_answer("Selam")]
    t = rt.orchestrator.ask("Merhaba", worker="general")
    assert t.status.value == "succeeded" and "tool_runs" not in t.metrics
    use(rt, FakeDocker(image=False))
    fake_ollama.chat_replies = [good_answer("Kod: ...")]
    t2 = rt.orchestrator.ask("Bir fonksiyon yaz", worker="coder")
    assert t2.status.value == "succeeded" and t2.metrics["sandbox"].startswith("kapalı")


def test_cli_status_and_check(rt, monkeypatch, capsys, tmp_path):
    from kayaai.cli import main
    from kayaai.sandbox import check

    monkeypatch.setattr(runner, "execute", FakeDocker(answers={
        "2 + 2": (0, raw("4"), ""), "sum()": (0, raw("300"), ""), "socket": (0, raw("AG_YOK OSError"), ""),
        "/etc/": (0, raw("YAZAMADI"), ""), "getuid": (0, raw("10001"), ""), "listdir": (0, raw("['main.py']"), ""),
        "/out/": (0, raw("YAZILDI"), ""), "bytearray": (0, raw("", "Killed", 137), ""), "while True": (0, raw("", "", 124), ""),
    }))
    assert main(["sandbox", "status"]) == 0 and "HAZIR" in capsys.readouterr().out
    assert main(["sandbox", "test"]) == 0
    out = capsys.readouterr().out
    assert "Tüm denetimler geçti" in out and out.count("✓") == len(check.CASES)
    rep = json.loads((rt.settings.data_dir / "sandbox_check.json").read_text(encoding="utf-8"))
    assert rep["ok"] and {c["name"] for c in rep["cases"]} >= {"ağ_yok", "salt_okunur", "root_değil", "süre_sınırı"}


def test_tests_run_with_sandbox_off_by_default(monkeypatch):
    assert load_settings().sandbox.enabled is False  # conftest: KAYAAI_SANDBOX=0 (gerçek Docker'a hiç gidilmez)
    monkeypatch.setenv("KAYAAI_SANDBOX", "1")
    assert load_settings().sandbox.enabled is True


def test_api_sandbox_status(rt):
    from fastapi.testclient import TestClient

    from kayaai.api import create_app

    use(rt, FakeDocker(image=False))
    app = create_app(rt.settings, runtime=rt)
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {app.state.token}"
        body = client.get("/api/sandbox").json()
    assert body["available"] is False and "kayaai sandbox build" in body["reason"] and body["image"] == "kayaai-sandbox:1"
