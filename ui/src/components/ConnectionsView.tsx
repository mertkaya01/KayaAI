import { AgentCloudPanel } from "./AgentCloudPanel";
import { IntegrationsPanel } from "./IntegrationsPanel";
import { ProvidersPanel } from "./ProvidersPanel";

/** Bağlantılar (Adım 22): dış LLM sağlayıcıları (API anahtarları), ajan → dış model, dış veri kaynakları — tek yerde. */
export function ConnectionsView({ refreshKey }: { refreshKey: number }) {
  return (
    <main className="grid">
      <div className="col">
        <ProvidersPanel refreshKey={refreshKey} />
      </div>
      <div className="col">
        <AgentCloudPanel />
        <IntegrationsPanel refreshKey={refreshKey} />
      </div>
    </main>
  );
}
