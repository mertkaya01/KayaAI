import type { AgentState, KEvent } from "./api";

export const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${Math.round(v)}%`);

export function gb(mb: number | null | undefined): string {
  if (mb === null || mb === undefined) return "—";
  return `${(mb / 1024).toFixed(1)} GB`;
}

export function ago(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "—";
  const s = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s} sn önce`;
  if (s < 3600) return `${Math.floor(s / 60)} dk önce`;
  if (s < 86400) return `${Math.floor(s / 3600)} sa önce`;
  return `${Math.floor(s / 86400)} gün önce`;
}

export const STATE_LABEL: Record<AgentState, string> = {
  idle: "Boşta",
  running: "Çalışıyor",
  waiting: "Bekliyor",
  completed: "Tamamlandı",
  failed: "Başarısız",
};

export const RISK_LABEL: Record<string, string> = {
  R0: "R0 · güvenli",
  R1: "R1 · düşük",
  R2: "R2 · riskli",
  R3: "R3 · kritik",
};

export const APPROVAL_STATUS_LABEL: Record<string, string> = {
  pending: "Bekliyor",
  approved: "Onaylandı",
  rejected: "Reddedildi",
  expired: "Süresi doldu",
  failed: "Çalıştırılamadı",
};

export const MEM_CATEGORY_LABEL: Record<string, string> = {
  preference: "tercih",
  project: "proje",
  decision: "karar",
  instruction: "talimat",
  file: "dosya",
  note: "not",
};

export const SENSITIVITY_LABEL: Record<string, string> = {
  public: "herkese açık",
  personal: "kişisel",
  private: "özel",
  secret: "gizli",
};

export const DISPUTE_RESOLUTION_LABEL: Record<string, string> = {
  producer: "üretici haklı bulundu",
  reviewer: "gözden geçirici haklı bulundu",
  claude: "Claude karar verdi",
  superseded: "iş yeniden yapıldı",
};

const TASK_STATUS: Record<string, string> = {
  pending: "sıraya alındı",
  running: "çalışıyor",
  succeeded: "tamamlandı",
  failed: "başarısız",
  cancelled: "iptal edildi",
  timed_out: "zaman aşımı",
  rejected: "reddedildi",
  awaiting_approval: "onay bekliyor",
  waiting_claude: "Claude kutusunda",
};

