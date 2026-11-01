import { describe, expect, it } from "vitest";
import { parseRoute, routePath } from "../route";

describe("yönlendirme", () => {
  it("sayfaları ayrıştırır ve geri yazar", () => {
    for (const path of ["/", "/asistan", "/asistan/abc123", "/hafiza", "/ofis", "/ofis/job42", "/modeller", "/altyazi", "/tarayici", "/zamanlama", "/sistem"]) {
      expect(routePath(parseRoute(path))).toBe(path);
    }
    expect(parseRoute("/modeller/")).toEqual({ page: "models" });
    expect(parseRoute("/akis/../x")).toEqual({ page: "today" });
    expect(parseRoute("/akis/job42")).toEqual({ page: "flow", jobId: "job42" }); // eski bağlantılar
    expect(parseRoute("/bilinmeyen")).toEqual({ page: "today" });
    expect(parseRoute("/sistem")).toEqual({ page: "control" });
    expect(routePath({ page: "control" })).toBe("/sistem");
  });
});
