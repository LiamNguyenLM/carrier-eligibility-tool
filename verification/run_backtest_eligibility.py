"""Round 32 step 3 (2026-10-09): the tool's verdicts on real homes, for the placement backtest.

Reads the HawkSoft export (untracked; no names, addresses or policy numbers), maps each row to the
intake form conservatively, and runs the normal check -- check_eligibility, the app's own code path,
retries and the Luna fallback included -- in the live configuration (Haiku 5.5 low by default; pilot,
Sage, HO3 and DP batches ON). Up to 3 checks at a time, each in its own process (the check keeps
per-check state in module globals, so threads would mix them). Writes one row per program the check
returned: home_id, program, status. Nothing else from the card. No data lives in this file. The run
log beside it (also untracked) keeps each check's wall time, errors, and the missing-information items
that held its Insufficient cards.

usage: python verification/run_backtest_eligibility.py <backtest_test_homes.csv> [--workers 3] [--limit N]
The results CSV and the usage log are written next to the input file.

Mapping (Liam, round 32 step 3). The data are carrier-coded and often missing, so:
- a field the data does not give stays at the form's blank / unknown value where the form has one
  (PPC "N/A", plumbing "Unknown", hydrant "Unknown", station / Coverage A / county blank, dwelling
  type blank);
- a field whose form control has no unknown value (year built, roof age, roof type, construction,
  pool, roof shape, coastal tier, dogs, solar) is left as the form leaves it blank: its topic box
  unticked, so the check does not consider it;
- occupancy (Owner Occupied unless the data say otherwise) and ownership (Individual Owner) are always
  on; pool accessories take the form's default "None". FORM_DEFAULTS lists these.
"""
import argparse
import collections
import csv
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CURRENT_YEAR = 2026
LIVE_SWITCHES = ("ELIGIBILITY_RULES_PILOT", "ELIGIBILITY_RULES_SAGE_BATCH", "ELIGIBILITY_RULES_HO3_BATCH",
                 "ELIGIBILITY_RULES_DP_BATCH")
# Round 35 step 3b: HawkSoft's "Metal" does not say which kind -- the old value, read as unknown; porcelain-enamel
# steel shingles are the metal shingle option
ROOF = {"Composition": "Composition Shingle", "Metal": "Metal",
        "SteelPorcelainShingle": "Metal: shingle / tile / shake (incl. stone-coated)",
        "SteelPorcelainShingles": "Metal: shingle / tile / shake (incl. stone-coated)", "Tile": "Tile", "ClayTile": "Tile",
        "WoodShakeShingle": "Wood shake / wood shingle"}
CONSTRUCTION = {"MasonryVeneer": "Masonry Veneer", "Frame": "Frame", "Masonry": "Masonry",
                "JoistedMasonry": "Masonry"}
DWELLING = {"Dwelling": "House", "Townhouse": "Townhome"}
PPC_OPTIONS = {"1", "2", "3", "4", "5", "6", "7", "8", "8A", "8B", "9", "10"}
# fields always sent with a value the data do not give (the form's default or Liam's instruction)
FORM_DEFAULTS = {"ownership_type": "Individual Owner", "pool_accessories": "None (when a pool is given)",
                 "occupancy_type": "Owner Occupied unless the data say Vacant / Secondary / Seasonal",
                 "primary_home_carrier / primary_home_miles": "blank (Seasonal / Secondary Home only)"}


