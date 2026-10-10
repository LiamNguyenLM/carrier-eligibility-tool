"""Round 36 step 6 (Liam, 2026-10-10): "This looks wrong" -- an agent's feedback on one carrier's card.

One JSON line per report in carrier_docs_db/feedback_log.jsonl (ELIGIBILITY_FEEDBACK_LOG overrides it; on
Railway carrier_docs_db is the persistent volume), written with the usage log's atomic append. A line holds
what is needed to replay the check: the time, the app version (git commit), the property details as entered,
the carrier, its verdict, reasons and deciding rows, the model, the agent's choice and comment, and the
optional name the agent typed. Writing never raises and never runs during a check.
"""
import csv
import datetime
import functools
import io
import json
import os
import re
import subprocess

import usage_log

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(HERE, "carrier_docs_db", "feedback_log.jsonl")
CHOICES = ("Should be Eligible", "Should be Ineligible", "Should be Refer", "Not sure")
ROW_ID = re.compile(r"\b[A-Z]{3}-\d{3}\b")
CSV_COLUMNS = ("ts", "app_version", "name", "carrier", "display_name", "verdict", "choice", "comment",
               "reasons", "deciding_rows", "model", "rules_table", "property_details")


def path():
    return os.environ.get("ELIGIBILITY_FEEDBACK_LOG") or DEFAULT_PATH


@functools.lru_cache(maxsize=1)
def app_version():
    """The deployed git commit: Railway's RAILWAY_GIT_COMMIT_SHA (Railway sets it on every deploy), else
    the checkout's HEAD, else "unknown"."""
    sha = os.environ.get("RAILWAY_GIT_COMMIT_SHA", "").strip()
    if sha:
        return sha[:7]
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=HERE, capture_output=True, text=True,
                             timeout=5)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def deciding_rows(record):
    """The rules-table rows the card rests on: every row ID in its reasons, citations, missing items and
    notes, in order of first appearance."""
    seen = []
    for field in ("reasons", "citations", "missing_info", "also_confirm"):
        for text in record.get(field) or []:
            for rid in ROW_ID.findall(str(text)):
                if rid not in seen:
                    seen.append(rid)
    for rid in ROW_ID.findall(str(record.get("notes") or "")):
        if rid not in seen:
            seen.append(rid)
    return seen


def record(record_, property_details, choice, comment="", name="", model="", display_name="", now=None):
    """The log line for one report."""
    ts = (now or datetime.datetime.now(datetime.timezone.utc)).isoformat(timespec="seconds")
    return {"ts": ts, "app_version": app_version(), "name": (name or "").strip(),
            "property_details": dict(property_details or {}), "carrier": record_.get("carrier", ""),
            "display_name": display_name or "", "verdict": record_.get("status", ""),
            "reasons": list(record_.get("reasons") or []), "deciding_rows": deciding_rows(record_),
            "model": model or "", "rules_table": bool(record_.get("rules_table")),
            "choice": choice if choice in CHOICES else "Not sure", "comment": (comment or "").strip()}


def append(line):
    """Never raises (usage_log.append_line)."""
    usage_log.append_line(path(), line, label="FEEDBACK LOG")


def read_all():
    out = []
    try:
        with open(path(), encoding="utf-8") as fh:
            for raw in fh:
                try:
                    out.append(json.loads(raw))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def week_start(now=None):
    """Monday 00:00 UTC of this week."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return (now - datetime.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def count_this_week(lines=None, now=None):
    start = week_start(now).isoformat(timespec="seconds")
    return sum(1 for line in (read_all() if lines is None else lines) if str(line.get("ts", "")) >= start)


def to_csv(lines=None):
    """Every report as CSV (one row per report; lists joined with " | ", property details as JSON)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for line in read_all() if lines is None else lines:
        row = []
        for col in CSV_COLUMNS:
            v = line.get(col, "")
            if col == "property_details":
                v = json.dumps(v, ensure_ascii=False, sort_keys=True, default=str)
            elif isinstance(v, list):
                v = " | ".join(str(x) for x in v)
            row.append(v)
        w.writerow(row)
    return buf.getvalue()
