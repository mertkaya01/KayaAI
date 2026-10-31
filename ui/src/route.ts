import { useEffect, useState } from "react";

/** Basit yönlendirme (History API): "/" Kontrol Merkezi, "/asistan[/<sohbet-id>]" Asistan. Sunucu SPA'ya düşürür. */
export type Route = { page: "control" } | { page: "memory" } | { page: "chat"; convId: string | null };

export function parseRoute(pathname: string): Route {
  const m = /^\/asistan(?:\/([A-Za-z0-9]+))?\/?$/.exec(pathname);
  if (m) return { page: "chat", convId: m[1] ?? null };
  if (/^\/hafiza\/?$/.test(pathname)) return { page: "memory" };
  return { page: "control" };
}

export function routePath(r: Route): string {
  if (r.page === "chat") return `/asistan${r.convId ? `/${r.convId}` : ""}`;
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
