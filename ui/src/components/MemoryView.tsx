import { useMemo, useState } from "react";
import { EmptyState } from "./EmptyState";
import { api, post, type DocumentsView, type MemCategory, type MemoryItem, type RecallView, type Sensitivity } from "../api";
import { MEM_CATEGORY_LABEL, SENSITIVITY_LABEL, ago } from "../format";
import { usePolling } from "../hooks";

const CATEGORIES = Object.keys(MEM_CATEGORY_LABEL) as MemCategory[];
const SENSITIVITIES = Object.keys(SENSITIVITY_LABEL) as Sensitivity[];
const SOURCE: Record<string, string> = { owner: "sen", chat: "sohbet", claude: "Claude önerisi" };

function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function ItemRow({ m, onChanged }: { m: MemoryItem; onChanged: (msg?: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [reveal, setReveal] = useState(false);
  const [revealed, setRevealed] = useState<string | null>(null);
  const [text, setText] = useState(m.text);
  const [category, setCategory] = useState<MemCategory>(m.category);
  const [sensitivity, setSensitivity] = useState<Sensitivity>(m.sensitivity);
  const [error, setError] = useState<string | null>(null);
  const secret = m.sensitivity === "secret";

  async function toggleReveal() {
    if (reveal) { setReveal(false); return; }
    try {
      const full = await api<MemoryItem>(`/api/memory/${m.id}/reveal`);
      setRevealed(full.text);
      setText(full.text);
      setReveal(true);
    } catch (e) {
      setError(errText(e));
    }
  }

  async function save() {
    try {
      await api(`/api/memory/${m.id}`, {
        method: "PATCH",
        body: JSON.stringify({ text, category, sensitivity, allow_secret: sensitivity === "secret" }),
      });
      setEditing(false);
      onChanged("Güncellendi");
    } catch (e) {
      setError(errText(e));
    }
  }

  async function remove() {
    if (!window.confirm("Bu hafıza öğesi kalıcı olarak silinsin mi?")) return;
    await api(`/api/memory/${m.id}`, { method: "DELETE" });
    onChanged("Silindi");
  }

  async function approve() {
    await post(`/api/memory/${m.id}/approve`, {});
    onChanged("Onaylandı");
  }

  return (
    <li className={`mem-item sens-${m.sensitivity}`}>
      {editing ? (
        <div className="mem-edit">
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} maxLength={1000} aria-label="Metin" />
          <select value={category} onChange={(e) => setCategory(e.target.value as MemCategory)} aria-label="Kategori">
            {CATEGORIES.map((c) => <option key={c} value={c}>{MEM_CATEGORY_LABEL[c]}</option>)}
          </select>
          <select value={sensitivity} onChange={(e) => setSensitivity(e.target.value as Sensitivity)} aria-label="Hassasiyet">
            {SENSITIVITIES.map((s) => <option key={s} value={s}>{SENSITIVITY_LABEL[s]}</option>)}
          </select>
          <button className="approve small" onClick={() => void save()}>Kaydet</button>
          <button className="ghost small" onClick={() => { setEditing(false); setText(m.text); }}>Vazgeç</button>
          {error && <p className="error">{error}</p>}
        </div>
      ) : (
        <>
          <p className="mem-text">{secret ? (reveal ? revealed : "•••••••• (gizli)") : m.text}</p>
          <div className="mem-meta">
            <span className="badge">{MEM_CATEGORY_LABEL[m.category]}</span>
            <span className={`badge sens sens-${m.sensitivity}`}>{SENSITIVITY_LABEL[m.sensitivity]}</span>
            <span className="muted">{SOURCE[m.source] ?? m.source} · {ago(m.created_at)}</span>
            {!m.embedded && <span className="muted" title="bge-m3 kurulu değilken eklendi">· yalnızca kelime araması</span>}
            <span className="spacer" />
            {secret && <button className="ghost small" onClick={() => void toggleReveal()}>{reveal ? "Gizle" : "Göster"}</button>}
            {m.status === "proposed" && <button className="approve small" onClick={() => void approve()}>Onayla</button>}
            <button className="ghost small" disabled={secret && !reveal} title={secret && !reveal ? "Önce Göster" : ""} onClick={() => setEditing(true)}>Düzenle</button>
            <button className="ghost small danger" onClick={() => void remove()}>Sil</button>
          </div>
        </>
      )}
    </li>
  );
}

export function MemoryView({ refreshKey }: { refreshKey: number }) {
  const [key, setKey] = useState(0);
  const items = usePolling<MemoryItem[]>("/api/memory?status=all", 30000, `${key}-${refreshKey}`);
  const docs = usePolling<DocumentsView>("/api/documents", 30000, `${key}-${refreshKey}`);
  const [text, setText] = useState("");
  const [category, setCategory] = useState<MemCategory>("note");
  const [sensitivity, setSensitivity] = useState<Sensitivity>("personal");
  const [secret, setSecret] = useState(false);
  const [filter, setFilter] = useState("");
  const [catFilter, setCatFilter] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<RecallView | null>(null);
  const [indexing, setIndexing] = useState(false);

  const changed = (msg?: string) => { setKey((k) => k + 1); if (msg) setNotice(msg); };
  const proposed = (items.data ?? []).filter((m) => m.status === "proposed");
  const active = useMemo(() => {
    const f = filter.trim().toLocaleLowerCase("tr");
    return (items.data ?? []).filter((m) => m.status === "active"
      && (!catFilter || m.category === catFilter)
      && (!f || (m.sensitivity !== "secret" && m.text.toLocaleLowerCase("tr").includes(f))));
  }, [items.data, filter, catFilter]);

  async function addManual() {
    if (!text.trim()) return;
    setBusy(true);
    setNotice(null);
    try {
      await post("/api/memory", { text: text.trim(), category, sensitivity: secret ? "secret" : sensitivity, allow_secret: secret });
      setText("");
      setSecret(false);
      changed("Hafızaya eklendi.");
    } catch (e) {
      setNotice(errText(e));
    } finally {
      setBusy(false);
    }
  }

  async function addSmart() {
    if (!text.trim()) return;
    setBusy(true);
    setNotice(null);
    try {
      const r = await post<{ message: string }>("/api/memory/from-text", { text: text.trim() });
      setText("");
      changed(r.message.replace(/\*/g, ""));
    } catch (e) {
      setNotice(errText(e));
    } finally {
      setBusy(false);
    }
  }

  async function exportAll() {
    const data = await api<unknown>("/api/memory-export");
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `kayaai-hafiza-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function reindex() {
    setIndexing(true);
    try {
      await post("/api/documents/index", {});
      setNotice("Dizinleme başladı; bitince liste güncellenir.");
    } catch (e) {
      setNotice(errText(e));
    } finally {
      setTimeout(() => setIndexing(false), 1500);
    }
  }

  async function search() {
    if (!query.trim()) return;
    try {
      setFound(await api<RecallView>(`/api/memory-search?q=${encodeURIComponent(query.trim())}`));
    } catch (e) {
      setNotice(errText(e));
    }
  }

  const st = docs.data?.status;
  return (
    <main className="grid">
      <div className="col">
        <section className="panel" aria-labelledby="mem-add">
          <h2 id="mem-add">Hafızaya ekle</h2>
          <p className="muted">
            Sohbette <code>hatırla: …</code> yazarak da ekleyebilirsin. Her şey bu bilgisayarda kalır. <strong>Özel</strong> öğeler
            Claude'a gönderilmez; <strong>gizli</strong> öğeler hiçbir sohbete otomatik girmez.
          </p>
          <textarea className="mem-input" value={text} onChange={(e) => setText(e.target.value)} rows={3} maxLength={1000}
            placeholder="Ör. Raporları her zaman PDF olarak isterim." aria-label="Hafıza metni" />
          <div className="decide">
            <select value={category} onChange={(e) => setCategory(e.target.value as MemCategory)} aria-label="Kategori">
              {CATEGORIES.map((c) => <option key={c} value={c}>{MEM_CATEGORY_LABEL[c]}</option>)}
            </select>
            <select value={sensitivity} disabled={secret} onChange={(e) => setSensitivity(e.target.value as Sensitivity)} aria-label="Hassasiyet">
              {SENSITIVITIES.filter((s) => s !== "secret").map((s) => <option key={s} value={s}>{SENSITIVITY_LABEL[s]}</option>)}
            </select>
            <label className="muted"><input type="checkbox" checked={secret} onChange={(e) => setSecret(e.target.checked)} /> gizli olarak kaydet (açık izin)</label>
            <button className="approve" disabled={busy || !text.trim()} onClick={() => void addManual()}>Kaydet</button>
            <button className="ghost" disabled={busy || !text.trim() || secret} onClick={() => void addSmart()} title="Yerel model metni kısa bir nota çevirir ve sınıflandırır">
              Otomatik sınıflandır
            </button>
          </div>
          {notice && <p className="notice" role="status">{notice}</p>}
        </section>

        {proposed.length > 0 && (
          <section className="panel" aria-labelledby="mem-prop">
            <h2 id="mem-prop">Onay bekleyen öneriler <span className="count">{proposed.length}</span></h2>
            <p className="muted">Claude ya da ajanlar önerdi; onaylamadığın sürece hiçbir cevapta kullanılmaz.</p>
            <ul className="mem-list">{proposed.map((m) => <ItemRow key={m.id} m={m} onChanged={changed} />)}</ul>
          </section>
        )}

        <section className="panel" aria-labelledby="mem-list">
          <div className="panel-head">
            <h2 id="mem-list">Hafıza ({active.length})</h2>
            <button className="ghost small" onClick={() => void exportAll()}>Dışa aktar (JSON)</button>
          </div>
          <div className="decide">
            <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Süz…" aria-label="Süz" />
            <select value={catFilter} onChange={(e) => setCatFilter(e.target.value)} aria-label="Kategori süz">
              <option value="">tüm kategoriler</option>
              {CATEGORIES.map((c) => <option key={c} value={c}>{MEM_CATEGORY_LABEL[c]}</option>)}
            </select>
          </div>
          {items.data && active.length === 0 && (
            <EmptyState icon="memory" title="Burada henüz bir şey yok">
              Yukarıdan ekle ya da sohbette <code>hatırla: …</code> yaz. Süzgeç açıksa onu temizle.
            </EmptyState>
          )}
          <ul className="mem-list">{active.map((m) => <ItemRow key={m.id} m={m} onChanged={changed} />)}</ul>
        </section>
      </div>

      <div className="col">
        <section className="panel" aria-labelledby="doc-title">
          <div className="panel-head">
            <h2 id="doc-title">Belgeler (arama dizini)</h2>
            <button className="toggle small" disabled={indexing} onClick={() => void reindex()}>Şimdi dizinle</button>
          </div>
          {st && (
            <>
              <p className="muted">
                {st.documents} dosya · {st.chunks} parça · son dizinleme {ago(st.last_indexed)} · model {st.embed_model}
                {st.not_embedded > 0 && ` · ${st.not_embedded} dosya yalnızca kelime aramasında (bge-m3 kurulu değildi)`}
              </p>
              <p className="muted">Klasörler: {st.roots.map((r) => <code key={r}>{r}</code>)}</p>
              <p className="muted">Metin dosyaları (md, txt, csv, kod…), PDF ve Excel dizinlenir; .env, anahtar dosyaları ve parola geçen parçalar atlanır.</p>
            </>
          )}
          {docs.data && docs.data.documents.length === 0 && <p className="muted">Henüz dizinlenmiş belge yok. Klasöre dosya koyup "Şimdi dizinle"ye bas.</p>}
          <ul className="doc-list">
            {docs.data?.documents.map((d) => (
              <li key={d.id}>
                <span className="doc-name" title={d.path}>{d.path.split(/[\\/]/).pop()}</span>
                <span className="muted">{d.chunks} parça{d.skipped_secret_chunks ? ` · ${d.skipped_secret_chunks} gizli parça atlandı` : ""}{d.embedded ? "" : " · kelime"}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="panel" aria-labelledby="mem-search">
          <h2 id="mem-search">Hafızada ara</h2>
          <form className="decide" onSubmit={(e) => { e.preventDefault(); void search(); }}>
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Ör. Atlas ne zaman teslim?" aria-label="Arama" />
            <button type="submit" className="ghost">Ara</button>
          </form>
          {found && (
            <div className="found">
              {found.memories.length === 0 && found.documents.length === 0 && <p className="muted">İlgili bir şey bulunamadı.</p>}
              {found.memories.map((m) => <p key={m.id}><span className="badge">{m.score.toFixed(2)}</span> {m.text}</p>)}
              {found.documents.map((d) => (
                <p key={d.chunk_id}><span className="badge">{d.score.toFixed(2)}</span> <code>{d.name}:{d.line}</code> {d.text.slice(0, 160)}</p>
              ))}
              {found.warnings.map((w, i) => <p key={i} className="warnings">{w}</p>)}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
