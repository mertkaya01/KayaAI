// kayaAI yerel API istemcisi. Anahtar: `kayaai ui` adresi #token=... ile açar; burada sessionStorage'a alınır
// ve adres çubuğundan silinir (URL parçası sunucuya hiç gitmez). Anahtar yoksa giriş ekranı gösterilir.

const TOKEN_KEY = "kayaai.token";

export function takeTokenFromHash(loc: Location = window.location, hist: History = window.history): string | null {
  const m = /(?:^|[#&])token=([^&]+)/.exec(loc.hash);
  if (!m) return null;
  const token = decodeURIComponent(m[1]);
  setToken(token);
  hist.replaceState(null, "", loc.pathname + loc.search); // anahtar adres çubuğunda/geçmişte kalmasın
  return token;
}

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    sessionStorage.setItem(TOKEN_KEY, token.trim());
  } catch {
    /* gizli pencere vb. — oturum boyunca bellekte kalır */
  }
}

export function clearToken(): void {
  try {
    sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* yok say */
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* gövde JSON değil */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const post = <T,>(path: string, body: unknown = {}) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body) });

export function eventsUrl(token: string, after?: number): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const q = new URLSearchParams({ token });
  // İlk bağlantıda son 50 olay da gelsin; yeniden bağlanırken kaldığı olaydan devam eder.
  if (after !== undefined) q.set("after", String(after));
  else q.set("backlog", "50");
  return `${proto}://${window.location.host}/api/events?${q}`;
}

// ---------------------------------------------------------------- API tipleri (kayaai/api/app.py ile eş)

export interface Health {
  app: string;
  version: string;
  workers: string[];
  ollama: { url: string; reachable: boolean; version?: string; loaded_models?: { name: string; size_vram_gb: number }[] };
  claude: ClaudeStatus | null;
  problems: string[];
}

export interface ClaudeStatus {
  enabled: boolean;
  state: "off" | "on_no_contact" | "on_recent_contact" | "on_stale_contact";
  last_contact: string | null;
  minutes_since_contact: number | null;
  waiting_tasks: number;
  label: string;
}

export interface Gpu {
  name: string;
  utilization_pct: number | null;
  vram_total_mb: number | null;
  vram_used_mb: number | null;
  vram_used_pct: number | null;
}

export interface SystemMetrics {
  cpu_pct: number;
  cpu_logical_cores: number;
  ram_total_gb: number;
  ram_used_gb: number;
  ram_used_pct: number;
  gpus: Gpu[];
  gpu_notes: string[];
  active_tasks: number;
}

export type AgentState = "idle" | "running" | "waiting" | "completed" | "failed";

export interface Agent {
  name: string;
  description: string;
  output: string;
  local_model: string;
  claude_tier: string;
  reviewed_by: string | null;
  checks: string[];
  lifecycle: "permanent" | "temporary";
  base: string | null;
  created_by: string | null;
  uses: number | null;
  successes: number | null;
  status: {
    state: AgentState;
    current_task_id: string | null;
    current_task: string | null;
    result_available: boolean;
    last_finished_at: string | null;
  };
}

export interface Approval {
  id: string;
  created_at: string;
  status: "pending" | "approved" | "rejected" | "expired" | "failed";
  action: {
    tool: string;
    risk: "R0" | "R1" | "R2" | "R3";
    summary: string;
    reason: string;
    preview: Record<string, unknown>;
    undo: string;
    requested_by: string;
  };
  decided_at: string | null;
  decided_by: string | null;
  decision_note: string | null;
  error: string | null;
}

export interface Dispute {
  id: string;
  created_at: string;
  status: "open" | "resolved";
  job_id: string | null;
  step_id: string;
  request: string;
  producer: string;
  reviewer: string;
  issue_id: string;
  severity: string;
  issue: string;
  evidence: string;
  producer_position: string;
  escalated_to: "owner" | "claude";
  resolution: "producer" | "reviewer" | "claude" | "superseded" | null;
  decided_by: string | null;
  decided_at: string | null;
  note: string;
}

export interface KEvent {
  id: number;
  ts: string;
  type: string;
  task_id: string | null;
  data: Record<string, unknown>;
}
