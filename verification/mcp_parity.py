"""Run by hand: does the MCP server give the same verdicts as the website? (Liam, 2026-10-16; 2026-10-25: "direct" is
now the website's path, engine.api.check with rules_data/engine_manifest.json loaded, not the Streamlit pipeline.)

    venv\\Scripts\\python.exe verification\\mcp_parity.py            # 3 profiles x 2 paths = 6 checks
    venv\\Scripts\\python.exe verification\\mcp_parity.py --runs 3   # repeat, to see any run-to-run difference

Free: no model call and no network (the engine decides every carrier from its rules tables). Both paths get the
same full profile (every topic checked), so a difference is the MCP wrapper (a bug here) -- the engine has no
run-to-run drift any more, so --runs should never change the answer.
"""
import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))

import carrier_mcp  # noqa: E402
from profiles import STANDARD_PROFILE, ALT_PROFILE, COASTAL_PPC4_PROFILE  # noqa: E402

PROFILES = {"STANDARD": STANDARD_PROFILE, "ALT": ALT_PROFILE, "COASTAL_PPC4": COASTAL_PPC4_PROFILE}
MANIFEST = os.path.join(ROOT, "rules_data", "engine_manifest.json")


def direct(profile):
    """The website's path: engine.api.check with the manifest loaded (no store, no retrieval, no model), set up here
    on its own rather than through carrier_mcp, so the comparison does not share the connector's code."""
    import engine.api as api
    import engine.pipeline as pipeline
    pd = dict(profile, dog_breeds=list(profile.get("dog_breeds") or ()))
    with open(MANIFEST, encoding="utf-8") as fh:
        api.load(manifest=json.load(fh))
    try:
        page = api.check(pd, None)
    finally:
        pipeline.FACTS = None
    return {c["carrier"]: c["status"] for c in page["cards"]}


def via_mcp(profile):
    """The server's own path. Its reply is the compact summary; the per-carrier verdicts are the cards it keeps for
    carrier_details (keyed here by program name, the same key the direct call uses)."""
    out = carrier_mcp.check_eligibility(dict(profile, dog_breeds=list(profile.get("dog_breeds") or ())),
                                        dwelling_type_quote=str(profile.get("dwelling_type", "")))
    if out.startswith("PROFILE NOT ACCEPTED"):
        raise SystemExit(f"MCP rejected the profile:\n{out}")
    cards = carrier_mcp._LAST["cards"].values()
    not_checked = next((l for l in out.splitlines() if l.startswith("**Not checked:**")), "")
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
            print(f"{name} run {run}: {len(a)} carriers direct (website), {len(b)} via MCP, {len(diffs)} differ"
                  + (f"; MCP left unchecked: {not_checked}" if not_checked not in ("", "nothing") else ""))
            for c in diffs:
                print(f"    {c}: website={a.get(c)}  mcp={b.get(c)}")
    print("PARITY OK" if total_diff == 0 else f"PARITY: {total_diff} differences")


if __name__ == "__main__":
    main()
