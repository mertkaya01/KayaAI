import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, post, ApiError, type Agent, type AttachmentRef, type ChatMessage, type ClaudeStatus, type Conversation, type ConversationView, type SubmitResult } from "../api";
import { ago, groupByDate } from "../format";
import { usePolling } from "../hooks";
import { Icon, type IconName } from "../icons";
import { Markdown } from "../markdown";
import { useProgress } from "../office/progress";
import type { Progress } from "../office/scene";
import { CapturePreview, grabScreenFrame } from "./ScreenCapture";
import { MicButton, SpeakButton } from "./Voice";

/**
 * Asistan (Adım 18a): iki sütun (sohbetler | konuşma), ortalı okuma alanı, modern mesajlar (senin mesajın balon, cevap
 * düz metin), tek ajanlı cevap yazıldıkça akar, şef işinde tek satır durum + "Ofiste izle", araç çubuğu üzerine gelince,
 * tek parça mesaj kutusu, boş sohbette öneri kartları, tarihe göre gruplu ve aranabilir sohbet listesi.
 */

const STATUS_TEXT: Record<string, string> = {
  pending: "sırada…",
  running: "düşünüyor…",
  waiting_claude: "Claude kutusunda — Claude Code oturumunda işlenecek",
  failed: "başarısız",
  cancelled: "iptal edildi",
};

const AGENT_LABEL: Record<string, string> = {
  general: "Genel", data: "Veri", document: "Belge", coder: "Kod", vision: "Görsel", planner: "Planlayıcı", reviewer: "Denetçi",
  claude: "Claude",
};

function agentName(a: string): string {
  return AGENT_LABEL[a.split(".")[0]] ?? a;
}

function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

const BINARY = /\.(pdf|xlsx|xlsm|png|jpe?g|webp|bmp)$/i;
const REPORT_FORMATS: [string, string][] = [["xlsx", "Excel"], ["pdf", "PDF"], ["docx", "Word"], ["md", "Markdown"]];
const KIND_ICON: Record<string, string> = { pdf: "📕", table: "📊", text: "📎", image: "🖼️" };

const SUGGESTIONS: { icon: IconName; title: string; sub: string; text: string; attach?: boolean; agent?: string }[] = [
  { icon: "chart", title: "Tablo analiz et", sub: "Excel/CSV ekle, sayıları program hesaplasın", text: "Bu tabloyu analiz et ve öne çıkanları özetle.", attach: true },
  { icon: "doc", title: "Belge özetle", sub: "PDF ya da metin ekle, kısa özet çıkar", text: "Bu belgeyi özetle: ana fikirler, tarihler, yapılacaklar.", attach: true },
  { icon: "edit", title: "E-posta taslağı", sub: "Kibar, net bir taslak yazsın", text: "Şu konu için kibar ve kısa bir e-posta taslağı yaz: " },
  { icon: "models", title: "Kod yaz", sub: "Python, JavaScript, SQL…", text: "Python ile şunu yapan bir fonksiyon yaz: ", agent: "coder" },
];

function readBase64(f: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",", 2)[1] ?? "");
    r.onerror = () => reject(r.error);
    r.readAsDataURL(f);
  });
}

/** Şef işi sürerken tek satır: hangi ajan ne yazıyor. */
function jobLine(jobId: string, progress: Record<string, Progress>): string | null {
  const kids = Object.values(progress).filter((p) => p.parent_id === jobId).sort((a, b) => b.at - a.at);
  if (!kids.length) return null;
  const p = kids[0];
  if (p.worker === "planner") return "Şef işi planlıyor…";
  if (p.worker.endsWith(".check") || p.worker === "reviewer") return `${agentName("reviewer")} kontrol ediyor…`;
  const who = `${agentName(p.worker)} yazıyor`;
  return p.field === "answer" && p.tail ? `${who}: “${p.tail}”` : `${who}…`;
}

