import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, post, type Approval, type FlowNode, type JobGraph } from "../api";
import { usePolling } from "../hooks";
import { useProgress } from "../office/progress";
import {
  CELL, deriveActors, diffVisits, flows, GRID, PIXEL, pickSeat, pickWalk, PX, seat, STATE_TEXT, taskGraph, top,
  visitorSpot, walkDir, type Actor, type Flow, type OfficeAssets, type Pt, type Sprite, type TaskLite, type Visit, type WalkDir,
} from "../office/scene";

/**
 * Canlı ofis (Adım 15b → Adım 21 pixel stil, sahip kararı "ofis A"): önden-üstten pixel bir ofis. Ajanlar masalarında
 * oturur (çalışırken masanın üstünde işine göre efekt, balonda canlı yazdıkları), iş birinden diğerine geçerken kalkıp
 * yürür (yöne göre yürüme animasyonu), denetçi kontrol için yanına gider, onay gereken ajan senin masana gelir.
 * Hazır çizimler: free-office-pixel-art (arlantr); sahibin çizimleri data/ofis'ten yerine geçer.
 * Bir karaktere tıkla → ayrıntı. "Hareketi azalt" açıksa yürüyüş ve kare animasyonu yok.
 */

const WALK_MS_PER_CELL = 520;
const STAY_MS = 1500;
const FRAME_MS = 140;
const WALL = 92;  // duvar bandı yüksekliği (sahne birimi)
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
  const go = Math.max(600, dist(home, spot) * WALK_MS_PER_CELL);
  return [
    { from: home, to: spot, start, dur: go },
    { from: spot, to: spot, start: start + go, dur: STAY_MS, note: v.note },
    { from: spot, to: home, start: start + go + STAY_MS, dur: go },
  ];
}

/** Pixel çizim: (at) noktasına çizimin (ax, ay) pikseli oturur; kareler yan yana, gösterilen kare `frame`. */
function SpriteImg({ s, at, frame = 0, flip = false, className }: { s: Sprite; at: Pt; frame?: number; flip?: boolean; className?: string }) {
  const w = s.fw * PX, h = s.fh * PX;
  const x = at.x - s.ax * PX, y = at.y - s.ay * PX;
  const f = s.frames > 1 ? ((frame % s.frames) + s.frames) % s.frames : 0;
  // Konum `transform` özniteliğinde; CSS animasyonu (kıpırdama) yalnız iç katmanda — yoksa CSS konumu ezer
  return (
    <g transform={flip ? `translate(${x + w} ${y}) scale(-1 1)` : `translate(${x} ${y})`}>
      <g className={className}>
        <svg width={w} height={h} viewBox={`${f * s.fw} 0 ${s.fw} ${s.fh}`} preserveAspectRatio="none" overflow="hidden">
          <image href={s.href} width={s.fw * s.frames} height={s.fh} className="px" preserveAspectRatio="none" />
        </svg>
      </g>
    </g>
  );
}

