import { useEffect, useMemo, useState } from "react";
import { api, ApiError, type FlowNode, type JobGraph, type JobSummary } from "../api";
import { NODE_H, NODE_W, layout } from "../dag";
import { ago } from "../format";
import { usePolling } from "../hooks";
import { OfficeView } from "./OfficeView";
import { OfficeArtPanel } from "./OfficeArtPanel";
import { EmptyState } from "./EmptyState";

const STATUS_TEXT: Record<string, string> = {
  pending: "bekliyor", running: "çalışıyor", succeeded: "tamamlandı", failed: "başarısız", waiting: "bekletiliyor", skipped: "atlandı",
};
const JOB_STATUS: Record<string, string> = {
  pending: "sırada", running: "çalışıyor", succeeded: "tamamlandı", failed: "başarısız", waiting_claude: "Claude kutusunda",
  cancelled: "iptal", timed_out: "zaman aşımı",
};
const KIND_TEXT: Record<string, string> = {
  request: "istek", planner: "planlama", step: "ajan adımı", check: "gözden geçirme", revise: "düzeltme",
  review: "son kontrol", addendum: "ek", merge: "birleştirme", result: "sonuç", claude: "Claude",
};

function NodeBox({ n, x, y, selected, onClick }: { n: FlowNode; x: number; y: number; selected: boolean; onClick: () => void }) {
  const sub = [n.model ?? (n.kind === "step" ? n.agent : null), n.duration_s != null ? `${n.duration_s} sn` : null].filter(Boolean).join(" · ");
  return (
    <g className={`fnode st-${n.status} k-${n.kind}${selected ? " sel" : ""}`} transform={`translate(${x},${y})`} onClick={onClick}
      role="button" tabIndex={0} aria-label={`${n.label}: ${STATUS_TEXT[n.status]}`}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onClick(); }}>
      <rect width={NODE_W} height={NODE_H} rx={10} />
      <circle className="dot-s" cx={14} cy={16} r={5} />
      <text x={26} y={20} className="t1">{n.label.length > 20 ? `${n.label.slice(0, 19)}…` : n.label}</text>
      <text x={12} y={38} className="t2">{KIND_TEXT[n.kind]}{n.review?.revised ? " · düzeltildi" : ""}{n.review?.disputes ? " · anlaşmazlık" : ""}</text>
      <text x={12} y={52} className="t2">{sub.length > 28 ? `${sub.slice(0, 27)}…` : sub}</text>
    </g>
  );
}

