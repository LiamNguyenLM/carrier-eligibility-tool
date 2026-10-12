"""Round 38 step 7b (Liam, 2026-10-11): the ten zero-API checks of the self-audit. Each check takes one profile
(property_details, checked topics) and returns its failures as dicts {check, carrier, detail}. The check runs the
real pipeline (rules tables, routing, cards, top box, placement) with a fake model that answers Eligible to whatever
it is asked, so a failure is never the model's.

  1 determinism        the same profile twice gives the same records
  2 unticked_blank     an unticked County / Coverage A topic is the same check as the topic ticked and left blank
  3 monotonic          a worse fact (older roof, older home, more losses) never turns a decline or referral Eligible
  4 answer_no_hold     answering a blank question never adds a hold (Insufficient Information)
  5 routing            owner-occupied homes see no dwelling-fire program; landlord homes see no homeowners program
  6 deciding_row       every code-decided Not eligible / Refer names its deciding row, quotes it, and never hedges
  7 no_reask           no card item or top-box line asks a question the form answered
  8 page               page hygiene: one record per carrier, one bucket each, display names, no empty / raw lines
  9 placement          the placement panel ranks only Eligible or Insufficient Information programs
 10 coverage           (collected, not a failure) the outcome of every map line, for the never-reached report
"""
import copy
import json
import os
import random
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
for k in ("ELIGIBILITY_RULES_PILOT", "ELIGIBILITY_RULES_SAGE_BATCH", "ELIGIBILITY_RULES_HO3_BATCH",
          "ELIGIBILITY_RULES_DP_BATCH", "ELIGIBILITY_PLACEMENT"):
    os.environ[k] = "1"
os.environ["ANTHROPIC_API_KEY"] = "invalid-guard"
os.environ["OPENAI_API_KEY"] = "invalid-guard"
os.environ.setdefault("ELIGIBILITY_USAGE_LOG", os.path.join(tempfile.gettempdir(), "usage_fuzz.jsonl"))   # never in the repo
sys.path.insert(0, ROOT)
import cards  # noqa: E402
import confirm_topics as ct  # noqa: E402
import display_names  # noqa: E402
import eligibility_check as ec  # noqa: E402
import intake_fields  # noqa: E402
import placement  # noqa: E402
import rules_evaluator as rv  # noqa: E402

USAGE = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


def _fake(system, user, max_tokens):
    names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)) | set(re.findall(r"--- (.+?) \(rule check\) ---", user)))
    return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["fixture"],
                                     "citations": [], "missing_info": [], "notes": ""} for n in names]}), dict(USAGE)


ec._complete = _fake
BATCHES_ON = ("sage", "ho3", "dp")
RANK = {"ELIGIBLE": 0, "REFER": 1, "INSUFFICIENT_INFORMATION": 1, "INELIGIBLE": 2}
HEDGE = re.compile(r"\b(appears? to|seems? to|likely|probably|presumably|might be)\b", re.I)
ROW_ID = re.compile(r"\[([A-Z][A-Z0-9]{2}-\d{3})\]")
DP_NAME = re.compile(r"DP-?3|DP_Guide|Dwelling|TDP", re.I)
HO_NAME = re.compile(r"(?<![A-Za-z])HO-?(3|5|6|B|A)(?![A-Za-z])|Homeowners", re.I)


def run(pd, checked):
    """The check as app.py runs it (unticked County / Coverage A is blank)."""
    return ec.check_eligibility(copy.deepcopy(pd), checked_topics=list(checked) if checked is not None else None,
                                log_usage=False)


def _key(results):
    """What the agent sees, per carrier."""
    return {r.get("carrier"): (r.get("status"), r.get("reasons"), r.get("missing_info"), r.get("citations"),
                               [dict(sorted(x.items())) for x in r.get("confirm_items") or []]) for r in results}


def _status(results):
    return {r.get("carrier"): r.get("status") for r in results}


RAN = []          # the checks that compared something on the current profile (a check with nothing to compare skips)


def _fail(check, carrier, detail):
    return {"check": check, "carrier": carrier, "detail": detail}


