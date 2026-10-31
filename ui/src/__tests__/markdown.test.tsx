import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { Markdown } from "../markdown";
import { parseRoute, routePath } from "../route";

const html = (t: string) => renderToStaticMarkup(<Markdown text={t} />);

describe("Markdown", () => {
  it("kod bloğu, başlık, liste, kalın ve satır içi kod", () => {
    const out = html("# Başlık\n\n- **bir**\n- `iki`\n\n1. ilk\n2. ikinci\n\n```python\nprint('x')\n```");
    expect(out).toContain("<h3>Başlık</h3>");
    expect(out).toContain("<li><strong>bir</strong></li>");
    expect(out).toContain("<li><code>iki</code></li>");
    expect(out).toContain("<ol><li>ilk</li><li>ikinci</li></ol>");
    expect(out).toContain("print(&#x27;x&#x27;)");
    expect(out).toContain("python");
  });

  it("HTML ve betik metin olarak kalır", () => {
    const out = html("<script>alert(1)</script> <img src=x onerror=alert(1)>");
    expect(out).not.toContain("<script>");
    expect(out).not.toContain("<img");
    expect(out).toContain("&lt;script&gt;");
  });

  it("tablo", () => {
    const out = html("| Ay | Satış |\n|---|---|\n| Ocak | 120 |");
    expect(out).toContain("<th>Ay</th>");
    expect(out).toContain("<td>120</td>");
  });

  it("bağlantılar tıklanabilir yapılmaz", () => {
    expect(html("[tıkla](https://ornek.com)")).not.toContain("<a");
  });
});

describe("yönlendirme", () => {
  it("yolları ayrıştırır", () => {
    expect(parseRoute("/")).toEqual({ page: "control" });
    expect(parseRoute("/asistan")).toEqual({ page: "chat", convId: null });
    expect(parseRoute("/asistan/abc123")).toEqual({ page: "chat", convId: "abc123" });
    expect(parseRoute("/asistan/../x")).toEqual({ page: "control" });
    expect(routePath({ page: "chat", convId: "abc" })).toBe("/asistan/abc");
    expect(parseRoute("/hafiza")).toEqual({ page: "memory" });
    expect(routePath({ page: "memory" })).toBe("/hafiza");
    expect(parseRoute("/akis/abc123")).toEqual({ page: "flow", jobId: "abc123" });
    expect(parseRoute("/akis")).toEqual({ page: "flow", jobId: null });
    expect(routePath({ page: "flow", jobId: "x1" })).toBe("/akis/x1");
    expect(parseRoute("/modeller")).toEqual({ page: "models" });
  });
});