def _blank(v):
    return v is None or str(v).strip() in ("", "None", "Unknown", "NotAnswered")


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def profile(row):
    """(property_details, checked_topics, notes) for one export row."""
    import intake_fields
    import topics
    pd, off, notes = {}, set(), []

    yb = _num(row.get("year_built"))
    if yb and 1800 <= yb <= CURRENT_YEAR:
        pd["year_built"] = int(yb)
    else:
        pd["year_built"] = 2000                                     # the form's default; topic unticked
        off.add("home_age")
    ry = _num(row.get("roof_year"))
    if ry and ry <= CURRENT_YEAR:
        pd["roof_age"] = min(100, int(CURRENT_YEAR - ry))
    else:
        pd["roof_age"] = 10
        off.add("roof_age")
    pd["roof_type"] = ROOF.get((row.get("roof_type_raw") or "").strip())
    if not pd["roof_type"]:
        pd["roof_type"] = "Composition Shingle"
        off.add("roof_type")
    pd["construction_type"] = CONSTRUCTION.get((row.get("construction_raw") or "").strip())
    if not pd["construction_type"]:
        pd["construction_type"] = "Frame"
        off.add("construction")
    # never in the export: the form's defaults, topics unticked
    pd.update(roof_shape="Gable", coastal_tier="Not Coastal", has_dogs="No", dog_breeds=(), solar_panels="No")
    off.update(("roof_shape", "coastal", "dogs", "solar"))
    pd["plumbing_type"] = "Unknown"                                 # HawkSoft gives update status only

    pool = (row.get("pool_raw") or "").strip()
    pd["pool_fence_4ft"] = pd["pool_gate_locking"] = False
    pd["pool_accessories"] = "None"
    if pool == "None":
        pd["swimming_pool"] = "No Pool"
    elif pool == "IngroundUnfenced":
        pd["swimming_pool"] = "In Ground - Unfenced"
    elif pool == "AboveGroundUnfenced":
        pd["swimming_pool"] = "Above Ground - Unfenced"
    elif pool.startswith("InGroundApprovedFenc"):
        pd["swimming_pool"], pd["pool_fence_4ft"], pd["pool_gate_locking"] = "In Ground - Fenced", True, True
    else:
        pd["swimming_pool"] = "No Pool"
        off.add("pool")

    ppc = (row.get("ppc_raw") or "").strip().lstrip("0")
    if ppc in PPC_OPTIONS:
        pd["ppc"] = ppc
    else:
        pd["ppc"] = "N/A"
        if ppc and ppc != "None":
            notes.append(f"ppc {row.get('ppc_raw')!r} is not a form option: N/A")
    pd["fire_station_miles"] = intake_fields.parse_station_miles(row.get("miles_to_fire_station") or None)
    feet = _num(row.get("feet_to_hydrant"))
    pd["hydrant_1000ft"] = "Unknown" if feet is None else ("Yes" if feet <= 1000 else "No")

    pd["zip"] = intake_fields.parse_zip(row.get("zip") or "")[0] or ""
    county = (row.get("county") or "").strip()
    if county and county not in intake_fields.TEXAS_COUNTIES:
        notes.append(f"county {county!r} is not a form option: blank")
        county = ""
    if not county and pd["zip"]:
        county = intake_fields.county_for_zip(pd["zip"])[0]        # what the form does when a ZIP is typed
        if county:
            notes.append("county from ZIP")
    pd["county"] = county
    pd["dwelling_amount"] = intake_fields.parse_dwelling_amount(row.get("coverage_a") or None)
    pd["dwelling_type"] = DWELLING.get((row.get("residence_raw") or "").strip(), "")

    occ, use = (row.get("occupancy_raw") or "").strip(), (row.get("use_raw") or "").strip()
    if occ == "Vacant" or use == "Vacant":
        pd["occupancy_type"] = "Vacant"
    elif use == "SecondaryNonSeasonal":
        pd["occupancy_type"] = "Secondary Home"
    elif use == "SeasonalSecondary":
        pd["occupancy_type"] = "Seasonal"
    else:
        pd["occupancy_type"] = "Owner Occupied"
    if pd["occupancy_type"] in intake_fields.OWNERS_OTHER_HOMES:
        pd["primary_home_carrier"], pd["primary_home_miles"] = "", None
    pd["ownership_type"] = "Individual Owner"
    checked = [t for t in topics.TOPIC_KEYS if t not in off]
    return pd, checked, notes


def status_of(rec):
    if rec.get("fixed_row") and rec.get("status") == "INELIGIBLE":
        return "CLOSED"                                             # a closed program's fixed row
    return rec.get("status") or "NOT_EVALUATED"


