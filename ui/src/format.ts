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
    default:
      return e.type;
  }
}

/** Grafik için kayan pencere: son `max` değeri tutar. */
export function pushSample(series: number[], value: number, max = 60): number[] {
  const next = [...series, value];
  return next.length > max ? next.slice(next.length - max) : next;
}
