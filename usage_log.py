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


def record(model, effort, calls, wall_s, carriers, now=None, timings=None):
    """The log line for one check. calls: {call name: usage dict or None}. Round 36 step 1: each call also
    carries its wall time (wall_s: the SDK's retries and any fallback included) and attempts (HTTP requests
    sent; 1 = no retry), and timings is the check's stage breakdown in seconds."""
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
        for key in ("wall_s", "attempts"):
            if u.get(key) is not None:
                per_call[name][key] = u[key]
        if u.get("fallback"):
            per_call[name]["fallback"] = True
    ts = (now or datetime.datetime.now(datetime.timezone.utc)).isoformat(timespec="seconds")
    return {"ts": ts, "model": model, "effort": effort, "fallback": fallback, "calls": per_call,
            "cost": round(total, 6), "wall_s": round(wall_s, 2), "carriers": carriers,
            "retries": sum(1 for n in per_call if n.endswith("_retry")),
            "timings": {k: round(v, 2) for k, v in (timings or {}).items()}}


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


def last_line():
    """The log's last whole line (a dict), or None. Reads only the file's tail."""
    try:
        with open(path(), "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 16384))
            tail = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    for raw in reversed(tail):
        try:
            return json.loads(raw)
        except ValueError:
            continue
    return None


# Round 36 step 1: the stage names, in pipeline order, as the panel shows them.
STAGES = (("routing", "routing"), ("code_eval", "rules in code"), ("retrieval", "retrieval + prompt"),
          ("models", "model calls"), ("after_models", "after the calls"), ("placement", "placement panel"),
          ("render", "page"))


def timing_line(line=None):
    """Round 36 step 1: the last check's breakdown for the Fingerprint panel, or "" when there is none."""
    line = line if line is not None else last_line()
    if not line or not line.get("timings"):
        return ""
    t = line["timings"]
    stages = " · ".join(f"{label} {t[k]:.1f}s" for k, label in STAGES if k in t)
    calls = []
    for name, c in (line.get("calls") or {}).items():
        if c.get("wall_s") is None:
            continue
        att = c.get("attempts")
        extra = (f", {att} attempts" if att and att > 1 else "") + (", FALLBACK" if c.get("fallback") else "")
        calls.append(f"{name} {c['wall_s']:.1f}s{extra}")
    total = t.get("total_with_page", t.get("total", line.get("wall_s", 0)))
    out = f"Last check ({str(line.get('ts', ''))[:16].replace('T', ' ')} UTC): {total:.1f}s -- {stages}"
    return out + (f" (calls: {'; '.join(calls)})" if calls else "")


def panel_line(now=None):
    checks, dollars = month_summary(now)
    return f"This month: {checks} checks, ${dollars:.2f} of the ${budget():.0f} budget (display only)"
