import { useState } from "react";
import { post, type Agent } from "../api";
import { STATE_LABEL, ago } from "../format";

const CREATOR: Record<string, string> = { owner: "sen", planner: "yerel planlayıcı", claude: "Claude şef" };

function Lifecycle({ a, onChanged }: { a: Agent; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function act(kind: "promote" | "remove") {
    if (kind === "remove" && !window.confirm(`'${a.name}' geçici ajanı kaldırılsın mı?`)) return;
    setBusy(true);
    setMessage(null);
    try {
      await post(`/api/agents/${a.name}/${kind}`, {});
      setMessage(kind === "promote" ? "Onay talebi oluşturuldu → Onay merkezi" : "Kaldırıldı");
      onChanged();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!a.created_by) return null;
  const temp = a.lifecycle === "temporary";
  return (
    <div className="lifecycle">
      <p className="muted">
        {temp ? "Geçici" : "Sonradan eklendi"} · temel: {a.base} · oluşturan: {CREATOR[a.created_by] ?? a.created_by}
        {" · "}kullanım: {a.successes ?? 0}/{a.uses ?? 0} başarılı
      </p>
      {temp && (
        <div className="decide">
          <button className="approve" disabled={busy || !a.successes} title={a.successes ? "" : "Önce en az bir kez başarıyla kullanılmalı"} onClick={() => void act("promote")}>
            Kalıcı yap
          </button>
          <button className="reject" disabled={busy} onClick={() => void act("remove")}>Kaldır</button>
        </div>
      )}
      {message && <p className="notice" role="status">{message}</p>}
    </div>
  );
}

export function AgentsPanel({ agents, error, onChanged }: { agents: Agent[] | null; error: string | null; onChanged: () => void }) {
  return (
    <section className="panel" aria-labelledby="agents-title">
      <h2 id="agents-title">Ajanlar</h2>
      {error && <p className="error">{error}</p>}
      {!agents ? (
        <p className="muted">Yükleniyor…</p>
      ) : (
        <div className="agents">
          {agents.map((a) => (
            <article key={a.name} className={`agent state-${a.status.state}${a.lifecycle === "temporary" ? " temporary" : ""}`}>
              <header>
                <h3>
                  {a.name}
                  {a.lifecycle === "temporary" && <span className="badge temp">geçici</span>}
                </h3>
                <span className={`badge state-${a.status.state}`}>{STATE_LABEL[a.status.state]}</span>
              </header>
              <p className="desc">{a.description}</p>
              <dl>
                <dt>Yerel model</dt>
                <dd>{a.local_model}</dd>
                <dt>Claude karşılığı</dt>
                <dd>{a.claude_tier === "none" ? "—" : a.claude_tier}</dd>
                <dt>Gözden geçiren</dt>
                <dd>{a.reviewed_by ? `${a.reviewed_by}${a.checks.length ? " + kod kontrolü" : ""}` : "—"}</dd>
                <dt>{a.status.state === "running" || a.status.state === "waiting" ? "Şu anki görev" : "Son görev"}</dt>
                <dd className="task">{a.status.current_task ?? "—"}</dd>
                <dt>Son bitiş</dt>
                <dd>{ago(a.status.last_finished_at)}</dd>
              </dl>
              {a.status.result_available && <p className="ok-text">Sonuç hazır</p>}
              <Lifecycle a={a} onChanged={onChanged} />
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
