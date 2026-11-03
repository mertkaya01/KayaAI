import { describe, expect, it } from "vitest";
import type { Approval, FlowNode, JobGraph } from "../api";
import { actorOf, deriveActors, diffVisits, floorTile, flows, introVisits, layout, ownSprite, pickArt, pickSeat, pickWalk, PIXEL, propSprite, seatLayers,
         taskGraph, top, walkDir, walkHeight, workStyle, type OfficeAssets } from "../office/scene";

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

describe("Adım 19a: animasyon bilgisi", () => {
  const g = graph(
    [node("request", "request", "succeeded"), node("planner", "planner", "succeeded", "planner"),
     node("step-s1", "step", "succeeded", "data", "t1"), node("check-s1", "check", "succeeded", null, "t2"),
     node("step-s2", "step", "running", "coder", "t3"), node("step-s3", "step", "pending", "document"),
     node("result", "result", "pending")],
    [["request", "planner"], ["planner", "step-s1"], ["step-s1", "check-s1"], ["check-s1", "step-s2"],
     ["planner", "step-s3"], ["step-s2", "result"], ["step-s3", "result"]],
  );

  it("thinking before the first token, typing after", () => {
    expect(deriveActors(g, {}, []).find((a) => a.id === "coder")!.activity).toBe("thinking");
    expect(deriveActors(g, {}, []).find((a) => a.id === "coder")!.bubble).toBeNull();
    const p = { t3: { task_id: "t3", worker: "coder", chars: 12, field: "answer", tail: "def f():", attempt: 1, at: 0 } };
    const c = deriveActors(g, p, []).find((a) => a.id === "coder")!;
    expect(c.activity).toBe("typing");
    expect(c.bubble).toBe("def f():");
    expect(deriveActors(g, p, []).find((a) => a.id === "data")!.activity).toBeNull();
  });

  it("work styles per agent", () => {
    expect([workStyle("coder"), workStyle("data"), workStyle("document"), workStyle("chef"), workStyle("reviewer"), workStyle("satisci")])
      .toEqual(["code", "chart", "paper", "board", "review", "type"]);
  });

  it("flows between desks with status, deduplicated", () => {
    const f = Object.fromEntries(flows(g).map((x) => [x.key, x.status]));
    expect(f).toEqual({ "owner>chef": "done", "chef>data": "done", "data>reviewer": "done", "reviewer>coder": "active",
                        "chef>document": "pending", "coder>chef": "pending", "document>chef": "pending" });
    expect(flows(null)).toEqual([]);
  });

  it("disputes mark both sides and add a dispute line", () => {
    const d = graph([{ ...node("step-s1", "step", "succeeded", "data", "t1"), review: { verdict: "request_changes", issues: 1, disputes: 1 } },
                     node("check-s1", "check", "succeeded", null, "t2")], [["step-s1", "check-s1"]]);
    const a = deriveActors(d, {}, []);
    expect(a.find((x) => x.id === "data")!.dispute && a.find((x) => x.id === "reviewer")!.dispute).toBe(true);
    expect(a.find((x) => x.id === "coder")!.dispute).toBe(false);
    expect(flows(d).find((x) => x.key === "data>reviewer")!.status).toBe("dispute");
  });
});

