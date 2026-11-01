import { describe, expect, it } from "vitest";
import { parseRoute, routePath } from "../route";

describe("yönlendirme", () => {
  it("sayfaları ayrıştırır ve geri yazar", () => {
    for (const path of ["/", "/asistan", "/asistan/abc123", "/hafiza", "/akis", "/akis/job42", "/modeller", "/altyazi"]) {
      expect(routePath(parseRoute(path))).toBe(path);
    }
    expect(parseRoute("/modeller/")).toEqual({ page: "models" });
    expect(parseRoute("/akis/../x")).toEqual({ page: "control" });
    expect(parseRoute("/bilinmeyen")).toEqual({ page: "control" });
  });
});
