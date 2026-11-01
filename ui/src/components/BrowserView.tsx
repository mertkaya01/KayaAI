import { useEffect, useState } from "react";
import { api, post } from "../api";

interface Step {
  n: number; action: string; description: string; thought: string; risk: string; reason: string;
  status: "yapıldı" | "onay bekliyor" | "reddedildi" | "kural dışı" | "hata" | "bitti"; approval_id: string | null; url: string; error: string | null;
}
interface Job {
  id: string; goal: string; start_url: string; status: "running" | "waiting" | "done" | "failed" | "stopped";
  steps: Step[]; notes: string[]; answer: string; error: string | null; url: string; title: string; screenshot?: string | null;
}

const STATUS: Record<Job["status"], string> = { running: "çalışıyor", waiting: "onayını bekliyor", done: "bitti", failed: "durdu", stopped: "durduruldu" };
const RISK: Record<string, string> = { R0: "okuma", R1: "kayda geçer", R2: "onay", R3: "her seferinde onay", refuse: "kural dışı" };

/**
 * Tarayıcı ajanı (Adım 12d). Kurulu Edge ayrı ve boş bir profille, görünür pencerede açılır. Okuma serbest; aynı sitede
 * tıklama kayda geçer; form doldurma ve başka siteye gitme senin onayınla; gönder/öde/sil her seferinde onayla.
 */
export function BrowserView() {
  const [goal, setGoal] = useState("");
  const [url, setUrl] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const active = job && (job.status === "running" || job.status === "waiting");

  useEffect(() => {
    void api<Job[]>("/api/browser/jobs").then((js) => { if (js[0]) void load(js[0].id); }).catch(() => undefined);
  }, []);
  useEffect(() => {
    if (!active) return;
    const t = window.setInterval(() => void load(job!.id), 1000);
    return () => window.clearInterval(t);
  }, [active, job?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function load(id: string) {
    try { setJob(await api<Job>(`/api/browser/jobs/${id}`)); } catch { /* yok say */ }
  }

  async function start() {
    setError(null);
    setBusy(true);
    try {
      setJob(await post<Job>("/api/browser/run", { goal: goal.trim(), url: url.trim() }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function decide(s: Step, approve: boolean) {
    if (!s.approval_id) return;
    try {
      await post(`/api/approvals/${s.approval_id}/${approve ? "approve" : "reject"}`, {});
      await load(job!.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <main className="browser">
      <section className="panel">
        <h2>Tarayıcıda yap</h2>
        <form className="browser-form" onSubmit={(e) => { e.preventDefault(); void start(); }}>
          <textarea rows={2} placeholder="Ne yapılsın? Ör. 'Python kitaplarını ara ve ilk üçünün fiyatını listele'" value={goal}
            onChange={(e) => setGoal(e.target.value)} aria-label="Hedef" disabled={!!active} />
          <div className="row-actions">
            <input placeholder="Başlangıç adresi (ör. kitapyurdu.com)" value={url} onChange={(e) => setUrl(e.target.value)} aria-label="Başlangıç adresi" disabled={!!active} />
            {active
              ? <button type="button" className="danger" onClick={() => void post(`/api/browser/jobs/${job!.id}/stop`, {}).then(() => load(job!.id))}>■ Durdur</button>
              : <button type="submit" className="toggle" disabled={busy || goal.trim().length < 5 || !url.trim()}>▶ Başlat</button>}
          </div>
        </form>
        <p className="muted small">
          Edge ayrı ve boş bir profille açılır (senin çerezlerin/şifrelerin yok); ne yaptığını pencerede görürsün. Okuma serbest ·
          aynı sitede tıklama kayda geçer · form doldurma ve başka siteye gitme <strong>onayınla</strong> · gönder / öde / satın al /
          sil <strong>her seferinde onayınla</strong> · parola-kart alanı, dosya indirme/yükleme ve yerel ağ yapılmaz.
        </p>
        {error && <p className="error">{error}</p>}
      </section>
      {job && (
        <div className="browser-grid">
          <section className="panel">
            <div className="panel-head">
              <h2 className="flow-title" title={job.goal}>{job.goal}</h2>
              <span className={`pill ${job.status === "done" ? "ok" : job.status === "waiting" ? "warn" : job.status === "running" ? "" : "bad"}`}>
                {active && <span className="dot" />} {STATUS[job.status]}
              </span>
            </div>
            <ol className="bsteps">
              {job.steps.map((s) => (
                <li key={s.n} className={`bstep st-${s.status.replace(/\s/g, "-")}`}>
                  <div>
                    <span className={`risk risk-${s.risk}`}>{s.risk}</span> <strong>{s.description}</strong>
                    <span className="muted small"> · {s.status}{s.status === "kural dışı" ? ` (${s.reason})` : s.risk ? ` · ${RISK[s.risk] ?? ""}` : ""}</span>
                  </div>
                  {s.thought && <div className="muted small">{s.thought}</div>}
                  {s.status === "onay bekliyor" && (
                    <div className="row-actions start">
                      <span className="small warn-text">{s.reason}</span>
                      <button className="small toggle" onClick={() => void decide(s, true)}>Onayla</button>
                      <button className="small danger" onClick={() => void decide(s, false)}>Reddet</button>
                    </div>
                  )}
                  {s.error && <div className="error small">{s.error}</div>}
                </li>
              ))}
              {active && job.status === "running" && <li className="muted">düşünüyor…</li>}
            </ol>
            {job.error && <p className="error">{job.error}</p>}
            {job.answer && (<><h3>Sonuç</h3><p className="answer">{job.answer}</p></>)}
            {!job.answer && job.notes.length > 0 && (<><h3>Notlar</h3><ul>{job.notes.map((n, i) => <li key={i}>{n}</li>)}</ul></>)}
          </section>
          <section className="panel">
            <h2>Sayfa</h2>
            <p className="muted small page-url" title={job.url}>{job.title} · {job.url}</p>
            {job.screenshot ? <img className="preview-shot" src={job.screenshot} alt="Tarayıcının şu anki sayfası" /> : <p className="muted">Görüntü yok.</p>}
          </section>
        </div>
      )}
    </main>
  );
}
