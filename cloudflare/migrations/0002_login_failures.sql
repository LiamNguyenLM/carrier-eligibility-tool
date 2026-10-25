-- Round 44 step 1 (Liam, 2026-10-25): the password gate's lockout. One row per address that typed a wrong password:
-- how many in the current window, when the window started, and until when the address is locked out (unix seconds).
-- A correct password deletes the row. (cloudflare/src/session.js: 10 wrong in 15 minutes -> 15 minutes locked.)
CREATE TABLE login_failures (
  ip           TEXT PRIMARY KEY,
  failures     INTEGER NOT NULL,
  window_start INTEGER NOT NULL,
  locked_until INTEGER NOT NULL DEFAULT 0
);
