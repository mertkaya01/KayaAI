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
  });

  it("kayan pencere en fazla max değer tutar", () => {
    let s: number[] = [];
    for (let i = 0; i < 70; i++) s = pushSample(s, i);
    expect(s).toHaveLength(60);
    expect(s[0]).toBe(10);
    expect(s[59]).toBe(69);
  });
});
