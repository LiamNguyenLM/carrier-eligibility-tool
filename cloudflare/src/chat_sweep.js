// Round 47 (Liam and Jonathan, 2026-11): a cross-carrier question names every program, each with the checker's label.
//
// "Which carriers will take an above ground pool with no fence?" used to go through top-k search, which kept a few
// rows per program and left most programs out ("the other programs' material did not come up"). Now a question that
// names no carrier and is about a topic in rules_data/chat/sweep_topics.json is a SWEEP:
//   1. topic, value, scope   the first topic / value whose pattern matches (a roof's age and a number of losses are
//                            read from the question; a dog breed by name); the scope is HO3 (owner-occupied) unless
//                            the question says rental / landlord / tenant / DP3 (DP3) or condo / HO6 (HO6)
//   2. every program         in that scope, with its label from outcomes.json -- the checker's own outcome for that
//                            form value on a neutral profile (export_chat_outcomes.py), or, with no form value, the
//                            program's strictest matching rule -- and the rows behind it, as sources
//   3. the model             writes one short line per program ("P3: ..."), explaining the label from the sources;
//                            it never decides the label, and a program it leaves out gets its first row's plain rule
// No Python and no checker run here: a lookup, well inside the Free plan's 10 ms.
import { normalize } from "./chat_text.js";

export const SWEEP_GROUPS = ["Eligible", "Confirm", "Refer", "Not eligible", "Coverage limited", "Guide silent", "Closed",
  "Not checked"];       // Not checked: the checker can't check the program (Liberty Mutual HO6: its file is the HO3 guide)
const GROUP_RANK = new Map(SWEEP_GROUPS.map((g, i) => [g, i]));
const RX = new Map();
const rx = (src) => { if (!RX.has(src)) RX.set(src, new RegExp(src, "i")); return RX.get(src); };
const WORDS = { one: 1, two: 2, three: 3, four: 4, five: 5, six: 6 };

/** A roof's age: "20+ years" / "20 years or older" -> 20, "over 20" / "older than 20" -> 21. */
function roofYears(q) {
  const m = /\b(over|older than|more than|greater than|above|past)\s+(\d{1,2})\b/.exec(q);
  if (m) return Number(m[2]) + 1;
  const n = /\b(\d{1,2})\s*(\+|plus|years?|yrs?|year old|years old)/.exec(q);
  return n ? Number(n[1]) : null;
}

/** Losses: "2 losses in 3 years", "two claims" -> 2. */
function lossCount(q) {
  const m = /\b(\d|one|two|three|four|five|six)\s+(?:\w+\s+){0,2}(losses|claims|loss|claim)\b/.exec(q);
  if (!m) return null;
  return /\d/.test(m[1]) ? Number(m[1]) : WORDS[m[1]];
}

/** The dog breed named in the question (longest name first), else "any". */
function breedOf(sweeps, q) {
  const names = Object.keys(sweeps).filter((k) => k.startsWith("dogs/")).map((k) => k.slice(5))
    .filter((b) => !/^(any|none of these|not sure)$/i.test(b));
  const qq = q.replace(/\bpitbulls?\b/g, "pit bull").replace(/\bpit bulls\b/g, "pit bull");
  const cands = [];
  for (const b of names) {
    const forms = [b.split(" (")[0], ...(b.match(/\(([^)]+)\)/) || []).slice(1)].map((f) => normalize(f).replace(/[^a-z0-9 ]+/g, " ").trim());
    for (const f of forms) if (f && new RegExp(`\\b${f.replace(/\s+/g, "\\s+")}s?\\b`).test(qq)) cands.push([f.length, b]);
  }
  cands.sort((a, b) => b[0] - a[0]);
  return cands.length ? cands[0][1] : "any";
}

