// A tiny markdown -> HTML for the engine's markdown strings (the card's first line, its "Missing:" list, the
// "Things to confirm" box, the Could Not Be Checked line, the placement panel, the tester note). What they use:
// headings (####), **bold**, *italics*, bullet and numbered lists (nested by indentation), paragraphs. Everything
// else is text: HTML in the text is escaped (Streamlit's st.markdown without unsafe_allow_html escapes it too).
//
// Deliberately NOT supported (Streamlit's renderer does them): $...$ as LaTeX math -- a line with two dollar
// amounts ("$400,000 ... $1,000,000") renders as math in app.py; here it stays text --, links, tables, code blocks.

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
export const escapeHtml = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ESC[c]);

export function inline(text) {
  const keep = [];
  let s = String(text ?? "").replace(/\\([\\`*_{}\[\]()#+\-.!$])/g, (_, c) => {
    keep.push(escapeHtml(c));
    return `\u0000${keep.length - 1}\u0000`;
  });
  s = s.replace(/`([^`]+)`/g, (_, c) => {
    keep.push(`<code>${escapeHtml(c)}</code>`);
    return `\u0000${keep.length - 1}\u0000`;
  });
  s = escapeHtml(s);
  s = s.replace(/\*\*(?=\S)([\s\S]*?\S)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/__(?=\S)([\s\S]*?\S)__(?![A-Za-z0-9])/g, "<strong>$1</strong>");
  s = s.replace(/(^|[^*])\*(?=[^\s*])([^*]*?[^\s*])\*(?!\*)/g, "$1<em>$2</em>");
  s = s.replace(/(^|[^A-Za-z0-9_])_(?=\S)([^_]*?\S)_(?![A-Za-z0-9_])/g, "$1<em>$2</em>");
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => keep[Number(i)]);
}

const LIST_ITEM = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;

export function markdown(src) {
  const lines = String(src ?? "").replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let para = [];
  const flushPara = () => {
    if (para.length) out.push(`<p>${para.map(inline).join("\n")}</p>`);
    para = [];
  };
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const h = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line);
    if (!line.trim()) { flushPara(); i++; continue; }
    if (h) { flushPara(); out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); i++; continue; }
    if (/^\s{0,3}(---+|\*\*\*+)\s*$/.test(line) && !para.length) { out.push("<hr>"); i++; continue; }
    if (LIST_ITEM.test(line)) {
      flushPara();
      const block = [];
      while (i < lines.length && lines[i].trim() && (LIST_ITEM.test(lines[i]) || /^\s+\S/.test(lines[i]))) {
        block.push(lines[i]);
        i++;
      }
      out.push(list(block));
      continue;
    }
    para.push(line.trim());
    i++;
  }
  flushPara();
  return out.join("\n");
}

// One list block: items by indentation; a deeper item nests under the one before it; a non-item line continues
// the item before it.
function list(block) {
  const items = [];
  for (const line of block) {
    const m = LIST_ITEM.exec(line);
    if (m) items.push({ indent: m[1].replace(/\t/g, "    ").length, ordered: /\d/.test(m[2]), text: [m[3]] });
    else if (items.length) items[items.length - 1].text.push(line.trim());
  }
  const render = (start, end, base) => {
    let html = "";
    let k = start;
    let tag = null;
    while (k < end) {
      const it = items[k];
      let j = k + 1;
      while (j < end && items[j].indent > base) j++;     // children of item k
      const t = it.ordered ? "ol" : "ul";
      if (tag !== t) {
        if (tag) html += `</${tag}>`;
        html += `<${t}>`;
        tag = t;
      }
      const kids = j > k + 1 ? render(k + 1, j, items[k + 1].indent) : "";
      html += `<li>${it.text.map(inline).join("\n")}${kids}</li>`;
      k = j;
    }
    return tag ? html + `</${tag}>` : html;
  };
  return items.length ? render(0, items.length, items[0].indent) : "";
}
