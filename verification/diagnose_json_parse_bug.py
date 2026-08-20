"""
Diagnostic: capture the FULL raw model response on a JSON parse failure
(check_eligibility() only prints raw[:1000], truncating well before the
actual break point in recent failures). Monkeypatches print() during the
call to intercept the "RAW RESPONSE:" line in full, then writes it to disk
untruncated so the exact malformed character(s) can be inspected directly.

Not a pytest file -- a one-time diagnostic script, retried in a loop since
the parse error is intermittent (~20-30% of runs observed this session).
"""
import builtins
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import eligibility_check
from eligibility_check import check_eligibility
from profiles import STANDARD_PROFILE

OUT_PATH = os.path.join(os.path.dirname(__file__), "json_parse_bug_full_capture.txt")
MAX_ATTEMPTS = 5

_captured = {}
_real_print = builtins.print
_real_json_loads = json.loads


def _capturing_json_loads(s, *args, **kwargs):
    # check_eligibility() calls json.loads(json_str) with the FULL,
    # untruncated model output -- unlike its own print("RAW RESPONSE:",
    # raw[:1000]) diagnostic, which truncates well before real recent
    # failures occur. Capture the exact string being parsed so a failure
    # can be inspected in full.
    _captured["last_json_str"] = s
    return _real_json_loads(s, *args, **kwargs)


def _capturing_print(*args, **kwargs):
    if args and args[0] == "JSON PARSE ERROR:":
        _captured["error"] = " ".join(str(a) for a in args[1:])
    return _real_print(*args, **kwargs)


def main():
    builtins.print = _capturing_print
    eligibility_check.json.loads = _capturing_json_loads
    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            _captured.clear()
            t0 = time.time()
            result = check_eligibility(STANDARD_PROFILE)
            elapsed = time.time() - t0
            if "error" in _captured:
                _real_print(f"[attempt {attempt}/{MAX_ATTEMPTS}] {elapsed:.0f}s -- CAPTURED a parse failure")
                with open(OUT_PATH, "w", encoding="utf-8") as f:
                    f.write("ERROR: " + _captured.get("error", "") + "\n\n")
                    f.write("FULL RAW RESPONSE (untruncated):\n")
                    f.write(_captured.get("last_json_str", "<not captured>"))
                _real_print(f"Full raw response written to {OUT_PATH}")
                return
            else:
                by_carrier = {r["carrier"]: r for r in result}
                swyfft = next((r["status"] for c, r in by_carrier.items() if "lloyds" in c.lower()), "NOT_FOUND")
                orion = next((r["status"] for c, r in by_carrier.items() if "orion" in c.lower()), "NOT_FOUND")
                _real_print(
                    f"[attempt {attempt}/{MAX_ATTEMPTS}] {elapsed:.0f}s -- clean run, no parse error, "
                    f"{len(result)} carriers, Swyfft_Lloyds={swyfft}, Orion={orion}"
                )
        _real_print("Did not reproduce the parse error in", MAX_ATTEMPTS, "attempts.")
    finally:
        builtins.print = _real_print
        eligibility_check.json.loads = _real_json_loads


if __name__ == "__main__":
    main()