/** Masanın üstünde işe göre efekt (Adım 19a): yalnız çalışırken; "hareketi azalt"ta CSS durdurur. Yerel koordinat. */
function WorkFx({ a, at }: { a: Actor; at: Pt }) {
  if (a.state !== "working" || a.kind === "claude" || a.kind === "owner") return null;
  const think = a.activity === "thinking";
  const mx = 0, my = 0;
  const fx = (() => {
    switch (a.style) {
      case "board":  // şef: panoya madde yazar
        return (
          <g className={`fx fx-board${think ? " slow" : ""}`}>
            <rect x={-2} y={-4} width={36} height={26} rx={3} className="board" />
            {[0, 1, 2, 3].map((i) => <rect key={i} className="fx-line" x={4} y={1 + i * 5} width={i === 3 ? 18 : 26} height={2} rx={1}
                                            style={{ animationDelay: `${i * 0.35}s`, fill: i === 0 ? a.color : undefined }} />)}
          </g>
        );
      case "code":
        return (
          <g className={`fx fx-code${think ? " slow" : ""}`}>
            <rect x={mx} y={my} width={18} height={13} rx={2} className="fx-screen" />
            {[0, 1, 2].map((i) => <rect key={i} className="fx-line" x={mx + 2 + (i === 1 ? 3 : 0)} y={my + 2.5 + i * 3.3} width={i === 1 ? 10 : 13} height={1.6} rx={0.8}
                                         style={{ animationDelay: `${i * 0.25}s`, fill: ["#7ee787", "#79c0ff", "#ff7b72"][i] }} />)}
            {!think && <text className="fx-float" x={mx + 9} y={my - 3} textAnchor="middle">{"</>"}</text>}
          </g>
        );
      case "chart":
        return (
          <g className={`fx fx-chart${think ? " slow" : ""}`}>
            <rect x={mx} y={my} width={18} height={13} rx={2} className="fx-screen" />
            {[0, 1, 2, 3].map((i) => <rect key={i} className="fx-bar" x={mx + 2.5 + i * 3.6} y={my + 2} width={2.4} height={9}
                                            style={{ animationDelay: `${i * 0.2}s`, fill: a.color }} />)}
          </g>
        );
      case "paper":
        return (
          <g className={`fx fx-paper${think ? " slow" : ""}`}>
            <rect x={mx} y={my - 4} width={14} height={18} rx={1.5} className="fx-sheet" />
            {[0, 1, 2, 3].map((i) => <rect key={i} className="fx-line" x={mx + 2} y={my - 1 + i * 3.6} width={i === 3 ? 6 : 10} height={1.4} rx={0.7}
                                            style={{ animationDelay: `${i * 0.3}s` }} />)}
          </g>
        );
      case "review":
        return (
          <g className={`fx fx-review${think ? " slow" : ""}`}>
            <rect x={mx} y={my - 4} width={14} height={16} rx={1.5} className="fx-sheet" />
            <g className="fx-glass"><circle cx={mx + 6} cy={my + 2} r={3.4} /><line x1={mx + 8.5} y1={my + 4.5} x2={mx + 11.5} y2={my + 7.5} /></g>
          </g>
        );
      case "vision":
        return (
          <g className={`fx fx-vision${think ? " slow" : ""}`}>
            <rect x={mx} y={my} width={18} height={13} rx={2} className="fx-screen" />
            <ellipse className="fx-eye" cx={mx + 9} cy={my + 6.5} rx={5.5} ry={3.2} />
            <circle className="fx-pupil" cx={mx + 9} cy={my + 6.5} r={1.6} />
          </g>
        );
      default:
        return (
          <g className={`fx fx-type${think ? " slow" : ""}`}>
            <rect x={mx} y={my} width={18} height={13} rx={2} className="fx-screen" />
            {[0, 1].map((i) => <rect key={i} className="fx-line" x={mx + 2} y={my + 3 + i * 3.5} width={13} height={1.6} rx={0.8} style={{ animationDelay: `${i * 0.4}s` }} />)}
            <rect className="fx-caret" x={mx + 2} y={my + 9.2} width={2} height={2.2} />
          </g>
        );
    }
  })();
  // Masanın sağ üstünde, ekranın yanında küçük bir "pencere" (oturanın başı ekranı kapatıyor)
  const ox = a.style === "board" ? at.x - 96 : at.x + 30, oy = a.style === "board" ? at.y - 128 : at.y - 112;
  return <g aria-hidden="true" transform={`translate(${ox} ${oy}) scale(1.5)`}>{fx}</g>;
}

/** Masalar arası iş akışı (Adım 19a): yay biçimli çizgi; aktifte ışık akar, anlaşmazlıkta kırmızı kesikli. */
function FlowLine({ f, actors, still }: { f: Flow; actors: Actor[]; still: boolean }) {
  const a = actors.find((x) => x.id === f.from), b = actors.find((x) => x.id === f.to);
  if (!a || !b) return null;
  const p0 = top(a.desk), q0 = top(b.desk);
  const p = { x: p0.x, y: p0.y - 70 }, q = { x: q0.x, y: q0.y - 70 };
  const mx = (p.x + q.x) / 2, my = (p.y + q.y) / 2 - Math.max(24, Math.hypot(q.x - p.x, q.y - p.y) * 0.22);
  const d = `M ${p.x} ${p.y} Q ${mx} ${my} ${q.x} ${q.y}`;
  return (
    <g className={`flow-line ${f.status}`} aria-hidden="true">
      <path d={d} className="flow-base" />
      {(f.status === "active" || f.status === "dispute") && <path d={d} className="flow-dash" />}
      {f.status === "active" && !still && [0, 1, 2].map((i) => (
        <circle key={i} r={3.2} className="flow-spark">
          <animateMotion dur="1.6s" begin={`${i * 0.53}s`} repeatCount="indefinite" path={d} />
        </circle>
      ))}
    </g>
  );
}

