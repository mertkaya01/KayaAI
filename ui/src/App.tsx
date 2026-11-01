import { useCallback, useEffect, useState } from "react";
import { clearToken, getToken, setToken, takeTokenFromHash, type Agent, type Approval, type AutomationState, type ClaudeStatus, type Dispute, type Health, type KEvent, type SystemMetrics } from "./api";
import { AgentsPanel } from "./components/AgentsPanel";
import { ApprovalsPanel } from "./components/ApprovalsPanel";
import { ChatView } from "./components/ChatView";
import { DisputesPanel } from "./components/DisputesPanel";
import { EventsPanel } from "./components/EventsPanel";
import { IntegrationsPanel } from "./components/IntegrationsPanel";
import { FlowView } from "./components/FlowView";
import { MemoryView } from "./components/MemoryView";
import { ModelsView } from "./components/ModelsView";
import { SubtitlesView } from "./components/SubtitlesView";
import { BrowserView } from "./components/BrowserView";
import { ScheduleView } from "./components/ScheduleView";
import { SystemPanel } from "./components/SystemPanel";
import { Sidebar } from "./components/Sidebar";
import { TodayView } from "./components/TodayView";
import { NotificationsPanel } from "./components/NotificationsPanel";
import { CloudPanel } from "./components/CloudPanel";
import { Icon } from "./icons";
import { useBrowserNotifier } from "./notify";
import { readPref, useTheme, writePref } from "./theme";
import { useEvents, usePolling } from "./hooks";
import { useRoute } from "./route";
import { ingestProgress } from "./office/progress";

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

interface Keys {
  agents: number;
  approvals: number;
  disputes: number;
}

/** Kontrol Merkezi sayfası: yalnızca açıkken veri çeker (sohbet ekranında sistem metrikleri yoklanmaz). */
function ControlCenter({ keys, bump, events, health, onUnauthorized, notifyKey, onNotifyChanged }: {
  keys: Keys;
  bump: (k: keyof Keys) => void;
  events: KEvent[];
  health: Health | null;
  onUnauthorized: () => void;
  notifyKey: number;
  onNotifyChanged: () => void;
}) {
  const system = usePolling<SystemMetrics>("/api/system", 2000);
  const agents = usePolling<Agent[]>("/api/agents", 5000, keys.agents);
  const pending = usePolling<Approval[]>("/api/approvals?status=pending", 10000, keys.approvals);
  const history = usePolling<Approval[]>("/api/approvals?status=all", 15000, keys.approvals);
  const openDisputes = usePolling<Dispute[]>("/api/disputes?status=open", 10000, keys.disputes);
  const disputeHistory = usePolling<Dispute[]>("/api/disputes?status=all", 15000, keys.disputes);
  const unauthorized = [system, agents, pending].some((p) => p.unauthorized);
  useEffect(() => {
    if (unauthorized) onUnauthorized();
  }, [unauthorized, onUnauthorized]);
  return (
      <main className="grid">
        <div className="col">
          <SystemPanel metrics={system.data} health={health} />
          <ApprovalsPanel pending={pending.data} history={history.data} onChanged={() => bump("approvals")} />
          <DisputesPanel open={openDisputes.data} history={disputeHistory.data} onChanged={() => bump("disputes")} />
          <IntegrationsPanel refreshKey={keys.approvals} />
          <CloudPanel refreshKey={keys.approvals} />
          <NotificationsPanel refreshKey={notifyKey} onChanged={onNotifyChanged} />
        </div>
        <div className="col">
          <AgentsPanel agents={agents.data} error={agents.error} onChanged={() => { bump("agents"); bump("approvals"); }} />
          <EventsPanel events={events} />
        </div>
      </main>
  );
}

