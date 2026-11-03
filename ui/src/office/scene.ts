// Canlı ofis (Adım 15b): iş grafiğinden (JobGraph) ve canlı ilerlemeden sahne durumu. Saf hesap — çizim OfficeView'da.
import type { Approval, FlowNode, JobGraph } from "../api";

export interface Pt { x: number; y: number }

/** Canlı ilerleme (task.progress olayı): ajan yazarken okunur kuyruk. */
export interface Progress {
  task_id: string; worker: string; chars: number; field: string | null; tail: string; attempt: number; at: number;
  parent_id?: string | null;  // şef işinin adımıysa iş numarası
  answer?: string;            // Adım 18: "answer" alanının şimdiye kadar yazılan metni (sohbette akar)
}

export type ActorState = "idle" | "working" | "waiting" | "error" | "done";

export interface ActorDef { id: string; label: string; color: string; desk: Pt; kind: "agent" | "chef" | "owner" | "claude" }

/** Ajanın masasındaki iş animasyonu (Adım 19a): kod satırları, grafik, kâğıt/daktilo, pano, büyüteç, göz, klavye. */
export type WorkStyle = "code" | "chart" | "paper" | "board" | "review" | "vision" | "type";
const STYLE: Record<string, WorkStyle> = {
  coder: "code", data: "chart", document: "paper", chef: "board", reviewer: "review", vision: "vision",
};
export function workStyle(id: string): WorkStyle {
  return STYLE[id] ?? "type";
}

export interface Actor extends ActorDef {
  state: ActorState;
  activity: "thinking" | "typing" | null;  // çalışırken: ilk kelime gelmeden düşünüyor, kelimeler akarken yazıyor
  style: WorkStyle;
  dispute: boolean;           // bu işte bir anlaşmazlığın tarafı (⚖)
  cloud: boolean;             // Adım 20b: bu işte dış sağlayıcıda çalıştı (☁)
  bubble: string | null;      // balonda gösterilen kısa metin
  nodes: FlowNode[];          // bu karakterin bu işteki düğümleri (inceleme paneli için)
  active: FlowNode | null;    // şu an çalışan / son düğüm
  approval: Approval | null;  // bu karakterin beklettiği onay
}

/** Bir karakterin başka bir masaya gidip dönmesi (teslim, gözden geçirme, onay, Claude'a devir). */
export interface Visit { key: string; actor: string; host: string; kind: "handoff" | "review" | "deliver" | "approval" | "claude"; note: string }

// Izgara (Adım 21: önden-üstten pixel ofis): 8×6 hücre. Masa noktası = masada oturanın ayak/sandalye hizası.
// Üç sıra ajan masası, sağda Şef ve senin masan, duvar dibinde Claude'un posta kutusu. Geçici ajanlar boş yerlere.
export const GRID = { w: 8, h: 5.6 };
const FIXED: ActorDef[] = [
  { id: "general", label: "Genel", color: "#4f8cff", desk: { x: 1.0, y: 2.0 }, kind: "agent" },
  { id: "data", label: "Veri", color: "#3fbf8f", desk: { x: 2.6, y: 2.0 }, kind: "agent" },
  { id: "document", label: "Belge", color: "#b07cf0", desk: { x: 4.2, y: 2.0 }, kind: "agent" },
  { id: "coder", label: "Kod", color: "#f07ca8", desk: { x: 1.0, y: 3.75 }, kind: "agent" },
  { id: "reviewer", label: "Denetçi", color: "#c9a227", desk: { x: 2.6, y: 3.75 }, kind: "agent" },
  { id: "vision", label: "Görsel", color: "#47c7d6", desk: { x: 4.2, y: 3.75 }, kind: "agent" },
  { id: "chef", label: "Şef", color: "#e8684a", desk: { x: 6.3, y: 2.2 }, kind: "chef" },
  { id: "owner", label: "Sen", color: "#f2b84b", desk: { x: 6.3, y: 4.3 }, kind: "owner" },
  { id: "claude", label: "Claude", color: "#d98a5f", desk: { x: 7.45, y: 1.15 }, kind: "claude" },
];
const SPARE: Pt[] = [{ x: 1.0, y: 5.35 }, { x: 2.6, y: 5.35 }, { x: 4.2, y: 5.35 }, { x: 5.6, y: 5.4 }, { x: 7.4, y: 5.4 }, { x: 7.45, y: 3.2 }];
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

