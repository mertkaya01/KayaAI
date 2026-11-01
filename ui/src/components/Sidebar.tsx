import { useState } from "react";
import { post, type AutomationState, type ClaudeStatus, type Health } from "../api";
import { Icon, type IconName } from "../icons";
import type { Route } from "../route";
import { NEXT_THEME, THEME_LABEL, type ThemePref } from "../theme";

/** Sol menü (Adım 16a): sayfalar, canlı durum, Claude modu ve otomasyon anahtarları, tema, daraltma. */

const CLAUDE_TEXT: Record<ClaudeStatus["state"], string> = {
  off: "kapalı",
  on_no_contact: "açık · bağlantı yok",
  on_recent_contact: "açık · bağlı",
  on_stale_contact: "açık · uzun süredir temas yok",
};

type Page = Route["page"];
const ITEMS: { page: Page; label: string; icon: IconName }[] = [
  { page: "today", label: "Bugün", icon: "today" },
  { page: "chat", label: "Asistan", icon: "chat" },
  { page: "flow", label: "Ofis", icon: "office" },
  { page: "memory", label: "Hafıza", icon: "memory" },
  { page: "schedule", label: "Zamanlama", icon: "schedule" },
  { page: "browser", label: "Tarayıcı", icon: "browser" },
  { page: "subtitles", label: "Altyazı", icon: "subtitles" },
  { page: "models", label: "Modeller", icon: "models" },
  { page: "control", label: "Sistem", icon: "system" },
];

function routeFor(page: Page, current: Route): Route {
  if (page === "chat") return { page: "chat", convId: current.page === "chat" ? current.convId : null };
  if (page === "flow") return { page: "flow", jobId: null };
  return { page } as Route;
}

export function Sidebar({
  health, claude, automation, live, route, approvals, theme, collapsed,
  onNavigate, onChanged, onLogout, onTheme, onCollapse,
}: {
  health: Health | null;
  claude: ClaudeStatus | null;
  automation?: AutomationState | null;
  live: boolean;
  route: Route;
  approvals: number;
  theme: ThemePref;
  collapsed: boolean;
  onNavigate: (r: Route) => void;
  onChanged: () => void;
  onLogout: () => void;
  onTheme: (t: ThemePref) => void;
  onCollapse: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try { await fn(); onChanged(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }

  function toggleClaude() {
    if (!claude) return;
    let handback = true;
    if (claude.enabled && claude.waiting_tasks > 0) {
      handback = window.confirm(
        `Claude kutusunda ${claude.waiting_tasks} iş var. Kapatırken bunlar şimdi yerel ekiple yapılsın mı?\n(İptal: işler kutuda bekler)`,
      );
    }
    void run(() => post("/api/claude", { enabled: !claude.enabled, handback }));
  }

  function toggleAutomation() {
    if (!automation) return;
    if (!automation.paused && !window.confirm("Otomasyon duraklatılsın mı?\nZamanlanmış görevler atlanır, tarayıcı işi başlamaz, süren tarayıcı işi durdurulur. Sohbet ve elle yaptıkların etkilenmez.")) return;
    void run(() => post(`/api/automation/${automation.paused ? "resume" : "pause"}`, {}));
  }

  const ollamaOk = health?.ollama.reachable;
  return (
    <aside className="sidebar" aria-label="Menü">
      <div className="brand">
        <span className="logo" aria-hidden>◆</span>
        <h1 className="brand-name">kayaAI</h1>
        {health && <span className="muted ver">v{health.version}</span>}
      </div>
      <nav className="nav" aria-label="Sayfalar">
        {ITEMS.map((it) => (
          <button key={it.page} className="nav-item" aria-current={route.page === it.page ? "page" : undefined}
                  title={collapsed ? it.label : undefined} aria-label={collapsed ? it.label : undefined}
                  onClick={() => onNavigate(routeFor(it.page, route))}>
            <Icon name={it.icon} />
            <span className="nav-label">{it.label}</span>
            {it.page === "today" && approvals > 0 && <span className="nav-badge" aria-label={`${approvals} onay bekliyor`}>{approvals}</span>}
          </button>
        ))}
      </nav>

      <div className="side-foot">
        <div className="side-status">
          <div className="line" title="Canlı olay akışı"><span className={`led ${live ? "ok" : "bad"}`} /><span>{live ? "Canlı" : "Bağlantı yok"}</span></div>
          <div className="line"><span className={`led ${ollamaOk ? "ok" : "bad"}`} /><span>Ollama {ollamaOk ? health?.ollama.version : "erişilemiyor"}</span></div>
          {claude && (
            <button className="switch-row" disabled={busy} onClick={toggleClaude} role="switch" aria-checked={claude.enabled}
                    title={claude.label}>
              <span>Claude <span className="muted">{CLAUDE_TEXT[claude.state]}{claude.waiting_tasks > 0 ? ` · kutuda ${claude.waiting_tasks}` : ""}</span></span>
              <span className={`switch${claude.enabled ? " on" : ""}`} aria-hidden="true" />
            </button>
          )}
          {automation && (
            <button className="switch-row" disabled={busy} onClick={toggleAutomation} role="switch" aria-checked={!automation.paused}
                    title={automation.paused ? `Duraklatıldı${automation.at ? ` (${automation.at})` : ""}` : "Zamanlanmış görevler ve tarayıcı işleri"}>
              <span>Otomasyon <span className={automation.paused ? "error" : "muted"}>{automation.paused ? "duraklatıldı" : "açık"}</span></span>
              <span className={`switch${automation.paused ? "" : " on"}`} aria-hidden="true" />
            </button>
          )}
          {error && <p className="error small">{error}</p>}
        </div>
        <div className="icon-row">
          <button className="icon-btn" onClick={() => onTheme(NEXT_THEME[theme])} title={THEME_LABEL[theme]} aria-label={`${THEME_LABEL[theme]} (değiştir)`}>
            <Icon name={theme === "light" ? "sun" : theme === "dark" ? "moon" : "auto"} />
          </button>
          <button className="icon-btn" onClick={onCollapse} title={collapsed ? "Menüyü genişlet" : "Menüyü daralt"} aria-label={collapsed ? "Menüyü genişlet" : "Menüyü daralt"}>
            <Icon name={collapsed ? "expand" : "collapse"} />
          </button>
          <button className="icon-btn" onClick={onLogout} title="Çıkış (anahtarı bu sekmeden sil)" aria-label="Çıkış">
            <Icon name="logout" />
          </button>
        </div>
      </div>
    </aside>
  );
}
