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

// ---------------------------------------------------------------- Asistan (Adım 8)

export interface Conversation {
  id: string;
  created_at: string;
  updated_at: string;
  title: string;
  agent: string;
}

export interface AttachmentRef {
  id: string;
  name: string;
  chars: number;
  kind?: "text" | "pdf" | "table";
}

export interface SubmitResult {
  status: "done" | "awaiting_approval" | "failed";
  risk: string;
  result: { path?: string; bytes?: number } | null;
  approval_id: string | null;
  error: string | null;
  message: string;
}

export type MessageStatus = "done" | "pending" | "running" | "waiting_claude" | "failed" | "cancelled";

export interface ChatMessage {
  id: string;
  conv_id: string;
  created_at: string;
  role: "user" | "assistant";
  content: string;
  status: MessageStatus;
  agent: string;
  job_id: string | null;
  job_kind?: "conductor" | "task" | null;
  reply_to: string | null;
  handoff: boolean;
  attachments: AttachmentRef[];
  warnings: string[];
  recall?: {
    memories?: { id: string; text: string; category: string; sensitivity: string }[];
    sources?: { path: string; name: string; line: number; loc?: string }[];
  };
  meta: {
    memory_saved?: string;
    business?: { kind: "analysis" | "summary" | "invoice" };
    agents?: string[];
    model?: string | null;
    routing?: string | null;
    duration_s?: number | null;
    reviewed?: number;
    revised?: number;
    disputes?: number;
    dropped?: number;
  };
}

export interface ConversationView {
  conversation: Conversation;
  messages: ChatMessage[];
}

// ---------------------------------------------------------------- Hafıza (Adım 9)

export type MemCategory = "preference" | "project" | "decision" | "instruction" | "file" | "note";
export type Sensitivity = "public" | "personal" | "private" | "secret";

export interface MemoryItem {
  id: string;
  created_at: string;
  updated_at: string;
  text: string;
  category: MemCategory;
  sensitivity: Sensitivity;
  status: "active" | "proposed";
  source: string;
  conv_id: string | null;
  embedded: boolean;
  secret_kinds: string[];
  masked?: boolean;
}

export interface DocInfo {
  id: string;
  path: string;
  root: string;
  size: number;
  chunks: number;
  skipped_secret_chunks: number;
  embedded: boolean;
  indexed_at: string;
}

export interface DocumentsView {
  status: { roots: string[]; documents: number; chunks: number; not_embedded: number; last_indexed: string | null; embed_model: string };
  documents: DocInfo[];
}

export interface RecallView {
  memories: { id: string; text: string; category: string; sensitivity: string; score: number }[];
  documents: { chunk_id: string; path: string; name: string; line: number; text: string; score: number }[];
  warnings: string[];
}

// ---------------------------------------------------------------- İş akışı (Adım 11)

export type FlowStatus = "pending" | "running" | "succeeded" | "failed" | "waiting" | "skipped";

export interface FlowNode {
  id: string;
  kind: "request" | "planner" | "step" | "check" | "revise" | "review" | "addendum" | "merge" | "result" | "claude";
  label: string;
  status: FlowStatus;
  agent: string | null;
  model: string | null;
  task_id: string | null;
  duration_s: number | null;
  tokens_per_second: number | null;
  detail: string;
  error: string | null;
  review: { verdict?: string; issues?: number; dropped?: number; revised?: boolean; disputes?: number } | null;
}

export interface JobGraph {
  job_id: string;
  objective: string;
  status: string;
  mode: string | null;
  routing: string | null;
  duration_s: number | null;
  warnings: string[];
  nodes: FlowNode[];
  edges: { source: string; target: string }[];
}

export interface JobSummary {
  id: string;
  objective: string;
  status: string;
  created_at: string;
  duration_s: number | null;
  mode: string | null;
  steps: number;
}

// ---------------------------------------------------------------- model yönetimi (Adım 11)

export interface ModelRow {
  key: string | null;
  name: string;
  status: "active" | "candidate" | "unregistered";
  purpose: string;
  license: string | null;
  approx_vram_gb: number | null;
  installed: boolean | null;
  size_gb: number | null;
  family: string | null;
  parameters: string | null;
  quantization: string | null;
  loaded: { vram_gb: number | null; expires_at: string | null } | null;
  agents: string[];
  embedding: boolean;
}

export interface AgentModelRow {
  name: string;
  model_key: string;
  model_name: string;
  overridden: boolean;
  user_agent: boolean;
  description: string;
  output: "answer" | "review" | "plan";
}

export interface PullState {
  name: string;
  status: string;
  completed: number;
  total: number;
  error: string | null;
}

export interface CompareRow {
  request: string;
  ok: boolean;
  succeeded: boolean;
  missing: string[];
  language_ok: boolean;
  code_ok: boolean;
  foreign_script: boolean;
  seconds: number;
  tokens_per_second: number | null;
  answer_head: string;
}

export interface CompareSide {
  model: string;
  cases: number;
  ok: number;
  avg_seconds: number;
  avg_tokens_per_second: number | null;
}

export interface CompareRecord {
  id: string;
  agent: string;
  current: string;
  candidate: string;
  status: "running" | "done" | "failed";
  started_at: string;
  finished_at?: string;
  error?: string;
  rows: Partial<Record<"current" | "candidate", CompareRow[]>>;
  summary: Partial<Record<"current" | "candidate", CompareSide>>;
  load_seconds?: Partial<Record<"current" | "candidate", number>>;
}

export interface ModelAdmin {
  ollama_reachable: boolean;
  models: ModelRow[];
  agents: AgentModelRow[];
  pulls: PullState[];
  compares: CompareRecord[];
}
