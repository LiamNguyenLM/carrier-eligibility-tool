# The static page (Round 43): the Eligibility Check in the browser

The Eligibility Check tab of `app.py`, as a static page. The Python engine (`engine/`) runs unchanged inside the
browser through Pyodide, and the Worker (`cloudflare/`) answers the placement panel and stores usage and feedback.

The page holds no rules of its own:
- the form, its follow-up questions and the `property_details` a submit builds come from `engine/form.py`, the same
  code `app.py` uses;
- every card string is the engine's.

## Files

| File | What it is |
|---|---|
| `index.html`, `src/styles.css` | the page shell and a plain desktop layout |
| `src/app.js` | renders the form from `engine.form.form_spec()`, wires its events, renders the results page and the "This looks wrong" control; test hook `window.__eligibility` |
| `src/engine.js` | loads Pyodide from `pyodide/`, unpacks `engine.tar.gz` into Pyodide's in-memory file system (which holds nothing else), loads `rules_data/engine_manifest.json` (no store, no model) and calls `engine.api` with JSON |
| `src/markdown.js` | the small markdown subset the card strings use (bold, italics, lists, line breaks) |
| `src/worker_api.js` | the Worker's `/api/*` calls; each one fails quietly, and the check never depends on the Worker |
| `build.mjs` | `npm run build`: writes `web/dist/`. Reports raw / gzip / brotli sizes, and fails if a placement table would ship |
| `tests/parity.mjs` | the headless-Edge parity harness (below) |
| `tests/candidate_to_golden.py` | the harness's output in the golden file's format, compared with `verification/parity/golden.json.xz` |
| `tools/serve.mjs` | a static server with a stand-in for `/api/*`, for the harness (the real Worker: `npm run dev`) |

## Build and run

```
npm ci                 # pyodide 0.28.3, playwright-core, wrangler (repo root)
npm run build          # web/dist
npm run dev            # wrangler dev: the page and the Worker together on http://localhost:8787
                       # (local D1: npm run migrate:local; a dev login: --var DEV_AUTH_EMAIL:<you>)
```

## The parity harness

```
python verification/parity/export_golden.py inputs verification/parity/golden.json.xz inputs.json
node web/tests/parity.mjs --profiles inputs.json --out web/tests/out/candidate.jsonl [--skip-form] [--ids sample.json]
python web/tests/candidate_to_golden.py web/tests/out/candidate.jsonl           # exit 0 = 0 differences
```

It has two parts.

**(a) The form.** It fills every profile's answers through the widgets' DOM events and submits. It then compares the
`property_details` the form built with the profile, and lists every profile the form cannot express, with the reason.

**(b) The check.** It runs every profile through the page, from `engine.api` to rendering, and reads each card back
from the DOM: its column and status, plus the raw strings the page rendered (`<script class="card-raw">`). That
becomes a candidate in the golden file's format.
- Each profile's `property_details` is handed over as Python's JSON text (`pd_json`), as the page's own submit
  hands over `form_request`'s text. JavaScript would turn a whole-number float such as 9.0 into 9, so a card would
  read "Fire station 9 mi" where the app reads "9.0 mi". The first full run found exactly that: 726 text differences
  in 71 profiles.

## Measured (2026-10-24, this PC, headless Edge, served from localhost)

| | |
|---|---|
| Download, first visit | 6.0 MB gzip / 5.0 MB brotli. Pyodide is 5.4 / 4.6 MB of that; its stdlib zip doesn't compress further. The engine bundle (`engine.tar.gz`, 35 files) is 648 KB gzip; the page is 15 KB. Cached after the first visit |
| First load | 1.3–1.4 s, without the download: Pyodide start about 1.05 s, bundle unpack 0.06 s, `import engine.api` 0.17 s |
| A check | engine (including the JSON round trip) median 195 ms, p95 317 ms, max 407 ms; rendering median 7 ms; 28 cards |
| Filling the form and submitting | median 187 ms |
| Parity (b), all 3,569 golden profiles | see the Round 43 step 2 commit message |

## The form: what it cannot express (part (a), all 3,569 golden profiles)

3,443 of 3,569 are expressible exactly. The rest are generated profiles the form can't produce:
- the pool boxes ticked for a pool that isn't fenced (57);
- loss follow-ups with no losses (30);
- `roof_age` over 100 (20);
- Seasonal without `primary_home_miles` (15);
- "Tier 4" (9);
- the Harris question for another county (5);
- older named profiles missing keys the form always sends;
- legacy values: "Flat/Built-Up", "Pit Bull".

Part (b) bypasses the form, so it covers all 3,569.

## Where the page differs from app.py

1. **Login:** none on the page. Cloudflare Access does it. The top bar shows the signed-in email and, for admins, a
   feedback download link.
2. **No Manage Carriers tab:** no upload or remove (see ADD_CARRIER.md), and no fingerprint, model or usage lines.
   The chat tab is gone in both versions.
3. **"This looks wrong":** an inline expander. It says "Sent -- thank you." only once the Worker has accepted the
   report; otherwise "Could not send ... Try again.", keeping what was typed.
4. **The placement panel:** fetched from the Worker after the cards render, then shown above the columns within 2 s,
   or not at all.
5. **Dollar signs:** `$...$` stays text. Streamlit turns a line with two dollar amounts into LaTeX.
6. **Inputs:** multiselects are checkbox lists (pick order kept, no type-to-search), and number inputs clamp to
   their range. Help texts are "?" tooltips.
7. **Kept as in app.py:**
   - any form change clears the results;
   - a hidden follow-up question goes back to its default;
   - the pool boxes reset when the pool answer changes.
8. **No model:** usage rows carry no token or cost fields, and feedback's `model` is "". A guide with no rules table
   shows under Could Not Be Checked: "No rules table yet for this guide...".
