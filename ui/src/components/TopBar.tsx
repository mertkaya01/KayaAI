import { useState } from "react";
import { post, type ClaudeStatus, type Health } from "../api";

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
  onChanged,
  onLogout,
}: {
  health: Health | null;
  claude: ClaudeStatus | null;
  live: boolean;
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
        <span className="muted">Control Center</span>
        {health && <span className="muted ver">v{health.version}</span>}
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