# ---------------------------------------------------------------- 1-4: the pipeline against itself

def c1_determinism(pd, checked, base):
    again = _key(run(pd, checked))
    first = _key(base)
    return [_fail("determinism", c, {"first": first.get(c), "again": again.get(c)})
            for c in sorted(set(first) | set(again)) if first.get(c) != again.get(c)]


def c2_unticked_blank(pd, checked, base, rng):
    out = []
    topic = rng.choice(["county", "dwelling_amount"])
    if topic not in checked:
        return out
    RAN.append(f"unticked_blank:{topic}")
    unticked = _status(run(pd, [t for t in checked if t != topic]))
    blank = dict(pd, **ec.BLANK_WHEN_UNTICKED[topic])
    if topic == "county":
        blank.pop("harris_east_146", None)
    ticked_blank = _status(run(blank, checked))
    for c in sorted(set(unticked) | set(ticked_blank)):
        if unticked.get(c) != ticked_blank.get(c):
            out.append(_fail("unticked_blank", c, {"topic": topic, "unticked": unticked.get(c),
                                                   "ticked_blank": ticked_blank.get(c)}))
    return out


def worse(pd, rng):
    """(dimension, a copy of pd with one fact made worse), or None when none can be."""
    options = []
    age = 2026 - int(pd["year_built"])
    if pd.get("roof_age", 0) < age and pd.get("roof_age", 0) < 100:
        options.append("roof_age")
    if pd["year_built"] > 1800:
        options.append("year_built")
    if pd.get("losses_5yr") in ("0", "1", "2"):
        options.append("losses_5yr")
    if pd.get("fire_station_miles") is not None:
        options.append("fire_station_miles")
    if not options:
        return None
    dim = rng.choice(options)
    w = dict(pd)
    if dim == "roof_age":
        w["roof_age"] = min(age, 100, pd["roof_age"] + rng.choice([1, 5, 10, 20]))
    elif dim == "year_built":
        w["year_built"] = max(1800, pd["year_built"] - rng.choice([1, 5, 10, 30]))
    elif dim == "fire_station_miles":
        w["fire_station_miles"] = round(pd["fire_station_miles"] + rng.choice([0.5, 2.0, 5.0]), 1)
    else:
        w["losses_5yr"] = {"0": "1", "1": "2", "2": "3 or more"}[pd["losses_5yr"]]
    return dim, w


def c3_monotonic(pd, checked, base, rng):
    got = worse(pd, rng)
    if not got:
        return []
    dim, w = got
    RAN.append(f"monotonic:{dim}")
    before, after = _status(base), _status(run(w, checked))
    return [_fail("monotonic", c, {"dimension": dim, "from": pd.get(dim), "to": w.get(dim), "before": before[c],
                                   "after": after.get(c)})
            for c in before if before[c] in ("INELIGIBLE", "REFER") and after.get(c) == "ELIGIBLE"]


def answered(pd, rng):
    """(field, value) answering one question the profile left blank, or None."""
    options = []
    if pd.get("fire_station_miles") is None:
        options.append(("fire_station_miles", rng.choice([1.0, 4.0, 5.5, 9.0])))
    if pd.get("hydrant_1000ft") == "Unknown":
        options.append(("hydrant_1000ft", rng.choice(["Yes", "No"])))
    if not pd.get("county"):
        options.append(("county", rng.choice(["Harris", "Travis", "Galveston", "Dallas", "Bexar", "Collin"])))
    if pd.get("dwelling_amount") is None:
        options.append(("dwelling_amount", rng.choice([200000, 450000, 900000])))
    if not pd.get("losses_5yr") or pd.get("losses_5yr") == "Unknown":
        options.append(("losses_5yr", rng.choice(["0", "1"])))
    if not pd.get("electrical") or "Unknown" in pd.get("electrical", []):
        options.append(("electrical", rng.choice([["Circuit breakers"], ["Fuses"]])))
    if pd.get("has_dogs") == "Yes" and intake_fields.dog_breeds(pd) is None:
        options.append(("dog_breeds", rng.choice([[intake_fields.DOG_NONE], ["Pit Bull"]])))
    if pd.get("ownership_type") == "Trust" and pd.get("trust_type") in (None, "Unknown"):
        options.append(("trust_type", rng.choice(intake_fields.TRUST_TYPES[1:])))
    if pd.get("county") == "Harris" and pd.get("harris_east_146") in (None, "Unknown"):
        options.append(("harris_east_146", rng.choice(["Yes", "No"])))
    if pd.get("plumbing_type") == "Unknown":
        options.append(("plumbing_type", rng.choice(["Copper", "PVC", "Galvanized"])))
    return rng.choice(options) if options else None


