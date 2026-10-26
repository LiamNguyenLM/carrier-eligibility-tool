# cfig-eligibility: the Worker and D1 (round 43 step 3)

The Worker answers the API. The static site (`web/dist`: the page and the Pyodide engine) is served by Workers
Static Assets. The Worker never runs for those files. Cloudflare Access sits in front of the whole hostname. The
placement tables are part of the Worker (round 44b; they were in D1 until loading them blew the free tier): the
browser posts one check's verdicts and gets back the panel's top 3 markets and their reason lines, never the tables.

Every command below runs from the **repo root**. `wrangler.toml` goes at the root; everything else goes under
`cloudflare/`.

## Files

| file | what it is |
|---|---|
| `wrangler.toml` (repo root) | Worker `cfig-eligibility`. Assets `web/dist` with binding `ASSETS`; `run_worker_first = ["/api/*"]`. D1 `cfig-eligibility` with binding `DB` and `migrations_dir = cloudflare/migrations`. Vars `ACCESS_TEAM_DOMAIN`, `ACCESS_AUD`, `ADMIN_EMAILS`. `workers_dev` and `preview_urls` are off (see Access). |
| `package.json` (repo root) | wrangler pinned to 4.149.0 (released 2026-10-08), plus the npm scripts: dev, migrate:local, migrate:remote, build:placement, import:logs, test:worker, bench:worker, bench:gate. |
| `cloudflare/src/worker.js` | Entry point. Sends `/api/*` to `routes.js` and everything else to `ASSETS`. |
| `cloudflare/src/access.js` | Checks the `Cf-Access-Jwt-Assertion` token: RS256, team JWKS cached per isolate, `iss`, `aud`, `exp`/`nbf`, and an email in the token. Also holds the local-only `DEV_AUTH_EMAIL` bypass. |
| `cloudflare/src/routes.js` | The six `/api` routes. Checks request bodies and size limits; builds the admin CSV and the weekly counts. |
| `cloudflare/src/csv.js` | `feedback.to_csv()`'s row, byte for byte. Each report's line is built when it is written and stored in `feedback.csv_row`, so the admin download is only a join of stored lines (see CPU). |
| `cloudflare/src/placement.js` | A line-for-line port of `placement.panel()` and the functions it calls. It reads only one panel's rows, from the bundled tables in memory. |
| `cloudflare/scripts/build_placement.mjs` | `rules_data/placement/*.csv` → `cloudflare/build/placement_data.js` (git-ignored), which `routes.js` imports. wrangler.toml's `[build]` runs it before every deploy and `wrangler dev`. It refuses a CSV with a missing column, a bad month or count, or no `data_through`. |
| `cloudflare/migrations/0001_init.sql` | Tables `feedback`, `usage`, and the placement tables (dropped again by 0003). |
| `cloudflare/migrations/0002_login_failures.sql` | The password gate's lockout counter. |
| `cloudflare/migrations/0003_drop_placement.sql` | Round 44b: drops `placement_zip/county/profile/all/markets/meta`. |
| `cloudflare/scripts/import_logs.mjs` | Turns Railway's `feedback_log.jsonl` and `usage_log.jsonl` into `INSERT OR IGNORE` SQL. Safe to re-run. |
| `cloudflare/scripts/placement_parity_cases.py` | Python side of the parity check. Runs `placement.panel()` on the parity golden's profiles and writes the expected answers. |
| `cloudflare/scripts/placement_parity.mjs` | JS side. Runs the Worker's code path on the tables `build_placement.mjs` makes, and requires a byte-identical JSON match. |
| `cloudflare/scripts/bench_cpu.mjs` | CPU per request for every route, measured over blocks of 2,000 requests. |
| `cloudflare/scripts/lib.mjs`, `harness.mjs` | CSV reader, SQL literals, a D1 stand-in on `node:sqlite`, and a test Access key pair with its JWKS. |
| `cloudflare/test/worker.test.mjs` (+ `fixtures/`) | 18 route tests, all in Node. Fixtures come from the real `feedback.record()`, `usage_log.record()` and `placement.panel()`. |

## The API

All routes need a verified Access identity. Without one they return 401; a service token without an email gets 403.
POST routes need `Content-Type: application/json`.

| route | body / answer |
|---|---|
| `GET /api/whoami` | `{email, admin}` |
| `POST /api/usage` | `{ts, app_version, wall_s, carriers, timings}`, at most 16 KB. Stored with the email. `model`/`effort` are `''` and `cost` is 0. 201 `{ok, id}`. If D1 can't write it: logged, 202 `{ok: false, saved: false}` (the page ignores it). |
| `POST /api/feedback` | The fields of `feedback.record()`, at most 64 KB. A `choice` not in `CHOICES` is stored as "Not sure"; `name` and `comment` are stripped. Stored with the email. 201. If D1 can't write it: logged, 503 `{error: "Couldn’t save — try again later."}`, which the page shows. |
| `POST /api/placement` | `{pd: {zip, county, year_built, dwelling_amount, occupancy_type}, results: [{carrier, status, missing_info, reasons}], as_of?}`, at most 64 KB. Answers `placement.panel()`'s dict or `null`. Bad body: 400. Never reads D1, so it answers the same while D1 is down or out of its daily allowance. `as_of` defaults to the current month in America/Chicago. |
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
npx wrangler dev --local --var DEV_AUTH_EMAIL:liam@cfigtx.com
#   http://127.0.0.1:8787/ serves web/dist (it must exist); http://127.0.0.1:8787/api/whoami
npm run test:worker                                  # the route and gate tests (zero network)
# wrangler dev builds cloudflare/build/placement_data.js first ([build]); the tests build it themselves
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