// Tek kelimelik seçim alanları: yarım değer ("a", "appr") gösterilmez
const ENUM_FIELDS = new Set(["verdict", "mode", "language", "task_type", "severity", "agent", "category", "sensitivity", "id", "depends_on"]);

const RANK: Record<string, number> = { running: 5, waiting: 4, failed: 3, pending: 2, succeeded: 1, skipped: 0 };

function approvalActor(a: Approval): string | null {
  const by = a.action.requested_by || "";
  return by.startsWith("agent:") ? by.slice(6).split(".")[0] : null;
}

export function deriveActors(graph: JobGraph | null, progress: Record<string, Progress>, approvals: Approval[]): Actor[] {
  const nodes = graph?.nodes ?? [];
  const ids = [...new Set(nodes.map(actorOf)), ...approvals.map(approvalActor).filter((x): x is string => !!x)];
  const defs = layout(ids);
  const disputeActors = new Set(disputePairs(nodes).flat());
  return defs.map((d) => {
    const mine = nodes.filter((n) => actorOf(n) === d.id);
    const active = [...mine].sort((a, b) => (RANK[b.status] ?? 0) - (RANK[a.status] ?? 0))[0] ?? null;
    const approval = approvals.find((a) => approvalActor(a) === d.id) ?? null;
    let state: ActorState = "idle";
    let bubble: string | null = null;
    let activity: Actor["activity"] = null;
    if (active) {
      if (active.status === "running") {
        state = "working";
        const p = active.task_id ? progress[active.task_id] : undefined;
        activity = p && p.chars > 0 ? "typing" : "thinking";
        if (activity === "typing") {
          const enumField = p?.field ? ENUM_FIELDS.has(p.field) : false;
          bubble = p?.tail && !(enumField && !FIELD_VALUES[p.tail]) ? (FIELD_VALUES[p.tail] ?? p.tail) : `${active.label}…`;
          if (p && p.attempt > 1) bubble = `(${p.attempt}. deneme) ${bubble}`;
        }
      } else if (active.status === "waiting") { state = "waiting"; bubble = "bekliyor…"; }
      else if (active.status === "failed") {
        state = "error";
        const why = active.error ? ` (${active.error})` : "";
        // İş yine de bittiyse (ör. plan olmadı → tek ajan cevapladı) bunu söyle; "Hata" tek başına yanıltıyordu
        bubble = graph?.status === "succeeded"
          ? (active.kind === "planner" ? `Plan yapılamadı${why}; iş tek ajanla bitti` : `Bu adım olmadı${why}; iş yine de bitti`)
          : active.error ? `Hata: ${active.error}` : "Hata";
      }
      else if (active.status === "succeeded" && d.kind !== "owner") state = "done";
    }
    if (approval) { state = "waiting"; bubble = `Onay bekliyor: ${approval.action.summary}`; }
    if (d.id === "owner" && approvals.length && !approval) { state = "waiting"; bubble = `${approvals.length} onay bekliyor`; }
    const dispute = disputeActors.has(d.id);
    return { ...d, state, bubble: bubble && bubble.length > 120 ? bubble.slice(0, 119) + "…" : bubble, nodes: mine, active, approval,
             activity, style: workStyle(d.id), dispute, cloud: mine.some((n) => (n.model ?? "").startsWith("☁")) };
  });
}

/** Anlaşmazlık tarafları: gözden geçirmesinde anlaşmazlık çıkan adımın ajanı ve denetçi. */
function disputePairs(nodes: FlowNode[]): [string, string][] {
  return nodes.filter((n) => n.kind === "step" && (n.review?.disputes ?? 0) > 0).map((n) => [actorOf(n), "reviewer"]);
}

/** İş akışı çizgisi (Adım 19a): iki masa arasında; durum ışığın görünüşünü belirler. */
export interface Flow { key: string; from: string; to: string; status: "active" | "done" | "pending" | "dispute" }
const FLOW_RANK: Record<Flow["status"], number> = { dispute: 4, active: 3, pending: 2, done: 1 };

