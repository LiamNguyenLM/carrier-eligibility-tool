"""Round 31 step 2 (Liam, 2026-10-08): one JSON line per eligibility check -- what it cost, never
what it was about. No property details, no client data: model, effort, fallback, each call's
tokens, cost, wall time, the number of carriers and of retry calls.

Where it lives: ELIGIBILITY_USAGE_LOG, default carrier_docs_db/usage_log.jsonl. On Railway
carrier_docs_db is the persistent volume (seed_db.sh), so the log survives a redeploy and a
restart; seed_db.sh keeps it across FORCE_RESEED=1 too. Anywhere else on Railway's disk would be
lost on every deploy. The panel only DISPLAYS the month's total against ELIGIBILITY_MONTHLY_BUDGET
(default 260, dollars); nothing ever blocks a check."""
import datetime
import json
import os
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(HERE, "carrier_docs_db", "usage_log.jsonl")

# Dollars per million tokens -- the ONE place prices live. Haiku 5.5: input / output from Anthropic's
# page (2026-10-07); cache read / write ASSUMED at Anthropic's usual 0.1x / 1.25x of input (not
# confirmed). gpt-6-luna: OpenAI's page (cache writes are not billed there).
PRICES = {
    "claude-haiku-5-5": {"input": 0.10, "cache_read": 0.01, "cache_write": 0.125, "output": 0.50},
    "gpt-6-luna": {"input": 0.10, "cache_read": 0.01, "cache_write": 0.0, "output": 0.50},
}
_LOCK = threading.Lock()


def path():
    return os.environ.get("ELIGIBILITY_USAGE_LOG") or DEFAULT_PATH


def budget():
    try:
        return float(os.environ.get("ELIGIBILITY_MONTHLY_BUDGET", "") or 260)
    except ValueError:
        return 260.0


def call_cost(model, usage):
    """Dollars for one call's usage dict (Anthropic-shaped keys); 0.0 for a model with no price."""
    p = PRICES.get(model)
    if not p or not usage:
        return 0.0
    return (usage.get("input_tokens", 0) * p["input"] + usage.get("cache_read_input_tokens", 0) * p["cache_read"]
            + usage.get("cache_creation_input_tokens", 0) * p["cache_write"]
            + usage.get("output_tokens", 0) * p["output"]) / 1e6


def record(model, effort, calls, wall_s, carriers, now=None):
    """The log line for one check. calls: {call name: usage dict or None}."""
    per_call, total, fallback = {}, 0.0, False
    for name, u in calls.items():
        if not u:
            continue
        m = u.get("model") or model
        fallback = fallback or bool(u.get("fallback"))
        c = call_cost(m, u)
        total += c
        per_call[name] = {"model": m, "input": u.get("input_tokens", 0),
                          "cache_read": u.get("cache_read_input_tokens", 0),
                          "cache_write": u.get("cache_creation_input_tokens", 0),
                          "output": u.get("output_tokens", 0), "cost": round(c, 6)}
    ts = (now or datetime.datetime.now(datetime.timezone.utc)).isoformat(timespec="seconds")
    return {"ts": ts, "model": model, "effort": effort, "fallback": fallback, "calls": per_call,
            "cost": round(total, 6), "wall_s": round(wall_s, 2), "carriers": carriers,
            "retries": sum(1 for n in per_call if n.endswith("_retry"))}


def append(line):
    """Append one line; a logging problem never breaks a check.

    Round 35 step 5: 300 checks in 3 processes wrote 299 lines (round 32). Each append is now one os.write
    of the whole line on an O_APPEND descriptor, under a lock every process shares: flock on the log itself
    (Linux, Railway), msvcrt.locking on a lock file beside it (Windows, where O_APPEND is a seek then a
    write, not atomic). The thread lock still orders writers inside one process."""
    try:
        p = path()
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        data = (json.dumps(line, ensure_ascii=False) + "\n").encode("utf-8")
        with _LOCK, _process_lock(p):
            fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
            try:
                os.write(fd, data)
            finally:
                os.close(fd)
    except OSError as e:
        print("USAGE LOG: could not write --", e)


class _process_lock:
    """An exclusive lock shared by every process writing the log."""

    def __init__(self, log_path):
        self.lock_path = log_path + ".lock"
        self.fd = None

    def __enter__(self):
        self.fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            import fcntl
            fcntl.flock(self.fd, fcntl.LOCK_EX)
        except ImportError:                                  # Windows
            import msvcrt
            while True:
                try:
                    msvcrt.locking(self.fd, msvcrt.LK_LOCK, 1)   # retries for about 10 s, then raises
                    break
                except OSError:
                    continue
        return self

    def __exit__(self, *exc):
        try:
            try:
                import fcntl
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            except ImportError:
                import msvcrt
                os.lseek(self.fd, 0, 0)
                msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(self.fd)
        return False


def month_summary(now=None):
    """(checks, dollars) for this calendar month (UTC), read from the log."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    prefix = now.strftime("%Y-%m")
    checks, dollars = 0, 0.0
    try:
        with open(path(), encoding="utf-8") as fh:
            for raw in fh:
                try:
                    line = json.loads(raw)
                except ValueError:
                    continue
                if str(line.get("ts", "")).startswith(prefix):
                    checks += 1
                    dollars += float(line.get("cost") or 0)
    except OSError:
        pass
    return checks, dollars


def panel_line(now=None):
    checks, dollars = month_summary(now)
    return f"This month: {checks} checks, ${dollars:.2f} of the ${budget():.0f} budget (display only)"
