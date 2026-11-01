// Canlı ofis (Adım 15b): iş grafiğinden (JobGraph) ve canlı ilerlemeden sahne durumu. Saf hesap — çizim OfficeView'da.
import type { Approval, FlowNode, JobGraph } from "../api";

export interface Pt { x: number; y: number }

/** Canlı ilerleme (task.progress olayı): ajan yazarken okunur kuyruk. */
export interface Progress { task_id: string; worker: string; chars: number; field: string | null; tail: string; attempt: number; at: number }

export type ActorState = "idle" | "working" | "waiting" | "error" | "done";

export interface ActorDef { id: string; label: string; color: string; desk: Pt; kind: "agent" | "chef" | "owner" | "claude" }

export interface Actor extends ActorDef {
  state: ActorState;
  bubble: string | null;      // balonda gösterilen kısa metin
  nodes: FlowNode[];          // bu karakterin bu işteki düğümleri (inceleme paneli için)
  active: FlowNode | null;    // şu an çalışan / son düğüm
  approval: Approval | null;  // bu karakterin beklettiği onay
}

/** Bir karakterin başka bir masaya gidip dönmesi (teslim, gözden geçirme, onay, Claude'a devir). */
export interface Visit { key: string; actor: string; host: string; kind: "handoff" | "review" | "deliver" | "approval" | "claude"; note: string }

// Izgara: 8×6 kare (izometrik çizilir). Masalar sabit; bilinmeyen (geçici) ajanlar boş masalara oturur.
export const GRID = { w: 8, h: 6 };
const FIXED: ActorDef[] = [
  { id: "owner", label: "Sen", color: "#f2b84b", desk: { x: 0, y: 5 }, kind: "owner" },
  { id: "chef", label: "Şef", color: "#e8684a", desk: { x: 3, y: 2 }, kind: "chef" },
  { id: "general", label: "Genel", color: "#4f8cff", desk: { x: 1, y: 1 }, kind: "agent" },
  { id: "data", label: "Veri", color: "#3fbf8f", desk: { x: 5, y: 1 }, kind: "agent" },
  { id: "document", label: "Belge", color: "#b07cf0", desk: { x: 6, y: 3 }, kind: "agent" },
  { id: "coder", label: "Kod", color: "#f07ca8", desk: { x: 1, y: 3 }, kind: "agent" },
  { id: "vision", label: "Görsel", color: "#47c7d6", desk: { x: 5, y: 4 }, kind: "agent" },
  { id: "reviewer", label: "Denetçi", color: "#c9a227", desk: { x: 3, y: 4 }, kind: "agent" },
  { id: "claude", label: "Claude", color: "#d98a5f", desk: { x: 7, y: 0 }, kind: "claude" },
];
const SPARE: Pt[] = [{ x: 7, y: 2 }, { x: 0, y: 2 }, { x: 7, y: 5 }, { x: 2, y: 0 }, { x: 4, y: 0 }, { x: 6, y: 5 }];
const SPARE_COLORS = ["#8fa3bf", "#a3bf8f", "#bf8fa3", "#bfb08f", "#8fbfb8", "#a88fbf"];

/** Düğüm → karakter. Adımlar ajan adına (data.revise → data), kontrol/son kontrol denetçiye, kalanı şefe. */
export function actorOf(n: FlowNode): string {
  switch (n.kind) {
    case "request": return "owner";
    case "planner": case "addendum": case "merge": return "chef";
    case "check": case "review": return "reviewer";
    case "claude": return "claude";
    case "result": return n.agent === "claude" ? "claude" : "chef";
    default: return (n.agent ?? "general").split(".")[0];
  }
}

export function layout(extra: string[]): ActorDef[] {
  const out = [...FIXED];
  const known = new Set(out.map((a) => a.id));
  let i = 0;
  for (const id of extra) {
    if (known.has(id) || i >= SPARE.length) continue;
    known.add(id);
    out.push({ id, label: id.charAt(0).toUpperCase() + id.slice(1), color: SPARE_COLORS[i % SPARE_COLORS.length], desk: SPARE[i], kind: "agent" });
    i++;
  }
  return out;
}

// Ajanların JSON'daki kısa İngilizce değerleri (ör. denetçinin kararı) balonda Türkçe görünsün
const FIELD_VALUES: Record<string, string> = {
  approve: "onaylıyorum", request_changes: "düzeltme istiyorum", plan: "plan yapıyorum", direct: "tek ajana veriyorum",
};

