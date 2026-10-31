import { describe, expect, it } from "vitest";
import { ago, describeEvent, gb, pct, pushSample } from "../format";

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
  });

  it("kayan pencere en fazla max değer tutar", () => {
    let s: number[] = [];
    for (let i = 0; i < 70; i++) s = pushSample(s, i);
    expect(s).toHaveLength(60);
    expect(s[0]).toBe(10);
    expect(s[59]).toBe(69);
  });
});
