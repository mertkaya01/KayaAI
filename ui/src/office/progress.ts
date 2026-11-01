// Canlı ilerleme deposu: App olay akışındaki task.progress olaylarını tutar; ofis bileşenleri abone olur.
import { useSyncExternalStore } from "react";
import type { KEvent } from "../api";
import type { Progress } from "./scene";

let state: Record<string, Progress> = {};
const listeners = new Set<() => void>();

function emit(): void {
  for (const l of listeners) l();
}

/** task.progress → kaydet; task.status (bitti) → sil. Diğer olaylar yok sayılır. True: olay ilerleme olayıydı. */
export function ingestProgress(e: KEvent): boolean {
  if (e.type === "task.progress" && e.task_id) {
    const d = e.data as Partial<Progress> & { text?: string };
    const prev = state[e.task_id];
    const field = (d.field as string | null) ?? null;
    const attempt = Number(d.attempt ?? 1);
    // cevap alanı yazılırken metni tut; model sonraki alana geçince son hâli kalır; yeni denemede sıfırlanır
    const answer = field === "answer" || field === null ? String(d.text ?? d.tail ?? "")
      : prev && prev.attempt === attempt ? prev.answer : undefined;
    state = { ...state, [e.task_id]: { task_id: e.task_id, worker: String(d.worker ?? ""), chars: Number(d.chars ?? 0),
                                       field, tail: String(d.tail ?? ""), attempt, at: Date.now(),
                                       parent_id: (d.parent_id as string | null | undefined) ?? null, answer } };
    emit();
    return true;
  }
  if (e.type === "task.status" && e.task_id && state[e.task_id] && !["running", "pending"].includes(String(e.data.status))) {
    const { [e.task_id]: _gone, ...rest } = state;
    state = rest;
    emit();
  }
  return false;
}

export function useProgress(): Record<string, Progress> {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => state);
}

export function resetProgress(): void {
  state = {};
  emit();
}