function Dashboard({ token, onUnauthorized, onLogout }: { token: string; onUnauthorized: () => void; onLogout: () => void }) {
  const [route, navigate] = useRoute();
  const [keys, setKeys] = useState<Keys>({ agents: 0, approvals: 0, disputes: 0 });
  const [claudeKey, setClaudeKey] = useState(0);
  const [chatKey, setChatKey] = useState(0);
  const [memoryKey, setMemoryKey] = useState(0);
  const [flowKey, setFlowKey] = useState(0);
  const [modelsKey, setModelsKey] = useState(0);
  const [scheduleKey, setScheduleKey] = useState(0);
  const [events, setEvents] = useState<KEvent[]>([]);
  const [todayKey, setTodayKey] = useState(0);
  const [notifyKey, setNotifyKey] = useState(0);
  const [theme, setTheme] = useTheme();
  const [collapsed, setCollapsed] = useState(() => readPref("kayaai.sidebar") === "collapsed");
  const [drawer, setDrawer] = useState(false);
  const notify = useBrowserNotifier(navigate, notifyKey);
  const pendingApprovals = usePolling<Approval[]>("/api/approvals?status=pending", 20000, keys.approvals);
  const bump = useCallback((k: keyof Keys) => setKeys((p) => ({ ...p, [k]: p[k] + 1 })), []);

  const health = usePolling<Health>("/api/health", 5000, claudeKey);
  const claude = usePolling<ClaudeStatus>("/api/claude", 5000, claudeKey);
  const automation = usePolling<AutomationState>("/api/automation", 15000, claudeKey);

  const unauthorized = [health, claude].some((p) => p.unauthorized);
  useEffect(() => {
    if (unauthorized) onUnauthorized();
  }, [unauthorized, onUnauthorized]);

  const onEvent = useCallback((e: KEvent) => {
    if (ingestProgress(e)) return;  // canlı ilerleme (Adım 15): yalnız ofis için, olay listesine girmez
    setEvents((prev) => [e, ...prev].slice(0, 50));
    notify(e);
    if (/^(approval|schedule|chat|automation|claude)\./.test(e.type) || (e.type === "task.status" && e.data.worker === "conductor")) setTodayKey((k) => k + 1);
    if (e.type === "notify.prefs") setNotifyKey((k) => k + 1);
    if (e.type === "task.status" || e.type.startsWith("agent.")) bump("agents");
    if (e.type.startsWith("approval.") || e.type === "tool.used") bump("approvals");
    if (e.type.startsWith("dispute.")) bump("disputes");
    if (e.type.startsWith("memory.")) setMemoryKey((k) => k + 1);
    if (e.type === "task.status" || e.type === "decision.summary") setFlowKey((k) => k + 1);
    if (e.type.startsWith("model.") || e.type === "agent.model_changed") setModelsKey((k) => k + 1);
    if (e.type.startsWith("schedule.") || e.type === "approval.decided") setScheduleKey((k) => k + 1);
    if (e.type.startsWith("chat.") || (e.type === "task.status" && e.data.worker === "conductor")) setChatKey((k) => k + 1);
    if (e.type.startsWith("automation.")) setClaudeKey((k) => k + 1);
    if (e.type === "claude.mode" || (e.type === "task.status" && e.data.status === "waiting_claude")) setClaudeKey((k) => k + 1);
  }, [bump, notify]);
  const live = useEvents(token, onEvent);
  const go = (r: Parameters<typeof navigate>[0]) => { setDrawer(false); navigate(r); };

  return (
    <>
      <a className="skip-link" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById("main")?.focus(); }}>İçeriğe atla</a>
      <div className={`shell${collapsed ? " collapsed" : ""}${drawer ? " drawer" : ""}`}>
      <Sidebar
        health={health.data}
        claude={claude.data}
        automation={automation.data}
        live={live}
        route={route}
        approvals={pendingApprovals.data?.length ?? 0}
        theme={theme}
        collapsed={collapsed}
        onNavigate={go}
        onChanged={() => setClaudeKey((k) => k + 1)}
        onLogout={onLogout}
        onTheme={setTheme}
        onCollapse={() => setCollapsed((c) => { writePref("kayaai.sidebar", c ? "open" : "collapsed"); return !c; })}
      />
      {drawer && <div className="scrim" onClick={() => setDrawer(false)} aria-hidden="true" />}
      <div className="content">
      <div className="mobile-bar">
        <button className="icon-btn" onClick={() => setDrawer(true)} aria-label="Menüyü aç"><Icon name="menu" /></button>
        <strong>kayaAI</strong>
      </div>
      <div id="main" tabIndex={-1}>
      {route.page === "today" ? (
        <TodayView refreshKey={todayKey} flowKey={flowKey} approvalsKey={keys.approvals} onNavigate={go}
                   onPrefsChanged={() => setNotifyKey((k) => k + 1)} />
      ) : route.page === "chat" ? (
        <ChatView
          convId={route.convId}
          onSelect={(id) => navigate({ page: "chat", convId: id })}
          onOpenMemory={() => go({ page: "memory" })}
          onOpenFlow={(jobId) => go({ page: "flow", jobId })}
          refreshKey={chatKey}
          flowKey={flowKey}
          approvalsKey={keys.approvals}
          claude={claude.data}
        />
      ) : route.page === "memory" ? (
        <MemoryView refreshKey={memoryKey} />
      ) : route.page === "schedule" ? (
        <ScheduleView refreshKey={scheduleKey} />
      ) : route.page === "browser" ? (
        <BrowserView />
      ) : route.page === "subtitles" ? (
        <SubtitlesView />
      ) : route.page === "models" ? (
        <ModelsView refreshKey={modelsKey} events={events} />
      ) : route.page === "flow" ? (
        <FlowView jobId={route.jobId} onSelect={(id) => navigate({ page: "flow", jobId: id })} refreshKey={flowKey} approvalsKey={keys.approvals} />
      ) : (
        <ControlCenter keys={keys} bump={bump} events={events} health={health.data} onUnauthorized={onUnauthorized}
                       notifyKey={notifyKey} onNotifyChanged={() => setNotifyKey((k) => k + 1)} />
      )}
      </div>
      </div>
      </div>
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