export function flows(graph: JobGraph | null): Flow[] {
  if (!graph) return [];
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const out = new Map<string, Flow>();
  const put = (f: Flow) => {
    const old = out.get(f.key);
    if (!old || FLOW_RANK[f.status] > FLOW_RANK[old.status]) out.set(f.key, f);
  };
  for (const e of graph.edges) {
    const src = byId.get(e.source), dst = byId.get(e.target);
    if (!src || !dst) continue;
    const from = actorOf(src), to = actorOf(dst);
    if (from === to) continue;
    const status: Flow["status"] = dst.status === "running" || dst.status === "waiting" ? "active"
      : src.status === "succeeded" && dst.status === "succeeded" ? "done" : "pending";
    put({ key: `${from}>${to}`, from, to, status });
  }
  for (const [a, b] of disputePairs(graph.nodes)) put({ key: `${a}>${b}`, from: a, to: b, status: "dispute" });
  return [...out.values()];
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
    // Adım 21b: iş başlarken sen (sahip) isteği ilk ajana götürürsün
    if (started && n.kind !== "request") {
      const fromReq = next.edges.some((e) => e.target === n.id && byId.get(e.source)?.kind === "request");
      const to = actorOf(n);
      if (fromReq && to !== "owner") out.push({ key: `${n.id}:request`, actor: "owner", host: to, kind: "handoff", note: "iş verdi" });
    }
    if (finished && n.kind === "result") out.push({ key: `${n.id}:deliver`, actor: "chef", host: "owner", kind: "deliver", note: "cevap hazır" });
    if (n.kind === "claude" && n.status !== "pending" && was === "pending") out.push({ key: `${n.id}:claude`, actor: "chef", host: "claude", kind: "claude", note: "Claude'a devir" });
  }
  return out;
}

/** İş ilk kez açıldığında (önceki durum yok) istek yeni başlamışsa: sen isteği ilk ajana götürürsün (bir kez). */
export function introVisits(g: JobGraph | null): Visit[] {
  if (!g || (g.status !== "running" && g.status !== "pending")) return [];
  const byId = new Map(g.nodes.map((n) => [n.id, n]));
  const first = g.nodes.find((n) => n.kind !== "request" && g.edges.some((e) => e.target === n.id && byId.get(e.source)?.kind === "request"));
  if (!first || (first.status !== "running" && first.status !== "pending")) return [];
  const to = actorOf(first);
  return to === "owner" ? [] : [{ key: `${first.id}:request`, actor: "owner", host: to, kind: "handoff", note: "iş verdi" }];
}

/** Tek ajanlı iş (şefsiz): istek → ajan → sonuç; ofis aynı sahneyle gösterir (Adım 17'de eklendi). */
export interface TaskLite {
  id: string; worker: string; objective: string; status: string; model: string | null; error: string | null;
  metrics?: Record<string, unknown>; started_at?: string | null; finished_at?: string | null;
}
const TASK_STATUS: Record<string, FlowNode["status"]> = {
  pending: "pending", running: "running", succeeded: "succeeded", awaiting_approval: "waiting", waiting_claude: "waiting",
  failed: "failed", timed_out: "failed", cancelled: "failed", rejected: "failed",
};

export function taskGraph(t: TaskLite): JobGraph {
  const st = TASK_STATUS[t.status] ?? "pending";
  const dur = t.started_at && t.finished_at ? Math.round((Date.parse(t.finished_at) - Date.parse(t.started_at)) / 100) / 10 : null;
  const tps = typeof t.metrics?.tokens_per_second === "number" ? (t.metrics.tokens_per_second as number) : null;
  const n = (id: string, kind: FlowNode["kind"], label: string, status: FlowNode["status"], extra: Partial<FlowNode> = {}): FlowNode =>
    ({ id, kind, label, status, agent: null, model: null, task_id: null, duration_s: null, tokens_per_second: null, detail: "", error: null, review: null, ...extra });
  return {
    job_id: t.id, objective: t.objective, status: t.status, mode: "direct", routing: null, duration_s: dur, warnings: [],
    nodes: [
      n("request", "request", "İstek", "succeeded", { detail: t.objective }),
      n("step-1", "step", t.worker, st, { agent: t.worker, model: t.model, task_id: t.id, duration_s: dur, tokens_per_second: tps,
                                          detail: t.objective, error: t.error }),
      n("result", "result", "Sonuç", st === "succeeded" ? "succeeded" : st === "failed" ? "failed" : "pending"),
    ],
    edges: [{ source: "request", target: "step-1" }, { source: "step-1", target: "result" }],
  };
}