const RANK: Record<string, number> = { running: 5, waiting: 4, failed: 3, pending: 2, succeeded: 1, skipped: 0 };

function approvalActor(a: Approval): string | null {
  const by = a.action.requested_by || "";
  return by.startsWith("agent:") ? by.slice(6).split(".")[0] : null;
}

export function deriveActors(graph: JobGraph | null, progress: Record<string, Progress>, approvals: Approval[]): Actor[] {
  const nodes = graph?.nodes ?? [];
  const ids = [...new Set(nodes.map(actorOf)), ...approvals.map(approvalActor).filter((x): x is string => !!x)];
  const defs = layout(ids);
  return defs.map((d) => {
    const mine = nodes.filter((n) => actorOf(n) === d.id);
    const active = [...mine].sort((a, b) => (RANK[b.status] ?? 0) - (RANK[a.status] ?? 0))[0] ?? null;
    const approval = approvals.find((a) => approvalActor(a) === d.id) ?? null;
    let state: ActorState = "idle";
    let bubble: string | null = null;
    if (active) {
      if (active.status === "running") {
        state = "working";
        const p = active.task_id ? progress[active.task_id] : undefined;
        bubble = p?.tail ? (FIELD_VALUES[p.tail] ?? p.tail) : `${active.label}…`;
        if (p && p.attempt > 1) bubble = `(${p.attempt}. deneme) ${bubble}`;
      } else if (active.status === "waiting") { state = "waiting"; bubble = "bekliyor…"; }
      else if (active.status === "failed") { state = "error"; bubble = active.error ? `Hata: ${active.error}` : "Hata"; }
      else if (active.status === "succeeded" && d.kind !== "owner") state = "done";
    }
    if (approval) { state = "waiting"; bubble = `Onay bekliyor: ${approval.action.summary}`; }
    if (d.id === "owner" && approvals.length && !approval) { state = "waiting"; bubble = `${approvals.length} onay bekliyor`; }
    return { ...d, state, bubble: bubble && bubble.length > 120 ? bubble.slice(0, 119) + "…" : bubble, nodes: mine, active, approval };
  });
}

/** Önceki ve yeni grafik arasında yeni başlayan/biten düğümler → yürüyüşler. */
export function diffVisits(prev: JobGraph | null, next: JobGraph): Visit[] {
  if (!prev || prev.job_id !== next.job_id) return [];
  const before = new Map(prev.nodes.map((n) => [n.id, n.status]));
  const byId = new Map(next.nodes.map((n) => [n.id, n]));
  const out: Visit[] = [];
  for (const n of next.nodes) {
    const was = before.get(n.id);
    const started = n.status === "running" && was !== "running";
    const finished = n.status === "succeeded" && was !== "succeeded";
    if (started) {
      for (const e of next.edges.filter((e) => e.target === n.id)) {
        const src = byId.get(e.source);
        if (!src || src.status !== "succeeded" || src.kind === "request") continue;
        const from = actorOf(src), to = actorOf(n);
        if (from === to) continue;
        if (n.kind === "check" || n.kind === "review") out.push({ key: `${n.id}:review`, actor: to, host: from, kind: "review", note: "kontrol ediyor" });
        else out.push({ key: `${e.source}>${n.id}`, actor: from, host: to, kind: "handoff", note: "teslim" });
      }
    }
    if (finished && n.kind === "result") out.push({ key: `${n.id}:deliver`, actor: "chef", host: "owner", kind: "deliver", note: "cevap hazır" });
    if (n.kind === "claude" && n.status !== "pending" && was === "pending") out.push({ key: `${n.id}:claude`, actor: "chef", host: "claude", kind: "claude", note: "Claude'a devir" });
  }
  return out;
}

/** Izgara → ekran (izometrik). */
export const TILE = { w: 96, h: 48 };
export function iso(p: Pt): Pt {
  return { x: (p.x - p.y) * (TILE.w / 2), y: (p.x + p.y) * (TILE.h / 2) };
}

/** Masanın önündeki duruş noktası (karakterin oturduğu yer) ve ziyaretçinin durduğu yer. */
export function seat(d: Pt): Pt { return { x: d.x + 0.2, y: d.y + 0.2 }; }           // masanın arkası
export function visitorSpot(d: Pt): Pt { return { x: d.x + 1.15, y: d.y + 0.45 }; }   // masanın sağ önü

export const STATE_TEXT: Record<ActorState, string> = {
  idle: "boşta", working: "çalışıyor", waiting: "bekliyor", error: "hata", done: "bitirdi",
};
