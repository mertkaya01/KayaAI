import { describe, expect, it } from "vitest";
import type { Approval, FlowNode, JobGraph } from "../api";
import { actorOf, deriveActors, diffVisits, iso, layout, pickArt, taskGraph, type OfficeAssets } from "../office/scene";

function node(id: string, kind: FlowNode["kind"], status: FlowNode["status"], agent: string | null = null, task_id: string | null = null): FlowNode {
  return { id, kind, label: id, status, agent, model: "qwen3:8b", task_id, duration_s: null, tokens_per_second: null, detail: "", error: null, review: null };
}

function graph(nodes: FlowNode[], edges: [string, string][], status = "running"): JobGraph {
  return { job_id: "j1", objective: "Satışları analiz et", status, mode: "plan", routing: null, duration_s: null, warnings: [],
           nodes, edges: edges.map(([source, target]) => ({ source, target })) };
}

const approval = (by: string, summary = "rapor.xlsx yaz"): Approval => ({
  id: "a1", created_at: "", status: "pending", decided_at: null, decided_by: null, decision_note: null, error: null,
  action: { tool: "fs.write", risk: "R1", summary, reason: "", preview: {}, undo: "", requested_by: by },
});

describe("actorOf", () => {
  it("maps node kinds to characters", () => {
    expect(actorOf(node("request", "request", "succeeded"))).toBe("owner");
    expect(actorOf(node("planner", "planner", "succeeded", "planner"))).toBe("chef");
    expect(actorOf(node("s", "step", "running", "data"))).toBe("data");
    expect(actorOf(node("r", "revise", "running", "data.revise"))).toBe("data");
    expect(actorOf(node("c", "check", "running"))).toBe("reviewer");
    expect(actorOf(node("result", "result", "pending"))).toBe("chef");
    expect(actorOf(node("result", "claude", "waiting"))).toBe("claude");
  });
});

describe("layout", () => {
  it("gives unknown agents spare desks without collisions", () => {
    const l = layout(["data", "satisci", "muhasebe"]);
    expect(l.find((a) => a.id === "satisci")?.kind).toBe("agent");
    const desks = l.map((a) => `${a.desk.x},${a.desk.y}`);
    expect(new Set(desks).size).toBe(desks.length);
  });
});

describe("deriveActors", () => {
  const g = graph(
    [node("request", "request", "succeeded"), node("planner", "planner", "succeeded", "planner"),
     node("step-s1", "step", "succeeded", "data", "t1"), node("step-s2", "step", "running", "document", "t2"),
     node("result", "result", "pending")],
    [["request", "planner"], ["planner", "step-s1"], ["step-s1", "step-s2"], ["step-s2", "result"]],
  );

  it("shows live tail on the working agent", () => {
    const actors = deriveActors(g, { t2: { task_id: "t2", worker: "document", chars: 50, field: "answer", tail: "Ankara önde", attempt: 1, at: 0 } }, []);
    const doc = actors.find((a) => a.id === "document")!;
    expect(doc.state).toBe("working");
    expect(doc.bubble).toBe("Ankara önde");
    expect(actors.find((a) => a.id === "data")!.state).toBe("done");
    expect(actors.find((a) => a.id === "coder")!.state).toBe("idle");
  });

  it("marks retries and errors", () => {
    const a = deriveActors(g, { t2: { task_id: "t2", worker: "document", chars: 1, field: null, tail: "x", attempt: 2, at: 0 } }, []);
    expect(a.find((x) => x.id === "document")!.bubble).toBe("(2. deneme) x");
    const failed = graph([{ ...node("step-s1", "step", "failed", "data"), error: "şema" }], []);
    expect(deriveActors(failed, {}, []).find((x) => x.id === "data")!.bubble).toBe("Hata: şema");
  });

  it("puts approvals on the requesting agent and the owner desk", () => {
    const a = deriveActors(g, {}, [approval("agent:data")]);
    expect(a.find((x) => x.id === "data")!.state).toBe("waiting");
    expect(a.find((x) => x.id === "data")!.bubble).toContain("rapor.xlsx");
    const b = deriveActors(null, {}, [approval("api")]);
    expect(b.find((x) => x.id === "owner")!.bubble).toBe("1 onay bekliyor");
  });

  it("translates short enum values", () => {
    const r = graph([node("check-s1", "check", "running", null, "t9")], []);
    const a = deriveActors(r, { t9: { task_id: "t9", worker: "reviewer.check", chars: 9, field: "verdict", tail: "approve", attempt: 1, at: 0 } }, []);
    expect(a.find((x) => x.id === "reviewer")!.bubble).toBe("onaylıyorum");
  });

  it("hides half-streamed enum values", () => {
    const r = graph([node("check-s1", "check", "running", null, "t9")], []);
    const a = deriveActors(r, { t9: { task_id: "t9", worker: "reviewer.check", chars: 3, field: "verdict", tail: "app", attempt: 1, at: 0 } }, []);
    expect(a.find((x) => x.id === "reviewer")!.bubble).toBe("check-s1…");
  });

  it("clips long bubbles", () => {
    const a = deriveActors(g, { t2: { task_id: "t2", worker: "document", chars: 1, field: null, tail: "y".repeat(300), attempt: 1, at: 0 } }, []);
    expect(a.find((x) => x.id === "document")!.bubble!.length).toBe(120);
  });
});

