# Moving the Carrier Eligibility Tool from Railway to Cloudflare

Round 42 (2026-10-24). Planning only. No product code changed this round. Railway stays live (Hobby) until the new
version matches it, the parity check passes and Liam signs off.

**Recommendation: Design B1.** The page is static, and today's Python engine runs unchanged in the agent's browser
(Pyodide). A small Worker writes feedback and the usage log to D1, and Cloudflare Access handles login. On the free
plans this costs **$0 a month** for CFIG's size (assumptions in §3.1).

**Fallback: Design C.** The same Python runs in a Python Worker on Workers Paid, at **$5 a month**. Use it if Liam does
not want the rules tables in agents' browsers, or if the first load is too slow on agents' machines. B1 and C share
the engine bundle and the page, so the choice between them can wait until the Round 44 prototype has been measured.

**Round 43 update (2026-10-24): Liam's answers, and the plan they set.**

1. Drop the chat tab. (Done: round 43 step 0c.)
2. cfigtx.com's DNS is unknown yet, so build for a workers.dev address; the custom domain can come later.
3. Move to Cloudflare as soon as parity passes; no long side-by-side.
4. Every office computer has a modern browser; no phone support is needed.
5. Design B1 is accepted: the Python engine runs unchanged in the browser (Pyodide), behind Cloudflare Access.
6. The Worker answers the placement panel. The placement tables never ship to the browser, which gets only the top 3
   markets and the reason lines.
7. Login: Cloudflare Access with the emailed one-time PIN first (no Microsoft admin setup needed); Microsoft 365 can
   be added later. Admins are Liam and Jonathan.

Rounds 43 and 44 below are merged: **Round 43** split the engine, built the page and the Worker and ran them locally
(not deployed); **Round 44** deploys them (DEPLOY_CLOUDFLARE.md). Railway stays only until Round 44's checks pass.

---

## 0. Step 0 results

### 0a. WIL-123 stays a decline (commit 2c8f3db)

The Wilshire guide's cell reads:

> "Risk is eligible only if all of the following criteria are met: … Age of Home must be less than 25 years, and
> Primary occupancy dwellings only, and No rental exposures allowed, and No prior fire losses."

The cell names no underwriting or referral path. The p.9 footer ("This list is not all inclusive. If any questions,
please check with your underwriter.") is general and attaches to no rule. By the Round 31 rule it stays a decline.
`verification/test_wil123_quote.py` pins the quote for Wilshire, SURE and Occidental, and the DECLINE decisions.

### 0b. A normal check makes no paid API call, and no network call at all (commit 7140e24)

Measured on Liam's Harris HO3 check and on LANDLORD, in the live configuration (every rules-table batch on,
placement on, the key loaded). Every socket connect and DNS lookup was logged with its caller:

- **0 connections and 0 DNS lookups**, at import and in every run.
- **The model was not called** (`LAST_CALL_USAGE` = None). Since Round 41 B4, code decides or holds every
  rules-table carrier.
- **What a check does use:** 2 local retrieval searches (FastEmbed + Chroma on disk, 0.05–0.3 s each), from the
  risk-factor pass. Their output feeds only the model prompt.
  - Run with the searches returning nothing on Harris, LANDLORD and 149 fuzz profiles (151 in all): **0 of 151
    profiles differ**, and no model call was attempted.
  - **Neither the verdict nor the card needs retrieval.**
- **The chat tab ("Ask the Guides", chat.py) is the only paid call:** OpenAI `gpt-6-luna` plus retrieval, every time
  it is used.

`verification/test_no_network.py` blocks every connect and lookup, then checks three things: both profiles and the
placement panel still run, nothing tried to reach the network, and the cards match a run with the network on.

---

## 1. Inventory: what each feature needs at run time

