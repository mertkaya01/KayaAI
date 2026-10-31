/** Küçük DAG yerleşimi (ek kütüphane yok): sütun = kaynaklardan en uzun yol derinliği, sütun içi = ilk görünüş sırası. */
export interface DagNode { id: string }
export interface DagEdge { source: string; target: string }
export interface Placed { x: number; y: number }
export interface Layout { pos: Record<string, Placed>; width: number; height: number }

export const NODE_W = 176;
export const NODE_H = 60;
const COL_GAP = 64;
const ROW_GAP = 22;
const PAD = 16;

export function layout(nodes: DagNode[], edges: DagEdge[]): Layout {
  const ids = nodes.map((n) => n.id);
  const known = new Set(ids);
  const incoming: Record<string, string[]> = {};
  for (const id of ids) incoming[id] = [];
  for (const e of edges) if (known.has(e.source) && known.has(e.target)) incoming[e.target].push(e.source);
  const depth: Record<string, number> = {};
  const visiting = new Set<string>();
  const d = (id: string): number => {
    if (depth[id] !== undefined) return depth[id];
    if (visiting.has(id)) return 0; // döngü koruması
    visiting.add(id);
    const v = incoming[id].length ? Math.max(...incoming[id].map(d)) + 1 : 0;
    visiting.delete(id);
    depth[id] = v;
    return v;
  };
  ids.forEach(d);
  const cols: string[][] = [];
  for (const id of ids) (cols[depth[id]] ??= []).push(id);
  const tallest = Math.max(1, ...cols.map((c) => c?.length ?? 0));
  const height = PAD * 2 + tallest * NODE_H + (tallest - 1) * ROW_GAP;
  const pos: Record<string, Placed> = {};
  cols.forEach((col, ci) => {
    if (!col) return;
    const colH = col.length * NODE_H + (col.length - 1) * ROW_GAP;
    const top = (height - colH) / 2;
    col.forEach((id, ri) => { pos[id] = { x: PAD + ci * (NODE_W + COL_GAP), y: top + ri * (NODE_H + ROW_GAP) }; });
  });
  const width = PAD * 2 + cols.length * NODE_W + Math.max(0, cols.length - 1) * COL_GAP;
  return { pos, width, height };
}
