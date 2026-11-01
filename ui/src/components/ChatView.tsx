import { useEffect, useMemo, useRef, useState } from "react";
import { api, post, ApiError, type Agent, type AttachmentRef, type ChatMessage, type ClaudeStatus, type Conversation, type ConversationView, type SubmitResult } from "../api";
import { ago } from "../format";
import { usePolling } from "../hooks";
import { Markdown } from "../markdown";
import { CapturePreview, grabScreenFrame } from "./ScreenCapture";
import { OfficeView } from "./OfficeView";
import { MicButton, SpeakButton } from "./Voice";

const STATUS_TEXT: Record<string, string> = {
  pending: "sırada…",
  running: "düşünüyor…",
  waiting_claude: "Claude kutusunda — Claude Code oturumunda işlenecek",
  failed: "başarısız",
  cancelled: "iptal edildi",
};

function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

const BINARY = /\.(pdf|xlsx|xlsm|png|jpe?g|webp|bmp)$/i;
const REPORT_FORMATS: [string, string][] = [["xlsx", "Excel"], ["pdf", "PDF"], ["docx", "Word"], ["md", "Markdown"]];
const KIND_ICON: Record<string, string> = { pdf: "📕", table: "📊", text: "📎", image: "🖼️" };

function readBase64(f: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",", 2)[1] ?? "");
    r.onerror = () => reject(r.error);
    r.readAsDataURL(f);
  });
}

function MessageView({ m, claude, onHandoff, onRemember, onReport, onOpenFlow, busy }: {
  m: ChatMessage;
  claude: ClaudeStatus | null;
  onHandoff: (m: ChatMessage) => void;
  onRemember: (m: ChatMessage) => void;
  onReport: (m: ChatMessage, format: string) => void;
  onOpenFlow: (jobId: string) => void;
  busy: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const sources = m.recall?.sources ?? [];
  const memories = m.recall?.memories ?? [];
  const waiting = m.status === "pending" || m.status === "running" || m.status === "waiting_claude";
  const agents = m.meta.agents?.length ? m.meta.agents.join(" → ") : m.agent === "auto" ? "" : m.agent;
  return (
    <article className={`msg msg-${m.role} status-${m.status}${m.handoff ? " handoff" : ""}`}>
      <header>
        <strong>{m.role === "user" ? "Sen" : m.agent === "claude" || m.handoff ? "Claude" : "kayaAI"}</strong>
        {m.role === "assistant" && agents && <span className="muted"> · {agents}</span>}
        {m.role === "user" && m.agent !== "auto" && <span className="muted"> · → {m.agent}</span>}
        <span className="muted when"> · {ago(m.created_at)}</span>
      </header>
      {m.attachments.length > 0 && (
        <div className="chips">{m.attachments.map((a) => <span key={a.id} className="chip">{KIND_ICON[a.kind ?? "text"]} {a.name}</span>)}</div>
      )}
      {waiting ? (
        <p className="thinking">
          <span className="dot" />{STATUS_TEXT[m.status]}
          {m.job_kind === "conductor" && m.job_id && <button className="ghost small" onClick={() => onOpenFlow(m.job_id!)}>Akışı izle</button>}
        </p>
      ) : m.role === "assistant" ? (
        <Markdown text={m.content} />
      ) : (
        <>
          <p className="user-text">{m.content}</p>
          <div className="msg-meta user-actions">
            <button className="ghost small" disabled={busy} title="Bu mesajı kısa bir not olarak hafızaya kaydet" onClick={() => onRemember(m)}>
              Hafızaya ekle
            </button>
          </div>
        </>
      )}
      {m.role === "assistant" && m.status === "done" && !!m.meta.vision?.ocr_text && (
        <details className="recall">
          <summary className="muted">Ekranda okunan yazı (OCR)</summary>
          <pre className="ocr-text">{m.meta.vision.ocr_text}</pre>
        </details>
      )}
      {m.role === "assistant" && m.status === "done" && (sources.length > 0 || memories.length > 0) && (
        <div className="recall">
          {sources.length > 0 && (
            <div className="chips">
              <span className="muted">Kaynaklar:</span>
              {sources.map((s, i) => <span key={i} className="chip" title={s.path}>📄 {s.name}:{s.loc || s.line}</span>)}
            </div>
          )}
          {memories.length > 0 && (
            <details>
              <summary className="muted">Hafızadan {memories.length} bilgi kullanıldı</summary>
              <ul>{memories.map((x) => <li key={x.id}>{x.text}</li>)}</ul>
            </details>
          )}
        </div>
      )}
      {m.role === "assistant" && m.status === "done" && (
        <div className="msg-meta">
          {!!m.meta.reviewed && <span className="badge state-completed">gözden geçirildi</span>}
          {!!m.meta.revised && <span className="badge state-waiting">düzeltildi</span>}
          {!!m.meta.disputes && <span className="badge state-failed">{m.meta.disputes} anlaşmazlık</span>}
          {m.meta.duration_s != null && <span className="muted">{m.meta.duration_s} sn</span>}
          {m.meta.vision && <span className="muted">{m.meta.vision.seconds} sn</span>}
          <span className="spacer" />
          {m.job_kind === "conductor" && m.job_id && (
            <button className="ghost small" onClick={() => onOpenFlow(m.job_id!)} title="Bu cevabın ajanlar arasında nasıl üretildiğini göster">Akışı göster</button>
          )}
          <select
            className="small-select"
            aria-label="Rapor oluştur"
            value=""
            disabled={busy}
            onChange={(e) => { if (e.target.value) onReport(m, e.target.value); }}
          >
            <option value="">Rapor oluştur…</option>
            {REPORT_FORMATS.map(([f, label]) => <option key={f} value={f}>{label} (.{f})</option>)}
          </select>
          <SpeakButton text={m.content} />
          <button className="ghost small" onClick={() => { void navigator.clipboard?.writeText(m.content).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }); }}>
            {copied ? "Kopyalandı" : "Kopyala"}
          </button>
          {!m.handoff && m.agent !== "claude" && (
            <button
              className="ghost small"
              disabled={!claude?.enabled || busy}
              title={claude?.enabled ? "Bu soruyu Claude kutusuna devret" : "Claude modu kapalı — yerel ekip cevaplıyor"}
              onClick={() => onHandoff(m)}
            >
              Claude'a devret
            </button>
          )}
        </div>
      )}
      {m.warnings.length > 0 && (
        <ul className="warnings">{m.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
      )}
    </article>
  );
}

