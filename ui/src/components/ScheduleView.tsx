import { useState } from "react";
import { post, type SubmitResult } from "../api";
import { ago } from "../format";
import { usePolling } from "../hooks";

type Kind = "docs_digest" | "sales_report" | "reindex" | "free";
interface Sched {
  id: string; name: string; kind: Kind; params: Record<string, unknown>; enabled: boolean; catch_up: boolean;
  registered: boolean; register_note: string | null; last_run: string | null; last_status: string | null; last_message: string | null;
  summary: string; cadence_text: string; next_run: string | null; in_windows: boolean | null;
}
interface RunRow { id: string; schedule_id: string; started_at: string; status: string; message: string; seconds: number | null; trigger: string; files: string[] }
interface Data { schedules: Sched[]; windows: boolean; sync: { supported: boolean; missing: string[]; orphans: string[] } }

const KIND: Record<Kind, string> = { docs_digest: "Belge klasörü özeti", sales_report: "Satış raporu", reindex: "Belge dizini yenileme", free: "Serbest görev" };
const DAYS = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"];
const RUN_STATUS: Record<string, string> = { running: "çalışıyor", succeeded: "başarılı", failed: "başarısız", skipped: "atlandı" };

function when(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("tr-TR", { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

/** Zamanlanmış görevler (Adım 13): Windows Görev Zamanlayıcı'ya kaydedilir, kayaAI kapalıyken de çalışır. */
export function ScheduleView({ refreshKey = 0 }: { refreshKey?: number }) {
  const [key, setKey] = useState(0);
  const data = usePolling<Data>("/api/schedules", 15000, `${key}-${refreshKey}`);
  const runs = usePolling<RunRow[]>("/api/schedules/runs?limit=20", 10000, `${key}-${refreshKey}`);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [form, setForm] = useState({ name: "", kind: "docs_digest" as Kind, freq: "daily", at: "09:00", days: [0] as number[], day: 1, on: "",
    path: "", folder: "", request: "", formats: ["xlsx", "pdf"] as string[], catch_up: true, skip_holidays: false, cloud: false });
  const refresh = () => setKey((k) => k + 1);

  async function act(path: string, body: unknown, ok: string) {
    setNote(null);
    try {
      const r = await post<SubmitResult>(path, body);
      setNote({ ok: r.status !== "failed", text: r.status === "awaiting_approval" ? "Onay bekliyor — Bugün ya da Sistem → Onay merkezi." : r.status === "failed" ? (r.error ?? "başarısız") : ok });
      refresh();
    } catch (e) {
      setNote({ ok: false, text: e instanceof Error ? e.message : String(e) });
    }
  }

  function create(e: React.FormEvent) {
    e.preventDefault();
    const params: Record<string, unknown> = {};
    if (form.kind === "docs_digest" && form.folder.trim()) params.folder = form.folder.trim();
    if (form.kind === "sales_report") { params.path = form.path.trim(); params.formats = form.formats; }
    if (form.kind === "free") params.request = form.request.trim();
    const cadence: Record<string, unknown> = { freq: form.freq, at: form.at };
    if (form.freq === "weekly") cadence.days = form.days;
    if (form.freq === "monthly") cadence.day = form.day;
    if (form.freq === "once") cadence.on = form.on;
    void act("/api/schedules", { name: form.name.trim() || KIND[form.kind], kind: form.kind, params, cadence, catch_up: form.catch_up, skip_holidays: form.skip_holidays,
                                    cloud: form.kind === "free" && form.cloud }, "Eklendi");
  }

  const d = data.data;
  const names = Object.fromEntries((d?.schedules ?? []).map((s) => [s.id, s.name]));
  return (
    <main className="sched">
      <section className="panel">
        <div className="panel-head">
          <h2>Zamanlanmış görevler</h2>
          <span className="muted small">{d?.windows ? "Windows Görev Zamanlayıcı — kayaAI kapalıyken de çalışır" : "Windows dışı: kayaai schedule run-due ile"}</span>
        </div>
        {note && <p className={note.ok ? "note ok-text" : "error"} role="status">{note.text}</p>}
        {d && d.sync.supported && (d.sync.missing.length > 0 || d.sync.orphans.length > 0) && (
          <p className="warn-text small">Tutarsızlık: Windows'ta eksik {d.sync.missing.join(", ") || "—"} · kayaAI'de olmayan {d.sync.orphans.join(", ") || "—"}</p>
        )}
        {d?.schedules.length === 0 && <p className="muted">Henüz görev yok. Aşağıdan ekle; ekleme senin onayınla Windows'a kaydedilir.</p>}
        <ul className="sched-list">
          {d?.schedules.map((s) => (
            <li key={s.id} className={s.enabled ? "" : "off"}>
              <div>
                <strong>{s.name}</strong> <span className="muted small">· {KIND[s.kind]} · {s.cadence_text}</span>
                <div className="small muted">
                  sonraki: {when(s.next_run)} · son: {s.last_run ? `${ago(s.last_run)} (${RUN_STATUS[s.last_status ?? ""] ?? s.last_status})` : "—"}
                  {s.in_windows === false && s.enabled && <span className="error"> · Windows'ta kayıtlı değil</span>}
                  {!s.registered && s.register_note && <span className="warn-text"> · {s.register_note}</span>}
                </div>
                {s.last_status === "failed" && s.last_message && <div className="error small">{s.last_message}</div>}
              </div>
              <div className="row-actions">
                <button className="small" onClick={() => void act(`/api/schedules/${s.id}/run`, {}, "Çalıştırıldı — sonuç Asistan'da \"Zamanlanmış görevler\" sohbetinde")}>Şimdi çalıştır</button>
                <button className="small ghost" onClick={() => void act(`/api/schedules/${s.id}/${s.enabled ? "disable" : "enable"}`, {}, s.enabled ? "Kapatıldı" : "Açıldı")}>{s.enabled ? "Kapat" : "Aç"}</button>
                <button className="small danger" onClick={() => void act(`/api/schedules/${s.id}/delete`, {}, "Silindi")}>Sil…</button>
              </div>
            </li>
          ))}
        </ul>
      </section>
      <div className="sched-grid">
        <section className="panel">
          <h2>Yeni görev</h2>
          <form className="sched-form" onSubmit={create}>
            <label>Tür <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as Kind })}>
              {(Object.keys(KIND) as Kind[]).map((k) => <option key={k} value={k}>{KIND[k]}</option>)}
            </select></label>
            <label>Ad <input value={form.name} placeholder={KIND[form.kind]} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
            {form.kind === "docs_digest" && <label>Klasör (isteğe bağlı) <input value={form.folder} placeholder="boş: tüm izinli klasörler" onChange={(e) => setForm({ ...form, folder: e.target.value })} /></label>}
            {form.kind === "sales_report" && (
              <>
                <label>Excel/CSV dosyası <input value={form.path} placeholder="ör. satis.xlsx (izinli klasör)" onChange={(e) => setForm({ ...form, path: e.target.value })} /></label>
                <div className="checks">Rapor: {["xlsx", "pdf", "docx", "md"].map((f) => (
                  <label key={f}><input type="checkbox" checked={form.formats.includes(f)}
                    onChange={(e) => setForm({ ...form, formats: e.target.checked ? [...form.formats, f] : form.formats.filter((x) => x !== f) })} /> {f}</label>))}
                </div>
              </>
            )}
            {form.kind === "free" && <label>İstek <textarea rows={2} value={form.request} placeholder="ör. Bu haftanın yapılacaklarını hatırlat" onChange={(e) => setForm({ ...form, request: e.target.value })} /></label>}
            <div className="checks">
              <label>Sıklık <select value={form.freq} onChange={(e) => setForm({ ...form, freq: e.target.value })}>
                <option value="daily">her gün</option><option value="weekly">haftalık</option><option value="monthly">aylık</option><option value="once">bir kez</option>
              </select></label>
              <label>Saat <input type="time" value={form.at} onChange={(e) => setForm({ ...form, at: e.target.value })} /></label>
              {form.freq === "monthly" && <label>Gün <input type="number" min={1} max={28} value={form.day} onChange={(e) => setForm({ ...form, day: Number(e.target.value) })} /></label>}
              {form.freq === "once" && <label>Tarih <input type="date" value={form.on} onChange={(e) => setForm({ ...form, on: e.target.value })} /></label>}
            </div>
            {form.freq === "weekly" && (
              <div className="checks">{DAYS.map((n, i) => (
                <label key={n}><input type="checkbox" checked={form.days.includes(i)}
                  onChange={(e) => setForm({ ...form, days: e.target.checked ? [...form.days, i].sort() : form.days.filter((x) => x !== i) })} /> {n}</label>))}
              </div>
            )}
            <label className="inline"><input type="checkbox" checked={form.catch_up} onChange={(e) => setForm({ ...form, catch_up: e.target.checked })} /> Bilgisayar kapalıyken kaçırılırsa açılınca çalıştır</label>
            <label className="inline"><input type="checkbox" checked={form.skip_holidays} onChange={(e) => setForm({ ...form, skip_holidays: e.target.checked })} /> Resmi tatilde çalışma (tatil takvimi açık olmalı)</label>
            {form.kind === "free" && (
              <label className="inline"><input type="checkbox" checked={form.cloud} onChange={(e) => setForm({ ...form, cloud: e.target.checked })} /> ☁ Buluta izin ver (bulut köprüsü açıksa; hafıza ve belgeler gitmez)</label>
            )}
            <button type="submit" className="toggle">Ekle (onay ister)</button>
          </form>
        </section>
        <section className="panel">
          <h2>Son çalışmalar</h2>
          {runs.data?.length === 0 && <p className="muted">Henüz çalışma yok.</p>}
          <ul className="runs">
            {runs.data?.map((r) => (
              <li key={r.id} className={`run-${r.status}`}>
                <span className="small muted">{when(r.started_at)} · {r.trigger === "windows" ? "Windows" : r.trigger === "manual" ? "elle" : r.trigger}</span>{" "}
                <strong>{names[r.schedule_id] ?? r.schedule_id}</strong> — {RUN_STATUS[r.status] ?? r.status}{r.seconds != null ? ` (${r.seconds} sn)` : ""}
                {r.message && <div className="small muted">{r.message}</div>}
              </li>
            ))}
          </ul>
          <p className="muted small">Sonuçlar Asistan'daki "Zamanlanmış görevler" sohbetine yazılır; raporlar ~/kayaAI-files/raporlar altına.</p>
        </section>
      </div>
    </main>
  );
}