/** Olay akışındaki bir olayı tek satırlık Türkçe metne çevirir. */
export function describeEvent(e: KEvent): string {
  const d = e.data as Record<string, string | boolean | null | undefined>;
  switch (e.type) {
    case "task.status":
      return `${d.worker} · ${TASK_STATUS[String(d.status)] ?? d.status}${d.objective ? ` — ${String(d.objective).slice(0, 80)}` : ""}`;
    case "approval.requested":
      return `Onay istendi (${d.risk}): ${d.summary}`;
    case "approval.decided":
      return `Onay kararı: ${APPROVAL_STATUS_LABEL[String(d.status)] ?? d.status}${d.decided_by ? ` (${d.decided_by})` : ""}`;
    case "tool.used":
      return `Araç kullanıldı (${d.risk}): ${d.summary ?? d.tool}`;
    case "tool.failed":
      return `Araç başarısız: ${d.tool} — ${d.error}`;
    case "claude.mode":
      return d.enabled ? "Claude modu açıldı" : "Claude modu kapatıldı";
    case "memory.added":
      return `Hafızaya eklendi (${MEM_CATEGORY_LABEL[String(d.category)] ?? d.category}, ${SENSITIVITY_LABEL[String(d.sensitivity)] ?? d.sensitivity})${d.status === "proposed" ? " — onay bekliyor" : ""}`;
    case "memory.updated":
      return d.status === "active" ? "Hafıza önerisi onaylandı" : "Hafıza öğesi güncellendi";
    case "memory.deleted":
      return "Hafıza öğesi silindi";
    case "memory.indexed":
      return `Belgeler dizinlendi: ${d.indexed} dosya işlendi, toplam ${d.chunks} parça${d.embed_available ? "" : " (anlam araması yok: bge-m3 kurulu değil)"}`;
    case "agent.created":
      return `Yeni geçici ajan: ${d.name} (temel: ${d.base}, oluşturan: ${d.created_by})`;
    case "agent.promoted":
      return `Ajan kalıcı yapıldı: ${d.name}`;
    case "agent.removed":
      return `Geçici ajan kaldırıldı: ${d.name}`;
    case "dispute.opened":
      return `Anlaşmazlık: ${d.producer} ↔ ${d.reviewer} — ${d.issue}${d.escalated_to === "claude" ? " (Claude'a)" : " (sana)"}`;
    case "dispute.resolved":
      return `Anlaşmazlık kapandı: ${DISPUTE_RESOLUTION_LABEL[String(d.resolution)] ?? d.resolution}`;
    case "decision.summary":
      return `İş bitti (${TASK_STATUS[String(d.status)] ?? d.status}): ${d.steps} adım, ${d.reviewed_steps} gözden geçirme`
        + `${Number(d.revised_steps) ? `, ${d.revised_steps} düzeltme` : ""}${Number(d.disputes) ? `, ${d.disputes} anlaşmazlık` : ""}`;
    case "model.loaded":
      return `Model belleğe yüklendi: ${d.name}`;
    case "model.unloaded":
      return `Model bellekten çıkarıldı: ${d.name}`;
    case "model.pull":
      return `Model indirme · ${d.name}: ${d.status}${d.percent != null ? ` (%${d.percent})` : ""}${d.error ? ` — ${d.error}` : ""}`;
    case "model.activated":
      return `Aday model aktif yapıldı: ${d.name}`;
    case "model.compare":
      return d.status ? `Model karşılaştırma ${d.status === "done" ? "bitti" : d.status === "failed" ? "başarısız" : "başladı"}`
        : `Model karşılaştırma: ${d.done}/${d.total}`;
    case "integration.enabled":
      return `Dış veri kaynağı açıldı: ${d.name}`;
    case "integration.disabled":
      return `Dış veri kaynağı kapatıldı: ${d.name}`;
    case "integration.call":
      return `Dış istek (${d.name} → ${d.host}): ${d.ok ? "başarılı" : `başarısız — ${d.error}`}`;
    case "automation.paused":
      return `Otomasyon duraklatıldı (${d.by})${d.reason ? `: ${d.reason}` : ""}`;
    case "automation.resumed":
      return `Otomasyon sürdürüldü (${d.by})`;
    case "schedule.run":
      return `Zamanlanmış görev · ${d.name}: ${({ running: "çalışıyor", succeeded: "başarılı", failed: "başarısız", skipped: "atlandı" } as Record<string, string>)[String(d.status)] ?? d.status}${d.seconds != null ? ` (${d.seconds} sn)` : ""}`;
    case "schedule.created":
      return `Zamanlanmış görev eklendi: ${d.name}${d.registered ? " (Windows'a kaydedildi)" : ""}`;
    case "schedule.deleted":
      return `Zamanlanmış görev silindi: ${d.name}`;
    case "browser.step":
      return `Tarayıcı ${d.n}. adım [${d.risk}] ${d.description} — ${d.status}`;
    case "speech.live":
      return d.status === "started" ? "Canlı altyazı başladı" : `Canlı altyazı bitti (${d.lines} satır, ${d.reason})`;
    case "speech.download":
      return `Ses modeli indirme · ${d.model}: ${d.status}${d.percent != null ? ` (%${d.percent})` : ""}${d.error ? ` — ${d.error}` : ""}`;
    case "speech.transcribed":
      return `Konuşma yazıya çevrildi (${d.audio_seconds} sn ses, ${d.device})`;
    case "agent.model_changed":
      return `Ajanın modeli değişti: ${d.name} → ${d.model_key}`;
    default:
      return e.type;
  }
}

/** Grafik için kayan pencere: son `max` değeri tutar. */
export function pushSample(series: number[], value: number, max = 60): number[] {
  const next = [...series, value];
  return next.length > max ? next.slice(next.length - max) : next;
}

/** Gelecek zaman: "bugün 09:00", "yarın 09:00", "Pzt 09:00", "3 Ara 09:00" (Adım 16b). */
export function when(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(d) - day(now)) / 86400000);
  if (diff === 0) return `bugün ${hm}`;
  if (diff === 1) return `yarın ${hm}`;
  if (diff === -1) return `dün ${hm}`;
  if (diff > 1 && diff < 7) return `${["Paz", "Pzt", "Sal", "Çar", "Per", "Cum", "Cmt"][d.getDay()]} ${hm}`;
  return `${d.getDate()} ${["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"][d.getMonth()]} ${hm}`;
}

/** Sohbet listesi grupları: Bugün, Dün, Bu hafta, Bu ay, Daha eski (Adım 18a). Sıra korunur. */
export function groupByDate<T extends { updated_at: string }>(items: T[], now: Date = new Date()): { label: string; items: T[] }[] {
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const today = day(now);
  const label = (iso: string) => {
    const diff = Math.round((today - day(new Date(iso))) / 86400000);
    if (diff <= 0) return "Bugün";
    if (diff === 1) return "Dün";
    if (diff < 7) return "Bu hafta";
    if (diff < 31) return "Bu ay";
    return "Daha eski";
  };
  const out: { label: string; items: T[] }[] = [];
  for (const it of items) {
    const l = label(it.updated_at);
    const last = out[out.length - 1];
    if (last && last.label === l) last.items.push(it);
    else out.push({ label: l, items: [it] });
  }
  return out;
}
