-- Round 45 (Liam, 2026-10-28): Ask the Guides.
--
-- chat_log: one row per answered question, written once when the answer ends (the only D1 write a question makes,
-- plus its one index entry: D1 Free allows 100k rows written a day). No answer text. The same rows are the rate
-- limit (a session's questions in the last hour) and the daily spend cap (today's cost_usd, UTC), so neither needs a
-- counter of its own. Admins download it as GET /api/admin/chat.csv.
CREATE TABLE chat_log (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  received_at        TEXT NOT NULL,                -- isoformat(timespec="seconds"), UTC: text order is time order
  session            TEXT NOT NULL DEFAULT '',     -- a hash of the session cookie (password mode) or the email
  name               TEXT NOT NULL DEFAULT '',     -- the name typed at the login, if any
  email              TEXT NOT NULL DEFAULT '',     -- the Access email (access mode)
  question           TEXT NOT NULL,
  programs           TEXT NOT NULL DEFAULT '[]',   -- JSON list: the programs the question was routed to ([] = all)
  cited              TEXT NOT NULL DEFAULT '[]',   -- JSON list: the carriers the answer cited
  model              TEXT NOT NULL DEFAULT '',
  input_tokens       INTEGER NOT NULL DEFAULT 0,
  output_tokens      INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens  INTEGER NOT NULL DEFAULT 0,
  cache_write_tokens INTEGER NOT NULL DEFAULT 0,
  cost_usd           REAL NOT NULL DEFAULT 0,
  first_ms           INTEGER NOT NULL DEFAULT 0,   -- time to the first words of the answer
  total_ms           INTEGER NOT NULL DEFAULT 0,
  status             TEXT NOT NULL DEFAULT 'ok',   -- ok | error | <the model's stop reason when not end_turn>
  unverified_quotes  INTEGER NOT NULL DEFAULT 0    -- quotes in the answer found in none of the sources sent
);
CREATE INDEX chat_log_by_received ON chat_log (received_at);

-- "This answer looks wrong" goes into the feedback table like a card's report, marked kind = 'chat'.
ALTER TABLE feedback ADD COLUMN kind TEXT NOT NULL DEFAULT 'check';