def c4_answer_no_hold(pd, checked, base, rng):
    got = answered(pd, rng)
    if not got:
        return []
    field, value = got
    a = dict(pd, **{field: value})
    if field == "county":
        a["zip"] = ""
        if value == "Harris":
            a["harris_east_146"] = "Unknown"      # the form shows it, Unknown, as soon as Harris is picked
    if field == "losses_5yr" and value == "0":
        for k in ("loss_types", "loss_year", "losses_3yr"):
            a.pop(k, None)
    topic = {"fire_station_miles": "ppc", "hydrant_1000ft": "ppc", "county": "county",
             "dwelling_amount": "dwelling_amount", "dog_breeds": "dogs", "harris_east_146": "county",
             "plumbing_type": "plumbing"}.get(field)
    if topic and topic not in checked:
        return []
    RAN.append(f"answer_no_hold:{field}")
    before, after = _status(base), _status(run(a, checked))
    return [_fail("answer_no_hold", c, {"field": field, "value": value, "before": before[c], "after": after.get(c)})
            for c in before if before[c] != "INSUFFICIENT_INFORMATION" and after.get(c) == "INSUFFICIENT_INFORMATION"]


# ---------------------------------------------------------------- 5-9: one check's page

def c5_routing(pd, checked, base):
    out = []
    occ = pd["occupancy_type"]
    for r in base:
        c = r.get("carrier", "")
        both = bool(DP_NAME.search(c)) and bool(HO_NAME.search(c))
        if both:
            continue
        if occ == "Owner Occupied" and DP_NAME.search(c):
            out.append(_fail("routing", c, {"occupancy": occ, "why": "dwelling-fire program on an owner's home"}))
        if occ in ("Tenant Occupied", "Vacant") and HO_NAME.search(c) and not (
                pd.get("dwelling_type") == "Condo" and occ in ec.CONDO_UNIT_OCCUPANCIES.get(c, ())):
            out.append(_fail("routing", c, {"occupancy": occ, "why": "homeowners program on a landlord home"}))
    return out


def c6_deciding_row(pd, checked, base):
    out = []
    for r in base:
        if r.get("status") not in ("INELIGIBLE", "REFER") or not (r.get("rules_table") or r.get("decided_by_code")):
            continue
        c = r.get("carrier")
        if r.get("fixed_row"):
            continue
        reasons = [x for x in r.get("reasons") or [] if isinstance(x, str)]
        ids = [i for x in reasons for i in ROW_ID.findall(x)]
        quoted = [x for x in r.get("citations") or [] if isinstance(x, str) and re.search(r"[\"'][^\"']{8,}[\"']", x)]
        if not ids and r.get("decided_by_code") and quoted and not HEDGE.search(reasons[0] if reasons else ""):
            continue                     # a code rule from the guide's own sentence (Chubb's tiers, Sage's FPC table)
        if not ids:
            out.append(_fail("deciding_row", c, {"status": r["status"], "why": "no row ID in any reason",
                                                 "reason": (reasons or [""])[0][:200]}))
            continue
        cites = " ".join(x for x in r.get("citations") or [] if isinstance(x, str))
        if not any(re.search(r"\[" + i + r"\] p\.\d+: \"[^\"]{8,}", cites) for i in ids):
            out.append(_fail("deciding_row", c, {"status": r["status"], "row": ids[0], "why": "no page and quote",
                                                 "citations": cites[:300]}))
        if HEDGE.search(reasons[0]):
            out.append(_fail("deciding_row", c, {"status": r["status"], "row": ids[0], "why": "hedged",
                                                 "reason": reasons[0][:200]}))
    return out


