// Tarayıcı bildirimleri (Adım 16c): olay → bildirim; yalnız sekme arka plandayken, sahibin tercihlerine ve sessiz
// saatlere göre. İzin, sahip "Bildirimleri aç"a tıklayınca istenir (tarayıcı kuralı). Hepsi bu bilgisayarda kalır.
import { useCallback, useEffect, useRef } from "react";
import { api, type KEvent, type NotifyPrefs } from "./api";
import type { Route } from "./route";

export interface Notice { kind: "approval" | "reply" | "schedule" | "error"; title: string; body: string; route: Route }

export function eventToNotice(e: KEvent): Notice | null {
  const d = e.data as Record<string, unknown>;
  if (e.type === "approval.requested") {
    return { kind: "approval", title: `Onay bekliyor (${String(d.risk ?? "")})`, body: String(d.summary ?? ""), route: { page: "today" } };
  }
  if (e.type === "chat.message" && d.role === "assistant" && (d.status === "done" || d.status === "failed")) {
    const ok = d.status === "done";
    return { kind: ok ? "reply" : "error", title: ok ? "Cevap hazır" : "Cevap üretilemedi",
             body: ok ? "Asistan'da yeni bir cevap var." : "Asistan'daki iş başarısız oldu.",
             route: { page: "chat", convId: typeof d.conv_id === "string" ? d.conv_id : null } };
  }
  if (e.type === "schedule.run" && (d.status === "succeeded" || d.status === "failed")) {
    const ok = d.status === "succeeded";
    return { kind: ok ? "schedule" : "error", title: `Zamanlanmış görev ${ok ? "bitti" : "başarısız"}`,
             body: String(d.name ?? ""), route: { page: "schedule" } };
  }
  return null;
}

function minutes(hhmm: string): number {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
}

export function inQuiet(p: Pick<NotifyPrefs, "quiet_start" | "quiet_end">, now: Date): boolean {
  if (!p.quiet_start || !p.quiet_end) return false;
  const a = minutes(p.quiet_start), b = minutes(p.quiet_end), t = now.getHours() * 60 + now.getMinutes();
  return a <= b ? a <= t && t < b : t >= a || t < b;
}

export function shouldNotify(p: NotifyPrefs | null, kind: Notice["kind"], visible: boolean, permission: string, now: Date): boolean {
  return !!p && p.browser && !!p.kinds[kind] && !visible && permission === "granted" && !inQuiet(p, now);
}

export function notificationsSupported(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

/** App olay akışına bağlanır: bağlantıdan önceki (geçmiş) olaylar bildirim üretmez. */
export function useBrowserNotifier(navigate: (r: Route) => void, prefsKey: number): (e: KEvent) => void {
  const prefs = useRef<NotifyPrefs | null>(null);
  const since = useRef(Date.now());
  useEffect(() => {
    api<NotifyPrefs>("/api/notifications").then((p) => { prefs.current = p; }).catch(() => undefined);
  }, [prefsKey]);
  return useCallback((e: KEvent) => {
    if (!notificationsSupported()) return;
    if (Date.parse(e.ts.endsWith("Z") || e.ts.includes("+") ? e.ts : `${e.ts}Z`) < since.current - 2000) return;
    const n = eventToNotice(e);
    if (!n || !shouldNotify(prefs.current, n.kind, document.visibilityState === "visible", Notification.permission, new Date())) return;
    try {
      const note = new Notification(`kayaAI · ${n.title}`, { body: n.body, tag: `${n.kind}-${e.id}` });
      note.onclick = () => { window.focus(); navigate(n.route); note.close(); };
    } catch { /* bazı ortamlarda yalnız service worker ile; sessizce geç */ }
  }, [navigate]);
}
