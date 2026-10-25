-- Round 43 step 3: the Worker's D1 database (cfig-eligibility, binding DB).
-- Apply with: npx wrangler d1 migrations apply DB --local   (or --remote)
--
-- Three groups of tables:
--   feedback, usage        -- what the browser posts (POST /api/feedback, POST /api/usage) plus the rows
--                             imported once from Railway's feedback_log.jsonl / usage_log.jsonl
--                             (cloudflare/scripts/import_logs.mjs). Never sent to the browser except the
--                             admin CSV / weekly counts.
--   placement_*            -- the HawkSoft placement tables (rules_data/placement/*.csv), replaced as a whole
--                             every month by cloudflare/scripts/sync_placement.mjs. They NEVER ship to the
--                             browser: POST /api/placement reads only the rows one panel needs.
--
-- Every timestamp is Python's isoformat(timespec="seconds") in UTC ("2026-10-24T18:05:09+00:00"), as in the
-- JSONL logs, so text order is time order.

-- ---------------------------------------------------------------------------------------------- feedback
-- One row per "This looks wrong" report: the fields of one feedback_log.jsonl line (feedback.record())
-- plus who sent it (the verified Access email; '' for rows imported from Railway, which never had one).
CREATE TABLE feedback (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  dedup_key        TEXT UNIQUE,                 -- import_logs: sha256 of the line; NULL for rows the Worker wrote
  source           TEXT NOT NULL DEFAULT 'worker',   -- 'worker' | 'railway'
  received_at      TEXT NOT NULL,               -- server time (the Worker's clock; = ts for imported rows)
  email            TEXT NOT NULL DEFAULT '',
  ts               TEXT NOT NULL,               -- as the browser sent it (feedback.record()'s ts)
  app_version      TEXT NOT NULL DEFAULT '',
  name             TEXT NOT NULL DEFAULT '',    -- the agent's optional typed name
  property_details TEXT NOT NULL DEFAULT '{}',  -- JSON object
  carrier          TEXT NOT NULL DEFAULT '',
  display_name     TEXT NOT NULL DEFAULT '',
  verdict          TEXT NOT NULL DEFAULT '',
  reasons          TEXT NOT NULL DEFAULT '[]',  -- JSON list of strings
  deciding_rows    TEXT NOT NULL DEFAULT '[]',  -- JSON list of row IDs
  model            TEXT NOT NULL DEFAULT '',
  rules_table      INTEGER NOT NULL DEFAULT 0,  -- 0 / 1
  checked_topics   TEXT,                        -- JSON list, or NULL = every topic (the full check)
  choice           TEXT NOT NULL DEFAULT 'Not sure',
  comment          TEXT NOT NULL DEFAULT '',
  csv_row          TEXT NOT NULL DEFAULT ''     -- this report's line of the admin CSV (src/csv.js), built when written
);
CREATE INDEX feedback_by_ts ON feedback (ts, id);
CREATE INDEX feedback_by_received ON feedback (received_at);

-- ---------------------------------------------------------------------------------------------- usage
-- One row per eligibility check: usage_log.record()'s fields. A check in the browser makes no model call,
-- so the Worker writes model '' / effort '' / cost 0 / calls '{}' / retries 0; imported Railway rows keep
-- theirs. No property details, no client data -- as today.
CREATE TABLE usage (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  dedup_key    TEXT UNIQUE,
  source       TEXT NOT NULL DEFAULT 'worker',
  received_at  TEXT NOT NULL,
  email        TEXT NOT NULL DEFAULT '',
  ts           TEXT NOT NULL,
  app_version  TEXT NOT NULL DEFAULT '',
  model        TEXT NOT NULL DEFAULT '',
  effort       TEXT NOT NULL DEFAULT '',
  fallback     INTEGER NOT NULL DEFAULT 0,
  calls        TEXT NOT NULL DEFAULT '{}',      -- JSON object (per-call tokens and cost; Railway rows only)
  cost         REAL NOT NULL DEFAULT 0,
  wall_s       REAL NOT NULL DEFAULT 0,
  carriers     INTEGER NOT NULL DEFAULT 0,
  retries      INTEGER NOT NULL DEFAULT 0,
  timings      TEXT NOT NULL DEFAULT '{}'       -- JSON object {stage: seconds}
);
CREATE INDEX usage_by_received ON usage (received_at);

-- ---------------------------------------------------------------------------------------------- placement
-- Mirrors of rules_data/placement/*.csv. Every row keeps its CSV order in seq (placement.py sums a market's
-- months in file order, and the port does the same) and its month as an index too: mi = year*12 + month-1
-- (placement.month_index), so a panel reads only the 36 whole months before as_of.
CREATE TABLE placement_zip (            -- placement_zip.csv: month,zip,market,n
  seq    INTEGER PRIMARY KEY,
  month  TEXT NOT NULL,
  mi     INTEGER NOT NULL,
  zip    TEXT NOT NULL,
  market TEXT NOT NULL,
  n      INTEGER NOT NULL
);
CREATE INDEX placement_zip_q ON placement_zip (zip, mi, market, n);          -- covering: one ZIP's window

CREATE TABLE placement_county (         -- placement_county.csv: month,county,market,n
  seq        INTEGER PRIMARY KEY,
  month      TEXT NOT NULL,
  mi         INTEGER NOT NULL,
  county     TEXT NOT NULL,             -- as in the CSV
  county_key TEXT NOT NULL,             -- county.strip().lower(), how placement.load_tables keys it
  market     TEXT NOT NULL,
  n          INTEGER NOT NULL
);
CREATE INDEX placement_county_q ON placement_county (county_key, mi, market, n);

CREATE TABLE placement_profile (        -- placement_profile.csv: month,dim,value,market,n
  seq    INTEGER PRIMARY KEY,
  month  TEXT NOT NULL,
  mi     INTEGER NOT NULL,
  dim    TEXT NOT NULL,                 -- age_band | covA_band
  value  TEXT NOT NULL,
  market TEXT NOT NULL,
  n      INTEGER NOT NULL
);
CREATE INDEX placement_profile_q ON placement_profile (dim, value, mi, market, n);

-- Derived by the sync, not a CSV: placement_zip summed per (month, market) -- placement.py's T["all"] (every
-- ZIP row), so the statewide mix is ~26 rows a month instead of every ZIP's. Rows are in the order each
-- (month, market) first appears in placement_zip.csv.
CREATE TABLE placement_all (
  seq    INTEGER PRIMARY KEY,
  month  TEXT NOT NULL,
  mi     INTEGER NOT NULL,
  market TEXT NOT NULL,
  n      INTEGER NOT NULL
);
CREATE INDEX placement_all_q ON placement_all (mi, market, n);

CREATE TABLE placement_markets (        -- placement_markets.csv: market,program_prefix (file order matters:
  seq            INTEGER PRIMARY KEY,   -- a program belongs to the FIRST prefix it starts with)
  market         TEXT NOT NULL,
  program_prefix TEXT NOT NULL
);

CREATE TABLE placement_meta (           -- placement_meta.csv (data_through, policies, built_at) plus the
  key   TEXT PRIMARY KEY,               -- sync's own sync_* keys (row counts, CSV hashes, when it ran)
  value TEXT NOT NULL
);