_EC = None


def _worker_init(env):
    os.chdir(ROOT)
    sys.path.insert(0, ROOT)
    os.environ.update(env)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    global _EC
    import eligibility_check
    _EC = eligibility_check


def run_one(row):
    pd, checked, notes = profile(row)
    t0 = time.perf_counter()
    try:
        results = _EC.check_eligibility(dict(pd), checked_topics=checked)
        err = None
    except Exception as exc:                                        # noqa: BLE001 -- reported, never hidden
        results, err = [], f"{type(exc).__name__}: {exc}"[:300]
    usage = dict(_EC.LAST_CALL_USAGE)
    rate_limited = "RateLimit" in (err or "") or any(
        "429" in str(u.get("fallback_reason", "")) for u in usage.values() if isinstance(u, dict))
    rows = [(row["home_id"], r.get("carrier", ""), status_of(r)) for r in results
            if r.get("carrier") and r.get("carrier") != "Parse Error"]
    failed = err or (not rows) or any(r.get("carrier") == "Parse Error" for r in results)
    # for the run log only (never the results CSV): what held the Insufficient cards, by item
    held = [m for r in results if r.get("status") == "INSUFFICIENT_INFORMATION" for m in (r.get("missing_info") or [])]
    return {"home_id": row["home_id"], "rows": rows, "held_on": held, "error": err if err else ("parse error / no records" if failed else None),
            "wall": time.perf_counter() - t0, "notes": notes, "fallback": bool(_EC.LAST_CHECK_INFO.get("fallback")),
            "rate_limited": rate_limited}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("homes")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    homes = os.path.abspath(a.homes)
    out_dir = os.path.dirname(homes)
    rows = list(csv.DictReader(open(homes, encoding="utf-8")))
    if a.limit:
        rows = rows[:a.limit]
    env = {k: os.environ.get(k) or "1" for k in LIVE_SWITCHES}
    env["ELIGIBILITY_USAGE_LOG"] = os.environ.get("ELIGIBILITY_USAGE_LOG") or os.path.join(out_dir, "backtest_usage_log.jsonl")
    out_csv = os.path.join(out_dir, "backtest_results.csv")
    runlog = os.path.join(out_dir, "backtest_run_log.jsonl")
    done, t0, rate_limited_in_a_row = [], time.perf_counter(), 0
    with ProcessPoolExecutor(max_workers=a.workers, initializer=_worker_init, initargs=(env,)) as pool:
        futs = {pool.submit(run_one, r): r["home_id"] for r in rows}
        for fut in as_completed(futs):
            res = fut.result()
            done.append(res)
            with open(runlog, "a", encoding="utf-8") as f:
                f.write(json.dumps({k: v for k, v in res.items() if k != "rows"}) + "\n")
            rate_limited_in_a_row = rate_limited_in_a_row + 1 if res["rate_limited"] else 0
            print(f"{len(done)}/{len(rows)} {res['home_id']} {len(res['rows'])} programs {res['wall']:.1f}s"
                  + (f" ERROR {res['error']}" if res["error"] else "") + (" FALLBACK" if res["fallback"] else ""),
                  flush=True)
            if rate_limited_in_a_row >= 3:
                print("PAUSED: Anthropic rate-limited 3 checks in a row", flush=True)
                for f_ in futs:
                    f_.cancel()
                break
    done.sort(key=lambda r: r["home_id"])
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["home_id", "program", "status"])
        for res in done:
            w.writerows(sorted(res["rows"]))
    counts = collections.Counter(s for res in done for _, _, s in res["rows"])
    print(json.dumps({"checks": len(done), "failures": [r["home_id"] for r in done if r["error"]],
                      "fallback_checks": sum(r["fallback"] for r in done), "wall_s": round(time.perf_counter() - t0, 1),
                      "status_counts": dict(counts), "out": out_csv, "form_defaults": FORM_DEFAULTS}, indent=1))


if __name__ == "__main__":
    main()
