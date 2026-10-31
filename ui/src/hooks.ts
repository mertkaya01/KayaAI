import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, eventsUrl, type KEvent } from "./api";

/** `path`'i `intervalMs`'de bir çeker; `refreshKey` değişince hemen yeniden çeker. */
export function usePolling<T>(path: string, intervalMs: number, refreshKey: unknown = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [unauthorized, setUnauthorized] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await api<T>(path));
      setError(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setUnauthorized(true);
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [path]);

  useEffect(() => {
    void load();
    if (intervalMs <= 0) return;
    const id = window.setInterval(() => void load(), intervalMs);
    return () => window.clearInterval(id);
  }, [load, intervalMs, refreshKey]);

  return { data, error, unauthorized, reload: load };
}

/** Canlı olay akışı (WS /api/events). Koparsa 2 sn sonra kaldığı olaydan devam eder. */
export function useEvents(token: string | null, onEvent: (e: KEvent) => void) {
  const [connected, setConnected] = useState(false);
  const lastId = useRef<number | undefined>(undefined);
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    if (!token) return;
    let ws: WebSocket | null = null;
    let stopped = false;
    let retry: number | undefined;

    const open = () => {
      ws = new WebSocket(eventsUrl(token, lastId.current));
      ws.onopen = () => setConnected(true);
      ws.onmessage = (msg) => {
        const ev = JSON.parse(msg.data) as KEvent;
        lastId.current = ev.id;
        handler.current(ev);
      };
      ws.onclose = () => {
        setConnected(false);
        if (!stopped) retry = window.setTimeout(open, 2000);
      };
    };
    open();
    return () => {
      stopped = true;
      window.clearTimeout(retry);
      ws?.close();
    };
  }, [token]);

  return connected;
}
