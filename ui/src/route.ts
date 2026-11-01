import { useEffect, useState } from "react";

/** Basit yönlendirme (History API): "/" Kontrol Merkezi, "/asistan[/<sohbet-id>]" Asistan. Sunucu SPA'ya düşürür. */
export type Route = { page: "control" } | { page: "memory" } | { page: "models" } | { page: "subtitles" } | { page: "browser" } | { page: "chat"; convId: string | null }
  | { page: "flow"; jobId: string | null };

export function parseRoute(pathname: string): Route {
  const m = /^\/asistan(?:\/([A-Za-z0-9]+))?\/?$/.exec(pathname);
  if (m) return { page: "chat", convId: m[1] ?? null };
  if (/^\/hafiza\/?$/.test(pathname)) return { page: "memory" };
  if (/^\/modeller\/?$/.test(pathname)) return { page: "models" };
  if (/^\/altyazi\/?$/.test(pathname)) return { page: "subtitles" };
  if (/^\/tarayici\/?$/.test(pathname)) return { page: "browser" };
  const f = /^\/akis(?:\/([A-Za-z0-9]+))?\/?$/.exec(pathname);
  if (f) return { page: "flow", jobId: f[1] ?? null };
  return { page: "control" };
}

export function routePath(r: Route): string {
  if (r.page === "chat") return `/asistan${r.convId ? `/${r.convId}` : ""}`;
  if (r.page === "flow") return `/akis${r.jobId ? `/${r.jobId}` : ""}`;
  if (r.page === "models") return "/modeller";
  if (r.page === "subtitles") return "/altyazi";
  if (r.page === "browser") return "/tarayici";
  return r.page === "memory" ? "/hafiza" : "/";
}

export function useRoute(): [Route, (r: Route) => void] {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.pathname));
  useEffect(() => {
    const onPop = () => setRoute(parseRoute(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const navigate = (r: Route) => {
    const path = routePath(r);
    if (path !== window.location.pathname) window.history.pushState(null, "", path);
    setRoute(r);
  };
  return [route, navigate];
}
