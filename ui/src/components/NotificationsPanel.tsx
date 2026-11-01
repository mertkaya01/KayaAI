import { useEffect, useState } from "react";
import { api, post, type NotifyPrefs } from "../api";
import { notificationsSupported } from "../notify";

/** Bildirim ayarları (Adım 16c): tarayıcı + Windows, türler, sessiz saatler, deneme. */
export function NotificationsPanel({ refreshKey, onChanged }: { refreshKey: number; onChanged: () => void }) {
  const [p, setP] = useState<NotifyPrefs | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [perm, setPerm] = useState(() => (notificationsSupported() ? Notification.permission : "unsupported"));

  useEffect(() => { api<NotifyPrefs>("/api/notifications").then(setP).catch((e) => setMsg(String(e))); }, [refreshKey]);

  async function save(next: NotifyPrefs) {
    setP(next);
    setMsg(null);
    try {
      const { labels: _l, ...body } = next;
      setP(await post<NotifyPrefs>("/api/notifications", body));
      onChanged();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  }

  async function testBrowser() {
    let perm2 = perm;
    if (perm === "default") { perm2 = await Notification.requestPermission(); setPerm(perm2); }
    if (perm2 === "granted") new Notification("kayaAI · Deneme", { body: "Tarayıcı bildirimleri çalışıyor." });
    else setMsg("Tarayıcı bildirim izni verilmedi (adres çubuğundaki kilit simgesinden açılabilir).");
  }

  async function testWindows() {
    const r = await post<{ windows: boolean }>("/api/notifications/test", {});
    setMsg(r.windows ? "Windows bildirimi gönderildi." : "Windows bildirimi gönderilemedi (yalnız Windows'ta çalışır).");
  }

  if (!p) return <section className="panel"><h2>Bildirimler</h2><p className="muted">{msg ?? "Yükleniyor…"}</p></section>;
  return (
    <section className="panel" aria-labelledby="notify-title" id="bildirimler">
      <h2 id="notify-title">Bildirimler</h2>
      <div className="form-grid">
        <label className="check"><input type="checkbox" checked={p.browser} onChange={(e) => void save({ ...p, browser: e.target.checked })} />
          Tarayıcı bildirimi <span className="muted small">(sekme arka plandayken{perm === "denied" ? " · izin reddedildi" : perm === "default" ? " · izin henüz verilmedi" : ""})</span></label>
        <label className="check"><input type="checkbox" checked={p.windows} onChange={(e) => void save({ ...p, windows: e.target.checked })} />
          Windows bildirimi <span className="muted small">(kayaAI kapalıyken çalışan zamanlanmış görevler)</span></label>
        <fieldset className="kinds">
          <legend className="muted small">Hangi durumlarda</legend>
          {Object.entries(p.labels ?? {}).map(([k, label]) => (
            <label key={k} className="check"><input type="checkbox" checked={!!p.kinds[k]}
              onChange={(e) => void save({ ...p, kinds: { ...p.kinds, [k]: e.target.checked } })} /> {label}</label>
          ))}
        </fieldset>
        <div className="quiet">
          <span className="muted small">Sessiz saatler</span>
          <input type="time" aria-label="Sessiz saat başlangıcı" value={p.quiet_start ?? ""} onChange={(e) => void save({ ...p, quiet_start: e.target.value || null })} />
          <span className="muted">–</span>
          <input type="time" aria-label="Sessiz saat bitişi" value={p.quiet_end ?? ""} onChange={(e) => void save({ ...p, quiet_end: e.target.value || null })} />
        </div>
      </div>
      <div className="row-actions start">
        {notificationsSupported() && <button className="ghost small" onClick={() => void testBrowser()}>Tarayıcıyı dene</button>}
        <button className="ghost small" onClick={() => void testWindows()}>Windows'u dene</button>
      </div>
      {msg && <p className="note small" role="status">{msg}</p>}
    </section>
  );
}
