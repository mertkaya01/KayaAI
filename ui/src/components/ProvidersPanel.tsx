import { useEffect, useState } from "react";
import { api, del, post, put, type Approval, type ProviderRow, type ProvidersStatus, type SubmitResult } from "../api";
import { usePolling } from "../hooks";

/**
 * Dış sağlayıcılar (Adım 20a; sahip kararı): Groq, OpenRouter, OmniRoute gibi OpenAI uyumlu servisler.
 * Kapalıyken hiçbir şey dışarı gitmez; her sağlayıcı sahip onayıyla açılır (R2), yalnız sahip seçince kullanılır.
 * Anahtar bir kez girilir (Windows Kimlik Bilgisi Yöneticisi), bir daha gösterilmez.
 */

function err(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** Satır içi sahip onayı (önizlemeyle): sağlayıcı açma ve ajan atama. Onay merkezinde de görünür. */
export function InlineApproval({ id, title, okLabel, onDone }: { id: string; title: string; okLabel: string; onDone: (msg: string) => void }) {
  const [a, setA] = useState<Approval | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { void api<Approval>(`/api/approvals/${id}`).then(setA).catch(() => setA(null)); }, [id]);
  async function decide(ok: boolean) {
    setBusy(true);
    try {
      await post(`/api/approvals/${id}/${ok ? "approve" : "reject"}`, {});
      onDone(ok ? "Onaylandı." : "Talep reddedildi.");
    } catch (e) { onDone(err(e)); } finally { setBusy(false); }
  }
  return (
    <div className="inbox-wait" role="group" aria-label={title}>
      <p className="small"><strong>{title}</strong> Onaylarsan aşağıdaki kurallarla geçerli olur:</p>
      {typeof a?.action.preview?.new_head === "string" && <pre className="prov-preview">{a.action.preview.new_head}</pre>}
      <div className="row-actions start">
        <button className="primary small" disabled={busy} onClick={() => void decide(true)}>{okLabel}</button>
        <button className="ghost small" disabled={busy} onClick={() => void decide(false)}>Reddet</button>
      </div>
    </div>
  );
}

function ProviderCard({ p, onChanged }: { p: ProviderRow; onChanged: () => void }) {
  const [keyOpen, setKeyOpen] = useState(false);
  const [key, setKey] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<string | null>) {
    setBusy(true);
    setMsg(null);
    try { setMsg(await fn()); onChanged(); } catch (e) { setMsg(err(e)); } finally { setBusy(false); }
  }

  const state = p.enabled ? "açık" : p.pending_approval ? "onay bekliyor" : "kapalı";
  return (
    <article className="prov" aria-labelledby={`prov-${p.id}`}>
      <div className="prov-head">
        <h3 id={`prov-${p.id}`}>{p.label}</h3>
        <span className={`pill ${p.internet ? "warn" : ""}`}>{p.internet ? "internet" : "bu bilgisayar"}</span>
        <span className={`pill ${p.enabled ? "ok" : ""}`}>{state}</span>
      </div>
      <p className="muted small">
        <code>{p.base_url}</code> · anahtar {p.has_key ? (p.key_source === "env" ? "ortam değişkeninde" : "kayıtlı") : <strong>yok</strong>}
        {" "}· bugün {p.used_today}/{p.daily_limit} çağrı · {p.models.length ? `${p.models.length} model` : "henüz denenmedi"}
      </p>
      {keyOpen && (
        <form className="row-actions start" onSubmit={(e) => {
          e.preventDefault();
          void run(async () => { await put(`/api/providers/${p.id}/key`, { key }); setKey(""); setKeyOpen(false); return "Anahtar kaydedildi (bir daha gösterilmez)."; });
        }}>
          <label className="sr-only" htmlFor={`key-${p.id}`}>{p.label} API anahtarı</label>
          <input id={`key-${p.id}`} type="password" autoComplete="off" spellCheck={false} placeholder="API anahtarı" value={key}
                 onChange={(e) => setKey(e.target.value)} className="prov-key" />
          <button className="primary small" disabled={busy || !key.trim()}>Kaydet</button>
          <button type="button" className="ghost small" onClick={() => { setKey(""); setKeyOpen(false); }}>Vazgeç</button>
        </form>
      )}
      {p.models.length > 0 && (
        <label className="field small prov-model">Varsayılan model
          <select value={p.default_model} disabled={busy} onChange={(e) => {
            const v = e.target.value;
            void run(async () => { await post(`/api/providers/${p.id}/settings`, { default_model: v }); return null; });
          }}>
            {p.models.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </label>
      )}
      {p.pending_approval && <InlineApproval id={p.pending_approval} title="Açma talebi onay bekliyor." okLabel="Onayla ve aç"
                                             onDone={(m) => { setMsg(m === "Onaylandı." ? "Açıldı." : m); onChanged(); }} />}
      <div className="row-actions start">
        <button className="small" disabled={busy} onClick={() => setKeyOpen((v) => !v)} aria-expanded={keyOpen}>
          {p.has_key ? "Anahtarı değiştir" : "Anahtar gir"}
        </button>
        <button className="small" disabled={busy || (p.internet && !p.has_key)} onClick={() => void run(async () => {
          const r = await post<{ ok: boolean; models?: string[]; error?: string; ms?: number }>(`/api/providers/${p.id}/test`, {});
          return r.ok ? `Bağlantı tamam (${r.ms} ms) · ${r.models?.length ?? 0} model. Senin verin gönderilmedi.` : `Bağlanamadı: ${r.error}`;
        })}>Bağlantıyı dene</button>
        {p.enabled ? (
          <button className="small" disabled={busy} onClick={() => void run(async () => { await post(`/api/providers/${p.id}/disable`, {}); return "Kapatıldı."; })}>Kapat</button>
        ) : !p.pending_approval && (
          <button className="primary small" disabled={busy || (p.internet && !p.has_key)} title={p.internet && !p.has_key ? "Önce anahtarı gir" : undefined}
                  onClick={() => void run(async () => {
                    const r = await post<SubmitResult>(`/api/providers/${p.id}/enable`, {});
                    return r.status === "awaiting_approval" ? null : r.message;
                  })}>Aç…</button>
        )}
        <button className="small danger" disabled={busy} onClick={() => {
          if (!window.confirm(`${p.label} silinsin mi? Kayıtlı anahtarı da silinir.`)) return;
          void run(async () => { await del(`/api/providers/${p.id}`); return null; });
        }}>Sil</button>
      </div>
      {msg && <p className="note small" role="status">{msg}</p>}
    </article>
  );
}

