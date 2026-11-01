import { useEffect, useRef, useState } from "react";

/**
 * Ekrandan tek kare (Adım 12a). Tarayıcının kendi izinli API'si: `getDisplayMedia` → sahip ekranı/pencereyi/sekmeyi
 * seçer (tarayıcı "paylaşılıyor" göstergesini gösterir) → tek kare alınır → akış HEMEN kapatılır. Sürekli kayıt yok.
 */
export async function grabScreenFrame(): Promise<HTMLCanvasElement> {
  const md = navigator.mediaDevices as MediaDevices & { getDisplayMedia?: (c?: DisplayMediaStreamOptions) => Promise<MediaStream> };
  if (!md?.getDisplayMedia) throw new Error("Bu tarayıcı ekran yakalamayı desteklemiyor (Edge/Chrome kullan).");
  const stream = await md.getDisplayMedia({ video: true, audio: false });
  try {
    const video = document.createElement("video");
    video.muted = true;
    video.srcObject = stream;
    await video.play();
    await new Promise((r) => setTimeout(r, 250)); // seçim penceresi kapansın, ilk kare otursun
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")!.drawImage(video, 0, 0);
    video.pause();
    return canvas;
  } finally {
    stream.getTracks().forEach((t) => t.stop());
  }
}

interface Rect { x: number; y: number; w: number; h: number }

/** Alınan kareyi gösterir; isteğe bağlı fareyle alan seçilir. "Ekle" PNG'yi base64 olarak döndürür. */
export function CapturePreview({ canvas, onAdd, onCancel }: {
  canvas: HTMLCanvasElement;
  onAdd: (b64: string, name: string) => void;
  onCancel: () => void;
}) {
  const view = useRef<HTMLCanvasElement>(null);
  const [sel, setSel] = useState<Rect | null>(null);
  const drag = useRef<{ x: number; y: number } | null>(null);
  const scale = Math.min(1, 900 / canvas.width, 520 / canvas.height);
  const first = useRef<HTMLButtonElement>(null);

  useEffect(() => {  // Adım 14d: açılınca odak pencerede, Escape kapatır, kapanınca odak geri döner
    const prev = document.activeElement as HTMLElement | null;
    first.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); prev?.focus?.(); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const v = view.current!;
    v.width = Math.round(canvas.width * scale);
    v.height = Math.round(canvas.height * scale);
    const g = v.getContext("2d")!;
    g.drawImage(canvas, 0, 0, v.width, v.height);
    if (sel && sel.w > 4 && sel.h > 4) {
      g.fillStyle = "rgba(0,0,0,.45)";
      g.fillRect(0, 0, v.width, v.height);
      g.drawImage(canvas, sel.x / scale, sel.y / scale, sel.w / scale, sel.h / scale, sel.x, sel.y, sel.w, sel.h);
      g.strokeStyle = "#4f8cff";
      g.lineWidth = 2;
      g.strokeRect(sel.x, sel.y, sel.w, sel.h);
    }
  }, [canvas, scale, sel]);

  function pos(e: React.PointerEvent) {
    const r = view.current!.getBoundingClientRect();
    return { x: Math.max(0, Math.min(r.width, e.clientX - r.left)), y: Math.max(0, Math.min(r.height, e.clientY - r.top)) };
  }

  function add(cropped: boolean) {
    let out = canvas;
    if (cropped && sel && sel.w > 4 && sel.h > 4) {
      out = document.createElement("canvas");
      out.width = Math.round(sel.w / scale);
      out.height = Math.round(sel.h / scale);
      out.getContext("2d")!.drawImage(canvas, sel.x / scale, sel.y / scale, out.width, out.height, 0, 0, out.width, out.height);
    }
    const b64 = out.toDataURL("image/png").split(",", 2)[1] ?? "";
    const d = new Date();
    const p = (n: number) => String(n).padStart(2, "0");
    onAdd(b64, `ekran-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}.png`);
  }

  const hasSel = !!sel && sel.w > 4 && sel.h > 4;
  return (
    <div className="modal-back" role="dialog" aria-modal="true" aria-label="Ekran görüntüsü">
      <div className="modal capture">
        <div className="panel-head">
          <h2>Ekran görüntüsü</h2>
          <span className="muted small">{canvas.width}×{canvas.height} · yalnızca bu kare alındı, paylaşım kapatıldı</span>
        </div>
        <p className="muted small">İstersen fareyle bir alan seç (yalnız o kısım gönderilir). Görüntü bu bilgisayarda yerel modelle yorumlanır; Claude'a gönderilmez.</p>
        <canvas ref={view} className="capture-canvas" role="img" aria-label="Yakalanan ekran; fareyle alan seçilebilir"
          onPointerDown={(e) => { const p = pos(e); drag.current = p; setSel({ x: p.x, y: p.y, w: 0, h: 0 }); (e.target as HTMLElement).setPointerCapture(e.pointerId); }}
          onPointerMove={(e) => { if (!drag.current) return; const p = pos(e); const s = drag.current; setSel({ x: Math.min(s.x, p.x), y: Math.min(s.y, p.y), w: Math.abs(p.x - s.x), h: Math.abs(p.y - s.y) }); }}
          onPointerUp={() => { drag.current = null; }} />
        <div className="row-actions">
          <button className="ghost" onClick={onCancel}>Vazgeç</button>
          {hasSel && <button className="ghost" onClick={() => setSel(null)}>Seçimi temizle</button>}
          <button ref={first} onClick={() => add(false)}>Tamamını ekle</button>
          <button className="toggle" disabled={!hasSel} onClick={() => add(true)}>Seçili alanı ekle</button>
        </div>
      </div>
    </div>
  );
}
