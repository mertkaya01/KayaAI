import { beforeEach, describe, expect, it } from "vitest";
import { clearToken, eventsUrl, getToken, takeTokenFromHash } from "../api";

describe("erişim anahtarı", () => {
  beforeEach(() => {
    clearToken();
    window.history.replaceState(null, "", "/");
  });

  it("#token= adresten alınır, saklanır ve adresten silinir", () => {
    window.history.replaceState(null, "", "/?x=1#token=abc%2B123");
    expect(takeTokenFromHash()).toBe("abc+123");
    expect(getToken()).toBe("abc+123");
    expect(window.location.hash).toBe("");
    expect(window.location.search).toBe("?x=1");
  });

  it("anahtar yoksa hiçbir şey değişmez", () => {
    window.history.replaceState(null, "", "/#baska=1");
    expect(takeTokenFromHash()).toBeNull();
    expect(getToken()).toBeNull();
    expect(window.location.hash).toBe("#baska=1");
  });

  it("olay akışı adresi aynı kökene gider ve anahtarı kodlar", () => {
    const url = new URL(eventsUrl("a b", 7));
    expect(url.protocol).toBe("ws:");
    expect(url.host).toBe(window.location.host);
    expect(url.pathname).toBe("/api/events");
    expect(url.searchParams.get("token")).toBe("a b");
    expect(url.searchParams.get("after")).toBe("7");
    expect(url.searchParams.get("backlog")).toBeNull();
    expect(new URL(eventsUrl("x")).searchParams.get("backlog")).toBe("50");
  });
});
