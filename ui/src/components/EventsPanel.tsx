import type { KEvent } from "../api";
import { describeEvent } from "../format";

export function EventsPanel({ events }: { events: KEvent[] }) {
  return (
    <section className="panel" aria-labelledby="ev-title">
      <h2 id="ev-title">Canlı olaylar</h2>
      {events.length === 0 ? (
        <p className="muted">Henüz olay yok. Bir görev çalıştırın (ör. <code>kayaai ask "Merhaba"</code>).</p>
      ) : (
        <ol className="events">
          {events.map((e) => (
            <li key={e.id} className={`ev ev-${e.type.split(".")[0]}`}>
              <time className="muted">{new Date(e.ts).toLocaleTimeString("tr-TR")}</time>
              <span>{describeEvent(e)}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