# what an answered field must never be asked again by (the question part, lower case)
REASKED = {
    "ownership": [r"owned by individuals", r"not an llc"],
    "occupancy": [r"^occupancy: no short-term rental, roomers, students or vacancy\?$"],
    "losses": [r"any losses or claims", r"how many, what type, when"],
    "electrical": [r"breakers \(no fuses\)", r"no federal pacific", r"no knob-and-tube"],
    "pool": [r"pool or spa details", r"diving board", r"\bslide\b"],
    "animals": [r"a dog with a bite history"],
    "roof": [r"enough life left"],
    "plumbing": [r"material and condition", r"no polybutylene"],
    "solar": [r"how and where installed"],
}


_ENTERED = re.compile(r"\([^()]*\bentered\)")


def question(text):
    """The part of an item that asks: "Pool (in ground - fenced, slide only entered): gate ...?" states the slide."""
    return _ENTERED.sub("", text).lower()


def _answered_topics(pd, checked):
    on = lambda t: checked is None or t in checked       # noqa: E731
    keys = {"ownership", "occupancy"}
    if intake_fields.loss_answers(pd)["losses_5yr"] is not None:
        keys.add("losses")
    if intake_fields.electrical_answer(pd):
        keys.add("electrical")
    if on("pool"):
        keys.add("pool")
    if on("dogs"):
        keys.add("animals")
    if on("roof_age") and pd.get("roof_age") not in (None, ""):
        keys.add("roof")
    if on("plumbing") and pd.get("plumbing_type") not in (None, "", "Unknown"):
        keys.add("plumbing")
    if on("solar") and (pd.get("solar_panels") == "No" or pd.get("solar_type")):
        keys.add("solar")
    return keys


def c7_no_reask(pd, checked, base):
    out = []
    keys = _answered_topics(pd, checked)
    for r in base:
        for it in ct.card_items(r, pd, checked):
            if it["key"] in keys and any(re.search(rx, question(it["ask"])) for rx in REASKED[it["key"]]):
                out.append(_fail("no_reask", r.get("carrier"), {"topic": it["key"], "ask": it["ask"]}))
    for text, _, _ in ct.top_box(base, pd, checked):
        for key in keys:
            if any(re.search(rx, question(text)) for rx in REASKED[key]):
                out.append(_fail("no_reask", "(top box)", {"topic": key, "line": text}))
    return out


_RAW = re.compile(r"\b(None|nan|null|undefined)\b|\[\s*\]|\{\s*\}")


def c8_page(pd, checked, base):
    out = []
    names = [r.get("carrier") for r in base]
    for c in {n for n in names if names.count(n) > 1}:
        out.append(_fail("page", c, {"why": "carrier twice", "count": names.count(c)}))
    buckets = ec.assign_buckets(base)
    for r in base:
        c = r.get("carrier")
        n = sum(1 for b in buckets.values() if any(x is r for x in b))
        if n != 1:
            out.append(_fail("page", c, {"why": f"in {n} buckets"}))
        shown = display_names.display_name(c or "")
        if not shown or "_" in shown:
            out.append(_fail("page", c, {"why": "display name", "shown": shown}))
        if r.get("status") not in RANK:
            continue
        first = cards.first_line_markdown(r, pd, checked, label=False)
        if not first.strip() or _RAW.search(first) or ROW_ID.search(first):
            out.append(_fail("page", c, {"why": "first line", "line": first[:200]}))
        html = cards.confirm_html(r, pd, checked)
        if "<li></li>" in html or _RAW.search(re.sub(r"<[^>]+>", " ", html)):
            out.append(_fail("page", c, {"why": "confirm list", "html": html[:300]}))
        for m in r.get("missing_info") or []:
            if isinstance(m, str) and (not m.strip() or ROW_ID.search(cards.agent_text(m))):
                out.append(_fail("page", c, {"why": "missing item", "item": m[:200]}))
    return out