Update the CSVs and push (round 44b, Liam 2026-10-25):

```sh
python rules_data/placement/sync_from_out.py             # as before: Claude's built tables -> rules_data/placement/
npm run build:placement                                  # optional: the row counts, or the CSV line at fault
git add rules_data/placement && git commit -m "Placement tables through YYYY-MM" && git push
```

The GitHub build runs `npx wrangler deploy`, whose `[build]` step rebuilds the module from the CSVs it checked out;
its log shows `placement tables: wrote ... data through YYYY-MM`. A bad CSV fails that step, so nothing deploys and
the live version keeps last month's tables. A deploy switches to the new tables for every request at once: no window
without a panel, and no D1 write at all.

**Why not D1:** on 2026-10-25 the D1 load used 143k rows written against D1 Free's 100k a day (about 28,700 table
rows, and each write to an indexed table counts once more per index). Once the allowance is gone, no D1 query runs
that day, reads included. In the bundle the tables cost 298 KB of the Worker's 64 MiB and about 1.5 ms of
JSON.parse at isolate start-up (limit 1 s), and the panel's CPU fell (below).

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

## Who gets in: AUTH_MODE

`AUTH_MODE` in wrangler.toml (round 44, Liam 2026-10-25):
- **"password"** (now): `src/session.js` is a shared-password gate in front of every path (`run_worker_first =
  true`). The agents' password gives a session, the admin password an admin one. The session is an HMAC-signed
  cookie, 7 days. 10 wrong passwords in 15 minutes lock that address out for 15 minutes (D1 `login_failures`).
  Secrets: `APP_PASSWORD`, `ADMIN_PASSWORD`, `SESSION_SECRET`, set with `npx wrangler secret put`; if one is missing
  or weak, every path fails closed. Tests: `test/gate.test.mjs`; CPU: `npm run bench:gate`.
- **"access"** (later): Cloudflare Access in front, and the API checks its token, as below.
- Anything else: every path 503.

## Access and the variables (AUTH_MODE = "access")

The click-by-click steps are in DEPLOY_CLOUDFLARE.md (repo root, section 8). In short:

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
Rerun this after any change to `placement.py`'s rules, or if `build_placement.mjs` changes. Round 44b (tables
from memory, 2026-10-25): 14,436 cases (no `native`), 0 differences.

## CPU per request (Workers Free plan: 10 ms)

`node cloudflare/scripts/bench_cpu.mjs --cases cloudflare/build/parity_cases.json`. Node 24 on this laptop. Each
cell is `process.cpuUsage()` over a block of 2,000 requests divided by 2,000. Every request carries an Access token
that is fully checked. Tables: the real placement tables (D1 in round 43, the bundle since 44b), 20,000 usage rows
(a year at ~55 checks a day) and 1,000 reports (5,000 for the last line).

- **A** counts everything in this process, SQLite's work included: an upper bound.
- **B** answers each D1 query from the JSON of its real answer, parsed fresh every time. That is what a Worker does
  with a D1 result, so B is the Worker's own CPU: the number the 10 ms limit counts.

Round 44b, 2026-10-25 (placement from the bundle; 5 blocks of 2,000, medians; nothing else running):

| route | A: ms/req | B: Worker ms/req |
|---|---|---|
| GET /api/whoami | 0.16 | 0.10 |
| POST /api/usage | 0.16 | 0.14 |
| POST /api/feedback | 0.22 | 0.17 |
| POST /api/placement, a panel (500 real check bodies, ~8 KB each) | 0.30 | 0.30 |
| POST /api/placement, null (fewer than 2 candidates) | 0.21 | 0.19 |
| GET /api/admin/weekly (20,000 checks) | 20.4 | 0.33 |
| GET /api/admin/feedback.csv (1,000 reports, part 1) | 12.3 | 1.01 |
| GET /api/whoami, no token (401) | 0.03 | 0.02 |

The placement rows are the same in A and B now: no D1. Under D1 (round 43, below) a panel was 3.3 ms in A and 1.0
ms in B. The password gate adds 0.05-0.10 ms a request (`npm run bench:gate`).

Round 43, 2026-10-24 (placement in D1; 3 blocks):

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
2x. Under D1 a panel read about 1,000 D1 rows (5 M rows read a day: roughly 5,000 panels); since round 44b it reads none.

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
