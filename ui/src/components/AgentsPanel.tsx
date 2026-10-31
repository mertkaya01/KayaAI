import type { Agent } from "../api";
import { STATE_LABEL, ago } from "../format";

export function AgentsPanel({ agents, error }: { agents: Agent[] | null; error: string | null }) {
  return (
    <section className="panel" aria-labelledby="agents-title">
      <h2 id="agents-title">Ajanlar</h2>
      {error && <p className="error">{error}</p>}
      {!agents ? (
        <p className="muted">Yükleniyor…</p>
      ) : (
        <div className="agents">
          {agents.map((a) => (
            <article key={a.name} className={`agent state-${a.status.state}`}>
              <header>
                <h3>{a.name}</h3>
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
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
