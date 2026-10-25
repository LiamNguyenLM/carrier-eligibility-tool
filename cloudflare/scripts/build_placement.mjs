// The placement tables, bundled into the Worker (round 44b, Liam 2026-10-25: the D1 load blew the free tier's
// 100k rows written a day -- 143k with the index writes).
//
// rules_data/placement/*.csv -> cloudflare/build/placement_data.js, a module the Worker imports (routes.js), so the
// panel reads its rows from memory: no D1, no load step. cloudflare/build/ is git-ignored and outside web/dist, so the
// tables never reach the browser (web/build.mjs refuses any placement file in the page too).
//
// Wrangler runs this before every `wrangler deploy` and `wrangler dev` (wrangler.toml [build]), so the monthly refresh
// is "update the CSVs, push": the GitHub build regenerates the module from the CSVs it checked out. A bad CSV (a
// missing column, a bad month or count, no data_through) stops the build, and the deploy with it: the version already
// live keeps answering.
//
// usage (cwd = the repo root):  node cloudflare/scripts/build_placement.mjs [--csv-dir DIR] [--out FILE]
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { readCsv } from "./lib.mjs";
import { countyKey, monthIndex } from "../src/placement.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..");
export const DEFAULT_CSV_DIR = join(ROOT, "rules_data", "placement");
export const DEFAULT_OUT = join(ROOT, "cloudflare", "build", "placement_data.js");
const FILES = ["placement_zip.csv", "placement_county.csv", "placement_profile.csv", "placement_markets.csv",
  "placement_meta.csv"];
const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;

function arg(name, dflt) {
  const i = process.argv.indexOf(name);
  return i > 0 ? process.argv[i + 1] : dflt;
}

/**
 * The tables as the Worker holds them. Every row is three numbers in a flat list, [mi, market, n, mi, market, n, ...]
 * (mi = placement.month_index, market = an index into `names`), kept in CSV order (placement.py sums a market's months
 * in file order, and the port does the same), and grouped by the key a panel looks up: the ZIP, the county key
 * (county.strip().lower(), as placement.load_tables keys it) and each profile band. `all` is placement_zip summed per
 * (month, market), in the order each pair first appears -- placement.py's T["all"] with the same weights (the
 * placement.js header says why).
 */
export function buildPlacementData(csvDir = DEFAULT_CSV_DIR) {
  const problems = [];
  const read = (f) => readCsv(join(csvDir, f));
  const check = (file, r, i, cols) => {
    for (const c of cols) if (!(c in r)) problems.push(`${file}: no column ${c}`);
    if ("month" in r && !MONTH.test(r.month)) problems.push(`${file} line ${i + 2}: month ${JSON.stringify(r.month)}`);
    if ("n" in r && !/^\d+$/.test(r.n)) problems.push(`${file} line ${i + 2}: n ${JSON.stringify(r.n)}`);
  };
  const zip = read("placement_zip.csv"), county = read("placement_county.csv"), profile = read("placement_profile.csv");
  const markets = read("placement_markets.csv"), meta = read("placement_meta.csv");
  zip.forEach((r, i) => check("placement_zip.csv", r, i, ["month", "zip", "market", "n"]));
  county.forEach((r, i) => check("placement_county.csv", r, i, ["month", "county", "market", "n"]));
  profile.forEach((r, i) => check("placement_profile.csv", r, i, ["month", "dim", "value", "market", "n"]));
  markets.forEach((r, i) => check("placement_markets.csv", r, i, ["market", "program_prefix"]));
  meta.forEach((r, i) => check("placement_meta.csv", r, i, ["key", "value"]));
  const metaMap = Object.fromEntries(meta.map((r) => [r.key, r.value]));
  if (!metaMap.data_through) problems.push("placement_meta.csv: no data_through");
  if (zip.length === 0 || markets.length === 0) problems.push("placement_zip.csv / placement_markets.csv is empty");
  if (problems.length) throw new Error("placement tables not built:\n  " + problems.slice(0, 20).join("\n  "));

  const names = [], nameIx = new Map();
  const ix = (m) => {
    if (!nameIx.has(m)) { nameIx.set(m, names.length); names.push(m); }
    return nameIx.get(m);
  };
  const group = (rows, keyOf) => {
    const out = {};
    for (const r of rows) {
      const k = keyOf(r);
      if (!Object.hasOwn(out, k)) out[k] = [];
      out[k].push(monthIndex(r.month), ix(r.market), parseInt(r.n, 10));
    }
    return out;
  };
  const all = new Map();
  for (const r of zip) {
    const k = `${r.month}\u0000${r.market}`;
    if (!all.has(k)) all.set(k, [monthIndex(r.month), ix(r.market), 0]);
    all.get(k)[2] += parseInt(r.n, 10);
  }
  const dims = {};
  for (const dim of new Set(profile.map((r) => r.dim))) dims[dim] = group(profile.filter((r) => r.dim === dim), (r) => r.value);

  const hash = createHash("sha256");
  for (const f of FILES) hash.update(f + "\n").update(readFileSync(join(csvDir, f)));
  const counts = { rows_zip: zip.length, rows_county: county.length, rows_profile: profile.length,
    rows_markets: markets.length, rows_all: all.size, csv_sha256: hash.digest("hex").slice(0, 16) };
  const data = {
    format: 1,
    meta: { ...metaMap, ...Object.fromEntries(Object.entries(counts).map(([k, v]) => ["build_" + k, String(v)])) },
    markets: markets.map((r) => [r.program_prefix, r.market]),   // file order: a program takes the FIRST prefix it matches
    names,
    all: [...all.values()].flat(),
    zip: group(zip, (r) => r.zip),
    county: group(county, (r) => countyKey(r.county)),
    profile: dims,
  };
  return { data, counts, dataThrough: metaMap.data_through };
}

/** The module's text: one JSON.parse of a string literal (V8 parses JSON faster than the same object as JS). */
export function placementModuleSource(data) {
  return "// Generated by cloudflare/scripts/build_placement.mjs from rules_data/placement/*.csv -- do not edit, do not\n"
    + "// commit (cloudflare/build/ is git-ignored). Wrangler rebuilds it on every deploy (wrangler.toml [build]).\n"
    + `// data_through ${data.meta.data_through}, csv sha256 ${data.meta.build_csv_sha256}.\n`
    + `export default JSON.parse(${JSON.stringify(JSON.stringify(data))});\n`;
}

/** Builds and writes the module (via a temporary file and a rename, so a reader never sees half of one). */
export function writePlacementModule(csvDir = DEFAULT_CSV_DIR, out = DEFAULT_OUT) {
  const built = buildPlacementData(csvDir);
  const src = placementModuleSource(built.data);
  mkdirSync(dirname(out), { recursive: true });
  const tmp = `${out}.${process.pid}.${Date.now()}.tmp`;
  writeFileSync(tmp, src, "utf8");
  renameSync(tmp, out);
  return { ...built, out, bytes: Buffer.byteLength(src) };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const { out, bytes, counts, dataThrough } = writePlacementModule(resolve(arg("--csv-dir", DEFAULT_CSV_DIR)),
      resolve(arg("--out", DEFAULT_OUT)));
    console.log(`placement tables: wrote ${out} (${Math.round(bytes / 1024)} KB), data through ${dataThrough}; `
      + Object.entries(counts).map(([k, v]) => `${k.replace("rows_", "")} ${v}`).join(", "));
  } catch (e) {
    console.error(e.message);
    process.exit(1);
  }
}