describe("Adım 21: pixel ofis", () => {
  it("top-down projection and walking direction", () => {
    expect(top({ x: 0, y: 0 })).toEqual({ x: 0, y: 0 });
    expect(top({ x: 1, y: 2 })).toEqual({ x: 112, y: 192 });
    expect(walkDir({ x: 1, y: 2 }, { x: 3, y: 2.2 })).toBe("right");
    expect(walkDir({ x: 3, y: 2 }, { x: 1, y: 2 })).toBe("left");
    expect(walkDir({ x: 1, y: 2 }, { x: 1.1, y: 4 })).toBe("down");
    expect(walkDir({ x: 1, y: 4 }, { x: 1.1, y: 2 })).toBe("up");
  });

  it("desks do not overlap and stay inside the room", () => {
    const desks = layout(["satisci", "hukukcu"]).map((a) => a.desk);
    for (const d of desks) {
      expect(d.x).toBeGreaterThanOrEqual(0.5);
      expect(d.x).toBeLessThanOrEqual(7.6);
      expect(d.y).toBeGreaterThanOrEqual(1);
      expect(d.y).toBeLessThanOrEqual(5.45);  // sahne yüksekliği 5.6 hücre
    }
    for (let i = 0; i < desks.length; i++) {
      for (let j = i + 1; j < desks.length; j++) {
        const far = Math.abs(desks[i].x - desks[j].x) >= 0.9 || Math.abs(desks[i].y - desks[j].y) >= 0.9;
        expect(far).toBe(true);
      }
    }
  });

  it("default pixel sprites, owner art with frames from the image size", () => {
    expect(pickSeat(null, { id: "data", kind: "agent", state: "working" })).toBe(PIXEL.seat.data);
    expect(pickSeat(null, { id: "satisci", kind: "agent", state: "idle" })).toBe(PIXEL.seat.default);
    // Adım 21d: her ajan kendi renkli çizimiyle yürür; adı olmayan (geçici) ajanlar hazır kızla
    expect(pickWalk(null, { id: "data", kind: "agent" }, "up")).toEqual({ s: PIXEL.walkBy.data.up, flip: false });
    expect(PIXEL.walkBy.data.up.href).toBe("/office/pixel/kaya/data-walk-up.png");
    expect(pickWalk(null, { id: "satisci", kind: "agent" }, "up")).toEqual({ s: PIXEL.walk.up, flip: false });
    const looks = ["general", "data", "document", "coder", "reviewer", "vision"].map((id) => [PIXEL.person[id].href, PIXEL.walkBy[id].down.href]);
    expect(new Set(looks.flat()).size).toBe(12);  // masada da yürürken de herkes farklı
    const assets: OfficeAssets = { folder: "", exists: true, desk: null, floor: null, unknown: [], skipped: [],
      actors: { data: { base: "/ofis/veri.png", walking: "/ofis/veri-yuruyor.png" }, coder: { walk_left: "/ofis/kod-yuruyor-sol.png" } },
      sizes: { "/ofis/veri.png": [128, 64], "/ofis/veri-yuruyor.png": [256, 64], "/ofis/kod-yuruyor-sol.png": [128, 32] } };
    const seat = pickSeat(assets, { id: "data", kind: "agent", state: "working" });
    expect([seat.href, seat.frames, seat.fw, seat.ay]).toEqual(["/ofis/veri.png", 2, 64, 61]);
    const left = pickWalk(assets, { id: "data", kind: "agent" }, "left");
    expect([left.s.frames, left.flip]).toEqual([4, true]);  // tek yürüme resmi sola yansıtılır
    const own = pickWalk(assets, { id: "coder", kind: "agent" }, "left");
    expect([own.s.frames, own.s.fw, own.flip]).toEqual([4, 32, false]);
    expect(ownSprite(assets, null, "seat")).toBeNull();
  });
});

describe("biten işte başarısız plan notu (sahip videosu)", () => {
  it("plan zaman aşımına uğrayıp iş tek ajanla bittiyse bunu söyler", () => {
    const g = {
      job_id: "j", objective: "neler yapabilirsiniz", status: "succeeded", mode: "direct", routing: null, duration_s: 130, warnings: [],
      nodes: [
        { id: "request", kind: "request", label: "İstek", status: "succeeded", agent: null, model: null, task_id: null, duration_s: null, tokens_per_second: null, detail: "", error: null, review: null },
        { id: "planner", kind: "planner", label: "Planlayıcı", status: "failed", agent: "planner", model: null, task_id: "p1", duration_s: 120, tokens_per_second: null, detail: "", error: "120 sn zaman aşımı", review: null },
        { id: "s1", kind: "step", label: "general", status: "succeeded", agent: "general", model: null, task_id: "t1", duration_s: 5, tokens_per_second: null, detail: "", error: null, review: null },
      ],
      edges: [],
    } as unknown as JobGraph;
    const chef = deriveActors(g, {}, []).find((a) => a.id === "chef")!;
    expect(chef.state).toBe("error");
    expect(chef.bubble).toBe("Plan yapılamadı (120 sn zaman aşımı); iş tek ajanla bitti");
  });
});

