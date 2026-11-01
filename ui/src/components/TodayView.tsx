import { useState } from "react";
import { post, type TodaySummary } from "../api";
import { ago, when } from "../format";
import { usePolling } from "../hooks";
import { Icon, type IconName } from "../icons";
import { notificationsSupported } from "../notify";
import type { Route } from "../route";
import { OfficeView } from "./OfficeView";

/**
 * Bugün (Adım 16b): giriş ekranı. Tek istek (/api/today) — onay bekleyenler (tek tıkla), şu an çalışan iş (canlı ofis),
 * zamanlanmış görevler, son sohbetler, sistem, açıksa kur ve resmi tatil. Olay gelince tazelenir.
 */

const STATUS: Record<string, string> = { succeeded: "bitti", failed: "başarısız", skipped: "atlandı", running: "çalışıyor",
  pending: "sırada", waiting_claude: "Claude kutusunda", cancelled: "iptal" };

function Stat({ icon, label, value, tone, onClick }: { icon: IconName; label: string; value: string; tone?: "ok" | "warn" | "bad"; onClick?: () => void }) {
  return (
    <button className={`stat${tone ? ` ${tone}` : ""}`} onClick={onClick} disabled={!onClick}>
      <span className="stat-icon"><Icon name={icon} size={18} /></span>
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </button>
  );
}

