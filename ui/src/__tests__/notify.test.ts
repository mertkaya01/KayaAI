import { describe, expect, it } from "vitest";
import type { KEvent, NotifyPrefs } from "../api";
import { eventToNotice, inQuiet, shouldNotify } from "../notify";

const ev = (type: string, data: Record<string, unknown>): KEvent => ({ id: 1, ts: "2026-11-01T10:00:00+00:00", type, task_id: null, data });
const prefs: NotifyPrefs = { browser: true, windows: true, kinds: { approval: true, reply: true, schedule: true, error: true }, quiet_start: null, quiet_end: null };

describe("eventToNotice", () => {
  it("maps events to notices", () => {
    expect(eventToNotice(ev("approval.requested", { risk: "R2", summary: "rapor.xlsx yaz" }))).toMatchObject({ kind: "approval", body: "rapor.xlsx yaz" });
    expect(eventToNotice(ev("chat.message", { role: "assistant", status: "done", conv_id: "c1" }))).toMatchObject({ kind: "reply", route: { page: "chat", convId: "c1" } });
    expect(eventToNotice(ev("chat.message", { role: "assistant", status: "failed" }))?.kind).toBe("error");
    expect(eventToNotice(ev("schedule.run", { status: "succeeded", name: "Gece" }))).toMatchObject({ kind: "schedule", body: "Gece" });
    expect(eventToNotice(ev("schedule.run", { status: "running" }))).toBeNull();
    expect(eventToNotice(ev("chat.message", { role: "user" }))).toBeNull();
    expect(eventToNotice(ev("task.progress", {}))).toBeNull();
  });
});

describe("shouldNotify", () => {
  const noon = new Date(2026, 10, 1, 12, 0);
  it("only in background, with permission and preference", () => {
    expect(shouldNotify(prefs, "reply", false, "granted", noon)).toBe(true);
    expect(shouldNotify(prefs, "reply", true, "granted", noon)).toBe(false);
    expect(shouldNotify(prefs, "reply", false, "default", noon)).toBe(false);
    expect(shouldNotify({ ...prefs, browser: false }, "reply", false, "granted", noon)).toBe(false);
    expect(shouldNotify({ ...prefs, kinds: { ...prefs.kinds, reply: false } }, "reply", false, "granted", noon)).toBe(false);
    expect(shouldNotify(null, "reply", false, "granted", noon)).toBe(false);
  });
  it("respects quiet hours across midnight", () => {
    const q = { ...prefs, quiet_start: "22:30", quiet_end: "08:00" };
    expect(inQuiet(q, new Date(2026, 0, 1, 23, 0))).toBe(true);
    expect(inQuiet(q, new Date(2026, 0, 1, 7, 59))).toBe(true);
    expect(inQuiet(q, new Date(2026, 0, 1, 8, 0))).toBe(false);
    expect(shouldNotify(q, "approval", false, "granted", new Date(2026, 0, 1, 23, 0))).toBe(false);
  });
});