/** Sahibin çizimleri (Adım 18d; /api/office/assets): karakter → durum → adres. */
export interface OfficeAssets {
  folder: string; exists: boolean; desk: string | null; floor: string | null;
  actors: Record<string, Record<string, string>>; unknown: string[]; skipped: string[];
  sizes?: Record<string, [number, number]>;  // PNG boyutları: kare sayısı = genişlik / yükseklik
  // Karenin dolu alanı [x0, y0, x1, y1] (kare içi): yürüyen karakter her yönde aynı boyda, ayağı yerde çizilir
  bounds?: Record<string, [number, number, number, number]>;
  props?: Record<string, string>;            // Adım 21b: sahibin eşyaları (water, cabinet, coffee…)
}

/** Pixel çizim (Adım 21): yan yana kareler; (ax, ay) = sahnedeki noktaya oturan piksel (ayak / masa altı). */
export interface Sprite { href: string; frames: number; fw: number; fh: number; ax: number; ay: number; scale?: number }
export type WalkDir = "down" | "up" | "left" | "right";

const PIX = "/office/pixel/";
const seatSprite = (file: string, frames = 1): Sprite => ({ href: PIX + file, frames, fw: 64, fh: 64, ax: 32, ay: 61 });
const walkSprite = (file: string): Sprite => ({ href: PIX + file, frames: 4, fw: 64, fh: 64, ax: 31, ay: 48 });
const kaya = (file: string): Sprite => seatSprite(`kaya/${file}`);
const prop = (file: string, w: number, h: number): Sprite => ({ href: `${PIX}kaya/${file}`, frames: 1, fw: w, fh: h, ax: w / 2, ay: h });
/** Kendi renkli çizimi olan ajanlar (saç + ajan renginde tişört; masada ve yürürken aynı). */
export const AGENT_ART = ["general", "data", "document", "coder", "reviewer", "vision"];

/** Hazır çizimler (free-office-pixel-art, arlantr — "free to use any way you want"). Sahibin çizimleri bunların yerine geçer. */
export const PIXEL = {
  seat: {
    general: seatSprite("worker1.png"), data: seatSprite("worker2.png"), document: seatSprite("worker4.png"),
    coder: seatSprite("worker2.png"), reviewer: seatSprite("worker4.png"), vision: seatSprite("worker1.png"),
    chef: seatSprite("boss.png"), default: seatSprite("worker1.png"),
  } as Record<string, Sprite>,
  // Adım 21b: masada oturanın yalnız kişi katmanı (masa ayrı çizilir → masa.png herkesin masasını değiştirir)
  // Adım 21d: ajan başına renkli kişi katmanı ve yürüme (scripts/office_art.py — hazır çizimlerden renk değiştirilerek)
  person: {
    general: kaya("general-person.png"), data: kaya("data-person.png"), document: kaya("document-person.png"),
    coder: kaya("coder-person.png"), reviewer: kaya("reviewer-person.png"), vision: kaya("vision-person.png"),
    default: seatSprite("worker1-person.png"),
  } as Record<string, Sprite>,
  emptyDesk: seatSprite("desk-with-pc.png"),
  busyDesk: seatSprite("Julia_PC.png", 6),          // sahibi kalkmışken ekranı çalışan masa
  ownerDesk: { href: PIX + "writing-table.png", frames: 1, fw: 64, fh: 64, ax: 32, ay: 49 } as Sprite,
  owner: { href: PIX + "Julia-Idle.png", frames: 4, fw: 32, fh: 32, ax: 16, ay: 31 } as Sprite,
  walk: { down: walkSprite("Julia_walk_Foward.png"), up: walkSprite("Julia_walk_Up.png"),
          left: walkSprite("Julia_walk_Left.png"), right: walkSprite("Julia_walk_Rigth.png") } as Record<WalkDir, Sprite>,
  walkBy: Object.fromEntries(AGENT_ART.map((a) => [a, Object.fromEntries((["down", "up", "left", "right"] as WalkDir[])
    .map((d) => [d, walkSprite(`kaya/${a}-walk-${d}.png`)]))])) as Record<string, Record<WalkDir, Sprite>>,
  props: [  // duvar dibi ve köşeler (ızgara birimi; ay = alt kenar). id: sahibin eşyası bunun yerine geçer (su.png…)
    // Adım 21d: detaylı eşyalar (scripts/office_art.py). sh: yerdeki gölgenin yarı genişliği (sahne birimi)
    { id: "cabinet", s: prop("bookshelf.png", 30, 50), at: { x: 0.28, y: 1.05 }, sh: 30 },
    { id: "water", s: prop("water.png", 18, 36), at: { x: 0.85, y: 1.0 }, sh: 16 },
    { id: "coffee", s: prop("coffee.png", 64, 46), at: { x: 1.8, y: 1.0 }, sh: 62 },
    { id: "printer", s: prop("copier.png", 60, 36), at: { x: 5.3, y: 1.0 }, sh: 60 },
    { id: "plant", s: prop("plant.png", 26, 36), at: { x: 6.1, y: 1.0 }, sh: 16 },
    { id: "plant", s: prop("plant.png", 26, 36), at: { x: 0.2, y: 5.45 }, sh: 16 },
    { id: "trash", s: prop("trash.png", 14, 16), at: { x: 3.45, y: 4.1 }, sh: 9 },
    { id: "sink", s: prop("sink.png", 36, 30), at: { x: 7.45, y: 4.6 }, sh: 36 },
  ] as { id: string; s: Sprite; at: Pt; sh: number }[],
};

