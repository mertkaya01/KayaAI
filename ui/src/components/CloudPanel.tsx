import { useEffect, useState } from "react";
import { post, type Agent, type CloudStatus, type SubmitResult } from "../api";
import { usePolling } from "../hooks";

/** Bulut köprüsü (Adım 17): OmniRoute gibi yerel ağ geçidi. Varsayılan kapalı; açmak onaylı; anahtar yalnız terminalde. */
export function CloudPanel({ refreshKey }: { refreshKey: number }) {
  const st = usePolling<CloudStatus>("/api/cloud", 30000, refreshKey);
  const agents = usePolling<Agent[]>("/api/agents", 60000);
  const [form, setForm] = useState<{ base_url: string; model: string; agents: string[]; daily_limit: number } | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (st.data && !form) setForm({ base_url: st.data.base_url, model: st.data.model, agents: st.data.agents, daily_limit: st.data.daily_limit });
  }, [st.data, form]);

  async function run(fn: () => Promise<string>) {
    setBusy(true);
    setMsg(null);
    try { setMsg(await fn()); void st.reload(); } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }

  const s = st.data;
  const choosable = (agents.data ?? []).filter((a) => a.name !== "vision" && !a.name.includes("."));
  return (
    <section className="panel" aria-labelledby="cloud-title">
      <div className="panel-head">
        <h2 id="cloud-title">Bulut köprüsü</h2>
        {s && <span className={`pill ${s.enabled ? "ok" : ""}`}>{s.enabled ? "açık" : "kapalı"}</span>}
      </div>
      <p className="muted small">
        OmniRoute gibi bu bilgisayarda çalışan bir ağ geçidi üzerinden bulut modelleri. Yalnız bir istekte <strong>☁ Bulut</strong> dersen
        kullanılır; hafıza, yerel belgeler ve ekran görüntüleri asla gitmez, gizli bilgi görülen istek yerelde yapılır.
      </p>
      {s && (
        <p className="small">
          Bugün <strong>{s.used_today}</strong>/{s.daily_limit} çağrı · anahtar: {s.has_key ? <span className="ok-text">var ({s.key_source === "env" ? "ortam değişkeni" : "dosya"})</span>
            : <span className="warn-text">yok — terminalde <code>kayaai cloud key</code></span>}
        </p>
      )}
      {form && (
        <div className="form-grid">
          <label className="field">Ağ geçidi adresi
            <input value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} spellCheck={false} />
          </label>
          <label className="field">Model <span className="muted small">(auto, auto/fast, sağlayıcı/model)</span>
            <input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} spellCheck={false} />
          </label>
          <fieldset className="kinds">
            <legend className="muted small">Buluta izinli ajanlar</legend>
            <div className="agent-checks">
              {choosable.map((a) => (
                <label key={a.name} className="check"><input type="checkbox" checked={form.agents.includes(a.name)}
                  onChange={(e) => setForm({ ...form, agents: e.target.checked ? [...form.agents, a.name] : form.agents.filter((x) => x !== a.name) })} /> {a.name}</label>
              ))}
            </div>
          </fieldset>
          <label className="field">Günlük çağrı sınırı
            <input type="number" min={1} max={10000} value={form.daily_limit} onChange={(e) => setForm({ ...form, daily_limit: Number(e.target.value) || 1 })} />
          </label>
        </div>
      )}
      <div className="row-actions start">
        <button className="toggle" disabled={busy || !form} onClick={() => void run(async () => {
          const r = await post<SubmitResult>("/api/cloud/enable", form);
          return r.status === "awaiting_approval" ? "Açma talebi Onay merkezinde — önizlemede neyin gidip neyin gitmediği yazıyor." : "Açıldı.";
        })}>{s?.enabled ? "Ayarları güncelle…" : "Aç…"}</button>
        {s?.enabled && <button disabled={busy} onClick={() => void run(async () => { await post("/api/cloud/disable", {}); return "Kapatıldı."; })}>Kapat</button>}
        <button className="ghost" disabled={busy} onClick={() => void run(async () => {
          const r = await post<{ ok: boolean; models?: string[]; error?: string }>("/api/cloud/test", {});
          return r.ok ? `Bağlantı tamam · ${r.models?.length ?? 0} model: ${(r.models ?? []).slice(0, 6).join(", ")}` : `Bağlanamadı: ${r.error}`;
        })}>Bağlantıyı dene</button>
      </div>
      {msg && <p className="note small" role="status">{msg}</p>}
    </section>
  );
}
