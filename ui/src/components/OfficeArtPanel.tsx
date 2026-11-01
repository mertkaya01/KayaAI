import type { OfficeAssets } from "../office/scene";
import { usePolling } from "../hooks";

/** Ofis çizimleri (Adım 18d): sahibin data\ofis klasörüne koyduğu resimler — hangi dosya bulundu, hangisi bekleniyor. */
const CHARACTERS: [string, string, string][] = [
  ["sef", "chef", "Şef"], ["sen", "owner", "Sen"], ["genel", "general", "Genel"], ["veri", "data", "Veri"],
  ["belge", "document", "Belge"], ["kod", "coder", "Kod"], ["gorsel", "vision", "Görsel"], ["denetci", "reviewer", "Denetçi"],
  ["claude", "claude", "Claude"], ["ajan", "default", "Diğer ajanlar"],
];
const STATES: [string, string][] = [["calisiyor", "working"], ["bekliyor", "waiting"], ["yuruyor", "walking"], ["hata", "error"], ["bitti", "done"]];

export function OfficeArtPanel({ onClose }: { onClose: () => void }) {
  const a = usePolling<OfficeAssets>("/api/office/assets", 0);
  const d = a.data;
  return (
    <section className="panel art-panel" aria-labelledby="art-title">
      <div className="panel-head">
        <h2 id="art-title">Ofis çizimleri</h2>
        <span className="row-actions">
          <button className="ghost small" onClick={() => void a.reload()}>Yenile</button>
          <button className="ghost small" onClick={onClose} aria-label="Çizimler panelini kapat">✕</button>
        </span>
      </div>
      <p className="muted small">
        Çizimlerini şu klasöre koy, sonra <strong>Yenile</strong>: <code>{d?.folder ?? "data\\ofis"}</code>
        {d && !d.exists && <> — klasör henüz yok, oluşturman yeterli.</>}
      </p>
      <p className="muted small">
        Biçim: arka planı şeffaf <strong>PNG</strong> (ya da SVG/WEBP), en çok 5 MB, küçük harfli Türkçe ad. Karakter yaklaşık
        <strong> 96×128</strong> px (ayakları alt ortada), masa ~<strong>160×140</strong>, zemin karosu <strong>96×48</strong> (izometrik).
        Durum resimleri isteğe bağlı: yoksa karakterin genel resmi kullanılır, o da yoksa şimdiki şekil.
      </p>
      <div className="table-wrap">
        <table className="mtable art-table">
          <thead><tr><th>Karakter</th><th>Genel</th>{STATES.map(([tr]) => <th key={tr}>-{tr}</th>)}</tr></thead>
          <tbody>
            {CHARACTERS.map(([file, id, label]) => {
              const have = d?.actors[id] ?? {};
              return (
                <tr key={id}>
                  <td><strong>{label}</strong> <span className="muted small">{file}.png</span></td>
                  <td>{have.base ? <img src={have.base} alt={`${label} çizimi`} className="art-thumb" /> : <span className="muted">—</span>}</td>
                  {STATES.map(([, st]) => <td key={st}>{have[st] ? <img src={have[st]} alt={`${label} ${st}`} className="art-thumb" /> : <span className="muted">—</span>}</td>)}
                </tr>
              );
            })}
            <tr>
              <td><strong>Masa</strong> <span className="muted small">masa.png</span></td>
              <td>{d?.desk ? <img src={d.desk} alt="Masa çizimi" className="art-thumb" /> : <span className="muted">—</span>}</td>
              <td colSpan={STATES.length} />
            </tr>
            <tr>
              <td><strong>Zemin</strong> <span className="muted small">zemin.png</span></td>
              <td>{d?.floor ? <img src={d.floor} alt="Zemin çizimi" className="art-thumb" /> : <span className="muted">—</span>}</td>
              <td colSpan={STATES.length} />
            </tr>
          </tbody>
        </table>
      </div>
      {d && d.unknown.length > 0 && <p className="warn-text small">Tanınmayan ad (kullanılmadı): {d.unknown.join(", ")}</p>}
      {d && d.skipped.length > 0 && <p className="warn-text small">Atlandı (tür/boyut/ad uygun değil): {d.skipped.join(", ")}</p>}
    </section>
  );
}