# a held reason or a Missing item that asks for an answered field (round 38 step 1, generalized)
HELD_REASKS = {
    "fire_station_miles": [r"confirm the distance", r"station distance", r"distance to the (responding )?fire station"],
    "hydrant_1000ft": [r"confirm the hydrant", r"whether a hydrant is within", r"hydrant within 1,000 ft if not given"],
    "county": [r"\bwhich county\b", r"county is not given", r"\bcounty -- "],
    "dwelling_amount": [r"coverage a is (also )?needed", r"dwelling amount \(coverage a\)"],
}


def c11_held_reasks(pd, checked, base):
    out = []
    on = {"fire_station_miles": "ppc", "hydrant_1000ft": "ppc", "county": "county", "dwelling_amount": "dwelling_amount"}
    answered = [f for f in HELD_REASKS if (checked is None or on[f] in checked)
                and pd.get(f) not in (None, "", "Unknown")]
    for r in base:
        if r.get("status") not in ("INSUFFICIENT_INFORMATION", "REFER"):
            continue
        texts = [cards.agent_text(x) for x in (r.get("reasons") or [])[:1] + (r.get("missing_info") or [])
                 if isinstance(x, str)]
        for f in answered:
            for t in texts:
                if any(re.search(rx, t.lower()) for rx in HELD_REASKS[f]):
                    out.append(_fail("held_reasks", r.get("carrier"), {"field": f, "value": pd.get(f),
                                                                       "text": t[:200]}))
                    break
    return out


def c9_placement(pd, checked, base):
    p = placement.panel(base, pd)
    if not p:
        return []
    status = _status(base)
    return [_fail("placement", prog, {"market": pick["market"], "status": status.get(prog)})
            for pick in p["picks"] for prog in pick["programs"]
            if status.get(prog) not in placement.CANDIDATE_STATUSES]


# ---------------------------------------------------------------- 10: map-line coverage

def c10_coverage(pd, checked):
    """{row_id: outcome} for every rules-table carrier this property routes to."""
    out = {}
    for canon in sorted(set(rv.CANON_TO_WB)):
        wb = rv.rules_table_wb(canon, BATCHES_ON, pd)
        if wb is None:
            continue
        try:
            for rid, (outcome, _) in rv.evaluate_carrier(canon, pd, checked, wb=wb).items():
                out[rid] = outcome
        except Exception as e:                       # noqa: BLE001 -- recorded as a failure by the runner
            out[f"!{canon}"] = f"{type(e).__name__}: {e}"
    return out


CHECKS = ("determinism", "unticked_blank", "monotonic", "answer_no_hold", "routing", "deciding_row", "no_reask",
          "page", "placement", "held_reasks")


def check_profile(pd, checked, seed, only=None):
    """(failures, coverage) for one profile. only: a set of check names to run (a fixture's replay)."""
    rng = random.Random(f"checks-{seed}")
    want = lambda name: only is None or name in only       # noqa: E731
    RAN.clear()
    base = run(pd, checked)
    pd_seen, checked_seen = ec.unticked_is_blank(pd, checked)    # what the page renders with
    fails = []
    if want("determinism"):
        fails += c1_determinism(pd, checked, base)
    if want("unticked_blank"):
        fails += c2_unticked_blank(pd, checked, base, rng)
    if want("monotonic"):
        fails += c3_monotonic(pd, checked, base, rng)
    if want("answer_no_hold"):
        fails += c4_answer_no_hold(pd, checked, base, rng)
    if want("routing"):
        fails += c5_routing(pd, checked, base)
    if want("deciding_row"):
        fails += c6_deciding_row(pd, checked, base)
    if want("no_reask"):
        fails += c7_no_reask(pd_seen, checked_seen, base)
    if want("page"):
        fails += c8_page(pd_seen, checked_seen, base)
    if want("placement"):
        fails += c9_placement(pd_seen, checked_seen, base)
    if want("held_reasks"):
        fails += c11_held_reasks(pd_seen, checked_seen, base)
    coverage = c10_coverage(pd_seen, checked_seen) if only is None else {}
    return fails, coverage, base
