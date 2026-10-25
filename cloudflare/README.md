# cfig-eligibility: the Worker and D1 (round 43 step 3)

The Worker answers the API. The static site (`web/dist`: the page and the Pyodide engine) is served by Workers
Static Assets. The Worker never runs for those files. Cloudflare Access sits in front of the whole hostname. The
placement tables live only in D1: the browser posts one check's verdicts and gets back the panel's top 3 markets and
their reason lines, never the tables.

Every command below runs from the **repo root**. `wrangler.toml` goes at the root; everything else goes under
`cloudflare/`.

## Files

| file | what it is |
|---|---|
| `wrangler.toml` (repo root) | Worker `cfig-eligibility`. Assets `web/dist` with binding `ASSETS`; `run_worker_first = ["/api/*"]`. D1 `cfig-eligibility` with binding `DB` and `migrations_dir = cloudflare/migrations`. Vars `ACCESS_TEAM_DOMAIN`, `ACCESS_AUD`, `ADMIN_EMAILS`. `workers_dev` and `preview_urls` are off (see Access). |
| `package.json` (repo root) | wrangler pinned to 4.149.0 (released 2026-10-08), plus the npm scripts: dev, migrate:local, migrate:remote, sync:placement, import:logs, test:worker, bench:worker. |
| `cloudflare/src/worker.js` | Entry point. Sends `/api/*` to `routes.js` and everything else to `ASSETS`. |
| `cloudflare/src/access.js` | Checks the `Cf-Access-Jwt-Assertion` token: RS256, team JWKS cached per isolate, `iss`, `aud`, `exp`/`nbf`, and an email in the token. Also holds the local-only `DEV_AUTH_EMAIL` bypass. |
| `cloudflare/src/routes.js` | The six `/api` routes. Checks request bodies and size limits; builds the admin CSV and the weekly counts. |
| `cloudflare/src/csv.js` | `feedback.to_csv()`'s row, byte for byte. Each report's line is built when it is written and stored in `feedback.csv_row`, so the admin download is only a join of stored lines (see CPU). |
| `cloudflare/src/placement.js` | A line-for-line port of `placement.panel()` and the functions it calls. It reads only one panel's rows from D1, in one batch. |
| `cloudflare/migrations/0001_init.sql` | Tables `feedback`, `usage`, `placement_zip/county/profile/all/markets/meta`, with the indexes the panel's queries use. |
| `cloudflare/scripts/sync_placement.mjs` | The monthly refresh: `rules_data/placement/*.csv` become one SQL file that replaces every placement table. |
| `cloudflare/scripts/check_placement.sql` | Run after a refresh: compares row counts with the counts the sync wrote. `all_ok` must be 1. |
| `cloudflare/scripts/import_logs.mjs` | Turns Railway's `feedback_log.jsonl` and `usage_log.jsonl` into `INSERT OR IGNORE` SQL. Safe to re-run. |
| `cloudflare/scripts/placement_parity_cases.py` | Python side of the parity check. Runs `placement.panel()` on the parity golden's profiles and writes the expected answers. |
| `cloudflare/scripts/placement_parity.mjs` | JS side. Runs the Worker's code path on node:sqlite and requires a byte-identical JSON match. |
| `cloudflare/scripts/bench_cpu.mjs` | CPU per request for every route, measured over blocks of 2,000 requests. |
| `cloudflare/scripts/lib.mjs`, `harness.mjs` | CSV reader, SQL literals, a D1 stand-in on `node:sqlite`, and a test Access key pair with its JWKS. |
| `cloudflare/test/worker.test.mjs` (+ `fixtures/`) | 18 route tests, all in Node. Fixtures come from the real `feedback.record()`, `usage_log.record()` and `placement.panel()`. |

## The API

All routes need a verified Access identity. Without one they return 401; a service token without an email gets 403.
POST routes need `Content-Type: application/json`.

| route | body / answer |
|---|---|
| `GET /api/whoami` | `{email, admin}` |
| `POST /api/usage` | `{ts, app_version, wall_s, carriers, timings}`, at most 16 KB. Stored with the email. `model`/`effort` are `''` and `cost` is 0. 201 `{ok, id}`. |
| `POST /api/feedback` | The fields of `feedback.record()`, at most 64 KB. A `choice` not in `CHOICES` is stored as "Not sure"; `name` and `comment` are stripped. Stored with the email. 201. |
| `POST /api/placement` | `{pd: {zip, county, year_built, dwelling_amount, occupancy_type}, results: [{carrier, status, missing_info, reasons}], as_of?}`, at most 64 KB. Answers `placement.panel()`'s dict or `null`. Bad body: 400. D1 unavailable (for example during a refresh import): 503, and the page should show no panel. `as_of` defaults to the current month in America/Chicago. |
| `GET /api/admin/feedback.csv` | Admins only (403 otherwise). The same bytes as `feedback.to_csv()` (same columns, same Python CSV and `json.dumps` formatting), plus an `email` column at the end. |
| `GET /api/admin/weekly` | Admins only. `{weeks: [{week: "2026-W43", start, checks, feedback}], totals}`, counted by `received_at` in UTC ISO weeks. |