describe("dış sağlayıcı işareti (Adım 20b)", () => {
  it("dış modelde çalışan ajan ☁ ile işaretlenir", () => {
    const g = {
      job_id: "j", objective: "x", status: "succeeded", mode: "plan", routing: null, duration_s: 3, warnings: [],
      nodes: [
        { id: "request", kind: "request", label: "İstek", status: "succeeded", agent: null, model: null, task_id: null, duration_s: null, tokens_per_second: null, detail: "", error: null, review: null },
        { id: "s1", kind: "step", label: "general", status: "succeeded", agent: "general", model: "☁ Groq/llama-3.3-70b", task_id: "t1", duration_s: 2, tokens_per_second: null, detail: "", error: null, review: null },
        { id: "s2", kind: "step", label: "data", status: "succeeded", agent: "data", model: "qwen3:8b", task_id: "t2", duration_s: 2, tokens_per_second: null, detail: "", error: null, review: null },
      ],
      edges: [],
    } as unknown as JobGraph;
    const actors = deriveActors(g, {}, []);
    expect(actors.find((a) => a.id === "general")!.cloud).toBe(true);
    expect(actors.find((a) => a.id === "data")!.cloud).toBe(false);
  });
});


describe("Adım 21b: sahibin çizimleri, katmanlı masa, senin yürüyüşün", () => {
  const assets: OfficeAssets = { folder: "", exists: true, desk: "/ofis/masa.png", floor: null, unknown: [], skipped: [],
    actors: { owner: { base: "/ofis/sen.png", walk_down: "/ofis/sen-yuruyor-asagi.png" } },
    props: { water: "/ofis/su.png" },
    sizes: { "/ofis/sen.png": [64, 64], "/ofis/masa.png": [64, 64], "/ofis/su.png": [17, 34], "/ofis/sen-yuruyor-asagi.png": [384, 96] } };

  it("desk layer under every seated person; own masa.png replaces the default desk", () => {
    const def = seatLayers(null, { id: "data", kind: "agent", state: "idle" });
    expect(def.desk).toBe(PIXEL.emptyDesk);
    expect(def.person).toBe(PIXEL.person.data);
    expect(seatLayers(null, { id: "data", kind: "agent", state: "working" }).desk).toBe(PIXEL.busyDesk);
    expect(seatLayers(null, { id: "chef", kind: "chef", state: "idle" })).toEqual({ desk: null, person: PIXEL.seat.chef });
    const own = seatLayers(assets, { id: "owner", kind: "owner", state: "idle" });
    expect([own.desk?.href, own.person.href]).toEqual(["/ofis/masa.png", "/ofis/sen.png"]);
    expect(seatLayers(assets, { id: "coder", kind: "agent", state: "idle" }).desk?.href).toBe("/ofis/masa.png");
  });

  it("big frames are scaled to the same size as the 64×64 ones", () => {
    const w = pickWalk(assets, { id: "owner", kind: "owner" }, "down");
    expect([w.s.frames, w.s.fw, w.s.scale, w.s.ay]).toEqual([4, 96, 2 * 64 / 96, 72]);
  });

  it("own props replace the default ones and huge images are fitted", () => {
    const water = PIXEL.props.find((p) => p.id === "water")!;
    expect(propSprite(assets, "water", water.s)).toMatchObject({ href: "/ofis/su.png", fw: 17, fh: 34, ay: 34 });
    expect(propSprite(null, "water", water.s)).toBe(water.s);
    const huge = propSprite({ ...assets, props: { water: "/x.png" }, sizes: { "/x.png": [1100, 1400] } }, "water", water.s);
    expect(huge.fh * (huge.scale ?? 2)).toBeLessThanOrEqual((water.s.ay + 2) * 1.5 * 2 + 0.001);
  });

  it("you carry the request to the first agent when a job starts", () => {
    const g = graph([node("request", "request", "succeeded"), node("planner", "planner", "running", "planner", "p1")], [["request", "planner"]]);
    g.status = "running";
    expect(introVisits(g)).toEqual([{ key: "planner:request", actor: "owner", host: "chef", kind: "handoff", note: "iş verdi" }]);
    const later = graph([node("request", "request", "succeeded"), node("planner", "planner", "succeeded", "planner", "p1")], [["request", "planner"]]);
    later.status = "running";
    expect(introVisits(later)).toEqual([]);
    const prev = graph([node("request", "request", "succeeded"), node("planner", "planner", "pending", "planner")], [["request", "planner"]]);
    expect(diffVisits(prev, { ...g, job_id: prev.job_id }).map((v) => v.note)).toContain("iş verdi");
  });
});

