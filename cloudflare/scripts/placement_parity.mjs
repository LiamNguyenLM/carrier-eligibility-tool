// The placement parity check (round 43 step 3): the Worker's /api/placement port against Python's placement.panel().
//
// usage (cwd = the repo root):
//   python cloudflare/scripts/placement_parity_cases.py cloudflare/build/parity_cases.json [--native 300]
//   node cloudflare/scripts/placement_parity.mjs cloudflare/build/parity_cases.json [more case files...]
//        [--csv-dir rules_data/placement] [--show 10]
//
// It builds the tables the Worker bundles (build_placement.mjs, from the same CSVs placement.py reads), then for
// every case runs the Worker's own code path -- parsePlacementBody (the request as the browser sends it),
// loadPanelTables (one panel's rows from those tables; round 44b, D1 before) and buildPanel -- and compares
// JSON.stringify of the result with Python's, exactly (key order included). Exit 1 on any difference.
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { buildPlacementData } from "./build_placement.mjs";
import { placementPanel } from "../src/placement.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..");

async function main() {
  const args = process.argv.slice(2);
  const opt = (name, d) => { const i = args.indexOf(name); if (i < 0) return d; const v = args[i + 1]; args.splice(i, 2); return v; };
  const csvDir = resolve(opt("--csv-dir", join(ROOT, "rules_data", "placement")));
  const show = parseInt(opt("--show", "10"), 10);
  const { data } = buildPlacementData(csvDir);
  let total = 0, diffs = 0;
  const by = {};
  const shown = [];
  for (const file of args) {
    const cases = JSON.parse(readFileSync(file, "utf8"));
    for (const c of cases) {
      const got = placementPanel(data, { pd: c.pd, results: c.results, as_of: c.as_of });
      const a = JSON.stringify(got), b = JSON.stringify(c.expected);
      const v = (by[c.variant] ??= { cases: 0, panels: 0, diffs: 0 });
      v.cases++; total++;
      if (c.expected) v.panels++;
      if (a !== b) {
        v.diffs++; diffs++;
        if (shown.length < show) shown.push({ id: c.id, variant: c.variant, as_of: c.as_of, js: got, py: c.expected });
      }
    }
  }
  for (const [v, s] of Object.entries(by)) console.log(`${v.padEnd(8)} ${s.cases} cases (${s.panels} with a panel): ${s.diffs} differences`);
  console.log(`TOTAL    ${total} cases: ${diffs} differences`);
  for (const s of shown) console.log(JSON.stringify(s, null, 1));
  process.exit(diffs ? 1 : 0);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
