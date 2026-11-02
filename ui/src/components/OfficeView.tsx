import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, post, type Approval, type FlowNode, type JobGraph } from "../api";
import { usePolling } from "../hooks";
import { useProgress } from "../office/progress";
import {
  deriveActors, diffVisits, flows, GRID, iso, pickArt, seat, STATE_TEXT, taskGraph, TILE, visitorSpot,
  type Actor, type Flow, type OfficeAssets, type Pt, type TaskLite, type Visit,
} from "../office/scene";

/**
 * Canlı ofis (Adım 15b): şefin işi bölüp ajanlara dağıtması 2B izometrik bir ofiste görünür. Ajanlar masalarında
 * çalışır (balonda canlı yazdıkları), iş birinden diğerine geçerken masasına yürür, denetçi kontrol için yanına gider,
 * onay gereken ajan senin masana gelir. Bir karaktere tıkla → ayrıntı. "Hareketi azalt" açıksa yürüyüş yok.
 */

const WALK_MS_PER_TILE = 420;
const STAY_MS = 1500;
const STATUS_TEXT: Record<FlowNode["status"], string> = {
  pending: "sırada", running: "çalışıyor", succeeded: "bitti", failed: "hata", waiting: "bekliyor", skipped: "atlandı",
};

interface Leg { from: Pt; to: Pt; start: number; dur: number; note?: string }

function reducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

function dist(a: Pt, b: Pt): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function lerp(a: Pt, b: Pt, t: number): Pt {
  const k = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2; // yumuşak başla/dur
  return { x: a.x + (b.x - a.x) * k, y: a.y + (b.y - a.y) * k };
}

function legsFor(v: Visit, actors: Actor[], start: number, still: boolean): Leg[] {
  const a = actors.find((x) => x.id === v.actor);
  const h = actors.find((x) => x.id === v.host);
  if (!a || !h) return [];
  const home = seat(a.desk);
  if (still) return [{ from: home, to: home, start, dur: 2200, note: `→ ${h.label}: ${v.note}` }];
  const spot = visitorSpot(h.desk);
  const go = Math.max(500, dist(home, spot) * WALK_MS_PER_TILE);
  return [
    { from: home, to: spot, start, dur: go },
    { from: spot, to: spot, start: start + go, dur: STAY_MS, note: v.note },
    { from: spot, to: home, start: start + go + STAY_MS, dur: go },
  ];
}

function Desk({ a, lit, art }: { a: Actor; lit: boolean; art?: string | null }) {
  const c = iso({ x: a.desk.x + 0.3, y: a.desk.y + 0.3 });  // karakter masanın arkasında oturur (seat: +0.2)
  const w = TILE.w * 0.36, h = TILE.h * 0.36, z = 14;
  if (art && a.kind !== "claude") {  // sahibin masa çizimi (data/ofis/masa.png)
    return (
      <g className="desk" aria-hidden="true">
        {lit && <ellipse cx={c.x} cy={c.y + h - z} rx={w * 0.9} ry={h * 0.8} className="desk-glow" style={{ fill: a.color }} />}
        <image href={art} x={c.x - w * 1.15} y={c.y - z - 30} width={w * 2.3} height={2 * h + z + 30} preserveAspectRatio="xMidYMax meet" />
        {a.kind === "chef" && <rect x={c.x + 14} y={c.y - z - 30} width={40} height={26} rx={3} className="board" />}
      </g>
    );
  }
  const top = `${c.x},${c.y - z} ${c.x + w},${c.y + h - z} ${c.x},${c.y + 2 * h - z} ${c.x - w},${c.y + h - z}`;
  const left = `${c.x - w},${c.y + h - z} ${c.x},${c.y + 2 * h - z} ${c.x},${c.y + 2 * h} ${c.x - w},${c.y + h}`;
  const right = `${c.x + w},${c.y + h - z} ${c.x},${c.y + 2 * h - z} ${c.x},${c.y + 2 * h} ${c.x + w},${c.y + h}`;
  if (a.kind === "claude") {
    return (
      <g className="desk" aria-hidden="true">
        <rect x={c.x - 12} y={c.y - 4} width={24} height={30} rx={4} className="mailbox" />
        <rect x={c.x - 8} y={c.y + 4} width={16} height={4} rx={1} className="slot" />
      </g>
    );
  }
  return (
    <g className="desk" aria-hidden="true">
      <polygon points={left} className="desk-left" />
      <polygon points={right} className="desk-right" />
      <polygon points={top} className="desk-top" />
      {a.kind === "chef" ? (
        <g>
          <rect x={c.x + 14} y={c.y - z - 30} width={40} height={26} rx={3} className="board" />
          <line x1={c.x + 34} y1={c.y - z - 4} x2={c.x + 34} y2={c.y + h - z} className="board-leg" />
        </g>
      ) : (
        <rect x={c.x + 8} y={c.y + h - z - 20} width={18} height={13} rx={2} className={`screen${lit ? " lit" : ""}`} style={lit ? { fill: a.color } : undefined} />
      )}
    </g>
  );
}