export function ProvidersPanel({ refreshKey }: { refreshKey: number }) {
  const [key, setKey] = useState(0);
  const st = usePolling<ProvidersStatus>("/api/providers", 30000, `${refreshKey}-${key}`);
  const [preset, setPreset] = useState("groq");
  const [label, setLabel] = useState("");
  const [url, setUrl] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const data = st.data;
  const open = data?.providers.filter((p) => p.enabled).length ?? 0;
  const chosen = data?.presets.find((x) => x.preset === preset);

  async function add() {
    setBusy(true);
    setMsg(null);
    try {
      const body = preset === "custom" ? { preset, label: label.trim() || "Özel", base_url: url.trim() } : { preset };
      await post("/api/providers", body);
      setLabel(""); setUrl("");
      setMsg("Eklendi. Sıradaki: anahtarı gir, bağlantıyı dene, sonra aç.");
      setKey((k) => k + 1);
    } catch (e) { setMsg(err(e)); } finally { setBusy(false); }
  }

  return (
    <section className="panel" aria-labelledby="providers-title">
      <div className="panel-head">
        <h2 id="providers-title">Dış sağlayıcılar</h2>
        <span className={`pill ${open ? "warn" : ""}`}>{open ? `${open} açık` : "hepsi kapalı"}</span>
      </div>
      <p className="muted small">
        Groq, OpenRouter, OmniRoute gibi OpenAI uyumlu servisler. Kapalıyken hiçbir şey dışarı gitmez; her sağlayıcı senin onayınla
        açılır ve yalnız sen seçince kullanılır. <strong>Asla gitmez:</strong> hafızan, belgelerin, ekran görüntüleri, bilgisayar ölçümü;
        gizli bilgi görülen istek yerelde yapılır. Anahtarlar: {data?.key_backend ?? "…"}.
      </p>
      {data?.providers.map((p) => <ProviderCard key={p.id} p={p} onChanged={() => setKey((k) => k + 1)} />)}
      <div className="prov-add">
        <label className="field small">Sağlayıcı ekle
          <select value={preset} onChange={(e) => setPreset(e.target.value)}>
            {data?.presets.map((x) => <option key={x.preset} value={x.preset}>{x.label}</option>)}
          </select>
        </label>
        {preset === "custom" && (
          <>
            <label className="field small">Ad<input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={60} /></label>
            <label className="field small">Adres (…/v1)<input value={url} onChange={(e) => setUrl(e.target.value)} spellCheck={false} placeholder="https://…/v1" /></label>
          </>
        )}
        <button className="small" disabled={busy || (preset === "custom" && !url.trim())} onClick={() => void add()}>Ekle</button>
      </div>
      {chosen?.note && <p className="muted small">{chosen.label}: {chosen.note}</p>}
      {msg && <p className="note small" role="status">{msg}</p>}
    </section>
  );
}