export function ChatView({
  convId,
  onSelect,
  onOpenMemory,
  onOpenFlow,
  refreshKey, flowKey, approvalsKey,
  claude,
}: {
  convId: string | null;
  onSelect: (id: string | null) => void;
  onOpenMemory: () => void;
  onOpenFlow: (jobId: string) => void;
  refreshKey: number;
  flowKey: number;
  approvalsKey: number;
  claude: ClaudeStatus | null;
}) {
  const [listKey, setListKey] = useState(0);
  const [viewKey, setViewKey] = useState(0);
  const list = usePolling<Conversation[]>("/api/chat", 20000, `${listKey}-${refreshKey}`);
  const agents = usePolling<Agent[]>("/api/agents", 30000);
  const [view, setView] = useState<ConversationView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [agent, setAgent] = useState("auto");
  const [attachments, setAttachments] = useState<AttachmentRef[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [capture, setCapture] = useState<HTMLCanvasElement | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const lastRecall = [...(view?.messages ?? [])].reverse().find((m) => m.role === "assistant" && m.status === "done")?.recall;
  const pending = view?.messages.some((m) => ["pending", "running", "waiting_claude"].includes(m.status)) ?? false;
  // Adım 15: sağdaki ofis — bu sohbetteki son şef işi (sürmekte olan önce)
  const conductorMsgs = (view?.messages ?? []).filter((m) => m.job_kind === "conductor" && m.job_id);
  const runningJob = [...conductorMsgs].reverse().find((m) => ["pending", "running"].includes(m.status))?.job_id ?? null;
  const officeJob = runningJob ?? conductorMsgs[conductorMsgs.length - 1]?.job_id ?? null;
  const [side, setSide] = useState<"office" | "memory">("office");
  useEffect(() => { if (runningJob) setSide("office"); }, [runningJob]);

  useEffect(() => {
    if (!convId) { setView(null); return; }
    let stop = false;
    api<ConversationView>(`/api/chat/${convId}`)
      .then((v) => { if (!stop) { setView(v); setError(null); } })
      .catch((e) => { if (!stop) { setError(e instanceof ApiError && e.status === 404 ? "Sohbet bulunamadı." : errText(e)); setView(null); } });
    return () => { stop = true; };
  }, [convId, viewKey, refreshKey]);

  // bekleyen cevap varken olay gelmese de seyrek yokla (başka süreçte biten işler, ör. Claude kutusu)
  useEffect(() => {
    if (!pending) return;
    const id = window.setInterval(() => setViewKey((k) => k + 1), 4000);
    return () => window.clearInterval(id);
  }, [pending]);

  // Son mesaja kay: kapsayıcının scrollTop'u ile (scrollIntoView, klavyede Tab başlangıç noktasını mesaj sonuna taşıyıp
  // "İçeriğe atla" bağlantısını atlatıyordu — Adım 14d)
  useEffect(() => {
    const list = bottom.current?.parentElement;
    if (list) list.scrollTop = list.scrollHeight;
  }, [view?.messages.length, pending]);

  const choices = useMemo(
    () => (agents.data ?? []).filter((a) => a.output === "GeneralAnswer" && a.name !== "vision"),
    [agents.data],
  );

  async function newChat() {
    const c = await post<Conversation>("/api/chat", {});
    setListKey((k) => k + 1);
    onSelect(c.id);
  }

  async function send(mode?: "analyze" | "summarize" | "invoice") {
    const defaults = { analyze: "Bu tabloyu analiz et ve öne çıkanları özetle.", summarize: "Bu belgeyi özetle.", invoice: "Bu faturanın bilgilerini çıkar." };
    const body = text.trim() || (mode ? defaults[mode] : "");
    if (!body || busy) return;
    setBusy(true);
    setError(null);
    try {
      let id = convId;
      if (!id) {
        id = (await post<Conversation>("/api/chat", {})).id;
        onSelect(id);
      }
      await post(`/api/chat/${id}/messages`, { text: body, agent, attachments: attachments.map((a) => a.id), mode: mode ?? null });
      setText("");
      setAttachments([]);
      setListKey((k) => k + 1);
      setViewKey((k) => k + 1);
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  async function addFiles(files: FileList | null) {
    if (!files) return;
    setError(null);
    for (const f of Array.from(files)) {
      try {
        const body = BINARY.test(f.name) ? { name: f.name, data_b64: await readBase64(f) } : { name: f.name, text: await f.text() };
        const a = await post<AttachmentRef>("/api/attachments", body);
        setAttachments((prev) => [...prev, a]);
      } catch (e) {
        setError(`${f.name}: ${errText(e)}`);
      }
    }
    if (fileInput.current) fileInput.current.value = "";
  }

  async function captureScreen() {
    setError(null);
    try {
      setCapture(await grabScreenFrame());
    } catch (e) {
      if (e instanceof DOMException && e.name === "NotAllowedError") return; // sahip vazgeçti
      setError(errText(e));
    }
  }

  async function addCapture(b64: string, name: string) {
    setCapture(null);
    try {
      const a = await post<AttachmentRef>("/api/attachments", { name, data_b64: b64 });
      setAttachments((prev) => [...prev, a]);
      if (!text.trim()) setText("Bu ekranda ne var?");
    } catch (e) {
      setError(errText(e));
    }
  }

  async function addFromFolder() {
    const path = window.prompt("İzinli klasördeki dosyanın yolu (ör. notlar.md ya da tam yol):");
    if (!path?.trim()) return;
    try {
      const a = await post<AttachmentRef>("/api/attachments/from-path", { path: path.trim() });
      setAttachments((prev) => [...prev, a]);
    } catch (e) {
      setError(errText(e));
    }
  }

  async function handoff(m: ChatMessage) {
    if (!convId) return;
    const ok = window.confirm(
      "Bu soru Claude kutusuna devredilecek. Sohbetin son mesajları ve bu sorunun ekleri Claude Code oturumunda " +
        "Claude'a gönderilecek. Devam edilsin mi?",
    );
    if (!ok) return;
    setBusy(true);
    try {
      await post(`/api/chat/${convId}/messages/${m.id}/handoff`, {});
      setViewKey((k) => k + 1);
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  async function report(m: ChatMessage, format: string) {
    if (!convId) return;
    setBusy(true);
    setError(null);
    try {
      const r = await post<SubmitResult>(`/api/chat/${convId}/messages/${m.id}/report`, { format });
      if (r.status === "done" && r.result?.path) setNotice(`Rapor kaydedildi: ${r.result.path}`);
      else if (r.status === "awaiting_approval") setNotice(`Aynı adda dosya var; üzerine yazmak için onay gerekiyor (Bugün ya da Sistem → Onay merkezi).`);
      else setError(r.error ?? r.message);
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  async function rememberMsg(m: ChatMessage) {
    setBusy(true);
    setError(null);
    try {
      const r = await post<{ message: string }>("/api/memory/from-text", { text: m.content, conv_id: convId });
      setNotice(r.message.replace(/\*/g, ""));
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  async function rename(c: Conversation) {
    const title = window.prompt("Sohbetin yeni adı:", c.title);
    if (!title?.trim()) return;
    await api(`/api/chat/${c.id}`, { method: "PATCH", body: JSON.stringify({ title: title.trim() }) });
    setListKey((k) => k + 1);
    setViewKey((k) => k + 1);
  }

  async function remove(c: Conversation) {
    if (!window.confirm(`"${c.title}" sohbeti ve tüm mesajları silinsin mi? Bu geri alınamaz.`)) return;
    await api(`/api/chat/${c.id}`, { method: "DELETE" });
    setListKey((k) => k + 1);
    if (c.id === convId) onSelect(null);
  }

  return (
    <main className={`chat${side === "office" ? " office-open" : ""}`}>
      <aside className="chat-list panel" aria-label="Sohbetler">
        <button className="toggle new-chat" onClick={() => void newChat()}>+ Yeni sohbet</button>
        {list.data?.length === 0 && <p className="muted">Henüz sohbet yok.</p>}
        <ul>
          {list.data?.map((c) => (
            <li key={c.id} className={c.id === convId ? "active" : ""}>
              <button className="conv" onClick={() => onSelect(c.id)} title={c.title}>
                <span className="conv-title">{c.title}</span>
                <span className="muted when">{ago(c.updated_at)}</span>
              </button>
              {c.id === convId && (
                <span className="conv-actions">
                  <button className="ghost small" onClick={() => void rename(c)}>Adlandır</button>
                  <button className="ghost small danger" onClick={() => void remove(c)}>Sil</button>
                </span>
              )}
            </li>
          ))}
        </ul>
      </aside>

      <section className="chat-main panel" aria-labelledby="chat-messages-title">
        <h2 id="chat-messages-title" className="sr-only">Mesajlar</h2>
        <div className="messages" aria-live="polite">
          {!view && !error && (
            <div className="empty">
              <h2>Merhaba, ben kayaAI.</h2>
              <p className="muted">
                Yerel modellerle, bilgisayarında çalışırım. Bir şey sor ya da bir metin/CSV dosyası ekle. "Otomatik" seçiliyse
                şef isteği uygun ajana (coder, data, document…) verir ve uzman cevaplarını gözden geçirtir.
              </p>
            </div>
          )}
          {view?.messages.length === 0 && <p className="muted">Bu sohbette henüz mesaj yok.</p>}
          {view?.messages.map((m) => (
            <MessageView key={m.id} m={m} claude={claude} onHandoff={(x) => void handoff(x)} onRemember={(x) => void rememberMsg(x)}
              onReport={(x, f) => void report(x, f)} onOpenFlow={onOpenFlow} busy={busy} />
          ))}
          <div ref={bottom} />
        </div>
        {error && <p className="error">{error}</p>}
        {notice && <p className="notice" role="status" onClick={() => setNotice(null)}>{notice}</p>}
        {capture && <CapturePreview canvas={capture} onAdd={(b, n) => void addCapture(b, n)} onCancel={() => setCapture(null)} />}
        <div className="composer">
          {attachments.length > 0 && (
            <div className="chips">
              {attachments.map((a) => (
                <span key={a.id} className="chip">
                  {KIND_ICON[a.kind ?? "text"]} {a.name}
                  <button className="chip-x" aria-label={`${a.name} ekini kaldır`} onClick={() => setAttachments((p) => p.filter((x) => x.id !== a.id))}>×</button>
                </span>
              ))}
            </div>
          )}
          <textarea
            value={text}
            placeholder="Mesajını yaz… (Enter gönderir, Shift+Enter yeni satır)"
            rows={3}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            aria-label="Mesaj"
          />
          <div className="composer-bar">
            <label className="muted">
              Ajan{" "}
              <select value={agent} onChange={(e) => setAgent(e.target.value)} aria-label="Ajan">
                <option value="auto">Otomatik (şef seçer)</option>
                {choices.map((a) => (
                  <option key={a.name} value={a.name}>{a.name}{a.lifecycle === "temporary" ? " (geçici)" : ""}</option>
                ))}
              </select>
            </label>
            <input ref={fileInput} type="file" multiple hidden onChange={(e) => void addFiles(e.target.files)} />
            <button className="ghost" onClick={() => fileInput.current?.click()}>Dosya ekle</button>
            <button className="ghost" onClick={() => void addFromFolder()}>Klasörden ekle</button>
            <button className="ghost" onClick={() => void captureScreen()} title="Ekrandan tek kare al (yerel görsel model yorumlar)">📷 Ekran</button>
            <MicButton disabled={busy} onNotice={setNotice}
              onText={(t) => setText((prev) => (prev.trim() ? `${prev.trimEnd()} ${t}` : t))} />
            {attachments.some((a) => a.kind === "table") && (
              <button className="ghost" disabled={busy} onClick={() => void send("analyze")} title="Sayıları program hesaplar">Analiz et</button>
            )}
            {attachments.some((a) => a.kind === "pdf") && (
              <>
                <button className="ghost" disabled={busy} onClick={() => void send("summarize")}>Özetle</button>
                <button className="ghost" disabled={busy} onClick={() => void send("invoice")}>Fatura olarak oku</button>
              </>
            )}
            <span className="muted hint">Metin, PDF, Excel/CSV, görüntü, ses</span>
            <span className="spacer" />
            <button className="toggle" disabled={busy || !text.trim()} onClick={() => void send()}>Gönder</button>
          </div>
        </div>
      </section>

      <aside className="chat-side panel" aria-label={side === "office" ? "Ofis" : "Hafıza ve Claude"}>
        <div className="seg" role="group" aria-label="Yan panel">
          <button aria-pressed={side === "office"} onClick={() => setSide("office")}>Ofis</button>
          <button aria-pressed={side === "memory"} onClick={() => setSide("memory")}>Hafıza</button>
        </div>
        {side === "office" ? (
          <OfficeView jobId={officeJob} refreshKey={flowKey} approvalsKey={approvalsKey} compact
                      onExpand={officeJob ? () => onOpenFlow(officeJob) : undefined} />
        ) : <>
        <h2>Hafıza</h2>
        {lastRecall && (lastRecall.memories?.length || lastRecall.sources?.length) ? (
          <>
            <p className="muted">Son cevapta kullanılanlar:</p>
            <ul className="side-list">
              {lastRecall.memories?.map((x) => <li key={x.id}>{x.text}</li>)}
              {lastRecall.sources?.map((s, i) => <li key={`s${i}`}>📄 {s.name}:{s.line}</li>)}
            </ul>
          </>
        ) : (
          <p className="muted">İlgili hafıza ve belge parçaları her soruda otomatik aranır; kullanılırsa burada görünür.</p>
        )}
        <p className="muted">Eklemek için: <code>hatırla: …</code> ya da mesajdaki "Hafızaya ekle".</p>
        <button className="ghost small" onClick={onOpenMemory}>Hafızayı yönet</button>
        <h2>Claude</h2>
        <p className="muted">
          {claude?.enabled
            ? "Claude modu açık. Bir cevabın altındaki \"Claude'a devret\" ile soruyu Claude kutusuna bırakabilirsin; cevap buraya gelir."
            : "Claude modu kapalı. Tüm cevaplar yerel ekipten gelir."}
        </p>
        </>}
      </aside>
    </main>
  );
}