/** Masanın ekranındaki/panosundaki iş animasyonu (Adım 19a). Yalnız çalışırken; "hareketi azalt"ta CSS durdurur. */
function WorkFx({ a }: { a: Actor }) {
  if (a.state !== "working" || a.kind === "claude" || a.kind === "owner") return null;
  const c = iso({ x: a.desk.x + 0.3, y: a.desk.y + 0.3 });
  const h = TILE.h * 0.36, z = 14;
  const mx = c.x + 8, my = c.y + h - z - 20;  // monitör (18×13)
  const think = a.activity === "thinking";
  switch (a.style) {
    case "board": {  // şef: panoya madde yazar
      const bx = c.x + 14, by = c.y - z - 30;
      return (
        <g className={`fx fx-board${think ? " slow" : ""}`} aria-hidden="true">
          {[0, 1, 2, 3].map((i) => <rect key={i} className="fx-line" x={bx + 5} y={by + 5 + i * 5} width={i === 3 ? 18 : 28} height={2} rx={1}
                                          style={{ animationDelay: `${i * 0.35}s`, fill: i === 0 ? a.color : undefined }} />)}
        </g>
      );
    }
    case "code":  // kod: monitörde akan renkli satırlar + yükselen </>
      return (
        <g className={`fx fx-code${think ? " slow" : ""}`} aria-hidden="true">
          <rect x={mx} y={my} width={18} height={13} rx={2} className="fx-screen" />
          {[0, 1, 2].map((i) => <rect key={i} className="fx-line" x={mx + 2 + (i === 1 ? 3 : 0)} y={my + 2.5 + i * 3.3} width={i === 1 ? 10 : 13} height={1.6} rx={0.8}
                                       style={{ animationDelay: `${i * 0.25}s`, fill: ["#7ee787", "#79c0ff", "#ff7b72"][i] }} />)}
          {!think && <text className="fx-float" x={mx + 9} y={my - 3} textAnchor="middle">{"</>"}</text>}
        </g>
      );
    case "chart":  // veri: büyüyen çubuklar
      return (
        <g className={`fx fx-chart${think ? " slow" : ""}`} aria-hidden="true">
          <rect x={mx} y={my} width={18} height={13} rx={2} className="fx-screen" />
          {[0, 1, 2, 3].map((i) => <rect key={i} className="fx-bar" x={mx + 2.5 + i * 3.6} y={my + 2} width={2.4} height={9}
                                          style={{ animationDelay: `${i * 0.2}s`, fill: a.color }} />)}
        </g>
      );
    case "paper":  // belge: daktilodan çıkan kâğıt, satırlar beliriyor
      return (
        <g className={`fx fx-paper${think ? " slow" : ""}`} aria-hidden="true">
          <rect x={mx - 3} y={my - 9} width={14} height={18} rx={1.5} className="fx-sheet" />
          {[0, 1, 2, 3].map((i) => <rect key={i} className="fx-line" x={mx - 1} y={my - 6 + i * 3.6} width={i === 3 ? 6 : 10} height={1.4} rx={0.7}
                                          style={{ animationDelay: `${i * 0.3}s` }} />)}
        </g>
      );
    case "review":  // denetçi: büyüteç kâğıdın üstünde gezer
      return (
        <g className={`fx fx-review${think ? " slow" : ""}`} aria-hidden="true">
          <rect x={mx} y={my - 4} width={14} height={16} rx={1.5} className="fx-sheet" />
          <g className="fx-glass"><circle cx={mx + 6} cy={my + 2} r={3.4} /><line x1={mx + 8.5} y1={my + 4.5} x2={mx + 11.5} y2={my + 7.5} /></g>
        </g>
      );
    case "vision":  // görsel: ekranda göz
      return (
        <g className={`fx fx-vision${think ? " slow" : ""}`} aria-hidden="true">
          <rect x={mx} y={my} width={18} height={13} rx={2} className="fx-screen" />
          <ellipse className="fx-eye" cx={mx + 9} cy={my + 6.5} rx={5.5} ry={3.2} />
          <circle className="fx-pupil" cx={mx + 9} cy={my + 6.5} r={1.6} />
        </g>
      );
    default:  // genel: yazılan satırlar + yanıp sönen imleç
      return (
        <g className={`fx fx-type${think ? " slow" : ""}`} aria-hidden="true">
          <rect x={mx} y={my} width={18} height={13} rx={2} className="fx-screen" />
          {[0, 1].map((i) => <rect key={i} className="fx-line" x={mx + 2} y={my + 3 + i * 3.5} width={13} height={1.6} rx={0.8} style={{ animationDelay: `${i * 0.4}s` }} />)}
          <rect className="fx-caret" x={mx + 2} y={my + 9.2} width={2} height={2.2} />
        </g>
      );
  }
}