describe("diffVisits", () => {
  const nodes = (s2: FlowNode["status"], chk: FlowNode["status"], res: FlowNode["status"]) => [
    node("planner", "planner", "succeeded", "planner"), node("step-s1", "step", "succeeded", "data"),
    node("check-s1", "check", chk), node("step-s2", "step", s2, "document"), node("result", "result", res)];
  const edges: [string, string][] = [["planner", "step-s1"], ["step-s1", "check-s1"], ["check-s1", "step-s2"], ["step-s2", "result"]];

  it("reviewer visits the step agent, then a handoff, then the chef delivers", () => {
    const g0 = graph(nodes("pending", "pending", "pending"), edges);
    const g1 = graph(nodes("pending", "running", "pending"), edges);
    expect(diffVisits(g0, g1)).toEqual([{ key: "check-s1:review", actor: "reviewer", host: "data", kind: "review", note: "kontrol ediyor" }]);
    const g2 = graph(nodes("running", "succeeded", "pending"), edges);
    expect(diffVisits(g1, g2)).toEqual([{ key: "check-s1>step-s2", actor: "reviewer", host: "document", kind: "handoff", note: "teslim" }]);
    const g3 = graph(nodes("succeeded", "succeeded", "succeeded"), edges, "succeeded");
    expect(diffVisits(g2, g3).map((v) => v.kind)).toEqual(["deliver"]);
  });

  it("no visits across jobs or on first load", () => {
    const g = graph(nodes("running", "succeeded", "pending"), edges);
    expect(diffVisits(null, g)).toEqual([]);
    expect(diffVisits({ ...g, job_id: "other" }, g)).toEqual([]);
  });
});

it("single-agent task as an office graph", () => {
  const g = taskGraph({ id: "t1", worker: "coder", objective: "Kod yaz", status: "running", model: "qwen3:8b", error: null,
                        metrics: { tokens_per_second: 50 }, started_at: null, finished_at: null });
  const a = deriveActors(g, {}, []);
  expect(a.find((x) => x.id === "coder")!.state).toBe("working");
  const done = taskGraph({ id: "t1", worker: "coder", objective: "Kod yaz", status: "succeeded", model: "qwen", error: null,
                           started_at: "2026-11-01T10:00:00Z", finished_at: "2026-11-01T10:00:03.5Z" });
  expect(diffVisits(g, done).map((v) => v.kind)).toEqual(["deliver"]);
  expect(done.nodes[1].duration_s).toBe(3.5);
});

it("picks owner-drawn art by state with fallbacks", () => {
  const assets: OfficeAssets = { folder: "", exists: true, desk: null, floor: null, unknown: [], skipped: [],
    actors: { data: { base: "/ofis/veri.png", working: "/ofis/veri-calisiyor.png" }, default: { base: "/ofis/ajan.png", walking: "/ofis/ajan-yuruyor.png" } } };
  expect(pickArt(assets, { id: "data", kind: "agent", state: "working" })).toBe("/ofis/veri-calisiyor.png");
  expect(pickArt(assets, { id: "data", kind: "agent", state: "error" })).toBe("/ofis/veri.png");
  expect(pickArt(assets, { id: "coder", kind: "agent", state: "idle" }, true)).toBe("/ofis/ajan-yuruyor.png");
  expect(pickArt(assets, { id: "chef", kind: "chef", state: "idle" })).toBeNull();  // "ajan" resmi yalnız ajanlar için
  expect(pickArt(null, { id: "data", kind: "agent", state: "idle" })).toBeNull();
});

it("iso projection", () => {
  expect(iso({ x: 0, y: 0 })).toEqual({ x: 0, y: 0 });
  expect(iso({ x: 1, y: 0 })).toEqual({ x: 48, y: 24 });
  expect(iso({ x: 0, y: 1 })).toEqual({ x: -48, y: 24 });
});