function Graph({ g, selected, onSelect }: { g: JobGraph; selected: string | null; onSelect: (id: string) => void }) {
  const { pos, width, height } = useMemo(() => layout(g.nodes, g.edges), [g]);
  return (
    <div className="flow-scroll">
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="flow-svg" role="img" aria-label="İş akışı grafiği">
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" className="arrowhead" />
          </marker>
        </defs>
        {g.edges.map((e, i) => {
          const a = pos[e.source];
          const b = pos[e.target];
          if (!a || !b) return null;
          const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2, x2 = b.x - 2, y2 = b.y + NODE_H / 2;
          const mx = (x1 + x2) / 2;
          const target = g.nodes.find((n) => n.id === e.target);
          return <path key={i} d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`} className={`fedge st-${target?.status ?? "pending"}`} markerEnd="url(#arrow)" />;
        })}
        {g.nodes.map((n) => pos[n.id] && (
          <NodeBox key={n.id} n={n} x={pos[n.id].x} y={pos[n.id].y} selected={n.id === selected} onClick={() => onSelect(n.id)} />
        ))}
      </svg>
    </div>
  );
}

function readPref(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}

export function FlowView({ jobId, onSelect, refreshKey, approvalsKey }: { jobId: string | null; onSelect: (id: string | null) => void; refreshKey: number; approvalsKey: number }) {
  const [mode, setMode] = useState<"office" | "graph">(() => (readPref("kayaai.flowMode") === "graph" ? "graph" : "office"));
  const [art, setArt] = useState(false);
  const pick = (m: "office" | "graph") => { setMode(m); try { localStorage.setItem("kayaai.flowMode", m); } catch { /* özel pencere */ } };
  const jobs = usePolling<JobSummary[]>("/api/jobs?limit=40", 15000, refreshKey);
  const [graph, setGraph] = useState<JobGraph | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const active = jobId ?? jobs.data?.[0]?.id ?? null;
  const live = graph?.status === "running" || graph?.status === "pending";

  useEffect(() => {
    if (!active) { setGraph(null); return; }
    let stop = false;
    api<JobGraph>(`/api/jobs/${active}/graph`)
      .then((g) => { if (!stop) { setGraph(g); setError(null); } })
      .catch((e) => { if (!stop) setError(e instanceof ApiError && e.status === 404 ? "İş bulunamadı." : String(e)); });
    return () => { stop = true; };
  }, [active, refreshKey, tick]);

  useEffect(() => {
    if (!live) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 1500);
    return () => window.clearInterval(id);
  }, [live]);

  const node = graph?.nodes.find((n) => n.id === selected) ?? null;
  return (
    <main className="flow">
      <aside className="panel flow-list">
        <h2>İşler</h2>
        {jobs.data?.length === 0 && (
          <EmptyState icon="office" title="Henüz iş yok">Asistan'da bir şey sor; ekip burada çalışırken görünür.</EmptyState>
        )}
        <ul>
          {jobs.data?.map((j) => (
            <li key={j.id}>
              <button className={`conv${j.id === active ? " activej" : ""}`} onClick={() => { setSelected(null); onSelect(j.id); }} title={j.objective}>
                <span className="conv-title">{j.objective}</span>
                <span className="muted when">{JOB_STATUS[j.status] ?? j.status} · {ago(j.created_at)}{j.steps ? ` · ${j.steps} adım` : ""}</span>
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <section className="panel flow-main">
        <div className="flow-top">
          <div className="seg" role="group" aria-label="Görünüm">
            <button aria-pressed={mode === "office"} onClick={() => pick("office")}>Ofis</button>
            <button aria-pressed={mode === "graph"} onClick={() => pick("graph")}>Akış grafiği</button>
          </div>
          {mode === "office" && <button className="ghost small" aria-expanded={art} onClick={() => setArt((v) => !v)}>🎨 Çizimler</button>}
        </div>
        {mode === "office" && art && <OfficeArtPanel onClose={() => setArt(false)} />}
        {mode === "office" ? <OfficeView jobId={active} refreshKey={refreshKey} approvalsKey={approvalsKey} /> : <>
        {error && <p className="error">{error}</p>}
        {!graph && !error && <p className="muted">Bir iş seç.</p>}
        {graph && (
          <>
            <div className="panel-head">
              <h2 className="flow-title" title={graph.objective}>{graph.objective}</h2>
              <span className={`pill ${graph.status === "succeeded" ? "ok" : graph.status === "failed" ? "bad" : "warn"}`}>
                {live && <span className="dot" />} {JOB_STATUS[graph.status] ?? graph.status}{graph.duration_s != null ? ` · ${graph.duration_s} sn` : ""}
              </span>
            </div>
            <Graph g={graph} selected={selected} onSelect={setSelected} />
            {node ? (
              <div className="flow-detail">
                <h3>{node.label} <span className="muted">· {KIND_TEXT[node.kind]} · {STATUS_TEXT[node.status]}</span></h3>
                <dl>
                  {node.agent && <><dt>Ajan</dt><dd>{node.agent}</dd></>}
                  {node.model && <><dt>Model</dt><dd>{node.model}</dd></>}
                  {node.duration_s != null && <><dt>Süre</dt><dd>{node.duration_s} sn{node.tokens_per_second ? ` · ${node.tokens_per_second} token/sn` : ""}</dd></>}
                  {node.review && <><dt>Gözden geçirme</dt><dd>{node.review.verdict ?? "—"} · {node.review.issues ?? 0} sorun · {node.review.dropped ?? 0} elendi{node.review.revised ? " · düzeltildi" : ""}{node.review.disputes ? ` · ${node.review.disputes} anlaşmazlık` : ""}</dd></>}
                  {node.task_id && <><dt>Görev</dt><dd><code>{node.task_id}</code></dd></>}
                </dl>
                {node.detail && <p className="flow-text">{node.detail}</p>}
                {node.error && <p className="error">{node.error}</p>}
              </div>
            ) : (
              <p className="muted">Ayrıntı için bir düğüme tıkla. İş sürerken grafik kendiliğinden güncellenir.</p>
            )}
            {graph.warnings.length > 0 && <ul className="warnings">{graph.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
          </>
        )}
        </>}
      </section>
    </main>
  );
}
