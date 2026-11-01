import { describe, expect, it } from "vitest";
import { ago, describeEvent, gb, groupByDate, pct, pushSample, when } from "../format";

describe("biçimlendirme", () => {
  it("yüzde ve GB", () => {
    expect(pct(42.6)).toBe("43%");
    expect(pct(null)).toBe("—");
    expect(gb(16384)).toBe("16.0 GB");
    expect(gb(undefined)).toBe("—");
  });

  it("göreli zaman", () => {
    const now = new Date("2026-10-31T12:00:00Z");
    expect(ago("2026-10-31T11:59:30Z", now)).toBe("30 sn önce");
    expect(ago("2026-10-31T11:55:00Z", now)).toBe("5 dk önce");
    expect(ago("2026-10-31T09:00:00Z", now)).toBe("3 sa önce");
    expect(ago("2026-10-29T12:00:00Z", now)).toBe("2 gün önce");
    expect(ago(null, now)).toBe("—");
  });

  it("olay metinleri Türkçe", () => {
    const base = { id: 1, ts: "2026-10-31T12:00:00Z", task_id: null };
    expect(describeEvent({ ...base, type: "task.status", data: { worker: "general", status: "succeeded", objective: "Merhaba" } }))
      .toBe("general · tamamlandı — Merhaba");
    expect(describeEvent({ ...base, type: "approval.requested", data: { risk: "R2", summary: "deneme.md üzerine yaz" } }))
      .toBe("Onay istendi (R2): deneme.md üzerine yaz");
    expect(describeEvent({ ...base, type: "claude.mode", data: { enabled: true } })).toBe("Claude modu açıldı");
    expect(describeEvent({ ...base, type: "bilinmeyen", data: {} })).toBe("bilinmeyen");
    expect(describeEvent({ ...base, type: "dispute.opened", data: { producer: "coder", reviewer: "reviewer", issue: "x yanlış", escalated_to: "owner" } }))
      .toBe("Anlaşmazlık: coder ↔ reviewer — x yanlış (sana)");
    expect(describeEvent({ ...base, type: "dispute.resolved", data: { resolution: "producer" } }))
      .toBe("Anlaşmazlık kapandı: üretici haklı bulundu");
    expect(describeEvent({ ...base, type: "decision.summary", data: { status: "succeeded", steps: 1, reviewed_steps: 1, revised_steps: 1, disputes: 0 } }))
      .toBe("İş bitti (tamamlandı): 1 adım, 1 gözden geçirme, 1 düzeltme");
    expect(describeEvent({ ...base, type: "model.pull", data: { name: "qwen3:4b", status: "downloading", percent: 45.5 } }))
      .toBe("Model indirme · qwen3:4b: downloading (%45.5)");
    expect(describeEvent({ ...base, type: "model.compare", data: { id: "a", done: 2, total: 6 } })).toBe("Model karşılaştırma: 2/6");
    expect(describeEvent({ ...base, type: "model.compare", data: { id: "a", status: "done" } })).toBe("Model karşılaştırma bitti");
    expect(describeEvent({ ...base, type: "agent.model_changed", data: { name: "data", model_key: "coder-7b" } }))
      .toBe("Ajanın modeli değişti: data → coder-7b");
  });

  it("kayan pencere en fazla max değer tutar", () => {
    let s: number[] = [];
    for (let i = 0; i < 70; i++) s = pushSample(s, i);
    expect(s).toHaveLength(60);
    expect(s[0]).toBe(10);
    expect(s[59]).toBe(69);
  });
});

describe("when", () => {
  const now = new Date(2026, 10, 1, 10, 0);
  it("relative day words", () => {
    expect(when(new Date(2026, 10, 1, 21, 5).toISOString(), now)).toBe("bugün 21:05");
    expect(when(new Date(2026, 10, 2, 9, 0).toISOString(), now)).toBe("yarın 09:00");
    expect(when(new Date(2026, 10, 4, 9, 0).toISOString(), now)).toBe("Çar 09:00");
    expect(when(new Date(2026, 11, 3, 9, 0).toISOString(), now)).toBe("3 Ara 09:00");
    expect(when(null, now)).toBe("—");
  });
});

describe("groupByDate", () => {
  it("groups conversations by day buckets", () => {
    const now = new Date(2026, 10, 10, 12);
    const at = (d: number) => ({ updated_at: new Date(2026, 10, d, 9).toISOString() });
    const g = groupByDate([at(10), at(10), at(9), at(6), at(1), { updated_at: new Date(2026, 8, 1).toISOString() }], now);
    expect(g.map((x) => [x.label, x.items.length])).toEqual([["Bugün", 2], ["Dün", 1], ["Bu hafta", 1], ["Bu ay", 1], ["Daha eski", 1]]);
  });
});
