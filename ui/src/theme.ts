// Tema (Adım 16a): "system" | "light" | "dark". Seçim bu tarayıcıda saklanır (kişisel tercih).
import { useEffect, useState } from "react";

export type ThemePref = "system" | "light" | "dark";
const KEY = "kayaai.theme";

export function readPref(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}

export function writePref(key: string, value: string): void {
  try { localStorage.setItem(key, value); } catch { /* özel pencere: yalnız bu oturum */ }
}

export function resolveTheme(pref: ThemePref, systemDark: boolean): "light" | "dark" {
  return pref === "system" ? (systemDark ? "dark" : "light") : pref;
}

export function useTheme(): [ThemePref, (p: ThemePref) => void] {
  const [pref, setPref] = useState<ThemePref>(() => {
    const v = readPref(KEY);
    return v === "light" || v === "dark" || v === "system" ? v : "system";
  });
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    const apply = () => { document.documentElement.dataset.theme = resolveTheme(pref, mq ? mq.matches : true); };
    apply();
    mq?.addEventListener?.("change", apply);
    return () => mq?.removeEventListener?.("change", apply);
  }, [pref]);
  return [pref, (p) => { writePref(KEY, p); setPref(p); }];
}

export const NEXT_THEME: Record<ThemePref, ThemePref> = { system: "light", light: "dark", dark: "system" };
export const THEME_LABEL: Record<ThemePref, string> = { system: "Tema: sistem", light: "Tema: açık", dark: "Tema: koyu" };
