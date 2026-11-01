import { useState } from "react";
import { post, type ClaudeStatus, type Health } from "../api";
import type { Route } from "../route";

const CLAUDE_TEXT: Record<ClaudeStatus["state"], string> = {
  off: "Claude kapalı",
  on_no_contact: "Claude açık · bağlantı yok",
  on_recent_contact: "Claude açık · bağlı",
  on_stale_contact: "Claude açık · uzun süredir temas yok",
};

export function TopBar({
  health,
  claude,
  live,
  route,
  onNavigate,
  onChanged,
  onLogout,
}: {
  health: Health | null;
  claude: ClaudeStatus | null;
  live: boolean;
  route: Route;
  onNavigate: (r: Route) => void;
  onChanged: () => void;
  onLogout: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle() {
    if (!claude) return;
    let handback = true;
    if (claude.enabled && claude.waiting_tasks > 0) {
      handback = window.confirm(
        `Claude kutusunda ${claude.waiting_tasks} iş var. Kapatırken bunlar şimdi yerel ekiple yapılsın mı?\n(İptal: işler kutuda bekler)`,
      );
    }
    setBusy(true);
    setError(null);
    try {
      await post("/api/claude", { enabled: !claude.enabled, handback });
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const ollamaOk = health?.ollama.reachable;
  return (
    <header className="topbar">
      <div className="brand">
        <span className="logo" aria-hidden>◆</span>
        <strong>kayaAI</strong>
        {health && <span className="muted ver">v{health.version}</span>}
        <nav className="tabs main-tabs" aria-label="Sayfalar">
          <button aria-selected={route.page === "chat"} onClick={() => onNavigate({ page: "chat", convId: route.page === "chat" ? route.convId : null })}>
            Asistan
          </button>
          <button aria-selected={route.page === "memory"} onClick={() => onNavigate({ page: "memory" })}>
            Hafıza
          </button>
          <button aria-selected={route.page === "flow"} onClick={() => onNavigate({ page: "flow", jobId: null })}>
            Akış
          </button>
          <button aria-selected={route.page === "subtitles"} onClick={() => onNavigate({ page: "subtitles" })}>
            Altyazı
          </button>
          <button aria-selected={route.page === "browser"} onClick={() => onNavigate({ page: "browser" })}>
            Tarayıcı
          </button>
          <button aria-selected={route.page === "schedule"} onClick={() => onNavigate({ page: "schedule" })}>
            Zamanlama
          </button>
          <button aria-selected={route.page === "models"} onClick={() => onNavigate({ page: "models" })}>
            Modeller
          </button>
          <button aria-selected={route.page === "control"} onClick={() => onNavigate({ page: "control" })}>
            Kontrol Merkezi
          </button>
        </nav>
      </div>
      <div className="status">
        <span className={`pill ${live ? "ok" : "bad"}`} title="Canlı olay akışı">{live ? "● Canlı" : "○ Bağlantı yok"}</span>
        <span className={`pill ${ollamaOk ? "ok" : "bad"}`}>
          Ollama {ollamaOk ? health?.ollama.version : "erişilemiyor"}
        </span>
        {claude && (
          <span className={`pill ${claude.enabled ? (claude.state === "on_recent_contact" ? "ok" : "warn") : ""}`} title={claude.label}>
            {CLAUDE_TEXT[claude.state]}
            {claude.waiting_tasks > 0 && ` · kutuda ${claude.waiting_tasks}`}
          </span>
        )}
        <button className="toggle" disabled={!claude || busy} onClick={() => void toggle()}>
          {claude?.enabled ? "Claude'u kapat" : "Claude'u aç"}
        </button>
        <button className="ghost" onClick={onLogout} title="Anahtarı bu sekmeden sil">Çıkış</button>
      </div>
      {error && <p className="error">{error}</p>}
    </header>
  );
}