function MessageView({ m, claude, progress, onHandoff, onRemember, onReport, onOpenFlow, busy }: {
  m: ChatMessage;
  claude: ClaudeStatus | null;
  progress: Record<string, Progress>;
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
  const agents = m.meta.agents?.length ? m.meta.agents.map(agentName).join(" → ") : m.agent === "auto" ? "" : agentName(m.agent);
  const isClaude = m.agent === "claude" || m.handoff;
  const live = waiting && m.job_kind === "task" && m.job_id ? progress[m.job_id]?.answer : undefined;
  const line = waiting && m.job_kind === "conductor" && m.job_id ? jobLine(m.job_id, progress) : null;

  if (m.role === "user") {
    return (
      <article className="msg msg-user" aria-label="Senin mesajın">
        {m.attachments.length > 0 && (
          <div className="chips">{m.attachments.map((a) => <span key={a.id} className="chip">{KIND_ICON[a.kind ?? "text"]} {a.name}</span>)}</div>
        )}
        <p className="user-text">{m.content}</p>
        <div className="msg-foot">
          {m.agent !== "auto" && <span className="muted small">→ {agentName(m.agent)}</span>}
          <span className="muted small">{ago(m.created_at)}</span>
          <button className="icon-btn sm hover-only" disabled={busy} title="Bu mesajı kısa bir not olarak hafızaya kaydet"
                  aria-label="Hafızaya ekle" onClick={() => onRemember(m)}><Icon name="pin" size={16} /></button>
        </div>
      </article>
    );
  }

  return (
    <article className={`msg msg-assistant status-${m.status}${m.handoff ? " handoff" : ""}`} aria-label={isClaude ? "Claude'un cevabı" : "kayaAI'nin cevabı"}>
      <div className={`avatar${isClaude ? " claude" : ""}`} aria-hidden="true">{isClaude ? "C" : "◆"}</div>
      <div className="msg-body">
        <header className="msg-head">
          <strong>{isClaude ? "Claude" : "kayaAI"}</strong>
          {agents && <span className="agent-chip">{agents}</span>}
          <span className="muted small">{ago(m.created_at)}</span>
        </header>
        {waiting ? (
          live ? (
            <div className="streaming"><Markdown text={live} /></div>
          ) : (
            <p className="thinking">
              <span className="dots" aria-hidden="true"><i /><i /><i /></span>
              <span>{line ?? STATUS_TEXT[m.status]}</span>
              {m.job_kind === "conductor" && m.job_id && (
                <button className="link-btn" onClick={() => onOpenFlow(m.job_id!)}><Icon name="office" size={15} /> Ofiste izle</button>
              )}
            </p>
          )
        ) : (
          <Markdown text={m.content} />
        )}
        {m.status === "done" && !!m.meta.vision?.ocr_text && (
          <details className="recall">
            <summary className="muted">Ekranda okunan yazı (OCR)</summary>
            <pre className="ocr-text">{m.meta.vision.ocr_text}</pre>
          </details>
        )}
        {m.status === "done" && (sources.length > 0 || memories.length > 0) && (
          <div className="recall">
            {sources.length > 0 && (
              <div className="chips">
                <span className="muted small">Kaynaklar:</span>
                {sources.map((s, i) => <span key={i} className="chip" title={s.path}>📄 {s.name}:{s.loc || s.line}</span>)}
              </div>
            )}
            {memories.length > 0 && (
              <details>
                <summary className="muted small">Hafızadan {memories.length} bilgi kullanıldı</summary>
                <ul>{memories.map((x) => <li key={x.id}>{x.text}</li>)}</ul>
              </details>
            )}
          </div>
        )}
        {m.warnings.length > 0 && <ul className="warnings">{m.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
        {m.status === "done" && (
          <div className="msg-tools" role="toolbar" aria-label="Cevap araçları">
            {!!m.meta.reviewed && <span className="badge state-completed">gözden geçirildi</span>}
            {!!m.meta.revised && <span className="badge state-waiting">düzeltildi</span>}
            {!!m.meta.disputes && <span className="badge state-failed">{m.meta.disputes} anlaşmazlık</span>}
            {m.meta.duration_s != null && <span className="muted small">{Number(m.meta.duration_s).toFixed(1).replace(".", ",")} sn</span>}
            {m.meta.vision && <span className="muted small">{m.meta.vision.seconds} sn</span>}
            <span className="tools hover-only">
              <button className="icon-btn sm" title={copied ? "Kopyalandı" : "Kopyala"} aria-label={copied ? "Kopyalandı" : "Kopyala"}
                      onClick={() => { void navigator.clipboard?.writeText(m.content).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }); }}>
                <Icon name={copied ? "check" : "copy"} size={16} />
              </button>
              <SpeakButton text={m.content} />
              <label className="report-pick" title="Rapor oluştur">
                <Icon name="report" size={16} />
                <select aria-label="Rapor oluştur" value="" disabled={busy} onChange={(e) => { if (e.target.value) onReport(m, e.target.value); }}>
                  <option value="">Rapor…</option>
                  {REPORT_FORMATS.map(([f, label]) => <option key={f} value={f}>{label} (.{f})</option>)}
                </select>
              </label>
              {m.job_kind === "conductor" && m.job_id && (
                <button className="icon-btn sm" title="Bu cevabın ajanlar arasında nasıl üretildiğini ofiste göster" aria-label="Ofiste göster"
                        onClick={() => onOpenFlow(m.job_id!)}><Icon name="office" size={16} /></button>
              )}
              {!m.handoff && m.agent !== "claude" && (
                <button className="icon-btn sm" disabled={!claude?.enabled || busy} aria-label="Claude'a devret"
                        title={claude?.enabled ? "Bu soruyu Claude kutusuna devret" : "Claude modu kapalı — yerel ekip cevaplıyor"}
                        onClick={() => onHandoff(m)}><Icon name="handoff" size={16} /></button>
              )}
            </span>
          </div>
        )}
      </div>
    </article>
  );
}

export function ChatView({ convId, onSelect, onOpenFlow, refreshKey, claude }: {
  convId: string | null;
  onSelect: (id: string | null) => void;
  onOpenFlow: (jobId: string) => void;
  refreshKey: number;
  claude: ClaudeStatus | null;
}) {
  const [listKey, setListKey] = useState(0);
  const [viewKey, setViewKey] = useState(0);
  const list = usePolling<Conversation[]>("/api/chat", 20000, `${listKey}-${refreshKey}`);
  const agents = usePolling<Agent[]>("/api/agents", 30000);
  const progress = useProgress();
  const [view, setView] = useState<ConversationView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [agent, setAgent] = useState("auto");
  const [query, setQuery] = useState("");
  const [attachments, setAttachments] = useState<AttachmentRef[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const [capture, setCapture] = useState<HTMLCanvasElement | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);  // kullanıcı yukarı kaydırmadıysa son mesaja yapış

  const pending = view?.messages.some((m) => ["pending", "running", "waiting_claude"].includes(m.status)) ?? false;
  const liveChars = Object.values(progress).reduce((a, p) => a + (p.answer?.length ?? 0), 0);

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

  // Son mesaja kay: kapsayıcının scrollTop'u ile (scrollIntoView klavyede Tab başlangıcını taşıyordu — Adım 14d);
  // akan cevapta da, kullanıcı yukarıdaysa zorla aşağı çekme
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [view?.messages.length, pending, liveChars]);
  useEffect(() => { stick.current = true; }, [convId]);

  // Mesaj kutusu yazdıkça büyür (en çok ~8 satır)
  useLayoutEffect(() => {
    const t = box.current;
    if (!t) return;
    t.style.height = "auto";
    t.style.height = `${Math.min(t.scrollHeight, 220)}px`;
  }, [text]);

  const choices = useMemo(
    () => (agents.data ?? []).filter((a) => a.output === "GeneralAnswer" && a.name !== "vision"),
    [agents.data],
  );
  const groups = useMemo(() => {
    const q = query.trim().toLocaleLowerCase("tr");
    const items = (list.data ?? []).filter((c) => !q || c.title.toLocaleLowerCase("tr").includes(q));
    return groupByDate(items);
  }, [list.data, query]);

  async function newChat() {
    const c = await post<Conversation>("/api/chat", {});
    setListKey((k) => k + 1);
    onSelect(c.id);
    box.current?.focus();
  }

  async function send(mode?: "analyze" | "summarize" | "invoice") {
    const defaults = { analyze: "Bu tabloyu analiz et ve öne çıkanları özetle.", summarize: "Bu belgeyi özetle.", invoice: "Bu faturanın bilgilerini çıkar." };
    const body = text.trim() || (mode ? defaults[mode] : "");
    if (!body || busy) return;
    setBusy(true);
    setError(null);
    stick.current = true;
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

  function suggest(s: (typeof SUGGESTIONS)[number]) {
    setText(s.text);
    if (s.agent && choices.some((a) => a.name === s.agent)) setAgent(s.agent);
    if (s.attach) fileInput.current?.click();
    box.current?.focus();
  }

  const empty = !view || view.messages.length === 0;
  return (
    <main className="chat">
      <aside className="chat-list" aria-labelledby="chat-list-title">
        <h2 id="chat-list-title" className="sr-only">Sohbetler</h2>
        <button className="toggle new-chat" onClick={() => void newChat()}><Icon name="plus" size={18} /> Yeni sohbet</button>
        <label className="search">
          <Icon name="search" size={16} />
          <input type="search" placeholder="Sohbetlerde ara" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Sohbetlerde ara" />
        </label>
        <nav className="conv-groups" aria-label="Sohbet listesi">
          {list.data?.length === 0 && <p className="muted small">Henüz sohbet yok.</p>}
          {list.data && list.data.length > 0 && groups.length === 0 && <p className="muted small">"{query}" bulunamadı.</p>}
          {groups.map((g) => (
            <section key={g.label} className="conv-group">
              <h3 className="group-label">{g.label}</h3>
              <ul>
                {g.items.map((c) => (
                  <li key={c.id} className={c.id === convId ? "active" : ""}>
                    <button className="conv" onClick={() => onSelect(c.id)} title={c.title} aria-current={c.id === convId ? "true" : undefined}>
                      <span className="conv-title">{c.title}</span>
                      <span className="muted when">{ago(c.updated_at)}</span>
                    </button>
                    <span className="conv-actions">
                      <button className="icon-btn sm" onClick={() => void rename(c)} aria-label={`${c.title}: yeniden adlandır`} title="Yeniden adlandır"><Icon name="edit" size={15} /></button>
                      <button className="icon-btn sm danger" onClick={() => void remove(c)} aria-label={`${c.title}: sil`} title="Sil"><Icon name="trash" size={15} /></button>
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </nav>
      </aside>

      <section className="chat-main" aria-labelledby="chat-messages-title">
        <h2 id="chat-messages-title" className="sr-only">Mesajlar</h2>
        <div className="messages" ref={scroller} aria-live="polite"
             onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80; }}>
          <div className="thread">
            {empty && !error && (
              <div className="welcome">
                <div className="welcome-logo" aria-hidden="true">◆</div>
                <h2>Ne yapalım?</h2>
                <p className="muted">Yerel modellerle, bilgisayarında çalışırım. "Otomatik" seçiliyse şef isteği uygun ajana verir ve cevabı gözden geçirtir.</p>
                <div className="suggestions">
                  {SUGGESTIONS.map((s) => (
                    <button key={s.title} className="suggestion" onClick={() => suggest(s)}>
                      <span className="sg-icon"><Icon name={s.icon} size={18} /></span>
                      <span className="sg-title">{s.title}</span>
                      <span className="sg-sub">{s.sub}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
            {view?.messages.map((m) => (
              <MessageView key={m.id} m={m} claude={claude} progress={progress} onHandoff={(x) => void handoff(x)} onRemember={(x) => void rememberMsg(x)}
                onReport={(x, f) => void report(x, f)} onOpenFlow={onOpenFlow} busy={busy} />
            ))}
          </div>
        </div>
        <div className="composer-wrap">
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
              ref={box}
              value={text}
              placeholder="kayaAI'ye yaz… (Enter gönderir, Shift+Enter yeni satır)"
              rows={1}
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
              <input ref={fileInput} type="file" multiple hidden onChange={(e) => void addFiles(e.target.files)} />
              <button className="icon-btn" onClick={() => fileInput.current?.click()} aria-label="Dosya ekle" title="Dosya ekle (metin, PDF, Excel/CSV, görüntü)"><Icon name="clip" /></button>
              <button className="icon-btn" onClick={() => void addFromFolder()} aria-label="Klasörden ekle" title="İzinli klasörden dosya ekle"><Icon name="folder" /></button>
              <button className="icon-btn" onClick={() => void captureScreen()} aria-label="Ekran görüntüsü" title="Ekrandan tek kare al (yerel görsel model yorumlar)"><Icon name="camera" /></button>
              <MicButton disabled={busy} onNotice={setNotice}
                onText={(t) => setText((prev) => (prev.trim() ? `${prev.trimEnd()} ${t}` : t))} />
              {attachments.some((a) => a.kind === "table") && (
                <button className="chip-btn" disabled={busy} onClick={() => void send("analyze")} title="Sayıları program hesaplar">Analiz et</button>
              )}
              {attachments.some((a) => a.kind === "pdf") && (
                <>
                  <button className="chip-btn" disabled={busy} onClick={() => void send("summarize")}>Özetle</button>
                  <button className="chip-btn" disabled={busy} onClick={() => void send("invoice")}>Fatura olarak oku</button>
                </>
              )}
              <span className="spacer" />
              <select className="agent-pick" value={agent} onChange={(e) => setAgent(e.target.value)} aria-label="Ajan">
                <option value="auto">Otomatik · şef seçer</option>
                {choices.map((a) => (
                  <option key={a.name} value={a.name}>{agentName(a.name)}{a.lifecycle === "temporary" ? " (geçici)" : ""}</option>
                ))}
              </select>
              <button className="send" disabled={busy || !text.trim()} onClick={() => void send()} aria-label="Gönder" title="Gönder (Enter)">
                <Icon name="send" size={18} />
              </button>
            </div>
          </div>
          <p className="composer-hint muted">Her şey bu bilgisayarda çalışır. Hafıza ve belgeler otomatik aranır; kullanılırsa cevabın altında görünür.</p>
        </div>
      </section>
    </main>
  );
}
