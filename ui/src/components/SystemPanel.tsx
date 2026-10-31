import { useEffect, useState } from "react";
import type { Health, SystemMetrics } from "../api";
import { gb, pct, pushSample } from "../format";

function Sparkline({ values, max = 100 }: { values: number[]; max?: number }) {
  const w = 160;
  const h = 36;
  if (values.length < 2) return <svg className="spark" width={w} height={h} aria-hidden />;
  const step = w / (values.length - 1);
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${(h - (Math.min(v, max) / max) * (h - 2) - 1).toFixed(1)}`);
  return (
    <svg className="spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden>
      <polyline points={pts.join(" ")} fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

function Meter({ label, value, detail, history }: { label: string; value: number | null; detail: string; history: number[] }) {
  const level = value === null ? "" : value >= 90 ? "crit" : value >= 70 ? "warn" : "ok";
  return (
    <div className={`meter ${level}`}>
      <div className="meter-head">
        <span className="meter-label">{label}</span>
        <span className="meter-value">{pct(value)}</span>
      </div>
      <div className="bar" role="progressbar" aria-label={label} aria-valuenow={value ?? 0} aria-valuemin={0} aria-valuemax={100}>
        <span style={{ width: `${Math.min(100, value ?? 0)}%` }} />
      </div>
      <div className="meter-foot">
        <span className="muted">{detail}</span>
        <Sparkline values={history} />
      </div>
    </div>
  );
}

export function SystemPanel({ metrics, health }: { metrics: SystemMetrics | null; health: Health | null }) {
  const [hist, setHist] = useState({ cpu: [] as number[], ram: [] as number[], gpu: [] as number[], vram: [] as number[] });

  useEffect(() => {
    if (!metrics) return;
    const g = metrics.gpus[0];
    setHist((h) => ({
      cpu: pushSample(h.cpu, metrics.cpu_pct),
      ram: pushSample(h.ram, metrics.ram_used_pct),
      gpu: g?.utilization_pct != null ? pushSample(h.gpu, g.utilization_pct) : h.gpu,
      vram: g?.vram_used_pct != null ? pushSample(h.vram, g.vram_used_pct) : h.vram,
    }));
  }, [metrics]);

  if (!metrics) return <section className="panel"><h2>Sistem</h2><p className="muted">Yükleniyor…</p></section>;
  const g = metrics.gpus[0];
  const loaded = health?.ollama.loaded_models ?? [];

  return (
    <section className="panel" aria-labelledby="sys-title">
      <h2 id="sys-title">Sistem</h2>
      <div className="meters">
        <Meter label="CPU" value={metrics.cpu_pct} detail={`${metrics.cpu_logical_cores} çekirdek`} history={hist.cpu} />
        <Meter label="RAM" value={metrics.ram_used_pct} detail={`${metrics.ram_used_gb} / ${metrics.ram_total_gb} GB`} history={hist.ram} />
        {g ? (
          <>
            <Meter label="GPU" value={g.utilization_pct} detail={g.name} history={hist.gpu} />
            <Meter label="VRAM" value={g.vram_used_pct} detail={`${gb(g.vram_used_mb)} / ${gb(g.vram_total_mb)}`} history={hist.vram} />
          </>
        ) : (
          <div className="meter"><span className="meter-label">GPU</span><p className="muted">{metrics.gpu_notes[0] ?? "NVIDIA GPU algılanmadı"}</p></div>
        )}
      </div>
      <div className="sys-foot">
        <div>
          <span className="muted">Bellekteki modeller: </span>
          {loaded.length ? loaded.map((m) => <span key={m.name} className="chip">{m.name} · {m.size_vram_gb} GB</span>) : <span className="muted">yok</span>}
        </div>
        <div><span className="muted">Aktif görev: </span><strong>{metrics.active_tasks}</strong></div>
      </div>
    </section>
  );
}