| Feature | What it needs at run time | Data (size) | Retrieval / model? |
|---|---|---|---|
| Form (app.py, intake_fields) | ZIP → county lookup, form choices | texas_counties.csv + zip_counties.csv, 73 KB (21 KB gz) | No |
| Password gate | `APP_PASSWORD` | – | No. Replaced by Access |
| The check: rules engine (rules_evaluator, structured_rules, hold_guard, intake_fields, topics) | Rules tables, map lines, CFIG knowledge, Occidental counties | 2,430 KB raw / 457 KB gz (review columns could be trimmed) | No |
| The check: routing, defects, closed programs, the Sage county hold, notes, the Chubb checks, held-by-code (eligibility_check.py) | **Today it reads the Chroma store's metadata** (carrier list, occupancies, combined programs) and scans the store's text for defects | Store 25 MB; the facts it reads would make a few KB of JSON | Store reads only. Must become a build-time manifest (Round 43) |
| Risk-factor retrieval pass | FastEmbed model + Chroma | about 130 MB model + 25 MB store | Retrieval, unused by any card (0b). Drop |
| Cards (cards.py, display_names) | The record and the guide dates | Guide dates come from the manifest | No |
| "Things to confirm" box (confirm_topics.top_box) | The results | – | No |
| Placement panel (placement.py) | Five HawkSoft tables | 947 KB raw / 101 KB gz | No. **Book-of-business data, see §3.5** |
| Feedback ("This looks wrong") | Append-only log on the Railway volume (`carrier_docs_db/feedback_log.jsonl`) | About 2 KB a line: the property details as entered (ZIP, county, no client name), the carrier, verdict, reasons, rows, the agent's choice and comment, and an optional agent name | No. Worker + D1 |
| Usage log | Append-only on the volume (`usage_log.jsonl`) | Under 0.5 KB a check; no property details | No. Worker + D1 (or drop: with no model calls it records no cost) |
| Manage tab: Fingerprint, status lines | Store fingerprint, env flags | – | Replaced by a build manifest |
| Manage tab: Upload PDF / Remove carrier | Chroma write, PDF folder | 42 PDFs, 16 MB | Replaced by the add-carrier runbook + a push |
| Manage tab: feedback download | The feedback log | – | An Access-gated Worker route |
| Chat tab (chat.py) | OpenAI key, Chroma, whole-guide rebuild (guides.py) | Store 25 MB + model | **Yes: retrieval and a paid model.** See §3.6 |
| Guide-only path (a carrier with no rules table) | The model reading the guide | – | Model. In the live configuration no routed carrier uses it. 39 of 42 carriers have tables; the other 3 are Liberty HO6 (defective) and the two closed NatGen Premier OneChoice programs |

Environment variables read today: `APP_PASSWORD`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `CHAT_MODEL`,
`CHAT_REASONING_EFFORT`, `CHAT_LOG_PATH`, `RAILWAY_GIT_COMMIT_SHA`, and the `ELIGIBILITY_*` flags. The new design
needs none of them in the browser. The Worker needs only its D1 binding (and the OpenAI key, if the chat moves).

---

## 2. The engine, measured

Same machine; numbers are single-threaded. Some of these runs overlapped the 8-shard test run, so treat them as
upper bounds.

### 2a. CPU per check

On the 3,409 Round 38 fuzz profiles, each check covered every routed carrier (median 28):

| Measured | CPU per check, median / p95 / max |
|---|---|
| Rules engine + card text (evaluate_carrier, code_record, card_items, first line) | **125 ms / 328 ms / 641 ms** (5.6 ms per carrier) |
| Today's full `check_eligibility` (300 profiles; embedding model, store reads, thread pool; summed over threads, under load) | 6.6 s / 9.3 s / 11.3 s |

- On wall-clock time a full check takes about 1 s on this machine. Most of that CPU goes to the embedding model, store
  reads and the thread pool. 0b shows no card needs them, so the new design removes them. The post-processing that
  stays was not timed on its own; Round 43's split measures it.
- **The post-processing in eligibility_check.py changes 216 of 7,573 core statuses (2.9%).** Examples are the Chubb
  checks, and Progressive HO6 routing that drops a card. A port must therefore carry that post-processing, not only
  rules_evaluator. The parity golden is taken on the full path for this reason.

### 2b. Imports

- **The engine modules are pure standard library:** rules_evaluator, intake_fields, structured_rules, hold_guard,
  cards, confirm_topics, display_names, topics, placement. They read only CSV/JSON files.
