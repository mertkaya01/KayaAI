import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { getToken, post, type SubmitResult } from "../api";

type Source = "system" | "mic";
interface Line { id: number; text: string; translation: string | null; lang: string | null; start: number; end: number; latency_s: number }
type Msg =
  | { type: "partial"; text: string }
  | ({ type: "final" } & Line)
  | { type: "status"; status: string; device?: string | null; reason?: string }
  | { type: "error"; message: string; fatal?: boolean };

const LANG: Record<string, string> = { tr: "Türkçe", en: "İngilizce", de: "Almanca", fr: "Fransızca", es: "İspanyolca", ru: "Rusça", ar: "Arapça" };
const MAX_S = 2 * 3600;

function liveUrl(token: string): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/api/speech/live?${new URLSearchParams({ token })}`;
}

function fmt(s: number): string {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = Math.floor(s % 60);
  return `${h ? `${h}:` : ""}${String(m).padStart(h ? 2 : 1, "0")}:${String(x).padStart(2, "0")}`;
}

function Display({ last, partial, big }: { last: Line | null; partial: string; big?: boolean }) {
  return (
    <div className={`sub-display${big ? " big" : ""}`} aria-live="polite">
      {last ? (
        <>
          <p className="sub-main">{last.translation ?? last.text}</p>
          {last.translation && <p className="sub-orig">{last.text}</p>}
        </>
      ) : !partial && <p className="sub-orig">Altyazılar burada görünecek…</p>}
      {partial && <p className="sub-partial">{partial}</p>}
    </div>
  );
}

/**
 * Canlı çeviri altyazı (Adım 12c). Kaynak: sistem sesi (getDisplayMedia + "sistem sesini paylaş") ya da mikrofon.
 * Ses yalnızca bellekte 16 kHz PCM olarak yerel API'ye akar (Whisper + yerel çeviri); kaydedilmez. Dinleme yalnızca
 * "Başlat" ile açılır, göstergesi sürekli görünür, "Durdur"/paylaşımı durdurma/2 saat ile kapanır.
 */
export function SubtitlesView({ onNotice }: { onNotice?: (s: string) => void }) {
  const [source, setSource] = useState<Source>("system");
  const [srcLang, setSrcLang] = useState("auto");
  const [target, setTarget] = useState<"tr" | "en" | "none">("tr");
  const [running, setRunning] = useState(false);
  const [starting, setStarting] = useState(false);
  const [lines, setLines] = useState<Line[]>([]);
  const [partial, setPartial] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [device, setDevice] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  const [pip, setPip] = useState<Window | null>(null);
  const ws = useRef<WebSocket | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const ctx = useRef<AudioContext | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const history = useRef<HTMLDivElement>(null);

  useEffect(() => () => cleanup(true), []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { history.current?.scrollTo({ top: history.current.scrollHeight }); }, [lines.length]);

  function cleanup(closeWs: boolean) {
    window.clearInterval(timer.current);
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    void ctx.current?.close().catch(() => undefined);
    ctx.current = null;
    if (closeWs) { ws.current?.close(); ws.current = null; }
    setRunning(false);
    setLevel(0);
  }

  async function start() {
    setError(null);
    setNote(null);
    setStarting(true);
    try {
      let s: MediaStream;
      if (source === "system") {
        s = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
        if (s.getAudioTracks().length === 0) {
          s.getTracks().forEach((t) => t.stop());
          throw new Error("Ses gelmedi: paylaşım penceresinde bir ekran/sekme seçip \"Sistem sesini paylaş\" (ya da sekme sesini paylaş) kutusunu işaretle.");
        }
        s.getVideoTracks().forEach((t) => { t.enabled = false; }); // görüntü kullanılmaz; paylaşım ses için açık kalır
      } else {
        s = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: true } });
      }
      stream.current = s;
      s.getAudioTracks()[0].addEventListener("ended", () => stop()); // tarayıcıdan "Paylaşımı durdur"
      const sock = new WebSocket(liveUrl(getToken() ?? ""));
      sock.binaryType = "arraybuffer";
      ws.current = sock;
      await new Promise<void>((resolve, reject) => {
        sock.onopen = () => resolve();
        sock.onerror = () => reject(new Error("Yerel API'ye bağlanılamadı"));
      });
      sock.send(JSON.stringify({ type: "start", source_lang: srcLang, target, source }));
      sock.onmessage = (e) => onMessage(JSON.parse(String(e.data)) as Msg);
      sock.onclose = () => { if (ws.current === sock) { ws.current = null; cleanup(false); } };
      const ac = new AudioContext();
      ctx.current = ac;
      await ac.audioWorklet.addModule("/pcm-worklet.js");
      const node = new AudioWorkletNode(ac, "pcm-worklet");
      node.port.onmessage = (e: MessageEvent<{ pcm: ArrayBuffer; peak: number }>) => {
        if (sock.readyState === WebSocket.OPEN) sock.send(e.data.pcm);
        setLevel(e.data.peak);
      };
      const mute = ac.createGain();
      mute.gain.value = 0; // hoparlöre geri verilmez (yankı yok)
      ac.createMediaStreamSource(new MediaStream(s.getAudioTracks())).connect(node).connect(mute).connect(ac.destination);
      const t0 = Date.now();
      setElapsed(0);
      timer.current = window.setInterval(() => {
        const sec = (Date.now() - t0) / 1000;
        setElapsed(sec);
        if (sec > MAX_S) stop();
      }, 500);
      setRunning(true);
    } catch (e) {
      cleanup(true);
      if (!(e instanceof DOMException && e.name === "NotAllowedError")) setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  }

  function onMessage(m: Msg) {
    if (m.type === "partial") setPartial(m.text);
    else if (m.type === "final") { setLines((p) => [...p, m].slice(-500)); setPartial(""); }
    else if (m.type === "status") {
      if (m.status === "listening") setDevice(m.device ?? null);
      if (m.status === "stopped") { ws.current?.close(); ws.current = null; }
    } else if (m.type === "error") {
      setError(m.message);
      if (m.fatal) cleanup(true);
    }
  }

  function stop() {
    const sock = ws.current;
    cleanup(false); // mikrofon/paylaşım hemen kapanır; son altyazılar için bağlantı kısa süre açık kalır
    if (sock && sock.readyState === WebSocket.OPEN) {
      sock.send(JSON.stringify({ type: "stop" }));
      window.setTimeout(() => { if (ws.current === sock) { sock.close(); ws.current = null; } }, 8000);
    }
  }

  async function openPip() {
    const dpip = (window as unknown as { documentPictureInPicture?: { requestWindow: (o: object) => Promise<Window> } }).documentPictureInPicture;
    if (!dpip) { setError("Bu tarayıcı küçük pencereyi (Picture-in-Picture) desteklemiyor — Edge/Chrome 116+ gerekli."); return; }
    const w = await dpip.requestWindow({ width: 720, height: 200 });
    document.querySelectorAll('link[rel="stylesheet"], style').forEach((n) => w.document.head.appendChild(n.cloneNode(true)));
    w.document.body.className = "pip-body";
    w.addEventListener("pagehide", () => setPip(null));
    setPip(w);
  }

  async function save(format: "txt" | "srt") {
    try {
      const r = await post<SubmitResult>("/api/speech/transcript", { format, lines });
      const msg = r.status === "done" ? `Kaydedildi: ${r.result?.path}` : r.message || r.error || r.status;
      setNote(msg);
      onNotice?.(msg);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const last = lines.length ? lines[lines.length - 1] : null;
  const avgLatency = lines.length ? lines.slice(-10).reduce((a, l) => a + l.latency_s, 0) / Math.min(10, lines.length) : null;
  return (
    <main className="subs">
      <section className="panel">
        <div className="panel-head">
          <h2>Canlı çeviri altyazı</h2>
          {running && <span className="pill bad live-pill" role="status"><span className="rec-dot" /> Dinleniyor {fmt(elapsed)}</span>}
        </div>
        <div className="subs-controls">
          <fieldset disabled={running || starting}>
            <legend className="muted small">Kaynak</legend>
            <label><input type="radio" name="src" checked={source === "system"} onChange={() => setSource("system")} /> Sistem sesi (video, toplantı)</label>
            <label><input type="radio" name="src" checked={source === "mic"} onChange={() => setSource("mic")} /> Mikrofon</label>
          </fieldset>
          <label className="muted small">Konuşulan dil
            <select value={srcLang} disabled={running} onChange={(e) => setSrcLang(e.target.value)}>
              <option value="auto">Otomatik</option><option value="tr">Türkçe</option><option value="en">İngilizce</option>
            </select>
          </label>
          <label className="muted small">Altyazı dili
            <select value={target} disabled={running} onChange={(e) => setTarget(e.target.value as "tr" | "en" | "none")}>
              <option value="tr">Türkçe</option><option value="en">İngilizce</option><option value="none">Çevirme (yalnız yazıya dök)</option>
            </select>
          </label>
          {running
            ? <button className="danger big-btn" onClick={stop}>■ Durdur</button>
            : <button className="toggle big-btn" disabled={starting} onClick={() => void start()}>{starting ? "Başlıyor…" : "▶ Başlat"}</button>}
          <button className="ghost" disabled={!!pip} onClick={() => void openPip()} title="Her zaman üstte duran küçük altyazı penceresi">Küçük pencere</button>
        </div>
        {running && <div className="bar level" aria-label="Ses seviyesi"><span style={{ width: `${Math.min(100, level * 140)}%` }} /></div>}
        <p className="muted small subs-info">
          {source === "system"
            ? "Başlat'a basınca tarayıcı ne paylaşılacağını sorar: ekranı ya da sekmeyi seç ve \"Sistem sesini paylaş\" kutusunu işaretle. Görüntü kullanılmaz."
            : "Mikrofonun yalnız Başlat ile Durdur arasında açık kalır."}
          {" "}Ses kaydedilmez; yazıya dökme ve çeviri bu bilgisayarda (Whisper + yerel model) yapılır.
          {device && ` · ${device === "cuda" ? "GPU" : device === "cpu" ? "işlemci" : device}`}
          {avgLatency != null && ` · gecikme ~${avgLatency.toFixed(1)} sn`}
        </p>
        {error && <p className="error">{error}</p>}
        {note && <p className="note ok-text">{note}</p>}
        <Display last={last} partial={partial} big />
      </section>
      <section className="panel">
        <div className="panel-head">
          <h2>Döküm ({lines.length})</h2>
          <span>
            <button className="ghost small" disabled={!lines.length} onClick={() => void save("txt")}>Kaydet .txt</button>{" "}
            <button className="ghost small" disabled={!lines.length} onClick={() => void save("srt")}>Kaydet .srt</button>{" "}
            <button className="ghost small" disabled={!lines.length || running} onClick={() => setLines([])}>Temizle</button>
          </span>
        </div>
        <div className="sub-history" ref={history}>
          {lines.length === 0 && <p className="muted">Henüz altyazı yok. Döküm yalnızca bu sayfada tutulur; "Kaydet" demedikçe hiçbir yere yazılmaz.</p>}
          {lines.map((l) => (
            <p key={l.id}><span className="muted small">{fmt(l.start)} {l.lang ? `· ${LANG[l.lang] ?? l.lang}` : ""}</span> {l.text}
              {l.translation && <><br /><strong>→ {l.translation}</strong></>}</p>
          ))}
        </div>
      </section>
      {pip && createPortal(<Display last={last} partial={partial} big />, pip.document.body)}
    </main>
  );
}
