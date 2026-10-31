import { useState } from "react";
import { post, type Approval } from "../api";
import { APPROVAL_STATUS_LABEL, RISK_LABEL, ago } from "../format";

function Preview({ a }: { a: Approval }) {
  const p = a.action.preview as Record<string, string | number | undefined>;
  return (
    <div className="preview">
      {a.action.reason && <p><strong>Neden riskli:</strong> {a.action.reason}</p>}
      {(p.old_head !== undefined || p.new_head !== undefined) && (
        <div className="diff">
          <div>
            <h4>Şu anki içerik {p.old_size !== undefined && <span className="muted">({p.old_size} bayt)</span>}</h4>
            <pre>{String(p.old_head ?? "")}</pre>
          </div>
          <div>
            <h4>Yeni içerik {p.new_size !== undefined && <span className="muted">({p.new_size} bayt)</span>}</h4>
            <pre>{String(p.new_head ?? "")}</pre>
          </div>
        </div>
      )}
      {a.action.undo && <p><strong>Geri alma:</strong> {a.action.undo}</p>}
      <p className="muted">İsteyen: {a.action.requested_by} · Araç: {a.action.tool}</p>
    </div>
  );
}

export function ApprovalsPanel({
  pending,
  history,
  onChanged,
}: {
  pending: Approval[] | null;
  history: Approval[] | null;
  onChanged: () => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<"pending" | "history">("pending");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const list = (tab === "pending" ? pending : history?.filter((a) => a.status !== "pending")) ?? [];
  const current = list.find((a) => a.id === selected) ?? null;

  async function decide(kind: "approve" | "reject") {
    if (!current) return;
    setBusy(true);
    setMessage(null);
    try {
      const res = await post<Approval>(`/api/approvals/${current.id}/${kind}`, { note });
      setMessage(`${APPROVAL_STATUS_LABEL[res.status]}: ${res.action.summary}${res.error ? ` — ${res.error}` : ""}`);
      setSelected(null);
      setNote("");
      onChanged();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="appr-title">
      <div className="panel-head">
        <h2 id="appr-title">Onay merkezi {pending && pending.length > 0 && <span className="count">{pending.length}</span>}</h2>
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "pending"} onClick={() => { setTab("pending"); setSelected(null); }}>Bekleyen</button>
          <button role="tab" aria-selected={tab === "history"} onClick={() => { setTab("history"); setSelected(null); }}>Geçmiş</button>
        </div>
      </div>
      {message && <p className="notice" role="status">{message}</p>}
      {list.length === 0 ? (
        <p className="muted">{tab === "pending" ? "Bekleyen onay yok." : "Henüz karar verilmiş talep yok."}</p>
      ) : (
        <ul className="approvals">
          {list.map((a) => (
            <li key={a.id}>
              <button className={`row ${a.id === selected ? "active" : ""}`} onClick={() => setSelected(a.id === selected ? null : a.id)}>
                <span className={`risk risk-${a.action.risk}`}>{RISK_LABEL[a.action.risk]}</span>
                <span className="summary">{a.action.summary}</span>
                <span className="muted when">{tab === "pending" ? ago(a.created_at) : APPROVAL_STATUS_LABEL[a.status]}</span>
              </button>
              {a.id === selected && (
                <div className="detail">
                  <Preview a={a} />
                  {a.status === "pending" ? (
                    <div className="decide">
                      <input placeholder="Not (isteğe bağlı)" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
                      <button className="approve" disabled={busy} onClick={() => void decide("approve")}>Onayla</button>
                      <button className="reject" disabled={busy} onClick={() => void decide("reject")}>Reddet</button>
                    </div>
                  ) : (
                    <p className="muted">
                      {APPROVAL_STATUS_LABEL[a.status]} · {a.decided_by ?? "—"} · {ago(a.decided_at)}
                      {a.decision_note ? ` · "${a.decision_note}"` : ""}{a.error ? ` · ${a.error}` : ""}
                    </p>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