/** Sahibin resmi → çizim: kareler yan yana (kare sayısı = genişlik/yükseklik), hazır kalıpla aynı hizalama.
 *  Kare 64'ten büyükse (ör. 96 — `kayaai ofis ice-aktar` büyük karakterler için seçer) orantılı küçültülür: sahnede
 *  hazır çizimlerle aynı boyda görünür. */
export function ownSprite(assets: OfficeAssets | null | undefined, url: string | null, kind: "seat" | "walk", walkH?: number): Sprite | null {
  if (!url) return null;
  const size = assets?.sizes?.[url];
  const [w, h] = size ?? [64, 64];
  const frames = Math.max(1, Math.round(w / h));
  const fw = w / frames;
  const box = kind === "walk" ? assets?.bounds?.[url] : undefined;
  if (box && walkH && box[3] > box[1]) {
    // Yürüyen: kişi istenen boyda (sahne birimi), ayakları dolu alanın alt kenarında, yatayda dolu alanın ortası
    const k = Math.min(4, Math.max(0.5, walkH / (box[3] - box[1])));
    return { href: url, frames, fw, fh: h, ax: (box[0] + box[2]) / 2, ay: box[3], scale: k };
  }
  return { href: url, frames, fw, fh: h, ax: fw / 2, ay: kind === "seat" ? h * (61 / 64) : h * (48 / 64), scale: PX * 64 / h };
}

/** Bir karakterin yürüme boyu (sahne birimi): kendi yönlü çizimlerinin ekrandaki boylarının ortancası. Yapay zekâyla
 *  ayrı ayrı üretilen yönlerde kişi farklı boyda çıkabiliyor (ör. sağa 90, diğerleri ~72); ortanca tek aykırı çizimi
 *  düzeltir, karakterler arasındaki gerçek boy farkını korur. Dolu alan bilgisi yoksa undefined (eski hizalama). */
export function walkHeight(assets: OfficeAssets | null | undefined, own: Record<string, string> | undefined): number | undefined {
  if (!own || !assets?.bounds) return undefined;
  const hs: number[] = [];
  for (const key of ["walk_down", "walk_up", "walk_left", "walk_right", "walking"]) {
    const url = own[key];
    const box = url ? assets.bounds[url] : undefined;
    const fh = url ? assets.sizes?.[url]?.[1] : undefined;
    if (box && fh && box[3] > box[1]) hs.push((box[3] - box[1]) * PX * 64 / fh);
  }
  if (!hs.length) return undefined;
  hs.sort((a, b) => a - b);
  const m = hs.length >> 1;
  return hs.length % 2 ? hs[m] : (hs[m - 1] + hs[m]) / 2;
}

/** Zemin karosunun sahnedeki boyu: resim kaç pikselse PX katı (16×16 → 32, 64×64 → 128); bilinmiyorsa 16×16. */
export function floorTile(assets: OfficeAssets | null | undefined): [number, number] {
  const size = assets?.floor ? assets.sizes?.[assets.floor] : undefined;
  return size ? [size[0] * PX, size[1] * PX] : [16 * PX, 16 * PX];
}

