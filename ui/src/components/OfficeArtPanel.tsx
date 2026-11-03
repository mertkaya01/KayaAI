import type { OfficeAssets } from "../office/scene";
import { usePolling } from "../hooks";

/** Ofis çizimleri (Adım 18d): sahibin data\ofis klasörüne koyduğu resimler — hangi dosya bulundu, hangisi bekleniyor. */
const CHARACTERS: [string, string, string][] = [
  ["sef", "chef", "Şef"], ["sen", "owner", "Sen"], ["genel", "general", "Genel"], ["veri", "data", "Veri"],
  ["belge", "document", "Belge"], ["kod", "coder", "Kod"], ["gorsel", "vision", "Görsel"], ["denetci", "reviewer", "Denetçi"],
  ["claude", "claude", "Claude"], ["ajan", "default", "Diğer ajanlar"],
];
const STATES: [string, string][] = [["calisiyor", "working"], ["bekliyor", "waiting"], ["yuruyor", "walking"], ["hata", "error"], ["bitti", "done"]];
// "-yuruyor" sütununda yönlü yürüme çizimleri de görünür (tek -yuruyor yoksa yalnız yönlüler)
const WALK_DIRS: [string, string][] = [["walk_down", "aşağı"], ["walk_up", "yukarı"], ["walk_left", "sol"], ["walk_right", "sağ"]];

function Thumb({ src, alt }: { src: string; alt: string }) {
  return <img src={src} alt={alt} title={alt} className="art-thumb" />;
}

function Cell({ have, st, label }: { have: Record<string, string>; st: string; label: string }) {
  const imgs: [string, string][] = have[st] ? [[have[st], `${label} ${st}`]] : [];
  if (st === "walking") for (const [k, dir] of WALK_DIRS) if (have[k]) imgs.push([have[k], `${label} yürüyor (${dir})`]);
  if (!imgs.length) return <span className="muted">—</span>;
  return <span className="art-thumbs">{imgs.map(([src, alt]) => <Thumb key={src} src={src} alt={alt} />)}</span>;
}

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
        Pixel stil, önden-üstten (hazır çizimler gibi). Arka planı şeffaf <strong>PNG</strong>, en çok 5 MB, küçük harfli Türkçe ad.
        Kare <strong>64×64</strong>: masada oturan (arkadan) — masanın altı 61. satırda; yürüyen — ayak 48. satırda. Animasyon için
        kareleri <strong>yan yana</strong> koy (ör. 4 kare → 256×64). Zemin karosu <strong>16×16</strong> (32×32, 64×64 de olur).
        Yürüme yönlü de olur: <code>-yuruyor-sol</code>, <code>-sag</code>, <code>-yukari</code>, <code>-asagi</code> (tek
        <code>-yuruyor</code> sola yansıtılır); yönler farklı boyda çizildiyse sahnede aynı boya getirilir.
        Olmayan resim yerine hazır çizim kullanılır. <code>masa.png</code> herkesin masasını değiştirir (kişi üstüne oturur);
        eşyalar: <code>su</code>, <code>dolap</code>, <code>kahve</code>, <code>yazici</code>, <code>bitki</code>, <code>cop</code>, <code>lavabo</code>.
        Büyük ya da yapay zekâyla üretilmiş resimleri önce çevir: <code>kayaai ofis ice-aktar resim.png ad</code>.
        Ayrıntı: <code>docs/OFIS_CIZIM.md</code>.
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
                  <td>{have.base ? <Thumb src={have.base} alt={`${label} çizimi`} /> : <span className="muted">—</span>}</td>
                  {STATES.map(([, st]) => <td key={st}><Cell have={have} st={st} label={label} /></td>)}
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