/** The value of a topic the question asks about: {id, text} or null. */
function valueOf(data, topic, q) {
  if (topic.values) {
    const v = topic.values.find((x) => rx(x.match).test(q));
    return v ? { id: v.id, text: v.text } : null;
  }
  if (topic.numeric) {
    const n = topic.numeric;
    let k = n.field === "losses" ? lossCount(q) : roofYears(q);
    if (k === null) k = n.field === "losses" ? 1 : null;
    if (k === null) return null;
    k = Math.max(n.min, Math.min(n.max, k));
    return { id: String(k), text: n.text.replace("{n}", String(k)) };
  }
  if (topic.breeds) {
    const b = breedOf(data.sweep.sweeps, q);
    return { id: b, text: b === "any" ? "a dog (no breed named)" : `a ${b}` };
  }
  return null;
}

/** The sweep for a question that names no carrier, or null (the question then goes through search as before). */
export function detectSweep(data, question) {
  if (!data.sweep) return null;
  const q = normalize(question);
  const { spec, sweeps, scopes } = data.sweep;
  for (const topic of spec.topics) {
    if (!rx(topic.match).test(q)) continue;
    const value = valueOf(data, topic, q);
    if (!value) continue;
    const key = `${topic.id}/${value.id}`;
    const scope = topic.scope
      || (rx(spec.scopes.DP3.match).test(q) ? "DP3" : rx(spec.scopes.HO6.match).test(q) ? "HO6" : "HO3");
    const per = sweeps[key] && sweeps[key][scope];
    if (!per) continue;
    const pIndex = new Map(data.programs.map((p, i) => [p.program, i]));
    const programs = Object.entries(per).map(([program, o]) => ({ program, p: pIndex.get(program), name: o.name,
      label: o.label, status: o.status, rows: o.rows }))
      .sort((a, b) => GROUP_RANK.get(a.label) - GROUP_RANK.get(b.label) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
    const others = Object.keys(spec.scopes).filter((s) => s !== scope && sweeps[key][s]);
    return { key, topic: topic.id, value: value.id, text: value.text, scope, scopeLabel: spec.scopes[scope].label,
      others: others.map((s) => spec.scopes[s].label), programs };
  }
  return null;
}

/** The sources: each program's rows, in the sweep's order; p.k numbers the programs (P1..), p.srcs their sources. */
export function sweepSources(data, sw) {
  const sources = [];
  sw.programs.forEach((p, i) => {
    p.k = i + 1;
    p.srcs = [];
    for (const id of p.rows) {
      const u = data.rid[id];
      if (u === undefined) continue;
      sources.push({ n: sources.length + 1, units: [u] });
      p.srcs.push(sources.length);
    }
  });
  return sources;
}

/** The scope line the page shows above the list (the Worker's, not the model's). */
export function scopeLine(sw) {
  return `${sw.programs.length} ${sw.scopeLabel} programs, for ${sw.text}.`
    + (sw.others.length ? ` Ask about ${sw.others.join(" or ")} for those programs.` : "");
}

/** "P3: ..." lines of the model's answer: {3: "..."} (the first line for a number wins). */
export function sweepLines(answer) {
  const out = {};
  for (const m of String(answer).matchAll(/^\s*\**P(\d{1,3})\**\s*[:.)\-–—]\s*(.+?)\s*$/gm)) {
    const k = Number(m[1]);
    if (!(k in out) && m[2].trim()) out[k] = m[2].trim();
  }
  return out;
}

/** Every program's line: the model's, else its first row's plain rule (a program it left out is never dropped). */
export function finishSweep(data, sw, answer) {
  const got = sweepLines(answer);
  const lines = {}, filled = [];
  for (const p of sw.programs) {
    if (got[p.k]) { lines[p.k] = got[p.k]; continue; }
    const u = p.rows.map((id) => data.units[data.rid[id]]).find((x) => x && x.pr);
    lines[p.k] = u ? `${u.pr} [S${p.srcs[0]}]` : "No rule on file for this.";
    filled.push(p.k);
  }
  return { lines, filled };
}

/** What the page needs before the model writes: the scope line and every program, numbered, with its label. */
export const sweepTable = (sw) => ({ scope_line: scopeLine(sw), topic: sw.key, scope: sw.scope,
  programs: sw.programs.map((p) => ({ k: p.k, name: p.name, label: p.label, srcs: p.srcs })) });