/** Masalar arası iş akışı (Adım 19a): yay biçimli çizgi; aktifte ışık akar, anlaşmazlıkta kırmızı kesikli. */
function FlowLine({ f, actors, still }: { f: Flow; actors: Actor[]; still: boolean }) {
  const a = actors.find((x) => x.id === f.from), b = actors.find((x) => x.id === f.to);
  if (!a || !b) return null;
  const p = iso({ x: a.desk.x + 0.5, y: a.desk.y + 0.5 }), q = iso({ x: b.desk.x + 0.5, y: b.desk.y + 0.5 });
  const mx = (p.x + q.x) / 2, my = (p.y + q.y) / 2 - Math.max(18, Math.hypot(q.x - p.x, q.y - p.y) * 0.22);
  const d = `M ${p.x} ${p.y} Q ${mx} ${my} ${q.x} ${q.y}`;
  return (
    <g className={`flow-line ${f.status}`} aria-hidden="true">
      <path d={d} className="flow-base" />
      {(f.status === "active" || f.status === "dispute") && <path d={d} className="flow-dash" />}
      {f.status === "active" && !still && [0, 1, 2].map((i) => (
        <circle key={i} r={2.6} className="flow-spark">
          <animateMotion dur="1.6s" begin={`${i * 0.53}s`} repeatCount="indefinite" path={d} />
        </circle>
      ))}
    </g>
  );
}

/** Düşünce balonu: ilk kelime gelmeden (model hazırlanıyor / düşünüyor). */
function ThoughtBubble({ a, at, scale }: { a: Actor; at: Pt; scale: number }) {
  if (a.activity !== "thinking" || a.state !== "working") return null;
  const p = iso(at);
  const y = p.y - 52 * scale;
  return (
    <g className="thought" aria-hidden="true" transform={`translate(${p.x + 10 * scale} ${y}) scale(${scale})`}>
      <circle cx={-6} cy={8} r={2} className="thought-cloud" />
      <circle cx={-2} cy={3} r={3} className="thought-cloud" />
      <rect x={0} y={-16} width={30} height={15} rx={7.5} className="thought-cloud" />
      {[0, 1, 2].map((i) => <circle key={i} cx={8 + i * 7} cy={-8.5} r={1.8} className="thought-dot" style={{ animationDelay: `${i * 0.2}s` }} />)}
    </g>
  );
}