/** Düşünce balonu: ilk kelime gelmeden (model hazırlanıyor / düşünüyor). `head`: başın üstü. */
function ThoughtBubble({ a, head }: { a: Actor; head: Pt }) {
  if (a.activity !== "thinking" || a.state !== "working") return null;
  return (
    <g className="thought" aria-hidden="true" transform={`translate(${head.x + 12} ${head.y - 6}) scale(1.3)`}>
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

function Bubble({ a, head, note, scale, bounds }: { a: Actor; head: Pt; note: string | null; scale: number; bounds: [number, number] }) {
  const text = bubbleOf(a, note);
  if (!text) return null;
  const w = 200 * scale, h = 64 * scale;
  const x = Math.min(Math.max(head.x - w / 2, bounds[0] + 4), bounds[1] - w - 4);  // sahneden taşmasın
  return (
    <foreignObject x={x} y={head.y - h - 4} width={w} height={h} className="bubble-wrap" aria-hidden="true">
      <div className="bubble-box">
        <div className={`bubble ${note ? "note" : a.state}`} style={{ fontSize: `${12 * Math.min(scale, 1.25)}px` }}>{text}</div>
      </div>
    </foreignObject>
  );
}

function Marks({ a, head }: { a: Actor; head: Pt }) {
  const x = head.x, y = head.y;
  return (
    <g aria-hidden="true">
      {a.state === "waiting" && <text x={x + 18} y={y} className="mark">🔔</text>}
      {a.state === "error" && <text x={x + 18} y={y} className="mark">!</text>}
      {a.dispute && <text x={x - 30} y={y} className="mark dispute">⚖</text>}
      {a.cloud && <text x={x - 32} y={y + 16} className="mark cloud">☁</text>}
      {a.state === "done" && <text x={x + 18} y={y} className="mark done">✓</text>}
      {a.state === "idle" && a.kind === "agent" && <text x={x + 34} y={y - 4} className="mark idle">z</text>}
    </g>
  );
}

function personLabel(a: Actor): string {
  return `${a.label}: ${STATE_TEXT[a.state]}${a.activity === "thinking" ? " (düşünüyor)" : ""}${a.dispute ? " (anlaşmazlık)" : ""}`
    + `${a.cloud ? " (dış sağlayıcı)" : ""}${a.bubble ? ` — ${a.bubble}` : ""}`;
}

/** Tıklanabilir karakter kabı (masadaki ya da yürüyen). */
function Clickable({ a, selected, onSelect, children }: { a: Actor; selected: boolean; onSelect: () => void; children: React.ReactNode }) {
  return (
    <g className={`person ${a.state}${a.activity ? ` ${a.activity}` : ""}${selected ? " selected" : ""}`}
       role="button" tabIndex={0} aria-label={personLabel(a)} aria-pressed={selected} onClick={onSelect}
       onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(); } }}>
      {children}
    </g>
  );
}

