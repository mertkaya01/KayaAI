"""Windows Görev Zamanlayıcı kaydı (Adım 13; sahip kararı). Ek paket yok: Windows'un kendi `schtasks.exe` aracı + görev XML'i.

- Görevler `\\kayaAI\\<id>` klasöründe, yalnız oturum açıkken ve SAHİBİN hesabıyla (InteractiveToken, en düşük yetki —
  yönetici/parola gerekmez).
- `StartWhenAvailable`: bilgisayar kapalıyken kaçırılan çalışma açılınca yapılır (sahip isterse).
- Eylem: `<venv>\\pythonw.exe -m kayaai schedule run <id> --trigger windows` (pencere açmaz), çalışma klasörü proje kökü.
- 2 saat süre sınırı; aynı görevin ikinci örneği başlatılmaz.
Testler `set_runner()` ile `schtasks` çağrılarını yakalar.
"""

from __future__ import annotations

import getpass
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from .model import Schedule

FOLDER = "kayaAI"
DAY_TAGS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTH_TAGS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
              "November", "December"]

Runner = Callable[[list[str]], tuple[int, str]]


def _run(args: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(args, capture_output=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    out = (p.stdout or b"") + (p.stderr or b"")
    return p.returncode, out.decode("utf-8", errors="replace") if b"\x00" not in out else out.decode("utf-16", "replace")


_RUNNER: Runner | None = None


def set_runner(fn: Runner | None) -> None:
    global _RUNNER
    _RUNNER = fn


def supported() -> bool:
    return _RUNNER is not None or sys.platform == "win32"


def task_name(sid: str) -> str:
    return f"{FOLDER}\\{sid}"


def python_exe() -> str:
    """Pencere açmayan yorumlayıcı (pythonw.exe) — yoksa python.exe."""
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.is_file() else exe)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def command(s: Schedule) -> tuple[str, str]:
    return python_exe(), f"-m kayaai schedule run {s.id} --trigger windows"


def _trigger(s: Schedule, start: datetime) -> str:
    c = s.cadence
    boundary = start.strftime("%Y-%m-%dT%H:%M:%S")
    head = f"<StartBoundary>{boundary}</StartBoundary><Enabled>true</Enabled>"
    if c.freq == "once":
        return f"<TimeTrigger>{head}</TimeTrigger>"
    if c.freq == "daily":
        body = "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>"
    elif c.freq == "weekly":
        days = "".join(f"<{DAY_TAGS[d]} />" for d in c.days)
        body = f"<ScheduleByWeek><WeeksInterval>1</WeeksInterval><DaysOfWeek>{days}</DaysOfWeek></ScheduleByWeek>"
    else:
        months = "".join(f"<{m} />" for m in MONTH_TAGS)
        body = (f"<ScheduleByMonth><DaysOfMonth><Day>{c.day}</Day></DaysOfMonth><Months>{months}</Months>"
                "</ScheduleByMonth>")
    return f"<CalendarTrigger>{head}{body}</CalendarTrigger>"


def task_xml(s: Schedule, now: datetime | None = None, user: str | None = None) -> str:
    start = s.cadence.next_after(now or datetime.now()) or datetime.now()
    exe, args = command(s)
    user = user or (f"{os.environ.get('USERDOMAIN')}\\{getpass.getuser()}" if os.environ.get("USERDOMAIN") else getpass.getuser())
    b = lambda v: "true" if v else "false"  # noqa: E731
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>kayaAI</Author>
    <Description>{escape(s.summary())} (kayaAI zamanlanmış görevi; kaldırmak için kayaai schedule rm {s.id})</Description>
  </RegistrationInfo>
  <Triggers>{_trigger(s, start)}</Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>{b(s.catch_up)}</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>{b(s.enabled)}</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(exe)}</Command>
      <Arguments>{escape(args)}</Arguments>
      <WorkingDirectory>{escape(str(project_root()))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


class SchedulerError(RuntimeError):
    pass


def _call(args: list[str]) -> str:
    code, out = (_RUNNER or _run)(args)
    if code != 0:
        raise SchedulerError(f"Görev Zamanlayıcı hatası ({' '.join(args[:2])}): {out.strip()[:300]}")
    return out


def register(s: Schedule, xml_dir: Path) -> str:
    """Görevi oluşturur ya da günceller (/F). XML dosyası `data/schedule/<id>.xml` (UTF-16, schtasks bunu ister)."""
    if not supported():
        raise SchedulerError("Windows Görev Zamanlayıcı yalnız Windows'ta")
    xml_dir.mkdir(parents=True, exist_ok=True)
    path = xml_dir / f"{s.id}.xml"
    path.write_text(task_xml(s), encoding="utf-16")
    return _call(["schtasks", "/Create", "/TN", task_name(s.id), "/XML", str(path), "/F"])


def unregister(sid: str) -> None:
    if supported():
        _call(["schtasks", "/Delete", "/TN", task_name(sid), "/F"])


def set_enabled(sid: str, enabled: bool) -> None:
    if supported():
        _call(["schtasks", "/Change", "/TN", task_name(sid), "/ENABLE" if enabled else "/DISABLE"])


def registered_ids() -> set[str] | None:
    """Görev Zamanlayıcı'daki kayaAI görevleri (Windows dışında None)."""
    if not supported():
        return None
    code, out = (_RUNNER or _run)(["schtasks", "/Query", "/FO", "CSV", "/NH"])
    if code != 0:
        return set()
    ids = set()
    for line in out.splitlines():
        first = line.split(",", 1)[0].strip().strip('"')
        prefix = f"\\{FOLDER}\\"
        if first.startswith(prefix):
            ids.add(first[len(prefix):])
    return ids
