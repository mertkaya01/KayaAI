import { useState } from "react";
import { post, type SubmitResult } from "../api";
import { usePolling } from "../hooks";

interface Source { name: string; label: string; provider: string; host: string; sends: string; use: string; enabled: boolean }

/** İsteğe bağlı dış veri kaynakları (Adım 14c). Varsayılan kapalı; açmak sahip onayı ister (internete istek yapılır). */
export function IntegrationsPanel({ refreshKey }: { refreshKey: number }) {
  const list = usePolling<Source[]>("/api/integrations", 30000, refreshKey);
  const [note, setNote] = useState<string | null>(null);

  async function toggle(s: Source) {
    setNote(null);
    try {
      const r = await post<SubmitResult>(`/api/integrations/${s.name}/${s.enabled ? "disable" : "enable"}`, {});
      setNote(r.status === "awaiting_approval" ? "Açma talebi Onay merkezinde (önizlemede hangi siteye ne gittiği yazıyor)." : "Kapatıldı.");
      void list.reload();
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <section className="panel" aria-labelledby="integrations-title">
      <h2 id="integrations-title">Dış veri kaynakları</h2>
      <p className="muted small">Varsayılan kapalı. Açınca kayaAI yalnız bu siteye istek yapar; kişisel veri, sohbet ya da dosya gönderilmez, her istek kayda geçer.</p>
      <ul className="integrations">
        {list.data?.map((s) => (
          <li key={s.name}>
            <div>
              <strong>{s.label}</strong> <span className={`pill ${s.enabled ? "ok" : ""}`}>{s.enabled ? "açık" : "kapalı"}</span>
              <div className="muted small">{s.provider} · {s.host} · gönderilen: {s.sends}</div>
              <div className="muted small">Kullanım: {s.use}</div>
            </div>
            <button className="small" onClick={() => void toggle(s)} aria-label={`${s.label}: ${s.enabled ? "kapat" : "aç"}`}>
              {s.enabled ? "Kapat" : "Aç…"}
            </button>
          </li>
        ))}
      </ul>
      {note && <p className="note small" role="status">{note}</p>}
    </section>
  );
}
