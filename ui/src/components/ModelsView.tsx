import { useEffect, useMemo, useState } from "react";
import { post, type CompareRecord, type KEvent, type ModelAdmin, type ModelRow, type SubmitResult } from "../api";
import { ago } from "../format";
import { usePolling } from "../hooks";

const STATUS_TEXT: Record<ModelRow["status"], string> = { active: "aktif", candidate: "aday", unregistered: "kayıtsız" };

/** Yükle/boşalt hemen olur (R1); ajan ataması, indirme ve aktif yapma sahip onayı ister (R2, Onay merkezi). */
function useAction(onDone: () => void) {
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  async function run(id: string, path: string, body: unknown, doneText: string) {
    setBusy(id);
    setNote(null);
    try {
      const r = await post<SubmitResult>(path, body);
      if (r.status === "awaiting_approval") setNote({ ok: true, text: "Onay bekliyor — Kontrol Merkezi → Onay merkezinden onayla." });
      else if (r.status === "failed") setNote({ ok: false, text: r.error ?? "Başarısız" });
      else setNote({ ok: true, text: doneText });
      onDone();
    } catch (e) {
      setNote({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  }
  return { busy, note, run, setNote };
}

function ModelTable({ data, act }: { data: ModelAdmin; act: ReturnType<typeof useAction> }) {
  return (
    <div className="table-wrap">
      <table className="mtable">
        <thead>
          <tr><th>Model</th><th>Durum</th><th>Boyut</th><th>VRAM</th><th>Bellekte</th><th>Kullanan</th><th></th></tr>
        </thead>
        <tbody>
          {data.models.map((m) => (
            <tr key={m.name} className={m.installed === false ? "dim" : ""}>
              <td>
                <strong>{m.name}</strong>{m.key && <span className="muted"> · {m.key}</span>}
                <div className="muted small">{[m.family, m.parameters, m.quantization].filter(Boolean).join(" · ") || m.purpose}</div>
              </td>
              <td>
                <span className={`pill ${m.status === "active" ? "ok" : m.status === "candidate" ? "warn" : ""}`}>{STATUS_TEXT[m.status]}</span>
                {m.installed === false && <div className="muted small">kurulu değil</div>}
              </td>
              <td>{m.size_gb != null ? `${m.size_gb} GB` : "—"}</td>
              <td>{m.approx_vram_gb != null ? `~${m.approx_vram_gb} GB` : "—"}</td>
              <td>
                {m.loaded ? (
                  <span className="ok-text">● {m.loaded.vram_gb ?? "?"} GB{m.loaded.expires_at && <span className="muted small"> · bitiş {until(m.loaded.expires_at)}</span>}</span>
                ) : <span className="muted">—</span>}
              </td>
              <td className="small">{m.agents.join(", ") || <span className="muted">—</span>}</td>
              <td>
                {m.installed && (m.loaded ? (
                  <button className="small" disabled={act.busy !== null} onClick={() => void act.run(`u-${m.name}`, "/api/models/unload", { name: m.name }, `${m.name} bellekten çıkarıldı`)}>
                    {act.busy === `u-${m.name}` ? "…" : "Boşalt"}
                  </button>
                ) : (
                  <button className="small" disabled={act.busy !== null} onClick={() => void act.run(`l-${m.name}`, "/api/models/load", { name: m.name }, `${m.name} belleğe yüklendi`)}>
                    {act.busy === `l-${m.name}` ? "Yükleniyor…" : "Yükle"}
                  </button>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function until(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime()) || d.getFullYear() > 2100) return "süresiz";
  return d.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
}

function AgentModels({ data, act }: { data: ModelAdmin; act: ReturnType<typeof useAction> }) {
  const choices = data.models.filter((m) => m.key && m.status === "active" && m.installed && !m.embedding);
  const [want, setWant] = useState<Record<string, string>>({});
  return (
    <ul className="agent-models">
      {data.agents.map((a) => {
        const sel = want[a.name] ?? a.model_key;
        return (
          <li key={a.name}>
            <div>
              <strong>{a.name}</strong>
              {a.overridden && <span className="pill warn" title="data/agent_overrides.yaml">değiştirildi</span>}
              {a.user_agent && <span className="pill">sonradan oluşturuldu</span>}
              <div className="muted small">{a.description}</div>
            </div>
            <select aria-label={`${a.name} modeli`} value={sel} onChange={(e) => setWant((w) => ({ ...w, [a.name]: e.target.value }))}>
              {!choices.some((c) => c.key === a.model_key) && <option value={a.model_key}>{a.model_name}</option>}
              {choices.map((c) => <option key={c.key} value={c.key!}>{c.name}</option>)}
            </select>
            <button className="small" disabled={sel === a.model_key || act.busy !== null}
              onClick={() => void act.run(`a-${a.name}`, `/api/agents/${a.name}/model`, { model_key: sel }, "Atandı")}>
              Değiştir
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function Pull({ data, act }: { data: ModelAdmin; act: ReturnType<typeof useAction> }) {
  const [name, setName] = useState("");
  return (
    <>
      <form className="pull-form" onSubmit={(e) => { e.preventDefault(); if (name.trim()) void act.run("pull", "/api/models/pull", { name: name.trim() }, "İndiriliyor"); }}>
        <input placeholder="ör. qwen3:4b" value={name} onChange={(e) => setName(e.target.value)} aria-label="Ollama model adı" />
        <button type="submit" disabled={!name.trim() || act.busy !== null}>İndir</button>
      </form>
      <p className="muted small">Ollama kütüphanesindeki ad:etiket. İndirmeden önce lisansını kontrol et; inen model <em>aday</em> olur, karşılaştırıp aktif yapmadan ajana atanamaz.</p>
      {data.pulls.map((p) => {
        const pct = p.total ? Math.round((100 * p.completed) / p.total) : null;
        return (
          <div key={p.name} className="pull-row">
            <div className="panel-head"><span>{p.name}</span><span className={p.error ? "error small" : "muted small"}>{p.error ?? p.status}{pct != null && !p.error ? ` · %${pct}` : ""}</span></div>
            <div className="bar"><span style={{ width: `${p.status === "tamamlandı" ? 100 : pct ?? 0}%` }} /></div>
          </div>
        );
      })}
    </>
  );
}

function CompareResult({ rec, data, act }: { rec: CompareRecord; data: ModelAdmin; act: ReturnType<typeof useAction> }) {
  const cand = data.models.find((m) => m.key === rec.candidate);
  return (
    <div className="compare-rec">
      <div className="panel-head">
        <strong>{rec.agent}: {rec.summary.current?.model ?? rec.current} ↔ {rec.summary.candidate?.model ?? rec.candidate}</strong>
        <span className="muted small">{ago(rec.finished_at ?? rec.started_at)}</span>
      </div>
      {rec.status === "failed" && <p className="error">{rec.error}</p>}
      {rec.status === "done" && (
        <>
          <table className="mtable">
            <thead><tr><th></th><th>Model</th><th>Doğru</th><th>Ort. süre</th><th>Token/sn</th></tr></thead>
            <tbody>
              {(["current", "candidate"] as const).map((side) => {
                const s = rec.summary[side];
                return s && (
                  <tr key={side}>
                    <td>{side === "current" ? "Mevcut" : "Aday"}</td><td>{s.model}</td>
                    <td><strong>{s.ok}/{s.cases}</strong></td><td>{s.avg_seconds} sn</td><td>{s.avg_tokens_per_second ?? "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <details>
            <summary>Vakalar</summary>
            {(["current", "candidate"] as const).map((side) => (
              <div key={side}>
                <h4>{rec.summary[side]?.model}</h4>
                <ul className="cases">
                  {(rec.rows[side] ?? []).map((r, i) => (
                    <li key={i} className={r.ok ? "" : "bad"} title={r.answer_head}>
                      {r.ok ? "✓" : "✗"} {r.request}
                      {!r.ok && <span className="muted small"> — {[
                        !r.succeeded && "görev başarısız", r.missing.length && `eksik: ${r.missing.join(", ")}`,
                        !r.language_ok && "yanlış dil", !r.code_ok && "kod hatalı", r.foreign_script && "yabancı yazı",
                      ].filter(Boolean).join("; ")}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </details>
          {cand?.status === "candidate" && (
            <button disabled={act.busy !== null} onClick={() => void act.run(`act-${rec.candidate}`, `/api/models/${rec.candidate}/activate`, {}, "Aktif")}>
              {cand.name} modelini aktif yap…
            </button>
          )}
        </>
      )}
    </div>
  );
}

function Compare({ data, act, progress, onStarted }: {
  data: ModelAdmin; act: ReturnType<typeof useAction>; progress: { done: number; total: number } | null; onStarted: () => void;
}) {
  const agents = data.agents.filter((a) => a.output === "answer");
  const [agent, setAgent] = useState(agents[0]?.name ?? "");
  const current = agents.find((a) => a.name === agent)?.model_key;
  const cands = data.models.filter((m) => m.key && m.installed && !m.embedding && m.key !== current);
  const [cand, setCand] = useState("");
  const candidate = cands.some((c) => c.key === cand) ? cand : cands[0]?.key ?? "";
  const running = data.compares.find((c) => c.status === "running");
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setError(null);
    try {
      await post("/api/model-compare", { agent, candidate });
      onStarted();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <>
      <div className="compare-form">
        <label>Ajan <select value={agent} onChange={(e) => setAgent(e.target.value)}>{agents.map((a) => <option key={a.name}>{a.name}</option>)}</select></label>
        <label>Aday <select value={candidate} onChange={(e) => setCand(e.target.value)}>
          {cands.map((c) => <option key={c.key} value={c.key!}>{c.name}{c.status === "candidate" ? " (aday)" : ""}</option>)}
        </select></label>
        <button disabled={!agent || !candidate || !!running || act.busy !== null} onClick={() => void start()}>Karşılaştır</button>
      </div>
      <p className="muted small">Ajanın sabit görev setinde iki model sırayla çalışır (ayrı kayıt, geçmiş kirlenmez); doğruluk kodla ölçülür.</p>
      {error && <p className="error">{error}</p>}
      {running && (
        <div className="pull-row">
          <div className="panel-head"><span>Sürüyor: {running.agent} · {running.candidate}</span><span className="muted small">{progress ? `${progress.done}/${progress.total}` : "başlıyor"}</span></div>
          <div className="bar"><span style={{ width: `${progress && progress.total ? (100 * progress.done) / progress.total : 3}%` }} /></div>
        </div>
      )}
      {data.compares.filter((c) => c.status !== "running").slice(0, 3).map((c) => <CompareResult key={c.id} rec={c} data={data} act={act} />)}
    </>
  );
}

export function ModelsView({ refreshKey, events }: { refreshKey: number; events: KEvent[] }) {
  const [local, setLocal] = useState(0);
  const [busyBg, setBusyBg] = useState(false);
  const admin = usePolling<ModelAdmin>("/api/model-admin", busyBg ? 2000 : 10000, `${refreshKey}-${local}`);
  const act = useAction(() => setLocal((k) => k + 1));
  const data = admin.data;
  useEffect(() => {
    setBusyBg(!!data && (data.compares.some((c) => c.status === "running")
      || data.pulls.some((p) => p.status !== "tamamlandı" && p.status !== "hata")));
  }, [data]);
  const progress = useMemo(() => {
    const running = data?.compares.find((c) => c.status === "running");
    const ev = running && events.find((e) => e.type === "model.compare" && e.data.id === running.id && e.data.total);
    return ev ? { done: Number(ev.data.done), total: Number(ev.data.total) } : null;
  }, [data, events]);
  useEffect(() => {
    if (!act.note) return;
    const id = window.setTimeout(() => act.setNote(null), 8000);
    return () => window.clearTimeout(id);
  }, [act.note]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!data) return <main className="models"><p className="muted">{admin.error ?? "Yükleniyor…"}</p></main>;
  return (
    <main className="models">
      {!data.ollama_reachable && <p className="error">Ollama'ya ulaşılamıyor: kurulu/yüklü bilgisi yok. (`ollama serve` çalışıyor mu?)</p>}
      {act.note && <p className={act.note.ok ? "note ok-text" : "error"} role="status">{act.note.text}</p>}
      <section className="panel">
        <h2>Modeller</h2>
        <ModelTable data={data} act={act} />
      </section>
      <div className="models-grid">
        <section className="panel">
          <h2>Ajan → model</h2>
          <p className="muted small">Değişiklik sahip onayı ister; repo dosyaları değişmez (data/agent_overrides.yaml).</p>
          <AgentModels data={data} act={act} />
        </section>
        <div className="col">
          <section className="panel">
            <h2>Yeni model indir</h2>
            <Pull data={data} act={act} />
          </section>
          <section className="panel">
            <h2>Karşılaştır</h2>
            <Compare data={data} act={act} progress={progress} onStarted={() => setLocal((k) => k + 1)} />
          </section>
        </div>
      </div>
    </main>
  );
}
