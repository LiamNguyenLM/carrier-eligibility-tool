// Ask the Guides (round 45, Liam 2026-10-28): the material the chat answers from, bundled into the Worker like the
// placement tables (cloudflare/build/chat_index.js, git-ignored, never in web/dist).
//
// Three kinds of unit, each searchable on its own:
//   "g"  a guide chunk: rules_data/chat/guide_chunks.jsonl (exported from the carrier store by
//        export_chat_corpus.py), with its program, page and section
//   "r"  a rules-table row: rules_data/carrier_rules_*.csv -- the plain rule, the guide's verbatim quote, its PDF
//        page, topic, effect, when it applies and its exceptions
//   "c"  a CFIG knowledge row: rules_data/cfig_knowledge.csv (labelled "CFIG experience", never the guide)
// plus a BM25 inverted index over all of them (chat_text.terms), the carrier-name aliases, and the program list.
//
// usage (cwd = the repo root):  node cloudflare/scripts/build_chat_index.mjs [--out FILE]
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, readdirSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseCsv } from "./lib.mjs";
import { buildAliases, terms } from "../src/chat_text.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..");
export const DEFAULT_OUT = join(ROOT, "cloudflare", "build", "chat_index.js");
const RULES_DIR = join(ROOT, "rules_data");

/** A rules CSV without its leading "# ..." comment lines. */
function readRulesCsv(path) {
  const text = readFileSync(path, "utf8").replace(/^﻿/, "");
  const lines = text.split(/\r?\n/);
  let i = 0;
  while (i < lines.length && lines[i].startsWith("#")) i++;
  return parseCsv(lines.slice(i).join("\n"), path);
}

const clean = (s) => String(s ?? "").replace(/\s+/g, " ").trim();

export function buildChatData(rulesDir = RULES_DIR) {
  const programs = JSON.parse(readFileSync(join(rulesDir, "chat", "programs.json"), "utf8"));
  const pIndex = new Map(programs.map((p, i) => [p.program, i]));
  const byWorkbook = new Map();
  for (const p of programs) for (const wb of p.workbook_names) byWorkbook.set(wb, p.program);
  const units = [];
  const problems = [];

  // guide chunks, in reading order per program
  const chunkLines = readFileSync(join(rulesDir, "chat", "guide_chunks.jsonl"), "utf8").split("\n").filter(Boolean);
  for (const [n, line] of chunkLines.entries()) {
    const c = JSON.parse(line);
    if (!pIndex.has(c.p)) { problems.push(`guide_chunks.jsonl line ${n + 1}: unknown program ${c.p}`); continue; }
    units.push({ k: "g", p: pIndex.get(c.p), pg: c.pg, t: c.t ? 1 : 0, s: clean(c.s), x: c.x.trim() });
  }

  // rules-table rows
  const ruleFiles = readdirSync(rulesDir).filter((f) => /^carrier_rules_.*\.csv$/.test(f)).sort();
  for (const f of ruleFiles) {
    for (const r of readRulesCsv(join(rulesDir, f))) {
      const program = byWorkbook.get(r.Carrier);
      if (!program) { problems.push(`${f} ${r["Rule ID"]}: no program for workbook carrier ${JSON.stringify(r.Carrier)}`); continue; }
      const page = parseInt(String(r["PDF page"] || "").replace(/\.0$/, ""), 10);
      units.push({ k: "r", p: pIndex.get(program), id: r["Rule ID"], wb: r.Carrier, topic: r.Topic, eff: r.Effect,
        pr: clean(r["Plain rule"]), aw: clean(r["Applies when"]), ex: clean(r["Exceptions / cure"]),
        q: clean(r["Verbatim quote from guide"]), pg: Number.isFinite(page) ? page : null });
    }
  }
  // CFIG's own experience
  for (const r of readRulesCsv(join(rulesDir, "cfig_knowledge.csv"))) {
    const program = byWorkbook.get(r.Carrier);
    if (!program) { problems.push(`cfig_knowledge.csv ${r["Rule ID"]}: no program for ${JSON.stringify(r.Carrier)}`); continue; }
    units.push({ k: "c", p: pIndex.get(program), id: r["Rule ID"], wb: r.Carrier, topic: r.Topic, eff: r.Effect,
      pr: clean(r["Plain rule"]), aw: clean(r["Applies when"]), ex: clean(r["Exceptions / cure"]), src: clean(r.Source) });
  }
  if (problems.length) throw new Error("chat index not built:\n  " + problems.slice(0, 20).join("\n  "));

  // BM25 postings: term -> [unit, tf, unit, tf, ...] in unit order
  const post = new Map();
  const len = new Array(units.length);
  units.forEach((u, i) => {
    const prog = programs[u.p];
    const text = u.k === "g" ? `${u.s} ${u.x}`
      : `${u.topic.replace(/_/g, " ")} ${u.pr} ${u.q || ""} ${u.aw} ${u.ex} ${prog.display}`;
    const ts = terms(text);
    len[i] = ts.length;
    const tf = new Map();
    for (const t of ts) tf.set(t, (tf.get(t) || 0) + 1);
    for (const [t, n] of tf) {
      if (!post.has(t)) post.set(t, []);
      post.get(t).push(i, n);
    }
  });
  const index = {};
  for (const [t, arr] of [...post].sort((a, b) => (a[0] < b[0] ? -1 : 1))) index[t] = arr;
  const avg = { g: 0, r: 0, c: 0 };
  const cnt = { g: 0, r: 0, c: 0 };
  units.forEach((u, i) => { avg[u.k] += len[i]; cnt[u.k]++; });
  for (const k of Object.keys(avg)) avg[k] = cnt[k] ? avg[k] / cnt[k] : 1;

  const hash = createHash("sha256");
  hash.update(readFileSync(join(rulesDir, "chat", "guide_chunks.jsonl")));
  hash.update(readFileSync(join(rulesDir, "chat", "programs.json")));
  for (const f of [...ruleFiles, "cfig_knowledge.csv"]) hash.update(f).update(readFileSync(join(rulesDir, f)));
  const data = { format: 1, sha: hash.digest("hex").slice(0, 16), programs, aliases: buildAliases(programs),
    units, len, avg, index };
  return { data, counts: { guide: cnt.g, rules: cnt.r, cfig: cnt.c, terms: post.size, programs: programs.length } };
}

export function chatModuleSource(data) {
  return "// Generated by cloudflare/scripts/build_chat_index.mjs from rules_data -- do not edit, do not commit\n"
    + "// (cloudflare/build/ is git-ignored). Wrangler rebuilds it on every deploy (wrangler.toml [build]).\n"
    + `export default JSON.parse(${JSON.stringify(JSON.stringify(data))});\n`;
}

export function writeChatModule(rulesDir = RULES_DIR, out = DEFAULT_OUT) {
  const built = buildChatData(rulesDir);
  const src = chatModuleSource(built.data);
  mkdirSync(dirname(out), { recursive: true });
  const tmp = `${out}.${process.pid}.${Date.now()}.tmp`;
  writeFileSync(tmp, src, "utf8");
  renameSync(tmp, out);
  return { ...built, out, bytes: Buffer.byteLength(src) };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const i = process.argv.indexOf("--out");
    const { out, bytes, counts } = writeChatModule(RULES_DIR, i > 0 ? resolve(process.argv[i + 1]) : DEFAULT_OUT);
    console.log(`chat index: wrote ${out} (${Math.round(bytes / 1024)} KB); `
      + Object.entries(counts).map(([k, v]) => `${k} ${v}`).join(", "));
  } catch (e) {
    console.error(e.message);
    process.exit(1);
  }
}