**`missing_info` / `reasons` in the placement body:** send the **first non-blank string** of each list, not
blindly the first item. `panel()` skips blank and non-string items, so a list that starts with `""` would otherwise
give a different "Held: confirm ..." line. On all 3,569 golden profiles the two readings give the same result. The
Worker reduces any list it gets to its first non-blank string, so sending the whole list is also correct, just bigger.

## Run it locally (no Cloudflare login needed)

```sh
npm ci                                              # at the repo root: wrangler 4.149.0, pyodide, playwright-core
npx wrangler d1 migrations apply DB --local
node cloudflare/scripts/sync_placement.mjs           # -> cloudflare/build/placement_sync.sql
npx wrangler d1 execute DB --local --file=cloudflare/build/placement_sync.sql
npx wrangler dev --local --var DEV_AUTH_EMAIL:liam@cfigtx.com
#   http://127.0.0.1:8787/ serves web/dist (it must exist); http://127.0.0.1:8787/api/whoami
npm run test:worker                                  # the route tests (zero network)
```

`DEV_AUTH_EMAIL` stands in for an Access token only when the request is plain `http://` to localhost, 127.0.0.1 or
[::1]. Under `wrangler dev`, a request with `Host: eligibility.cfigtx.com` still gets 401; I tried it. Never put
`DEV_AUTH_EMAIL` in `wrangler.toml`. Use `--var` or a git-ignored `.dev.vars`.

**Windows path length:** the local D1 file sits at
`.wrangler/state/v3/d1/miniflare-D1DatabaseObject/<64 hex>.sqlite`. Under a long directory (anything in `%TEMP%`)
the full path goes past 260 characters, and wrangler then fails with a bare `internal error; reference = ...`. Run it
from the repo, not from a Temp copy.

Add to `.gitignore`: `cloudflare/node_modules/`, `cloudflare/build/`, `.wrangler/`, `.dev.vars`.

## The monthly placement refresh (Liam)

This replaces "commit and push the refreshed CSVs" for the panel's data. The CSVs stay in the repo as the source and
are still committed.

```sh
python rules_data/placement/sync_from_out.py             # as today: Claude's built tables -> rules_data/placement/
git add rules_data/placement && git commit -m "Placement tables through YYYY-MM"
node cloudflare/scripts/sync_placement.mjs               # -> cloudflare/build/placement_sync.sql (~1.6 MB)
npx wrangler d1 execute cfig-eligibility --remote --file=cloudflare/build/placement_sync.sql
npx wrangler d1 execute cfig-eligibility --remote --file=cloudflare/scripts/check_placement.sql
#   all_ok = 1, data_through = the new month
```

**Is a half-applied refresh possible?** No, as far as wrangler 4.149 says, though I could not try it against a real
account:

- `--remote --file` goes through D1's import API, and wrangler prints: "if the execution fails to complete, your DB
  will return to its original state and you can safely retry". It also warns that the database is unavailable to
  queries while the import runs. In that window `/api/placement` answers 503 and the page shows no panel; nothing
  ever reads a half-written table.
- `--local --file` runs the whole file as one `batch()`, which is one transaction.
- For the same reason the file has no `BEGIN`/`COMMIT`: wrangler strips one pair and refuses more.

The file is DELETE-all followed by INSERTs. It is byte-identical for the same CSVs, so re-running it is harmless. The
sync refuses to write anything if a CSV is missing a column, has a bad month or count, or `placement_meta.csv` has no
`data_through`. `check_placement.sql` is the after-check. A versioned-rows design (load a new version, then flip a
pointer) would cover a non-atomic import too. I left it out because the import is atomic and it would add a column
to every query.

## Importing the Railway logs (once, or again later)

```sh
# Liam: download carrier_docs_db/feedback_log.jsonl and usage_log.jsonl from the Railway volume first
node cloudflare/scripts/import_logs.mjs --feedback feedback_log.jsonl --usage usage_log.jsonl
npx wrangler d1 execute cfig-eligibility --remote --file=cloudflare/build/import_logs.sql
```

- Each line's key is the sha256 of its JSON with sorted keys, inserted with `INSERT OR IGNORE`. Importing the same
  or a longer download again adds only the new lines. Tested: imported twice, the counts stayed the same.
- Imported rows get `source = 'railway'`, `email = ''` and `received_at = ts`.
- Lines that are not JSON, or have no `ts`, are skipped and reported.
- The SQL holds real agent feedback. Do not commit it; delete it after the import.

## Access and the variables

The click-by-click steps are in DEPLOY_CLOUDFLARE.md (repo root). In short:

1. Protect the Worker with Access (the Worker's **Access** tab → All traffic; it covers the workers.dev address
   Liam chose for now and any custom domain later). Copy the application's **AUD tag** into `ACCESS_AUD`.
2. `ACCESS_TEAM_DOMAIN` is the team domain, `<team>.cloudflareaccess.com`. `wrangler.toml` ships a placeholder; until
   both are real values every /api call fails closed (500).
