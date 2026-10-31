import { Fragment, useState, type ReactNode } from "react";

/**
 * Küçük, güvenli Markdown görüntüleyici: yalnızca React öğeleri üretir (dangerouslySetInnerHTML YOK), bu yüzden
 * model çıktısındaki HTML/betik metin olarak görünür. Desteklenen: kod bloğu (```dil), başlık (#, ##, ###),
 * madde ve numaralı liste, alıntı (>), kalın (**x**), italik (*x*), satır içi kod (`x`), tablo (| a | b |).
 * Bağlantılar tıklanabilir yapılmaz (yerel arayüzden dış adrese istemeden çıkılmasın).
 */

function inline(text: string, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    const k = `${key}-${i++}`;
    if (tok.startsWith("`")) out.push(<code key={k}>{tok.slice(1, -1)}</code>);
    else if (tok.startsWith("**")) out.push(<strong key={k}>{tok.slice(2, -2)}</strong>);
    else out.push(<em key={k}>{tok.slice(1, -1)}</em>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="codeblock">
      <div className="codeblock-head">
        <span className="muted">{lang || "kod"}</span>
        <button
          className="ghost small"
          onClick={() => {
            void navigator.clipboard?.writeText(code).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); });
          }}
        >
          {copied ? "Kopyalandı" : "Kopyala"}
        </button>
      </div>
      <pre><code>{code}</code></pre>
    </div>
  );
}

const isTableRow = (l: string) => /^\s*\|.*\|\s*$/.test(l);
const isTableSep = (l: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l);
const cells = (l: string) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());

export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let n = 0;
  const key = () => `b${n++}`;
  while (i < lines.length) {
    const line = lines[i];
    const fence = /^\s*```\s*([\w+#.-]*)/.exec(line);
    if (fence) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i++]);
      i++; // kapanış
      blocks.push(<CodeBlock key={key()} lang={fence[1]} code={code.join("\n")} />);
      continue;
    }
    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    if (h) {
      const k = key();
      const content = inline(h[2], k);
      blocks.push(h[1].length === 1 ? <h3 key={k}>{content}</h3> : h[1].length === 2 ? <h4 key={k}>{content}</h4> : <h5 key={k}>{content}</h5>);
      i++;
      continue;
    }
    if (isTableRow(line) && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      const head = cells(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && isTableRow(lines[i])) rows.push(cells(lines[i++]));
      const k = key();
      blocks.push(
        <div key={k} className="table-wrap">
          <table>
            <thead><tr>{head.map((c, j) => <th key={j}>{inline(c, `${k}h${j}`)}</th>)}</tr></thead>
            <tbody>{rows.map((r, ri) => <tr key={ri}>{r.map((c, j) => <td key={j}>{inline(c, `${k}r${ri}${j}`)}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*([-*+]|\d+[.)])\s+/, ""));
        i++;
      }
      const k = key();
      const lis = items.map((it, j) => <li key={j}>{inline(it, `${k}-${j}`)}</li>);
      blocks.push(ordered ? <ol key={k}>{lis}</ol> : <ul key={k}>{lis}</ul>);
      continue;
    }
    if (/^\s*>\s?/.test(line)) {
      const quote: string[] = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) quote.push(lines[i++].replace(/^\s*>\s?/, ""));
      const k = key();
      blocks.push(<blockquote key={k}>{inline(quote.join(" "), k)}</blockquote>);
      continue;
    }
    if (!line.trim()) {
      i++;
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^\s*(```|#{1,3}\s|[-*+]\s|\d+[.)]\s|>)/.test(lines[i]) && !isTableRow(lines[i])) {
      para.push(lines[i++]);
    }
    if (para.length === 0) {
      // tanınmayan satır: düz paragraf olarak göster (sonsuz döngüye girme)
      para.push(lines[i++]);
    }
    const k = key();
    blocks.push(
      <p key={k}>
        {para.map((p, j) => (
          <Fragment key={j}>{j > 0 && <br />}{inline(p, `${k}-${j}`)}</Fragment>
        ))}
      </p>,
    );
  }
  return <div className="md">{blocks}</div>;
}
