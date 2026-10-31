import { useCallback, useEffect, useState } from "react";
import { clearToken, getToken, setToken, takeTokenFromHash, type Agent, type Approval, type ClaudeStatus, type Dispute, type Health, type KEvent, type SystemMetrics } from "./api";
import { AgentsPanel } from "./components/AgentsPanel";
import { ApprovalsPanel } from "./components/ApprovalsPanel";
import { DisputesPanel } from "./components/DisputesPanel";
import { EventsPanel } from "./components/EventsPanel";
import { SystemPanel } from "./components/SystemPanel";
import { TopBar } from "./components/TopBar";
import { useEvents, usePolling } from "./hooks";

function Login({ onToken, failed }: { onToken: (t: string) => void; failed: boolean }) {
  const [value, setValue] = useState("");
  return (
    <main className="login">
      <h1>kayaAI Control Center</h1>
      <p>Bu arayüz yalnızca bu bilgisayarda çalışan kayaAI'ye bağlanır.</p>
      <p className="muted">
        En kolayı: terminalde <code>kayaai ui</code> çalıştırın (tarayıcıyı anahtarla açar). Ya da{" "}
        <code>kayaai api token</code> çıktısını buraya yapıştırın:
      </p>
      {failed && <p className="error">Anahtar geçersiz. Lütfen tekrar deneyin.</p>}
      <form onSubmit={(e) => { e.preventDefault(); if (value.trim()) onToken(value.trim()); }}>
        <input type="password" autoFocus placeholder="Erişim anahtarı" value={value} onChange={(e) => setValue(e.target.value)} aria-label="Erişim anahtarı" />
        <button type="submit">Bağlan</button>
      </form>
    </main>
  );
}

function Dashboard({ token, onUnauthorized, onLogout }: { token: string; onUnauthorized: () => void; onLogout: () => void }) {
  const [agentsKey, setAgentsKey] = useState(0);
  const [approvalsKey, setApprovalsKey] = useState(0);
  const [claudeKey, setClaudeKey] = useState(0);
  const [disputesKey, setDisputesKey] = useState(0);
  const [events, setEvents] = useState<KEvent[]>([]);

  const health = usePolling<Health>("/api/health", 5000, claudeKey);
  const system = usePolling<SystemMetrics>("/api/system", 2000);
  const agents = usePolling<Agent[]>("/api/agents", 5000, agentsKey);
  const claude = usePolling<ClaudeStatus>("/api/claude", 5000, claudeKey);
  const pending = usePolling<Approval[]>("/api/approvals?status=pending", 10000, approvalsKey);
  const history = usePolling<Approval[]>("/api/approvals?status=all", 15000, approvalsKey);
  const openDisputes = usePolling<Dispute[]>("/api/disputes?status=open", 10000, disputesKey);
  const disputeHistory = usePolling<Dispute[]>("/api/disputes?status=all", 15000, disputesKey);

  const unauthorized = [health, system, agents, claude, pending].some((p) => p.unauthorized);
  useEffect(() => {
    if (unauthorized) onUnauthorized();
  }, [unauthorized, onUnauthorized]);

  const onEvent = useCallback((e: KEvent) => {
    setEvents((prev) => [e, ...prev].slice(0, 50));
    if (e.type === "task.status" || e.type.startsWith("agent.")) setAgentsKey((k) => k + 1);
    if (e.type.startsWith("approval.") || e.type === "tool.used") setApprovalsKey((k) => k + 1);
    if (e.type.startsWith("dispute.")) setDisputesKey((k) => k + 1);
    if (e.type === "claude.mode" || (e.type === "task.status" && e.data.status === "waiting_claude")) setClaudeKey((k) => k + 1);
  }, []);
  const live = useEvents(token, onEvent);

  return (
    <>
      <TopBar
        health={health.data}
        claude={claude.data}
        live={live}
        onChanged={() => setClaudeKey((k) => k + 1)}
        onLogout={onLogout}
      />
      <main className="grid">
        <div className="col">
          <SystemPanel metrics={system.data} health={health.data} />
          <ApprovalsPanel pending={pending.data} history={history.data} onChanged={() => setApprovalsKey((k) => k + 1)} />
          <DisputesPanel open={openDisputes.data} history={disputeHistory.data} onChanged={() => setDisputesKey((k) => k + 1)} />
        </div>
        <div className="col">
          <AgentsPanel agents={agents.data} error={agents.error} onChanged={() => { setAgentsKey((k) => k + 1); setApprovalsKey((k) => k + 1); }} />
          <EventsPanel events={events} />
        </div>
      </main>
    </>
  );
}

export default function App({ initialToken }: { initialToken: string | null }) {
  const [token, setTokenState] = useState<string | null>(initialToken ?? getToken());
  const [failed, setFailed] = useState(false);
  const onUnauthorized = useCallback(() => { clearToken(); setFailed(true); setTokenState(null); }, []);

  // Sekme zaten açıkken `kayaai ui` yeni anahtarlı adresi aynı sekmede açarsa (yalnızca #token= değişir) yakala.
  useEffect(() => {
    const onHash = () => {
      const t = takeTokenFromHash();
      if (t) { setFailed(false); setTokenState(t); }
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  if (!token) {
    return <Login failed={failed} onToken={(t) => { setToken(t); setFailed(false); setTokenState(t); }} />;
  }
  return (
    <Dashboard
      key={token}
      token={token}
      onUnauthorized={onUnauthorized}
      onLogout={() => { clearToken(); setFailed(false); setTokenState(null); }}
    />
  );
}