/** Sahibin eşyası (su.png…) ya da hazır eşya; çok büyük resim hazır eşyanın 1,5 katına sığdırılır. */
export function propSprite(assets: OfficeAssets | null | undefined, id: string, dflt: Sprite): Sprite {
  const url = assets?.props?.[id];
  if (!url) return dflt;
  const [w, h] = assets?.sizes?.[url] ?? [dflt.fw, dflt.fh];
  const maxH = (dflt.ay + 2) * 1.5;
  return { href: url, frames: 1, fw: w, fh: h, ax: w / 2, ay: h, scale: h > maxH ? PX * maxH / h : PX };
}

/** Masada oturan, katman katman: masa (sahibin masa.png'si ya da hazır; çalışırken ekranı oynayan) + kişi.
 *  `desk` null: kişi çizimi masayla birlikte (hazır Şef: patron masası). */
export function seatLayers(assets: OfficeAssets | null | undefined, a: Pick<Actor, "id" | "kind" | "state">): { desk: Sprite | null; person: Sprite } {
  const own = ownSprite(assets, pickArt(assets, a), "seat");
  const desk = assets?.desk ? ownSprite(assets, assets.desk, "seat")! : a.state === "working" ? PIXEL.busyDesk : PIXEL.emptyDesk;
  if (own) return { desk, person: own };
  if (a.kind === "chef") return { desk: null, person: PIXEL.seat.chef };
  return { desk, person: PIXEL.person[a.id] ?? PIXEL.person.default };
}

/** Yürürken çizim: sahibin yönlü resmi → tek yürüme resmi (sola yansıtılır) → hazır Julia. */
export function pickWalk(assets: OfficeAssets | null | undefined, a: Pick<Actor, "id" | "kind">, dir: WalkDir): { s: Sprite; flip: boolean } {
  const key = { down: "walk_down", up: "walk_up", left: "walk_left", right: "walk_right" }[dir];
  const pools = [assets?.actors[a.id], a.kind === "agent" ? assets?.actors["default"] : undefined];
  for (const own of pools) {
    if (!own) continue;
    const h = walkHeight(assets, own);
    if (own[key]) return { s: ownSprite(assets, own[key], "walk", h)!, flip: false };
    if (own.walking) return { s: ownSprite(assets, own.walking, "walk", h)!, flip: dir === "left" };
  }
  return { s: PIXEL.walkBy[a.id]?.[dir] ?? PIXEL.walk[dir], flip: false };
}

/** Masada (oturan) çizim: sahibin durum/genel resmi → hazır çalışan çizimi. */
export function pickSeat(assets: OfficeAssets | null | undefined, a: Pick<Actor, "id" | "kind" | "state">): Sprite {
  const own = ownSprite(assets, pickArt(assets, a), "seat");
  return own ?? PIXEL.seat[a.id] ?? (a.kind === "chef" ? PIXEL.seat.chef : PIXEL.seat.default);
}

/** Karakter çizimi: önce o durumun resmi, sonra genel resmi; adı olmayan ajanlar için "ajan" resmi. Yoksa null (şekil). */
export function pickArt(assets: OfficeAssets | null | undefined, a: Pick<Actor, "id" | "kind" | "state">, walking = false): string | null {
  if (!assets) return null;
  const state = walking ? "walking" : a.state;
  const own = assets.actors[a.id];
  const dflt = a.kind === "agent" ? assets.actors["default"] : undefined;
  return own?.[state] ?? own?.base ?? dflt?.[state] ?? dflt?.base ?? null;
}

/** Izgara → ekran (Adım 21: önden-üstten). Pixel çizimler PX katı büyütülür (en yakın komşu). */
export const CELL = { w: 112, h: 96 };
export const PX = 2;
export function top(p: Pt): Pt {
  return { x: p.x * CELL.w, y: p.y * CELL.h };
}

/** Masadaki oturuş noktası ve ziyaretçinin durduğu yer (masanın sağ yanı). */
export function seat(d: Pt): Pt { return { x: d.x, y: d.y }; }
export function visitorSpot(d: Pt): Pt { return { x: d.x + 0.62, y: d.y + 0.05 }; }

/** Yürüme yönü (ekranda hangi yöne gidiyor). */
export function walkDir(from: Pt, to: Pt): WalkDir {
  const dx = to.x - from.x, dy = to.y - from.y;
  if (Math.abs(dx) * CELL.w >= Math.abs(dy) * CELL.h) return dx < 0 ? "left" : "right";
  return dy < 0 ? "up" : "down";
}

export const STATE_TEXT: Record<ActorState, string> = {
  idle: "boşta", working: "çalışıyor", waiting: "bekliyor", error: "hata", done: "bitirdi",
};
