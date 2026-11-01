import { useEffect, useRef, useState } from "react";
import { api, post, type SubmitResult } from "../api";

interface SpeechStatus {
  installed: boolean;
  model: string;
  approx_mb: number | null;
  max_seconds: number;
  download?: { status?: string; percent?: number; error?: string | null };
}

function blobToBase64(b: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",", 2)[1] ?? "");
    r.onerror = () => reject(r.error);
    r.readAsDataURL(b);
  });
}

/**
 * Bas-konuş (Adım 12b). Basılı tut → bırakınca biter; kısa tıklama → tıkla-başlat / tıkla-bitir.
 * Mikrofon yalnız kayıt sürerken açıktır (tarayıcı göstergesi + buradaki kırmızı sayaç); ses diske yazılmaz,
 * yerel Whisper'a gider, metin yazı kutusuna eklenir.
 */
export function MicButton({ onText, onNotice, disabled }: {
  onText: (t: string) => void;
  onNotice: (msg: string) => void;
  disabled?: boolean;
}) {
  const [state, setState] = useState<"idle" | "starting" | "recording" | "busy">("idle");
  const [elapsed, setElapsed] = useState(0);
  const [missing, setMissing] = useState<SpeechStatus | null>(null);
  const rec = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const chunks = useRef<Blob[]>([]);
  const pressAt = useRef(0);
  const stopWanted = useRef(false);
  const maxS = useRef(120);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => { window.clearInterval(timer.current); stream.current?.getTracks().forEach((t) => t.stop()); }, []);

  async function start() {
    stopWanted.current = false;
    setState("starting");
    try {
      const st = await api<SpeechStatus>("/api/speech/status");
      maxS.current = st.max_seconds;
      if (!st.installed) { setMissing(st); setState("idle"); return; }
      const s = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      stream.current = s;
      const type = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "";
      const r = new MediaRecorder(s, type ? { mimeType: type } : undefined);
      chunks.current = [];
      r.ondataavailable = (e) => { if (e.data.size) chunks.current.push(e.data); };
      r.onstop = () => void finish(r.mimeType);
      rec.current = r;
      r.start(250);
      const t0 = Date.now();
      setElapsed(0);
      timer.current = window.setInterval(() => {
        const s2 = (Date.now() - t0) / 1000;
        setElapsed(s2);
        if (s2 >= maxS.current) stop();
      }, 200);
      setState("recording");
      if (stopWanted.current) stop(); // izin penceresi açıkken bırakıldıysa
    } catch (e) {
      setState("idle");
      stream.current?.getTracks().forEach((t) => t.stop());
      if (e instanceof DOMException && e.name === "NotAllowedError") onNotice("Mikrofon izni verilmedi.");
      else onNotice(e instanceof Error ? e.message : String(e));
    }
  }

  function stop() {
    stopWanted.current = true;
    window.clearInterval(timer.current);
    if (rec.current && rec.current.state !== "inactive") rec.current.stop();
    stream.current?.getTracks().forEach((t) => t.stop()); // mikrofon hemen kapanır
    stream.current = null;
  }

  async function finish(mime: string) {
    rec.current = null;
    const blob = new Blob(chunks.current, { type: mime || "audio/webm" });
    chunks.current = [];
    if (blob.size < 1500) { setState("idle"); return; }
    setState("busy");
    try {
      const t = await post<{ text: string; seconds: number; device: string }>("/api/speech/transcribe", { data_b64: await blobToBase64(blob) });
      if (t.text) onText(t.text);
      else onNotice("Konuşma algılanmadı.");
    } catch (e) {
      onNotice(e instanceof Error ? e.message : String(e));
    } finally {
      setState("idle");
    }
  }

  async function download() {
    try {
      const r = await post<SubmitResult>("/api/speech/download", {});
      onNotice(r.status === "awaiting_approval" ? "Ses modeli indirme talebi onay bekliyor — Bugün ya da Sistem → Onay merkezi." : r.message);
    } catch (e) {
      onNotice(e instanceof Error ? e.message : String(e));
    } finally {
      setMissing(null);
    }
  }

  const down = (e: React.PointerEvent) => {
    if (disabled || state === "busy") return;
    e.preventDefault();
    if (state === "recording" || state === "starting") { stop(); return; }
    pressAt.current = Date.now();
    void start();
  };
  const up = () => {
    // basılı tutma (>400 ms) → bırakınca biter; kısa tıklama → kayıt sürer, ikinci tıklama bitirir
    if ((state === "recording" || state === "starting") && Date.now() - pressAt.current > 400) stop();
  };

  const mm = `${Math.floor(elapsed / 60)}:${String(Math.floor(elapsed % 60)).padStart(2, "0")}`;
  return (
    <>
      <button
        className={`ghost mic${state === "recording" ? " rec" : ""}`}
        disabled={disabled || state === "busy"}
        onPointerDown={down}
        onPointerUp={up}
        onKeyDown={(e) => { if ((e.key === " " || e.key === "Enter") && !e.repeat) { e.preventDefault(); if (state === "recording") stop(); else { pressAt.current = 0; void start(); } } }}
        aria-pressed={state === "recording"}
        aria-label={state === "recording" ? "Kaydı bitir" : "Konuşarak yaz"}
        title="Basılı tut ve konuş (bırakınca biter) ya da tıkla-başlat / tıkla-bitir. Ses yerel modelle yazıya çevrilir, saklanmaz."
      >
        {state === "recording" ? <><span className="rec-dot" aria-hidden /> {mm}</> : state === "busy" ? "…" : "🎤"}
      </button>
      {state === "recording" && <span className="rec-label" role="status">Dinleniyor — bitince bırak / tıkla</span>}
      {state === "busy" && <span className="muted hint" role="status">Yazıya çevriliyor…</span>}
      {missing && (
        <span className="mic-missing" role="status">
          Ses tanıma modeli kurulu değil (whisper {missing.model}, ~{missing.approx_mb ?? "?"} MB).
          <button className="small" onClick={() => void download()}>İndir…</button>
          <button className="ghost small" onClick={() => setMissing(null)}>×</button>
        </span>
      )}
    </>
  );
}

