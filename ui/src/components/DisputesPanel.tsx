import { useState } from "react";
import { post, type Dispute } from "../api";
import { DISPUTE_RESOLUTION_LABEL, ago } from "../format";

/** Ajan anlaşmazlıkları (Adım 7): gözden geçirici bir sorun bildirdi, üretici itiraz etti. Karar sahibin. */
export function DisputesPanel({
  open,
  history,
  onChanged,
}: {
  open: Dispute[] | null;
  history: Dispute[] | null;
  onChanged: () => void;
}) {
  const [tab, setTab] = useState<"open" | "history">("open");
  const [selected, setSelected] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const list = (tab === "open" ? open : history?.filter((d) => d.status !== "open")) ?? [];
  const current = list.find((d) => d.id === selected) ?? null;

  async function decide(side: "producer" | "reviewer") {
    if (!current) return;
    setBusy(true);
    setMessage(null);
    try {
      const res = await post<Dispute>(`/api/disputes/${current.id}/resolve`, { side, note });
      setMessage(`Karar kaydedildi: ${side === "producer" ? res.producer : res.reviewer} haklı.`);
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
    <section className="panel" aria-labelledby="disp-title">
      <div className="panel-head">
        <h2 id="disp-title">Anlaşmazlıklar {open && open.length > 0 && <span className="count">{open.length}</span>}</h2>
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "open"} onClick={() => { setTab("open"); setSelected(null); }}>Açık</button>
          <button role="tab" aria-selected={tab === "history"} onClick={() => { setTab("history"); setSelected(null); }}>Geçmiş</button>
        </div>
      </div>
      {message && <p className="notice" role="status">{message}</p>}
      {list.length === 0 ? (
        <p className="muted">{tab === "open" ? "Ajanlar arasında açık anlaşmazlık yok." : "Henüz kapanmış anlaşmazlık yok."}</p>
      ) : (
        <ul className="approvals">
          {list.map((d) => (
            <li key={d.id}>
              <button className={`row ${d.id === selected ? "active" : ""}`} onClick={() => setSelected(d.id === selected ? null : d.id)}>
                <span className="risk risk-R2">{d.producer} ↔ {d.reviewer}</span>
                <span className="summary">{d.issue}</span>
                <span className="muted when">
                  {d.status === "open" ? (d.escalated_to === "claude" ? "Claude'da" : ago(d.created_at)) : DISPUTE_RESOLUTION_LABEL[d.resolution ?? ""] ?? d.resolution}
                </span>
              </button>
              {d.id === selected && (
                <div className="detail">
                  <p className="muted">İstek: {d.request.slice(0, 300)}</p>
                  <div className="diff">
                    <div>
                      <h4>Gözden geçirici ({d.reviewer}) · {d.severity}</h4>
                      <pre>{d.issue}{d.evidence ? `\n\nKanıt: “${d.evidence}”` : ""}</pre>
                    </div>
                    <div>
                      <h4>Üretici ({d.producer}) itirazı</h4>
                      <pre>{d.producer_position}</pre>
                    </div>
                  </div>
                  {d.status === "open" ? (
                    <>
                      {d.escalated_to === "claude" && <p className="muted">Bu anlaşmazlık Claude kutusunda; yine de sen karar verebilirsin.</p>}
                      <div className="decide">
                        <input placeholder="Not (isteğe bağlı)" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
                        <button className="approve" disabled={busy} onClick={() => void decide("producer")}>{d.producer} haklı</button>
                        <button className="reject" disabled={busy} onClick={() => void decide("reviewer")}>{d.reviewer} haklı</button>
                      </div>
                    </>
                  ) : (
                    <p className="muted">
                      {DISPUTE_RESOLUTION_LABEL[d.resolution ?? ""] ?? d.resolution} · {d.decided_by ?? "—"} · {ago(d.decided_at)}
                      {d.note ? ` · "${d.note}"` : ""}
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