export function TodayView({ refreshKey, flowKey, approvalsKey, onNavigate, onPrefsChanged }: {
  refreshKey: number;
  flowKey: number;
  approvalsKey: number;
  onNavigate: (r: Route) => void;
  onPrefsChanged: () => void;
}) {
  const t = usePolling<TodaySummary>("/api/today", 30000, `${refreshKey}-${approvalsKey}`);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [perm, setPerm] = useState(() => (notificationsSupported() ? Notification.permission : "unsupported"));
  const d = t.data;

  async function decide(id: string, kind: "approve" | "reject") {
    setBusy(id);
    setMsg(null);
    try {
      await post(`/api/approvals/${id}/${kind}`, { note: "" });
      setMsg(kind === "approve" ? "Onaylandı." : "Reddedildi.");
      await t.reload();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function enableNotifications() {
    const p = await Notification.requestPermission();
    setPerm(p);
    onPrefsChanged();
  }

  const running = d?.jobs.find((j) => j.status === "running" || j.status === "pending") ?? null;
  const upcoming = (d?.schedules ?? []).filter((s) => s.enabled && s.next_run);
  const dueToday = upcoming.filter((s) => new Date(s.next_run!).toDateString() === new Date().toDateString()).length;
  const loaded = d?.system.loaded ?? [];

  return (
    <main className="today">
      <header className="hero">
        <div>
          <p className="muted hero-date">{d?.date ?? " "}</p>
          <h2 className="hero-title">{d?.greeting ?? "Merhaba"} <span aria-hidden>👋</span></h2>
          <p className="muted">
            {d?.holiday?.today ? <>Bugün resmi tatil: <strong>{d.holiday.today}</strong>. </> : null}
            {d?.holiday?.next && !d.holiday.today && d.holiday.days_left !== null && d.holiday.days_left <= 30
              ? <>Sıradaki tatil: {d.holiday.next.name} ({d.holiday.days_left} gün sonra). </> : null}
            {d ? (d.running ? `${d.running} iş sürüyor.` : "Ekip hazır, şu an çalışan iş yok.") : "Yükleniyor…"}
          </p>
        </div>
        <div className="quick">
          <button className="toggle" onClick={() => onNavigate({ page: "chat", convId: null })}><Icon name="chat" size={18} /> Yeni sohbet</button>
          <button onClick={() => onNavigate({ page: "flow", jobId: null })}><Icon name="office" size={18} /> Ofis</button>
          <button onClick={() => onNavigate({ page: "schedule" })}><Icon name="schedule" size={18} /> Görev planla</button>
          <button onClick={() => onNavigate({ page: "memory" })}><Icon name="memory" size={18} /> Hafıza</button>
        </div>
      </header>

      {t.error && !d && <p className="error page-pad">{t.error}</p>}

      <section className="stats" aria-label="Özet">
        <Stat icon="bell" label="onay bekliyor" value={String(d?.approvals.count ?? "–")} tone={d?.approvals.count ? "warn" : undefined}
              onClick={d?.approvals.count ? () => document.getElementById("today-approvals")?.focus() : undefined} />
        <Stat icon="office" label="çalışan iş" value={String(d?.running ?? "–")} tone={d?.running ? "ok" : undefined}
              onClick={() => onNavigate({ page: "flow", jobId: running?.id ?? null })} />
        <Stat icon="schedule" label="bugün planlı görev" value={String(d ? dueToday : "–")} onClick={() => onNavigate({ page: "schedule" })} />
        <Stat icon="models" label={d?.system.ollama ? (loaded.length ? loaded.map((m) => m.name).join(", ") : "model yüklü değil") : "Ollama erişilemiyor"}
              value={d ? (d.system.ollama ? `${loaded.reduce((a, m) => a + m.vram_gb, 0).toFixed(1)} GB` : "!") : "–"}
              tone={d && !d.system.ollama ? "bad" : undefined} onClick={() => onNavigate({ page: "models" })} />
      </section>

      {perm === "default" && d?.notifications.browser && (
        <div className="banner">
          <Icon name="bell" />
          <span>İş bitince ya da onay gerekince haber vereyim mi? Bildirimler yalnız bu bilgisayarda görünür.</span>
          <button className="toggle" onClick={() => void enableNotifications()}>Bildirimleri aç</button>
        </div>
      )}

      <div className="today-grid">
        <div className="col">
          <section className="panel" aria-labelledby="today-approvals">
            <div className="panel-head">
              <h2 id="today-approvals" tabIndex={-1}>Onay bekleyenler</h2>
              {d && d.approvals.count > d.approvals.items.length && <button className="ghost small" onClick={() => onNavigate({ page: "control" })}>Tümü ({d.approvals.count})</button>}
            </div>
            {d && d.approvals.count === 0 && <p className="muted empty-line"><Icon name="check" size={18} /> Bekleyen onay yok.</p>}
            <ul className="list">
              {d?.approvals.items.map((a) => (
                <li key={a.id} className="list-row">
                  <span className={`risk risk-${a.risk}`}>{a.risk}</span>
                  <span className="grow"><strong>{a.summary}</strong><span className="muted small"> · {a.requested_by} · {ago(a.created_at)}</span></span>
                  <button className="approve small" disabled={busy === a.id} onClick={() => void decide(a.id, "approve")}>Onayla</button>
                  <button className="reject small" disabled={busy === a.id} onClick={() => void decide(a.id, "reject")}>Reddet</button>
                </li>
              ))}
            </ul>
            {msg && <p className="note small" role="status">{msg}</p>}
          </section>

          <section className="panel" aria-labelledby="today-now">
            <div className="panel-head"><h2 id="today-now">Şu an</h2></div>
            {running ? (
              <OfficeView jobId={running.id} refreshKey={flowKey} approvalsKey={approvalsKey} compact
                          onExpand={() => onNavigate({ page: "flow", jobId: running.id })} />
            ) : (
              <>
                <p className="muted">Çalışan iş yok. Son işler:</p>
                <ul className="list">
                  {d?.jobs.slice(0, 4).map((j) => (
                    <li key={j.id}>
                      <button className="list-row link" onClick={() => onNavigate({ page: "flow", jobId: j.id })}>
                        <span className="grow ellipsis">{j.objective}</span>
                        <span className={`pill ${j.status === "succeeded" ? "ok" : j.status === "failed" ? "bad" : ""}`}>{STATUS[j.status] ?? j.status}</span>
                        <span className="muted small">{ago(j.created_at)}</span>
                      </button>
                    </li>
                  ))}
                  {d && d.jobs.length === 0 && <li className="muted">Henüz iş yok — Asistan'da "Otomatik" ile bir istek ver.</li>}
                </ul>
              </>
            )}
          </section>
        </div>

        <div className="col">
          <section className="panel" aria-labelledby="today-sched">
            <div className="panel-head">
              <h2 id="today-sched">Zamanlanmış görevler</h2>
              {d?.system.automation.paused && <span className="pill bad">otomasyon duraklatıldı</span>}
            </div>
            {d && d.schedules.length === 0 && <p className="muted">Henüz görev yok. <button className="ghost small" onClick={() => onNavigate({ page: "schedule" })}>Görev ekle</button></p>}
            <ul className="list">
              {d?.schedules.slice(0, 6).map((s) => (
                <li key={s.id} className={`list-row${s.enabled ? "" : " off"}`}>
                  <span className="grow">
                    <strong>{s.name}</strong>
                    <span className="muted small"> · {s.cadence}</span>
                    {s.last_run && <span className={`small block ${s.last_status === "failed" ? "error" : "muted"}`}>son: {STATUS[s.last_status ?? ""] ?? s.last_status} · {ago(s.last_run)}{s.last_message ? ` — ${s.last_message}` : ""}</span>}
                  </span>
                  <span className="pill">{s.enabled ? when(s.next_run) : "kapalı"}</span>
                </li>
              ))}
            </ul>
          </section>

          <section className="panel" aria-labelledby="today-chats">
            <div className="panel-head">
              <h2 id="today-chats">Son sohbetler</h2>
              <button className="ghost small" onClick={() => onNavigate({ page: "chat", convId: null })}><Icon name="plus" size={14} /> Yeni</button>
            </div>
            <ul className="list">
              {d?.chats.map((c) => (
                <li key={c.id}>
                  <button className="list-row link" onClick={() => onNavigate({ page: "chat", convId: c.id })}>
                    <Icon name="chat" size={16} />
                    <span className="grow ellipsis">{c.title}</span>
                    <span className="muted small">{ago(c.updated_at)}</span>
                  </button>
                </li>
              ))}
              {d && d.chats.length === 0 && <li className="muted">Henüz sohbet yok.</li>}
            </ul>
          </section>

          {d?.rates && (
            <section className="panel" aria-labelledby="today-rates">
              <div className="panel-head"><h2 id="today-rates">Döviz kurları</h2><span className="muted small">{d.rates.date ?? ""} · ECB</span></div>
              {d.rates.error ? <p className="error small">{d.rates.error}</p> : (
                <div className="rates">
                  {Object.entries(d.rates.per_try).map(([c, v]) => (
                    <div key={c} className="rate"><span className="muted">1 {c}</span><strong>{v.toFixed(2).replace(".", ",")} ₺</strong></div>
                  ))}
                </div>
              )}
            </section>
          )}
        </div>
      </div>
    </main>
  );
}