- **eligibility_check.py is not pure.** It imports Streamlit, LangChain/Chroma, Anthropic and shared_resources
  (FastEmbed), and reads the store through store_cache / data_defects / guides. Round 43 splits its decision code
  into pure modules.

### 2c. Download size for a browser

| Part | Raw | gzip -9 |
|---|---|---|
| Engine code (pure modules) | 230 KB | 72 KB |
| eligibility_check.py (to be split) | 284 KB | 89 KB |
| Rules tables, map lines, CFIG, Occidental counties | 2,430 KB | 457 KB |
| ZIP / county lookups | 73 KB | 21 KB |
| Placement tables | 947 KB | 101 KB |
| **All of it** | **3,965 KB** | **740 KB** |
| Pyodide 0.28.3 runtime (core + stdlib) | about 12.3 MB | about 5.4 MB |

Brotli was not installed, so it was not measured. It would be somewhat smaller than gzip.

### 2d. Pyodide (Node, Pyodide 0.28.3, 200 fuzz profiles)

- **It works unchanged.** The engine files and CSVs were copied into Pyodide's file system with no code edits.
- **Its verdicts and card text are identical to native** on all 200 profiles, for every field compared: status,
  reasons, citations, missing items, confirm items, first line, and program and coverage notes. This ran the rules
  engine and card helpers. eligibility_check.py's post-processing was not in it, because that file imports Streamlit.
- **Speed:**
  - First load: 2.05 s (Pyodide start from local disk), plus 0.52 s for the first check, which reads the tables.
  - After that: median 114 ms CPU per check, p95 202 ms, max 476 ms.
- **First visit in a browser:** about 6.2 MB gzip to download (Pyodide + engine + data), cached afterwards. On a
  50 Mbit/s office line that is about 1 s, plus about 2 s for Pyodide to start, plus 0.5 s for the first check.
  Later visits skip the download.

---

## 3. Designs

### 3.1 Assumptions for cost

- 10–15 agents.
- At most 100 checks a day (about 3,000 a month).
- About 10 feedback rows a day, and one usage row per check.
- Office hours of about 10 h a day, 22 days a month.

### 3.2 The four designs

