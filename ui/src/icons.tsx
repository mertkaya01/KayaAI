// Sade çizgi simgeler (kendi çizimimiz; dış kütüphane yok, CSP 'self').
import type { ReactElement } from "react";

const P: Record<string, ReactElement> = {
  today: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  chat: <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-4.5 4v-4h0A1.5 1.5 0 0 1 4 14.5z" />,
  office: <><path d="M3 21h18" /><path d="M5 21V8l7-4 7 4v13" /><circle cx="9.5" cy="12" r="1.3" /><circle cx="14.5" cy="12" r="1.3" /><path d="M7.5 17c.4-1.3 1.1-2 2-2s1.6.7 2 2M12.5 17c.4-1.3 1.1-2 2-2s1.6.7 2 2" /></>,
  memory: <><path d="M12 5a3 3 0 0 0-5.8 1A3 3 0 0 0 4 9.5a3 3 0 0 0 1 5.6A3 3 0 0 0 9 19a3 3 0 0 0 3-1" /><path d="M12 5a3 3 0 0 1 5.8 1A3 3 0 0 1 20 9.5a3 3 0 0 1-1 5.6A3 3 0 0 1 15 19a3 3 0 0 1-3-1z" /><path d="M12 5v13" /></>,
  schedule: <><circle cx="12" cy="13" r="8" /><path d="M12 9v4l2.5 2.5M9 2h6" /></>,
  browser: <><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z" /></>,
  subtitles: <><rect x="3" y="5" width="18" height="14" rx="2.5" /><path d="M10.5 10.5a2 2 0 1 0 0 3M17 10.5a2 2 0 1 0 0 3" /></>,
  models: <><rect x="6" y="6" width="12" height="12" rx="2" /><rect x="9.5" y="9.5" width="5" height="5" rx="1" /><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3" /></>,
  system: <><path d="M4 18a8 8 0 1 1 16 0" /><path d="M12 18l4-5" /><circle cx="12" cy="18" r="1.4" /></>,
  bell: <><path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z" /><path d="M10 20.5a2 2 0 0 0 4 0" /></>,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  moon: <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />,
  auto: <><circle cx="12" cy="12" r="8.5" /><path d="M12 3.5v17" /><path d="M12 3.5a8.5 8.5 0 0 1 0 17z" fill="currentColor" stroke="none" /></>,
  collapse: <><rect x="3" y="4" width="18" height="16" rx="2.5" /><path d="M9 4v16M15 10l-2 2 2 2" /></>,
  expand: <><rect x="3" y="4" width="18" height="16" rx="2.5" /><path d="M9 4v16M13 10l2 2-2 2" /></>,
  logout: <><path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4" /><path d="M10 16l-4-4 4-4M6 12h10" /></>,
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  plus: <path d="M12 5v14M5 12h14" />,
  doc: <><path d="M7 3h7l5 5v13H7z" /><path d="M14 3v5h5M10 13h6M10 17h6" /></>,
  chart: <><path d="M4 20V4M4 20h16" /><path d="M8 16v-4M12 16V8M16 16v-6" /></>,
  camera: <><path d="M4 8h3l2-2.5h6L17 8h3v11H4z" /><circle cx="12" cy="13" r="3.5" /></>,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
};

export type IconName = keyof typeof P;

export function Icon({ name, size = 20, label }: { name: IconName; size?: number; label?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}
         strokeLinecap="round" strokeLinejoin="round" role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      {P[name]}
    </svg>
  );
}
