import { useState } from "react";
import { post, type Agent, type ProvidersStatus, type SubmitResult } from "../api";
import { usePolling } from "../hooks";
import { InlineApproval } from "./ProvidersPanel";

/** Ajan → dış model (Adım 20b): bir ajanın BÜTÜN işlerini açık bir dış sağlayıcıya ver (sahip onayı R2) ya da yerele al. */
export function AgentCloudPanel() {
  const [key, setKey] = useState(0);
  const st = usePolling<ProvidersStatus>("/api/providers", 20000, key);
  const agents = usePolling<Agent[]>("/api/agents", 60000);
  const [want, setWant] = useState<Record<string, { provider: string; model: string }>>({});
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const open = (st.data?.providers ?? []).filter((p) => p.enabled);
  const list = (agents.data ?? []).filter((a) => !a.name.includes(".") && a.name !== "vision");

  async function submit(agent: string, provider: string, model: string) {
    setBusy(true);
    setMsg(null);
    try {
      const r = await post<SubmitResult>("/api/providers/assign", provider ? { agent, provider, model } : { agent });
      setMsg(r.status === "awaiting_approval" ? null : provider ? "Atandı." : `${agent} yerel modele alındı.`);
      setKey((k) => k + 1);
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }

  return (
    <section className="panel" aria-labelledby="agent-cloud-title">
      <h2 id="agent-cloud-title">Ajan → dış model</h2>
      <p className="muted small">
        Bir ajanın bütün işlerini (zamanlanmış görevler dahil) açık bir dış sağlayıcıya ver; örneğin Şef'i (planner) büyük bir modele.
        Atamak senin onayını ister. Hafıza, belgeler, ekran ve bilgisayar ölçümü yine gitmez; hata olursa yerel model yapar.
      </p>
      {open.length === 0 && <p className="muted small">Açık dış sağlayıcı yok. Soldaki Dış sağlayıcılar panelinden ekleyip aç.</p>}
      <ul className="agent-models">
        {list.map((a) => {
          const cur = st.data?.assignments[a.name];
          const pending = st.data?.pending_assign[a.name];
          const w = want[a.name] ?? { provider: cur?.provider ?? "", model: cur?.model ?? "" };
          const prov = open.find((p) => p.id === w.provider);
          const model = w.model || prov?.default_model || "";
          const changed = (w.provider || "") !== (cur?.provider || "") || (w.provider && model !== (cur?.model || ""));
          return (
            <li key={a.name}>
              <div>
                <strong>{a.name}</strong>{" "}
                <span className={`pill ${cur ? "warn" : ""}`}>{cur ? `☁ ${cur.provider}/${cur.model}` : "yerel"}</span>
                {pending && <InlineApproval id={pending} title={`${a.name} için dış model ataması onay bekliyor.`} okLabel="Onayla ve ata"
                                            onDone={(m) => { setMsg(m); setKey((k) => k + 1); }} />}
              </div>
              {(open.length > 0 || cur) && !pending && (
                <div className="row-actions start">
                  <select aria-label={`${a.name}: sağlayıcı`} value={w.provider} disabled={busy}
                          onChange={(e) => setWant((x) => ({ ...x, [a.name]: { provider: e.target.value, model: "" } }))}>
                    <option value="">Yerel</option>
                    {open.map((p) => <option key={p.id} value={p.id}>☁ {p.label}</option>)}
                  </select>
                  {prov && prov.models.length > 0 && (
                    <select aria-label={`${a.name}: model`} value={model} disabled={busy}
                            onChange={(e) => setWant((x) => ({ ...x, [a.name]: { provider: w.provider, model: e.target.value } }))}>
                      {prov.models.map((m) => <option key={m} value={m}>{m}</option>)}
                    </select>
                  )}
                  <button className="small" disabled={busy || !changed} onClick={() => void submit(a.name, w.provider, model)}>
                    {w.provider ? "Ata…" : "Yerele al"}
                  </button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {msg && <p className="note small" role="status">{msg}</p>}
    </section>
  );
}
