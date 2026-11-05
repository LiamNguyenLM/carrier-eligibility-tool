// Round 47 (Liam and Jonathan, 2026-11): a cross-carrier answer as one compact list -- every program in scope, grouped
// by the label CFIG's eligibility check gives it, one line each -- with the sources behind "Show sources".
//
// The Worker sends the list first (the "start" event: the scope line and every program with its label), so the
// labels show at once; the model's lines ("P3: ...") fill in as they stream; "done" brings every program's final
// line (the model's, or its rule's own text where the model left it out) and the sources. No DOM here except
// through the strings returned: the page (chat.js) puts them in place.
import { escapeHtml, inline } from "./markdown.js";

export const GROUPS = [
  ["Eligible", "Eligible", "ok"],
  ["Confirm", "Eligible if confirmed", "warn"],
  ["Refer", "Refer to underwriting", "warn"],
  ["Not eligible", "Not eligible", "bad"],
  ["Coverage limited", "Eligible, coverage limited", "info"],
  ["Guide silent", "Guide silent (no rule on file)", "muted"],
  ["Closed", "Closed to new business", "muted"],
  ["Not checked", "Could not be checked", "muted"],
];
const TONE = Object.fromEntries(GROUPS.map(([l, , t]) => [l, t]));

/** "P3: ..." lines of a partial or whole answer: {3: "..."}. The Worker's sweepLines, for the page while streaming. */
export function streamedLines(text) {
  const out = {};
  for (const m of String(text).matchAll(/^\s*\**P(\d{1,3})\**\s*[:.)\-–—]\s*(.+?)\s*$/gm)) {
    const k = Number(m[1]);
    if (!(k in out) && m[2].trim()) out[k] = m[2].trim();
  }
  return out;
}

/** The list as HTML: groups in order, a program's line from lines[k] (or "…" while it is being written). */
export function sweepHtml(sweep, lines, cite, writing) {
  const parts = [`<p class="sweep-scope">${escapeHtml(sweep.scope_line)}</p>`];
  for (const [label, title, tone] of GROUPS) {
    const rows = sweep.programs.filter((p) => p.label === label);
    if (!rows.length) continue;
    parts.push(`<div class="sweep-group"><div class="sweep-head"><span class="badge tone-${tone}">${escapeHtml(title)}</span>`
      + ` <span class="caption">${rows.length}</span></div><ul class="sweep-list">`
      + rows.map((p) => {
        const line = lines[p.k];
        const body = line ? cite(inline(line)) : `<span class="caption">${writing ? "…" : "No rule on file for this."}</span>`;
        return `<li class="tone-${TONE[label]}" data-k="${p.k}"><span class="sw-name">${escapeHtml(p.name)}</span> `
          + `<span class="sw-line">${body}</span></li>`;
      }).join("") + "</ul></div>");
  }
  return parts.join("");
}

/** The answer as text, for the chat's history and a "This answer looks wrong" report. */
export function sweepText(sweep, lines) {
  return [sweep.scope_line, ...sweep.programs.map((p) => `${p.name}: ${p.label}. ${lines[p.k] || ""}`.trim())].join("\n");
}