// ---------------------------------------------------------------- sesli okuma

/** Markdown → okunacak düz metin (kod blokları okunmaz). */
export function speakableText(md: string): string {
  return md
    .replace(/```[\s\S]*?```/g, " (kod bloğu) ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/^\s{0,3}(#{1,6}|>|[-*+]|\d+\.)\s+/gm, "")
    .replace(/[*_~|]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function guessLang(text: string): "tr" | "en" {
  if (/[çğıöşüÇĞİÖŞÜ]/.test(text)) return "tr";
  const tr = (text.match(/\b(ve|bir|bu|için|ile|da|de|ne|var|değil|olarak)\b/gi) ?? []).length;
  const en = (text.match(/\b(the|and|is|of|to|for|with|that|this|are)\b/gi) ?? []).length;
  return tr >= en ? "tr" : "en";
}

/** Yalnızca bu bilgisayardaki sesler (localService); çevrim içi sesler metni dışarı gönderir, kullanılmaz. */
export function pickLocalVoice(voices: SpeechSynthesisVoice[], lang: "tr" | "en"): SpeechSynthesisVoice | null {
  const local = voices.filter((v) => v.localService);
  return local.find((v) => v.lang.toLowerCase().startsWith(lang) && v.default)
    ?? local.find((v) => v.lang.toLowerCase().startsWith(lang)) ?? null;
}

function useVoices(): SpeechSynthesisVoice[] {
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>(() => (typeof speechSynthesis !== "undefined" ? speechSynthesis.getVoices() : []));
  useEffect(() => {
    if (typeof speechSynthesis === "undefined") return;
    const on = () => setVoices(speechSynthesis.getVoices());
    speechSynthesis.addEventListener("voiceschanged", on);
    on();
    return () => speechSynthesis.removeEventListener("voiceschanged", on);
  }, []);
  return voices;
}

export function SpeakButton({ text }: { text: string }) {
  const voices = useVoices();
  const [speaking, setSpeaking] = useState(false);
  const plain = speakableText(text);
  const lang = guessLang(plain);
  const voice = pickLocalVoice(voices, lang);
  useEffect(() => () => { if (speaking) speechSynthesis.cancel(); }, [speaking]);
  if (typeof speechSynthesis === "undefined") return null;
  const label = lang === "tr" ? "Türkçe" : "İngilizce";
  return (
    <button
      className="ghost small"
      disabled={!voice}
      title={voice ? `Sesli oku (${voice.name}, bu bilgisayarda)` : `Bu bilgisayarda yerel ${label} ses yok — Windows: Ayarlar → Saat ve dil → Konuşma → Ses ekle`}
      onClick={() => {
        if (speaking) { speechSynthesis.cancel(); setSpeaking(false); return; }
        speechSynthesis.cancel();
        const u = new SpeechSynthesisUtterance(plain);
        u.voice = voice;
        u.lang = voice!.lang;
        u.onend = u.onerror = () => setSpeaking(false);
        setSpeaking(true);
        speechSynthesis.speak(u);
      }}
    >
      {speaking ? "⏹ Durdur" : "🔊 Oku"}
    </button>
  );
}