describe("Adım 21c: yürüyenler her yönde aynı boyda, zemin karosu kendi boyunda", () => {
  // Sahibin gerçek çizimlerindeki gibi: sağa bakan kişi diğer yönlerden büyük (45 px), aşağı bakan 96'lık karede
  const assets: OfficeAssets = { folder: "", exists: true, desk: null, floor: "/ofis/zemin.png", unknown: [], skipped: [],
    actors: { chef: { base: "/ofis/sef.png", walk_down: "/d.png", walk_right: "/r.png", walk_left: "/l.png", walk_up: "/u.png" },
              data: { walking: "/w.png" } },
    sizes: { "/ofis/zemin.png": [64, 64], "/d.png": [96, 96], "/r.png": [64, 64], "/l.png": [64, 64], "/u.png": [64, 64], "/w.png": [256, 64] },
    bounds: { "/d.png": [36, 20, 60, 72], "/r.png": [22, 3, 41, 48], "/l.png": [24, 12, 39, 48], "/u.png": [24, 11, 39, 48], "/w.png": [20, 16, 44, 48] } };

  it("ortanca boy: aykırı yön düzelir, ayak dolu alanın alt kenarında", () => {
    // ekrandaki boylar: aşağı 52·128/96 ≈ 69,3 · sağ 90 · sol 72 · yukarı 74 → ortanca (72 + 74) / 2 = 73
    expect(walkHeight(assets, assets.actors.chef)).toBeCloseTo(73, 5);
    for (const dir of ["down", "up", "left", "right"] as const) {
      const { s, flip } = pickWalk(assets, { id: "chef", kind: "chef" }, dir);
      const box = assets.bounds![s.href];
      expect(flip).toBe(false);
      expect((box[3] - box[1]) * s.scale!).toBeCloseTo(73, 5);
      expect([s.ax, s.ay]).toEqual([(box[0] + box[2]) / 2, box[3]]);
    }
  });

  it("tek yürüme resminde boy değişmez; dolu alan bilgisi yoksa eski hizalama", () => {
    const w = pickWalk(assets, { id: "data", kind: "agent" }, "left");
    expect([w.flip, w.s.frames, w.s.ax, w.s.ay]).toEqual([true, 4, 32, 48]);
    expect(32 * w.s.scale!).toBeCloseTo(64, 5);  // 48 − 16 = 32 px, eskisi gibi 2 kat
    const old = pickWalk({ ...assets, bounds: undefined }, { id: "chef", kind: "chef" }, "right");
    expect([old.s.scale, old.s.ax, old.s.ay]).toEqual([2, 32, 48]);
    expect(walkHeight(assets, undefined)).toBeUndefined();
  });

  it("zemin karosu resmin boyunda döşenir (64×64 → 128 birim); bilinmiyorsa 16×16", () => {
    expect(floorTile(assets)).toEqual([128, 128]);
    expect(floorTile(null)).toEqual([32, 32]);
    expect(floorTile({ ...assets, sizes: {} })).toEqual([32, 32]);
  });
});