3. `ADMIN_EMAILS` is a comma list, case-insensitive. Liam (`liam@cfigtx.com`) is in it. **Jonathan's address is a
   placeholder** (`JONATHAN-ADDRESS-TBD@cfigtx.com`): replace it.
4. `workers_dev` stays false until Access is on, then Liam sets it to true (the app's address); `preview_urls` stays
   false. A `*.workers.dev` or preview URL without Access in front would serve `web/dist` (the engine and its rules
   tables); the API would still refuse requests there, because it checks the token itself.
5. Once: `npx wrangler d1 create cfig-eligibility`, then put the printed `database_id` into `wrangler.toml`.

## Placement parity (the port against Python)

```sh
python cloudflare/scripts/placement_parity_cases.py cloudflare/build/parity_cases.json [--native 300]   # ~4 min (+~25 min native)
node cloudflare/scripts/placement_parity.mjs cloudflare/build/parity_cases.json
```

Result on 2026-10-24, data through 2026-10, wrangler not involved: **0 differences in 14,896 cases.** The JSON was
compared byte for byte, key order included.

- `golden`: 3,569 cases (all profiles at 2026-10).
- `months`: 7,138 cases (the same profiles at 2025-12 and 2027-02).
- `literal`: 3,569 cases (each list cut to its first item even when blank).
- `edge`: 160 cases (awkward whitespace, a 200-code-point emoji reason, a re-cased county, an empty ZIP).
- `native`: 460 cases (the 160 named profiles plus 300 seeded fuzz profiles, re-checked by the native engine with
  their real reason texts).

Python always got the full records and the full property details. The Worker got the reduced body the browser sends.
Rerun this after any change to `placement.py`'s rules, or before trusting a new month's tables if the sync changed.

## CPU per request (Workers Free plan: 10 ms)

`node cloudflare/scripts/bench_cpu.mjs --cases cloudflare/build/parity_cases.json`. Node 24 on this laptop. Each
cell is `process.cpuUsage()` over a block of 2,000 requests divided by 2,000. Every request carries an Access token
that is fully checked. Tables: the real placement tables, 20,000 usage rows (a year at ~55 checks a day) and 1,000
reports (5,000 for the last line).

- **A** counts everything in this process, SQLite's work included: an upper bound.
- **B** answers each D1 query from the JSON of its real answer, parsed fresh every time. That is what a Worker does
  with a D1 result, so B is the Worker's own CPU: the number the 10 ms limit counts.

| route | A: ms/req (3 blocks) | B: Worker ms/req (3 blocks) |
|---|---|---|
| GET /api/whoami | 0.22, 0.29, 0.23 | 0.24, 0.29, 0.27 |
| POST /api/usage | 0.34, 0.35, 0.30 | 0.30, 0.23, 0.29 |
| POST /api/feedback | 0.23, 0.47, 0.34 | 0.30, 0.37, 0.37 |
| POST /api/placement, a panel (500 real check bodies, ~8 KB each) | 3.41, 3.27, 3.29 | 1.06, 0.96, 0.95 |
| POST /api/placement, null (fewer than 2 candidates) | 2.19, 2.15, 1.95 | 0.49, 0.41, 0.41 |
| GET /api/admin/weekly (20,000 checks) | 17.6, 18.7, 18.2 | 0.34, 0.31, 0.34 |
| GET /api/admin/feedback.csv (1,000 reports) | 3.20, 3.40, 3.66 | 1.59, 1.63, 1.67 |
| GET /api/admin/feedback.csv (5,000 reports, ~4.5 MB) | 39.3, 32.7, 22.8 | 8.18, 8.11, 8.04 |
| GET /api/whoami, no token (401) | 0.06, 0.04, 0.05 | 0.06, 0.06, 0.04 |

The Access check alone costs 0.05 to 0.2 ms; the laptop was shared with other jobs, so small numbers wander by about
2x. A panel reads about 1,000 D1 rows; at D1 Free's 5 M rows read a day, that is roughly 5,000 panels a day.

**What this proves:** the Worker's own JavaScript (token check, body parsing, the panel arithmetic, building the
CSV) stays under 10 ms by a wide margin on every route, except the CSV once there are about 6,000 reports. Two
designs came out of these measurements:

- The weekly counts are grouped by week in SQL, not by day in JS.
- Each report's CSV line is built when the report is written, and D1 joins the lines 400 at a time. Building 1,000
  CSV rows in the Worker cost 15 to 36 ms.

**What it does not prove:**

- workerd is not Node. Both run V8, but the runtime around it, the WebCrypto backend (BoringSSL against OpenSSL) and
  how a D1 result is deserialized all differ.
- A D1 query's time in production is I/O to the database, not Worker CPU. A's SQLite share says nothing about D1's
  real latency, about D1's own per-query limits, or about the 18 ms weekly query: D1 runs it, and it grows with the
  usage table.
- A cold start and the isolate's first JWKS fetch are not in the blocks (each route warms up first).
- The Free plan allows some burst above 10 ms; I did not rely on that.

Confirming in production: Workers Observability (`[observability] enabled = true`) shows CPU time per invocation.
