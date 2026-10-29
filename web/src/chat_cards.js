// Round 46 (Liam, 2026-10-29): an Ask the Guides answer as one card per carrier program, instead of one long list.
// The Worker's prompt (cloudflare/src/chat.js, rule 7) asks for: a short opening answer, then one section per program,
//
//   ### The Hartford (HO3)
//   **Ineligible**: one short sentence [S3]
//   - every condition, limit or exception, with the guide's exact wording [S3][S4]
//
// splitCards reads that back -- also mid-stream, from a partial answer -- into {intro, cards}. No DOM: the page
// (chat.js) renders it, and web/tests/chat_cards.test.mjs tests it in Node. An answer with no sections (not on file,
// an unknown carrier, a refusal) has no cards and renders as plain text.

const LABELS = ["Ineligible", "Referral", "Conditions", "Coverage limit", "Acceptable", "Not addressed"];
// the badge colour: bad (declines), warn (needs something), info (coverage, not eligibility), ok, muted
export const TONES = { ineligible: "bad", referral: "warn", conditions: "warn", "coverage limit": "info",
  acceptable: "ok", "not addressed": "muted" };
const LABEL = Object.fromEntries(LABELS.map((l) => [l.toLowerCase(), l]));

const HEADING = /^\s{0,3}#{2,4}\s+(.+?)\s*#*\s*$/;
const VERDICT_LINE = /^\*\*([^*]+?)\*\*\s*[:—–-]?\s*(.*)$/;
const BULLET = /^\s*([-*+]|\d+[.)])\s+/;

function finish(title, lines) {
  const rest = [...lines];
  while (rest.length && !rest[0].trim()) rest.shift();
  let verdict = "", summary = "";
  if (rest.length) {
    const first = rest[0].trim().replace(BULLET, "");
    const m = VERDICT_LINE.exec(first);
    const key = m ? m[1].trim().replace(/[:.]$/, "").trim().toLowerCase() : "";
    if (m && LABEL[key]) {
      verdict = LABEL[key];
      summary = m[2].trim();
      rest.shift();
    } else if (!BULLET.test(rest[0])) {
      summary = rest.shift().trim();
    }
  }
  return { title: title.replace(/\*\*/g, "").trim(), verdict, tone: TONES[verdict.toLowerCase()] || "muted",
    summary, body: rest.join("\n").trim() };
}

/** text -> {intro, cards: [{title, verdict, tone, summary, body}]} */
export function splitCards(text) {
  const intro = [];
  const sections = [];
  for (const line of String(text ?? "").replace(/\r\n?/g, "\n").split("\n")) {
    const h = HEADING.exec(line);
    if (h) sections.push({ title: h[1], lines: [] });
    else (sections.length ? sections[sections.length - 1].lines : intro).push(line);
  }
  return { intro: intro.join("\n").trim(), cards: sections.map((s) => finish(s.title, s.lines)) };
}