/** Claude'un posta kutusu (pixel tarzı). */
function Mailbox({ at }: { at: Pt }) {
  return (
    <g className="mailbox-px" aria-hidden="true" shapeRendering="crispEdges">
      <rect x={at.x - 14} y={at.y - 56} width={28} height={8} className="mb-top" />
      <rect x={at.x - 14} y={at.y - 48} width={28} height={30} className="mb-body" />
      <rect x={at.x - 9} y={at.y - 40} width={18} height={4} className="mb-slot" />
      <rect x={at.x - 3} y={at.y - 18} width={6} height={18} className="mb-post" />
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
  const [frame, setFrame] = useState(0);
  const prev = useRef<JobGraph | null>(null);
  const plans = useRef<Map<string, Leg[]>>(new Map());
  const [localKey, setLocalKey] = useState(0);
  const live = graph?.status === "running" || graph?.status === "pending";
  const still = reducedMotion();

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

  // Kare animasyonu (çalışan masalar, senin bekleme duruşun): yalnız iş sürerken ve hareket açıkken
  const anyBusy = actors.some((a) => a.state === "working" || (a.kind === "owner" && a.state === "waiting"));
  useEffect(() => {
    if (!anyBusy || still) return;
    const id = window.setInterval(() => setFrame((f) => f + 1), 220);
    return () => window.clearInterval(id);
  }, [anyBusy, still]);

  // Yeni grafik → yürüyüş planları
  useEffect(() => {
    if (!graph) return;
    const visits = diffVisits(prev.current, graph);
    prev.current = graph;
    if (!visits.length) return;
    const t = performance.now();
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

  function where(a: Actor): { at: Pt; note: string | null; away: boolean; moving: boolean; dir: WalkDir } {
    const home = seat(a.desk);
    const legs = plans.current.get(a.id);
    if (legs) {
      for (const l of legs) {
        if (now >= l.start && now <= l.start + l.dur) {
          const moving = l.from.x !== l.to.x || l.from.y !== l.to.y;
          const at = lerp(l.from, l.to, l.dur ? (now - l.start) / l.dur : 1);
          const away = dist(at, home) > 0.02;
          return { at, note: l.note ?? null, away, moving, dir: moving ? walkDir(l.from, l.to) : "left" };
        }
      }
    }
    return { at: home, note: null, away: false, moving: false, dir: "down" };
  }

  const sel = actors.find((a) => a.id === selected) ?? null;
  const placed = actors.map((a) => ({ a, ...where(a) }));
  const W = GRID.w * CELL.w, H = GRID.h * CELL.h;
  const pad = compact ? 8 : 16;
  const bounds: [number, number] = [-pad, W + pad];
  const scale = compact ? 1.35 : 1;
  const flowList = useMemo(() => flows(graph), [graph]);
  const walkFrame = Math.floor(now / FRAME_MS);
  const art = assets.data;

  // Derinlik sırası (aşağıdaki önde): masalar (oturan ya da boş) ve yürüyenler birlikte, ayak hizasına göre
  type Layer = { key: string; y: number; node: React.ReactNode };
  const layers: Layer[] = [];
  const heads: { a: Actor; head: Pt; note: string | null }[] = [];
  for (const p of placed) {
    const { a } = p;
    const d = top(a.desk);
    const isSel = a.id === selected;
    const onSelect = () => setSelected(isSel ? null : a.id);
    if (a.kind === "claude") {
      layers.push({ key: `d-${a.id}`, y: d.y, node: (
        <Clickable key={`d-${a.id}`} a={a} selected={isSel} onSelect={onSelect}><Mailbox at={d} /></Clickable>) });
      heads.push({ a, head: { x: d.x, y: d.y - 64 }, note: p.note });
      continue;
    }
    if (a.kind === "owner") {
      const own = art?.actors.owner;
      const body = own ? { s: pickSeat(art, a), frame: 0 } : { s: PIXEL.owner, frame: a.state === "waiting" ? frame : 0 };
      layers.push({ key: `d-${a.id}`, y: d.y, node: (
        <Clickable key={`d-${a.id}`} a={a} selected={isSel} onSelect={onSelect}>
          {!own && <SpriteImg s={body.s} at={{ x: d.x, y: d.y - 54 }} frame={body.frame} />}
          <SpriteImg s={own ? body.s : PIXEL.ownerDesk} at={d} />
        </Clickable>) });
      heads.push({ a, head: { x: d.x, y: d.y - 116 }, note: p.note });
      continue;
    }
    if (!p.away) {  // masasında oturuyor
      const s = pickSeat(art, a);
      layers.push({ key: `d-${a.id}`, y: d.y, node: (
        <Clickable key={`d-${a.id}`} a={a} selected={isSel} onSelect={onSelect}>
          {a.state === "working" && <ellipse cx={d.x} cy={d.y - 54} rx={46} ry={34} className="desk-glow" style={{ fill: a.color }} />}
          <SpriteImg s={s} at={d} frame={frame} className={a.state === "working" ? "seated busy" : "seated"} />
          <WorkFx a={a} at={d} />
        </Clickable>) });
      heads.push({ a, head: { x: d.x, y: d.y - 84 }, note: p.note });
    } else {  // masası boş, kendisi yolda / başka masanın yanında
      const desk = art?.desk ? { href: art.desk, frames: 1, fw: 64, fh: 64, ax: 32, ay: 61 } as Sprite
        : a.state === "working" ? PIXEL.busyDesk : PIXEL.emptyDesk;
      layers.push({ key: `d-${a.id}`, y: d.y, node: <SpriteImg key={`d-${a.id}`} s={desk} at={d} frame={frame} /> });
      const q = top(p.at);
      const w = pickWalk(art, a, p.dir);
      layers.push({ key: `w-${a.id}`, y: q.y + 1, node: (
        <Clickable key={`w-${a.id}`} a={a} selected={isSel} onSelect={onSelect}>
          <ellipse cx={q.x} cy={q.y} rx={18} ry={6} className="shadow" />
          <SpriteImg s={w.s} at={q} frame={p.moving ? walkFrame : 0} flip={w.flip} />
        </Clickable>) });
      heads.push({ a, head: { x: q.x, y: q.y - 70 }, note: p.note });
    }
  }
  layers.sort((p, q) => p.y - q.y);

  return (
    <div className={`office pixel${compact ? " compact" : ""}`}>
      <div className="office-head">
        <strong>Ofis</strong>
        {graph ? (
          <span className={`pill ${graph.status === "succeeded" ? "ok" : graph.status === "failed" ? "bad" : "warn"}`}>
            {live && <span className="dot" />} {live ? `${actors.filter((a) => a.state === "working").length} ajan çalışıyor` : HEAD_STATUS[graph.status] ?? graph.status}
          </span>
        ) : <span className="muted small">{jobId ? "" : "şefe iş ver, ekip burada çalışsın"}</span>}
        {onExpand && <button className="ghost small" onClick={onExpand} title="Ofisi tam ekran aç">Büyüt ⤢</button>}
      </div>
      {error && <p className="error">{error}</p>}
      <div className="office-body">
        <svg className="office-scene" viewBox={`${-pad} ${-pad} ${W + 2 * pad} ${H + 2 * pad + 20}`}
             role="group" aria-label={`Canlı ofis${graph ? `: ${graph.objective}` : ""}`}>
          <defs>
            <pattern id="office-floor" width={32} height={32} patternUnits="userSpaceOnUse">
              {art?.floor ? <image href={art.floor} width={32} height={32} className="px" preserveAspectRatio="none" /> : (
                <>
                  <rect width={32} height={32} className="floor-a" />
                  <rect width={16} height={16} className="floor-b" />
                  <rect x={16} y={16} width={16} height={16} className="floor-b" />
                </>
              )}
            </pattern>
          </defs>
          <g aria-hidden="true" shapeRendering="crispEdges">
            <rect x={0} y={0} width={W} height={H + 20} fill="url(#office-floor)" />
            <rect x={0} y={0} width={W} height={WALL} className="wall-px" />
            <rect x={0} y={WALL - 6} width={W} height={6} className="wall-base" />
            {[0.18, 0.5, 0.82].map((k) => <rect key={k} x={W * k - 40} y={14} width={80} height={44} className="window-px" />)}
            {PIXEL.props.map((pr, i) => <SpriteImg key={i} s={pr.s} at={top(pr.at)} />)}
          </g>
          <g className="flows">{flowList.map((fl) => <FlowLine key={fl.key} f={fl} actors={actors} still={still} />)}</g>
          {layers.map((l) => l.node)}
          {placed.map(({ a }) => {  // isimler masaların önünde
            const d = top(a.desk);
            return (
              <g key={`n-${a.id}`} aria-hidden="true">
                <rect x={d.x - 30} y={d.y + 6} width={60} height={17} rx={4} className={`nameplate${a.id === selected ? " sel" : ""}`} />
                <rect x={d.x - 26} y={d.y + 11} width={7} height={7} rx={2} style={{ fill: a.color }} />
                <text x={d.x + 4} y={d.y + 19} className="name" textAnchor="middle">{a.label}</text>
              </g>
            );
          })}
          {heads.map(({ a, head }) => <Marks key={`m-${a.id}`} a={a} head={head} />)}
          {heads.map(({ a, head, note }) => note || a.activity !== "thinking"
            ? <Bubble key={`b-${a.id}`} a={a} head={head} note={note} scale={scale} bounds={bounds} />
            : <ThoughtBubble key={`t-${a.id}`} a={a} head={head} />)}
        </svg>
        {sel && <Inspector a={sel} graph={graph} onClose={() => setSelected(null)} onChanged={() => { setLocalKey((k) => k + 1); void approvals.reload(); }} />}
      </div>
      <ul className="sr-only" aria-live="polite">
        {actors.filter((a) => a.state !== "idle").map((a) => <li key={a.id}>{a.label}: {STATE_TEXT[a.state]}</li>)}
      </ul>
    </div>
  );
}