function bubbleOf(a: Actor, note: string | null): string | null {
  return note ?? (a.state === "working" || a.state === "waiting" || a.state === "error" ? a.bubble : null);
}

function Bubble({ a, at, note, scale, bounds }: { a: Actor; at: Pt; note: string | null; scale: number; bounds: [number, number] }) {
  const text = bubbleOf(a, note);
  if (!text) return null;
  const p = iso(at);
  const w = 190 * scale, h = 62 * scale, head = 46 * scale;
  const x = Math.min(Math.max(p.x - w / 2, bounds[0] + 4), bounds[1] - w - 4);  // sahneden taşmasın
  return (
    <foreignObject x={x} y={p.y - head - h} width={w} height={h} className="bubble-wrap" aria-hidden="true">
      <div className="bubble-box">
        <div className={`bubble ${note ? "note" : a.state}`} style={{ fontSize: `${11 * Math.min(scale, 1.25)}px` }}>{text}</div>
      </div>
    </foreignObject>
  );
}

function Person({ a, at, selected, onSelect, scale, art }: { a: Actor; at: Pt; selected: boolean; onSelect: () => void; scale: number; art?: string | null }) {
  const p = iso(at);
  const label = `${a.label}: ${STATE_TEXT[a.state]}${a.activity === "thinking" ? " (düşünüyor)" : ""}${a.dispute ? " (anlaşmazlık)" : ""}${a.cloud ? " (dış sağlayıcı)" : ""}${a.bubble ? ` — ${a.bubble}` : ""}`;
  return (
    <g
      className={`person ${a.state}${a.activity ? ` ${a.activity}` : ""}${selected ? " selected" : ""}`}
      transform={`translate(${p.x} ${p.y}) scale(${scale})`}
      role="button"
      tabIndex={0}
      aria-label={label}
      aria-pressed={selected}
      onClick={onSelect}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(); } }}
    >
      <ellipse cx={0} cy={2} rx={13} ry={6} className="shadow" />
      {art ? (  // sahibin çizimi (data/ofis): 3:4 kutu, ayak noktası alt orta
        <image className="body art" href={art} x={-24} y={-60} width={48} height={64} preserveAspectRatio="xMidYMax meet" />
      ) : (
        <g className="body">
          <path d="M -10 0 Q -11 -24 0 -26 Q 11 -24 10 0 Z" style={{ fill: a.color }} />
          <circle cx={0} cy={-34} r={9} className="head" />
          {a.kind === "chef" && <rect x={-7} y={-48} width={14} height={6} rx={2} className="hat" />}
        </g>
      )}
      {a.state === "waiting" && <text x={12} y={-40} className="mark" aria-hidden="true">🔔</text>}
      {a.state === "error" && <text x={12} y={-40} className="mark" aria-hidden="true">!</text>}
      {a.dispute && <text x={-24} y={-40} className="mark dispute" aria-hidden="true">⚖</text>}
      {a.cloud && <text x={-26} y={-28} className="mark cloud" aria-hidden="true">☁</text>}
      {a.state === "done" && <text x={12} y={-40} className="mark done" aria-hidden="true">✓</text>}
      {a.state === "idle" && a.kind === "agent" && <text x={10} y={-40} className="mark idle" aria-hidden="true">z</text>}
    </g>
  );
}