| | **A. Container** (today's Streamlit app in a Cloudflare Container) | **B1. Static page + Pyodide** (recommended) | **B2. Static page + TypeScript port** | **C. Python Worker on Workers Paid** |
|---|---|---|---|---|
| Monthly cost | **About $13** if it sleeps when idle (standard-1: ½ vCPU, 4 GiB; $5 plan + about $7.70 memory + $0.40 disk; CPU inside the 375 vCPU-min included). **About $33** if always on. Railway's bill could carry on too if the chat stays there | **$0** (Workers Free + D1 Free + Access Free) | **$0** | **$5** (Workers Paid). Checks use about 0.9 M of the 30 M CPU-ms included |
| Work, in rounds | 1–2 (Dockerfile; the logs move to D1 or R2 because disk is ephemeral) | 4 (§5) | 7–9: port about 4,000 lines of engine plus the post-processing to TS, and keep two engines in step | 4, like B1. The page calls the Worker instead of Pyodide |
| Engine code | Unchanged | **Unchanged Python** | Rewritten | **Unchanged Python** |
| First load / cold start | 1–3 s container start (Cloudflare's figure), plus app boot (Streamlit, FastEmbed, Chroma; not measured, probably 10 s or more) after every idle sleep | About 3.5 s on a first visit, about 2.5 s on later ones (Pyodide start); then 0.1–0.5 s a check | Under 1 s; about 0.8 MB | Python Worker cold start plus a 0.5 s table read on a cold isolate. Under 1 s once warm |
| 10 ms CPU limit | n/a | **Holds** for the Worker: 0.08–0.17 ms CPU a request (Access token check + parse + insert parameters, measured). The engine never runs in the Worker | Holds, same as B1 | Does not hold (125–641 ms a check), so Workers Paid (30 s default) |
| Rules tables and placement data | Stay on the server | **In every agent's browser cache** (behind Access) | In the browser | Stay on the server |
| Risks | Ephemeral disk; Streamlit websocket sessions keep the container awake (cost); the least change but the least gain | First-load time on older laptops; Pyodide on agents' browsers (an old browser or a phone) | Two engines drifting; every rules change made twice; the 6,000-test Python suite no longer tests what agents run | Python Workers' maturity (the docs page does not say whether it is still beta); 128 MB memory per isolate (not measured); 1 s startup limit (load tables lazily) |
| Lost | Little: upload and reseed would need rework (disk) | See §3.7 | Same as B1 | Same as B1 |

**Why B1 over C:** it is free, needs no server compute, and no cold start can stack up. The engine Python is the
same file in both.

**Why C might win:** the rules tables (derived from carrier guides, 17 of which are marked confidential) and the
HawkSoft placement data would never leave Cloudflare. Agents would download about 1 MB instead of 6.

**Not recommended:**
- **A** keeps every Railway-era cost driver (embedding model, store, Streamlit) for a monthly bill.
- **B2** rewrites code the test suite exists to protect.

### 3.3 Cloudflare Access

- **Free plan limit:** Cloudflare's Access product page, https://www.cloudflare.com/sase/products/access/ (read
  2026-10-24), says the Free plan is "$0 … forever", lists a "50 user limit", and is "Best for teams under 50 users".
- **If CFIG outgrows it:** pay-as-you-go is "$7 per user/month (paid annually)", from the same page.
  - Community answers (not official) say that past 50, all seats become billable, not only the extra ones.
  - At 51 users that would be about $357 a month. CFIG is far below 50.
- **Seats:**
  - A user takes a seat on their first Access login.
  - When the limit is reached, new users are blocked
    (https://developers.cloudflare.com/cloudflare-one/identity/users/seat-management/).
  - Seats can be removed in Zero Trust → Users.
- **How agents would log in.** Both options below are free:
  - **One-time PIN by email.** The PIN goes only to addresses the policy allows (e.g. `*@cfigtx.com`, or a list of
    agents). It is single use and expires in 10 minutes.
  - **Microsoft Entra ID (Microsoft 365) single sign-on**, so agents use their work login. Recommended if CFIG's mail
    is on Microsoft 365.
  - The session lasts as long as the policy sets (e.g. 24 h or a week).
- **The Worker trusts Access:**
  - It checks the `Cf-Access-Jwt-Assertion` token against the team's public keys. That is the 0.1 ms measured above.
  - It records the agent's email with each feedback row. That replaces the optional typed name.
- **Must check in Round 45:** Access covers every hostname that serves the app, including `*.workers.dev` and the
  preview URLs, or those are turned off. I believe a Worker's settings can put Access on workers.dev and preview
  URLs, but that is not verified this round.

### 3.4 Replacements for what has no place in a static page

| Today | Replacement |
|---|---|
| Guide-only path (the model reads a guide with no rules table) | A carrier without a table shows under "Could Not Be Checked" as "Rules not built yet — read the guide", until its table is built. None is routed today (see the §1 inventory) |
| In-app Upload PDF / Remove carrier | The add-carrier runbook (rules table, map lines, tests), then a commit and a push. The push deploys the new carrier. Removing a carrier is a one-line manifest edit and a push |
| Fingerprint panel and status lines | A build manifest written at deploy time and shown on an "About" panel: commit, build date, each carrier's guide date and table row count, and the golden file's digest. Same purpose, and it cannot drift from what is deployed |
| Reseed / `FORCE_RESEED` | Not needed: no store at run time, and every deploy carries its data. (The store stays an offline build input, for defect scans and the chat tab if it is kept) |
| Feedback download (Manage tab) | `GET /admin/feedback.csv` on the Worker, behind an Access policy for Liam only. Or `wrangler d1 export` |
| Usage / budget panel | A count of checks per month from D1. There is no model spend to show |

### 3.5 Placement panel: what it would ship

- **What the tables hold:** month, ZIP / county / profile dimension, market and n. No client names, policy numbers or
  IDs, hashed or otherwise.
- **They are very granular:** 10,527 of the 12,174 ZIP rows have n = 1. That is CFIG's book of business, one placed
  policy a row.
- **Under B1**, anyone who passes Access can save it from the browser cache.
- **Options** (decision for Liam):
  1. **The Worker answers the panel** (recommended). Load the tables into D1, and have the Worker return only the
     ranked panel for one ZIP/county. That means porting placement.py's ranking (315 lines) to JS, with its own parity
     test over the fuzz set. It costs well under 10 ms a request (a keyed D1 read and a sort).
  2. **Coarsen the tables before shipping:** year instead of month, cells under 5 suppressed. It changes the panel's
     numbers, so it needs Liam's sign-off.
  3. **Ship the tables as they are**, behind Access.

### 3.6 The chat tab

- It cannot run in the browser: the OpenAI key would be exposed, and FastEmbed + Chroma are not portable.
- **Options:**
  1. **Drop it.**
  2. **Keep it on Railway, chat only, while it is used.** Railway's cost stays.
  3. **Move it to a Worker on Paid.** The OpenAI key becomes a Worker secret. Retrieval needs Vectorize and
     Workers AI or OpenAI embeddings, because FastEmbed does not run there. That is one more round, and a new
     retrieval stack to re-test against test_chat.py.
- Whether agents use it is in `CHAT_LOG_PATH` on the Railway volume, which only Liam can read.

### 3.7 What Liam loses under B1 / C

- Uploading or removing a carrier from the app. That becomes a push.
- The guide-only model check for a carrier with no table. That becomes a "rules not built yet" card.
- The chat tab, unless it is kept (§3.6).
- The Streamlit look. The page is rebuilt in plain HTML with the same columns, cards and expanders.
- **A slower first visit under B1:** about 3.5 s, then about 2.5 s on each later page load.
- **Nothing in verdicts or cards.** The parity check makes sure of that before cut-over.

### 3.8 Deploys, how Liam pushes, rollback

- **Deploys:** Workers Builds connects the GitHub repo.
  - **A push to `main` builds and deploys**, as on Railway today. The build step assembles the static site: engine
    .py files, CSVs, manifest and a self-hosted Pyodide.
  - A push to another branch gets a preview URL, behind Access.
  - The 25 MiB per-file limit fits Pyodide's largest file.
- **How Liam pushes:** the same `git push` as now. There are no Railway variables to set, because the Worker's D1
  binding lives in `wrangler.toml`.
- **Rollback:**
  - **Code:** Dashboard → Workers → Deployments → Rollback, or `npx wrangler rollback <version>`. Any of the 100 most
    recent versions.
  - **Data:** D1 Time Travel restores the database to a minute in the last 7 days (Free) or 30 days (Paid).
  - **Keep D1 schema changes additive,** so a code rollback never meets a newer schema.
- **Cut-over rollback:** Railway keeps running for at least 30 days after cut-over. Rolling back is "use the old
  link", and needs no deploy.

---

## 4. Parity harness (Step 4; commit in this round)

**`verification/parity/export_golden.py`** writes, compares and shows the golden file
`verification/parity/golden.json.xz`.

**What it captures.** Today's engine output, on the full `check_eligibility` path in the live configuration (no model
call; a stub raises), for:
- the 3,409 Round 38 fuzz profiles;
- the named profiles: LIVE, STANDARD, ALT, COASTAL_PPC4, LANDLORD, HOME, Liam's Harris HO3 check, The Hartford's cases
  a–k (31), the Round 40 base pair, and the first 60 profiles each of the Hartford and Round 40 deep checks.

For each profile:
- its inputs, and the "Things to confirm" box;
- for each carrier, in the order returned:
  - the record (status, raw status, flaw_count, deciding rows, held fields, confirm rows, reasons, citations, notes,
    also-confirm, confirm items);
  - the rendered card (name, first line, Missing, Confirm, Details, row IDs; the warning line for a carrier that could
    not be checked).

**How the check works:**
- **Exact match** on:
  - the carriers and their order;
  - status, raw status, flaw_count;
  - the deciding rows (row IDs in the reasons);
  - the held fields (missing_info);
  - the confirm rows;
  - the inputs.
- **Every text is compared after collapsing whitespace.** HTML is split after each list item.
- **Named profiles keep their texts in full**, so a difference reads as text.
- **Fuzz cards keep a 12-hex sha1 of each canonical text,** which keeps the file small. `export_golden.py show
  <profile>` prints the native card in full.
- A port writes the same format, using the same `canonical()` and `digest()`, and passes when
  `export_golden.py compare golden.json.xz port.json.xz` reports 0 differences.
  - `export_golden.py inputs` writes the 3,569 profiles' inputs as plain JSON (3.1 MB) for the port's runner.

**The file as committed:**
- 3,569 profiles, 90,782 cards.
- 10,343 distinct texts, 240,745 distinct text hashes, 30,857 distinct row lists. Each is stored once and cards hold
  indices.
- **4.2 MB, xz-compressed** (56 MB as JSON). A first gzip layout was 15 MB. Every re-export adds about 4 MB to the
  repo's history, so re-export when a change needs it, not on every commit.
- **The whole export takes about 30 minutes** as 8 processes at once, then `merge` (the steps are in the script's
  docstring). A single process took about 10 s a profile while the test shards were running.
- A full `compare` takes about 6 s.

**When a rules table, a card or the year changes** (ages count from today):
1. Re-export on the native engine (8 shards, then merge).
2. Run `compare` old vs new. Every difference should be the intended one.
3. Commit the new golden with the change, with a dated line in the commit naming the decision.
4. Rerun the port against it.

`verification/test_parity_golden.py` holds the golden to the engine on a sample of named and fuzz profiles on every
fast tier. So a change that forgets step 3 fails, and so does a golden made in a past year.

---

## 5. Migration rounds

Railway stays live throughout. Nothing changes for agents until step 4 of Round 46.

**Round 43: split the engine. No behaviour change.**
1. Move routing, defects, closed programs, the Sage county hold, notes, the Chubb checks, held-by-code and the record
   post-processing out of eligibility_check.py into pure modules (no Streamlit, LangChain or Anthropic).
2. A build step writes the store-derived facts to `rules_data/manifest.json`: carriers, occupancies, combined
   programs, guide dates, defects.
3. eligibility_check calls the new modules, so Railway runs the same code path.
4. Gate: golden compare 0 differences, the fast tier green, Tier 2 on the baseline profiles.

**Round 44: the browser page, on a branch.**
1. A static page with the form, confirm box, the four columns, Could Not Be Checked and the About panel. Cards come
   from cards.py's own HTML, run in Pyodide.
2. A headless-browser parity runner over the whole golden must report 0 differences.
3. Measure the first load on an agent's laptop. If it is too slow, or Liam picks C, the same bundle moves into a
   Python Worker.

**Round 45: Worker, D1, Access, deploys.** Liam's hands are needed for the Cloudflare account, the Access application
and policy, the IdP, creating the D1 database and connecting GitHub.
1. Worker routes: feedback, usage, the admin CSV, and placement (§3.5 option 1).
2. A D1 schema (additive migrations).
3. Workers Builds from GitHub.
4. Access on the hostname and on previews.
5. A staging URL.
6. Import the Railway feedback and usage logs into D1.

**Round 46: side by side, then cut-over.**
1. Agents use both for a week; feedback from both is compared.
2. Rerun the parity harness on the commit that is deployed.
3. Liam signs off.
4. **Cut-over:** agents get the new link and bookmark it.
5. **Rollback:** use the Railway link, which stays up at least 30 days.
6. Liam exports the last Railway logs into D1, then cancels Railway (or keeps chat only, §3.6).

**New Railway variable: none.**

---

## 6. Open questions for Liam (answered 2026-10-24: see the Round 43 update at the top)

1. **The chat tab:** is it used? Drop it, keep it on Railway, or a Worker round (§3.6)?
2. **Are the rules tables in agents' browsers acceptable?** Yes means B1 at $0; no means C at $5.
3. **Placement data:** the Worker answers the panel, coarsen it, or ship it as it is (§3.5)?
4. **Domain:** is cfigtx.com's DNS on Cloudflare (a custom hostname under Access), or should the app live on
   workers.dev with Access turned on there?
5. **Login:** Microsoft 365 single sign-on, or an emailed PIN? Who besides Liam gets the admin route?
6. **Railway's current monthly bill,** to compare against.
7. **Agents' devices:** any phones, or old browsers? Pyodide needs WebAssembly and a current browser.
