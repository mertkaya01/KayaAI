import type { ReactNode } from "react";
import { Icon, type IconName } from "../icons";

/** Boş ekran (Adım 18e): simge, kısa başlık, ne yapılacağına dair tek satır, isteğe bağlı düğme. */
export function EmptyState({ icon, title, children, action }: { icon: IconName; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty-state">
      <span className="empty-icon" aria-hidden="true"><Icon name={icon} size={22} /></span>
      <p className="empty-title">{title}</p>
      {children && <p className="muted small">{children}</p>}
      {action}
    </div>
  );
}