function Inspector({ a, graph, onClose, onChanged }: { a: Actor; graph: JobGraph | null; onClose: () => void; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    setMsg(null);
    try { await fn(); setMsg(ok); onChanged(); } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  const n = a.active;
  return (
    <aside className="inspector" aria-label={`${a.label} ayrıntısı`}>
      <div className="panel-head">
        <h3><span className="swatch" style={{ background: a.color }} /> {a.label} <span className="muted">· {STATE_TEXT[a.state]}</span></h3>
        <button className="ghost small" onClick={onClose} aria-label="Ayrıntıyı kapat">✕</button>
      </div>
      {a.bubble && a.state === "working" && <p className="live-tail" aria-live="polite">{a.bubble}</p>}
      {a.approval && (
        <div className="inspector-approval">
          <p><strong>Onay bekliyor:</strong> {a.approval.action.summary} <span className="pill warn">{a.approval.action.risk}</span></p>
          {a.approval.action.reason && <p className="muted small">{a.approval.action.reason}</p>}
          <div className="row-actions">
            <button className="approve" disabled={busy} onClick={() => void run(() => post(`/api/approvals/${a.approval!.id}/approve`, { note: "" }), "Onaylandı")}>Onayla</button>
            <button className="reject" disabled={busy} onClick={() => void run(() => post(`/api/approvals/${a.approval!.id}/reject`, { note: "" }), "Reddedildi")}>Reddet</button>
          </div>
        </div>
      )}
      {a.nodes.length === 0 && !a.approval && <p className="muted">Bu işte görevi yok.</p>}
      {a.nodes.map((x) => (
        <div key={x.id} className={`inspector-node ${x === n ? "current" : ""}`}>
          <p><strong>{x.label}</strong> <span className="muted">· {STATUS_TEXT[x.status]}</span></p>
          {x.detail && <p className="flow-text">{x.detail}</p>}
          <dl>
            {x.model && <><dt>Model</dt><dd>{x.model}</dd></>}
            {x.duration_s != null && <><dt>Süre</dt><dd>{x.duration_s} sn{x.tokens_per_second ? ` · ${x.tokens_per_second} token/sn` : ""}</dd></>}
            {x.review && <><dt>Kontrol</dt><dd>{x.review.verdict ?? "—"} · {x.review.issues ?? 0} sorun{x.review.revised ? " · düzeltildi" : ""}</dd></>}
          </dl>
          {x.error && <p className="error">{x.error}</p>}
          {x.status === "running" && x.task_id && (
            <button className="ghost small" disabled={busy} onClick={() => void run(() => post(`/api/tasks/${x.task_id}/cancel`, {}), "Durdurma istendi")}>Bu adımı durdur</button>
          )}
        </div>
      ))}
      {graph && <p className="muted small">İş: {graph.objective}</p>}
      {msg && <p className="note small" role="status">{msg}</p>}
    </aside>
  );
}

const HEAD_STATUS: Record<string, string> = {
  succeeded: "bitti", failed: "başarısız", waiting_claude: "Claude kutusunda bekliyor", cancelled: "iptal edildi",
  timed_out: "zaman aşımı", pending: "sırada",
};

export function OfficeView({ jobId, jobKind = "conductor", refreshKey, approvalsKey, compact = false, onExpand }: {
  jobId: string | null;
  jobKind?: "conductor" | "task";
  refreshKey: number;
  approvalsKey: number;
  compact?: boolean;
  onExpand?: () => void;
}) {
  const progress = useProgress();
  const assets = usePolling<OfficeAssets>("/api/office/assets", 60000);
  const approvals = usePolling<Approval[]>("/api/approvals?status=pending", 10000, approvalsKey);
  const [graph, setGraph] = useState<JobGraph | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [now, setNow] = useState(() => performance.now());
  const prev = useRef<JobGraph | null>(null);
  const plans = useRef<Map<string, Leg[]>>(new Map());
  const [localKey, setLocalKey] = useState(0);
  const live = graph?.status === "running" || graph?.status === "pending";

  useEffect(() => {
    if (!jobId) { setGraph(null); prev.current = null; return; }
    let stop = false;
    const load = jobKind === "task"
      ? api<{ task: TaskLite }>(`/api/tasks/${jobId}`).then((r) => taskGraph(r.task))
      : api<JobGraph>(`/api/jobs/${jobId}/graph`);
    load
      .then((g) => { if (!stop) { setGraph(g); setError(null); } })
      .catch((e) => { if (!stop) setError(e instanceof ApiError && e.status === 404 ? "İş bulunamadı." : String(e)); });
    return () => { stop = true; };
  }, [jobId, jobKind, refreshKey, tick, localKey]);

  useEffect(() => {
    if (!live) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 2000);
    return () => window.clearInterval(id);
  }, [live]);

  const actors = useMemo(() => deriveActors(graph, progress, approvals.data ?? []), [graph, progress, approvals.data]);

  // Yeni grafik → yürüyüş planları
  useEffect(() => {
    if (!graph) return;
    const visits = diffVisits(prev.current, graph);
    prev.current = graph;
    if (!visits.length) return;
    const t = performance.now();
    const still = reducedMotion();
    for (const v of visits) {
      const queue = plans.current.get(v.actor) ?? [];
      const last = queue[queue.length - 1];
      const start = last ? Math.max(t, last.start + last.dur) : t;
      plans.current.set(v.actor, [...queue, ...legsFor(v, actors, start, still)]);
    }
    setNow(performance.now());
  }, [graph]); // eslint-disable-line react-hooks/exhaustive-deps

  // Animasyon döngüsü: yalnız yürüyüş varken çalışır
  const animating = plans.current.size > 0;
  useEffect(() => {
    if (!animating) return;
    let raf = 0;
    const step = () => {
      const t = performance.now();
      for (const [id, legs] of plans.current) {
        const end = legs[legs.length - 1];
        if (t > end.start + end.dur) plans.current.delete(id);
      }
      setNow(t);
      if (plans.current.size) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [animating, now]);

  function where(a: Actor): { at: Pt; note: string | null; walking: boolean } {
    const legs = plans.current.get(a.id);
    if (legs) {
      for (const l of legs) {
        if (now >= l.start && now <= l.start + l.dur) {
          return { at: lerp(l.from, l.to, l.dur ? (now - l.start) / l.dur : 1), note: l.note ?? null,
                   walking: l.from.x !== l.to.x || l.from.y !== l.to.y };
        }
      }
      if (now < legs[0].start) return { at: legs[0].from, note: null, walking: false };
    }
    return { at: seat(a.desk), note: null, walking: false };
  }

  const sel = actors.find((a) => a.id === selected) ?? null;
  const placed = actors.map((a) => ({ a, ...where(a) })).sort((p, q) => (p.at.x + p.at.y) - (q.at.x + q.at.y));
  // Derinlik sırası: masa (orta noktası) ve karakter (ayak noktası) birlikte; arkadaki önce çizilir
  const layers = [
    ...actors.map((a) => ({ kind: "desk" as const, a, at: a.desk, depth: a.desk.x + a.desk.y + 0.66 })),
    ...placed.map((p) => ({ kind: "person" as const, a: p.a, at: p.at, depth: p.at.x + p.at.y, walking: p.walking })),
  ].sort((p, q) => p.depth - q.depth);
  const scale = compact ? 1.45 : 1;
  const minX = -GRID.h * (TILE.w / 2) - (compact ? 10 : 40), maxX = GRID.w * (TILE.w / 2) + (compact ? 10 : 40);
  const busyCount = actors.filter((a) => a.state === "working").length;
  const flowList = useMemo(() => flows(graph), [graph]);
  const still = reducedMotion();

  return (
    <div className={`office${compact ? " compact" : ""}`}>
      <div className="office-head">
        <strong>Ofis</strong>
        {graph ? (
          <span className={`pill ${graph.status === "succeeded" ? "ok" : graph.status === "failed" ? "bad" : "warn"}`}>
            {live && <span className="dot" />} {live ? `${busyCount} ajan çalışıyor` : HEAD_STATUS[graph.status] ?? graph.status}
          </span>
        ) : <span className="muted small">{jobId ? "" : "şefe iş ver, ekip burada çalışsın"}</span>}
        {onExpand && <button className="ghost small" onClick={onExpand} title="Ofisi tam ekran aç">Büyüt ⤢</button>}
      </div>
      {error && <p className="error">{error}</p>}
      <div className="office-body">
        <svg className="office-scene" viewBox={`${minX} ${compact ? -150 : -120} ${maxX - minX} ${(GRID.w + GRID.h) * (TILE.h / 2) + (compact ? 190 : 150)}`}
             role="group" aria-label={`Canlı ofis${graph ? `: ${graph.objective}` : ""}`}>
          <g aria-hidden="true">
            {Array.from({ length: GRID.w * GRID.h }, (_, i) => {
              const x = i % GRID.w, y = Math.floor(i / GRID.w);
              const c = iso({ x, y });
              return assets.data?.floor
                ? <image key={i} href={assets.data.floor} x={c.x - TILE.w / 2} y={c.y} width={TILE.w} height={TILE.h} preserveAspectRatio="none" />
                : <polygon key={i} className={`tile${(x + y) % 2 ? " alt" : ""}`}
                           points={`${c.x},${c.y} ${c.x + TILE.w / 2},${c.y + TILE.h / 2} ${c.x},${c.y + TILE.h} ${c.x - TILE.w / 2},${c.y + TILE.h / 2}`} />;
            })}
            <polygon className="wall" points={`${iso({ x: 0, y: 0 }).x},${iso({ x: 0, y: 0 }).y} ${iso({ x: GRID.w, y: 0 }).x},${iso({ x: GRID.w, y: 0 }).y} ${iso({ x: GRID.w, y: 0 }).x},${iso({ x: GRID.w, y: 0 }).y - 60} ${iso({ x: 0, y: 0 }).x},${iso({ x: 0, y: 0 }).y - 60}`} />
            <polygon className="wall dark" points={`${iso({ x: 0, y: 0 }).x},${iso({ x: 0, y: 0 }).y} ${iso({ x: 0, y: GRID.h }).x},${iso({ x: 0, y: GRID.h }).y} ${iso({ x: 0, y: GRID.h }).x},${iso({ x: 0, y: GRID.h }).y - 60} ${iso({ x: 0, y: 0 }).x},${iso({ x: 0, y: 0 }).y - 60}`} />
          </g>
          <g className="flows">{flowList.map((fl) => <FlowLine key={fl.key} f={fl} actors={actors} still={still} />)}</g>
          {layers.map((l) => l.kind === "desk"
            ? <g key={`d-${l.a.id}`}><Desk a={l.a} lit={l.a.state === "working"} art={assets.data?.desk} /><WorkFx a={l.a} /></g>
            : <Person key={l.a.id} a={l.a} at={l.at} scale={scale} selected={l.a.id === selected}
                      art={pickArt(assets.data, l.a, "walking" in l && !!l.walking)}
                      onSelect={() => setSelected(l.a.id === selected ? null : l.a.id)} />)}
          {placed.map(({ a, at }) => {  // isimler masaların önünde (masa ayağı örtmesin)
            const p = iso(at);
            return <text key={`n-${a.id}`} x={p.x} y={p.y + 40 * scale} className={`name${a.id === selected ? " sel" : ""}`}
                         textAnchor="middle" aria-hidden="true" style={{ fontSize: `${11 * scale}px` }}>{a.label}</text>;
          })}
          {placed.map(({ a, at, note }) => note || a.activity !== "thinking"
            ? <Bubble key={`b-${a.id}`} a={a} at={at} note={note} scale={scale} bounds={[minX, maxX]} />
            : <ThoughtBubble key={`t-${a.id}`} a={a} at={at} scale={scale} />)}
        </svg>
        {sel && <Inspector a={sel} graph={graph} onClose={() => setSelected(null)} onChanged={() => { setLocalKey((k) => k + 1); void approvals.reload(); }} />}
      </div>
      <ul className="sr-only" aria-live="polite">
        {actors.filter((a) => a.state !== "idle").map((a) => <li key={a.id}>{a.label}: {STATE_TEXT[a.state]}</li>)}
      </ul>
    </div>
  );
}
