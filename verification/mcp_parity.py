"""Paid, run by hand: does the MCP server give the same verdicts as the app's own call? (Liam, 2026-10-16)

    venv\\Scripts\\python.exe verification\\mcp_parity.py            # 3 profiles x 2 paths = 6 checks
    venv\\Scripts\\python.exe verification\\mcp_parity.py --runs 3   # repeat, to see flakiness

Both paths get the same full profile (every topic checked), so any difference is either the MCP wrapper
(a bug here) or the pipeline's own run-to-run drift (run it again, or use --runs, before calling it a bug).
"""
import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))

import carrier_mcp  # noqa: E402
from profiles import STANDARD_PROFILE, ALT_PROFILE, COASTAL_PPC4_PROFILE  # noqa: E402

PROFILES = {"STANDARD": STANDARD_PROFILE, "ALT": ALT_PROFILE, "COASTAL_PPC4": COASTAL_PPC4_PROFILE}


def direct(profile):
    ec = carrier_mcp._load()["ec"]
    pd = dict(profile, dog_breeds=list(profile.get("dog_breeds") or ()))
    return {r["carrier"]: r.get("status") for r in ec.check_eligibility(pd, checked_topics=None)}


def via_mcp(profile):
    """The server's own path. Its reply is the compact summary; the per-carrier verdicts are the cards it keeps for
    carrier_details (keyed here by program name, the same key the direct call uses)."""
    out = carrier_mcp.check_eligibility(dict(profile, dog_breeds=list(profile.get("dog_breeds") or ())))
    if "error" in out:
        raise SystemExit(f"MCP rejected the profile: {out['problems']}")
    cards = carrier_mcp._LAST["cards"].values()
    not_checked = next((l for l in out["summary_markdown"].splitlines() if l.startswith("**Not checked:**")), "")
    return {c["program"]: c.get("status") for c in cards}, not_checked.replace("**Not checked:** ", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    args = ap.parse_args()
    total_diff = 0
    for name, profile in PROFILES.items():
        for run in range(1, args.runs + 1):
            a = direct(profile)
            b, not_checked = via_mcp(profile)
            diffs = sorted(c for c in set(a) | set(b) if a.get(c) != b.get(c))
            total_diff += len(diffs)
            print(f"{name} run {run}: {len(a)} carriers direct, {len(b)} via MCP, {len(diffs)} differ"
                  + (f"; MCP left unchecked: {not_checked}" if not_checked not in ("", "nothing") else ""))
            for c in diffs:
                print(f"    {c}: app={a.get(c)}  mcp={b.get(c)}")
    print("PARITY OK" if total_diff == 0 else f"PARITY: {total_diff} differences -- rerun to separate drift")


if __name__ == "__main__":
    main()
