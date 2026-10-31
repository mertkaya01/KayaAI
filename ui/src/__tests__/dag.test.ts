import { describe, expect, it } from "vitest";
import { NODE_H, NODE_W, layout } from "../dag";

describe("DAG yerleşimi", () => {
  it("en uzun yola göre sütunlar, çakışma yok", () => {
    const nodes = ["request", "planner", "a", "b", "check", "c", "result"].map((id) => ({ id }));
    const edges = [
      ["request", "planner"], ["planner", "a"], ["planner", "b"], ["a", "check"], ["check", "c"], ["b", "c"], ["c", "result"],
    ].map(([source, target]) => ({ source, target }));
    const { pos, width, height } = layout(nodes, edges);
    const col = (id: string) => Math.round(pos[id].x / 10);
    expect(col("request")).toBeLessThan(col("planner"));
    expect(col("a")).toBe(col("b"));
    expect(col("c")).toBeGreaterThan(col("check")); // c, b'den değil en uzun yoldan (check) sonra
    expect(col("result")).toBeGreaterThan(col("c"));
    const boxes = Object.values(pos);
    for (let i = 0; i < boxes.length; i++)
      for (let j = i + 1; j < boxes.length; j++) {
        const [p, q] = [boxes[i], boxes[j]];
        const overlap = Math.abs(p.x - q.x) < NODE_W && Math.abs(p.y - q.y) < NODE_H;
        expect(overlap).toBe(false);
      }
    expect(width).toBeGreaterThan(5 * NODE_W);
    expect(height).toBeGreaterThanOrEqual(2 * NODE_H);
  });

  it("döngü ve bilinmeyen düğüm kenarlarında çökmez", () => {
    const r = layout([{ id: "a" }, { id: "b" }], [{ source: "a", target: "b" }, { source: "b", target: "a" }, { source: "x", target: "a" }]);
    expect(Object.keys(r.pos).sort()).toEqual(["a", "b"]);
  });
});
