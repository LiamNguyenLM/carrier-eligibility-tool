"""Round 29 step 1 (Liam, 2026-10-08): the hold guard.

Project rule: a fact the intake form never asks is "confirm", never a hold.
Round 28 step 6: all 25 Haiku/Luna disagreements were Haiku holding on such
facts (brush area, acreage, loss history, heating, wiring...), and Luna held 2-3
carriers per CLEAN run the same way.

After the model call and every code rule, each INSUFFICIENT_INFORMATION card's
missing_info items are classified:
  (a) a form field (intake_fields.FORM_FIELDS) -- blank, so the agent can fill
      it in: KEEP
  (b) an item code wrote (county / CHUBB / Sage FPC / pool-spec / TWICO / roof
      holds; anything not in the model's own list): KEEP
  (c) a fact the form does not collect (NOT_ASKED below): moved to a
      "Confirm: ..." note
  anything else is unclassified and counts as (a): KEEP.
Round 36 step 4b (Liam, 2026-10-03, restated 2026-10-10): an (a) item on a form field left BLANK whose blank
answer is a note for that carrier (blank_notes: County and Coverage A, except the named holds -- Sage's
territory, CHUBB) is moved to a "Confirm: ..." note too.
All items (c) -> ELIGIBLE (decided by code, with the notes). Some (c) -> only
those move; the status stays. Never touched: INELIGIBLE / REFER / ELIGIBLE
cards, rules-table cards, cards whose hold code made, and cards citing a
rules-table row."""
import re

import intake_fields

# (b) items code writes into a model's record (eligibility_check), by prefix.
CODE_ITEM_PREFIXES = (
    "County -- ", "Dwelling amount (Coverage A)", "Pool enclosure specifics are not confirmed",
    "Driving distance to the responding fire station", "Whether this flat roof is a poured concrete deck",
    "TWICO distinguishes",
)
ROW_ID = re.compile(r"\[[A-Z]{3}-\d{3}\]")

# (c) facts the intake form does not collect: canonical name -> patterns. Checked BEFORE the form
# fields, because many name a form field's topic ("plumbing update date", "solar panel mounting").
NOT_ASKED = {
    "roof remaining life": (r"\b(remaining|useful)\b[^.;]{0,25}\blife\b", r"\blife expectancy\b"),
    "roof overlay / layers": (r"\boverlay\b", r"\broof\b[^.;]{0,30}\blayers?\b", r"\blayers? of (shingles|roofing)\b"),
    "heating / cooling system": (r"\bheating\b", r"\bheat source\b", r"\bfurnace\b", r"\bhvac\b", r"\bheat pump\b",
                                 r"\bboiler\b", r"\bcentral (a/c|air|heat)\b", r"\bair[- ]condition", r"\ba/c\b",
                                 r"\bcooling\b"),
    "wood stove / space heater": (r"\b(wood|coal)[- ]?(burning |or coal |or wood )?stoves?\b", r"\bspace heaters?\b",
                                  r"\bsolid[- ]fuel\b"),
    "wiring / electrical": (r"\bwiring\b", r"\bknob[- ]and[- ]tube\b", r"\bbreakers?\b", r"\belectrical\b",
                            r"\bamperage\b", r"\b\d+\s*amps?\b", r"\bfuses?\b", r"\bfuse ?box", r"\bservice panel\b",
                            r"\bcircuit panel\b", r"\belectrician\b"),
    "system updates": (r"\b(plumbing|systems?)\b[^.;]{0,40}\bupdat", r"\bupdat\w*\b[^.;]{0,40}\b(plumbing|systems?)\b",
                       r"\bre-?plumb", r"\brenovat"),
    "brush / wildfire / hillside": (r"\bbrush\b", r"\bbrushfire\b", r"\bwildfire\b", r"\bwildland\b", r"\bhillside\b",
                                    r"\blandslide\b", r"\bslope\b", r"\bwind hazard\b"),
    "commercial exposure": (r"\bcommercial (exposure|property|business|building)",),
    "acreage": (r"\bacres?\b", r"\bacreage\b", r"\blot size\b"),
    "mortgages": (r"\bmortgage",),
    "loss history": (r"\b(loss|claim)(es|s)?\b[^.;]{0,15}\bhistory\b", r"\bprior\b[^.;]{0,40}\b(loss|losses|claims?)\b",
                     r"\b(water|fire|liability|theft|sinkhole|mold|weather|wind|hail|non-weather)\b[^.;]{0,10}\b(loss|losses|claims?)\b",
                     r"\bopen claims?\b", r"\blosses? in the (last|past)\b"),
    "prior insurance": (r"\bcancell?(ation|ed)\b", r"\bnon-?renew", r"\blapses?\b", r"\bprior (insurance|carrier)\b",
                        r"\bcontinuous coverage\b"),
    "bankruptcy / foreclosure": (r"\bbankrupt", r"\bforeclos"),
    "flood zone": (r"\bflood (zone|designation|policy|insurance)\b", r"\bspecial flood hazard\b",
                   r"\bbase flood elevation\b", r"\bwave wash\b"),
    "historic registry": (r"\bhistoric",),
    # (not a roof's replacement-cost settlement: that follows from the form's roof type and age)
    "replacement cost / insurance to value": (r"^(?!.*\broof).*\breplacement cost\b", r"\binsurance[- ]to[- ]value\b",
                                              r"\binsured to (100|value)", r"\bitv\b", r"\brce\b"),
    "occupancy details": (r"\bmonths? (per|a|each|of the) year\b", r"\bincidental occupancy\b",
                          r"\brelationship to (the )?occupant", r"\bshort[- ]term rental", r"\brental (history|exposure|weeks|period)",
                          r"\bstudents?\b", r"\broomers?\b", r"\bboarders?\b"),
    "gated / secured community": (r"\b(gated|secured|patrolled) community\b", r"\bsecured community\b"),
    "title / deed": (r"\bdeeded\b", r"\btitled? (to|in)\b", r"\bnamed insured\b"),
    "home details": (r"\bmodular\b", r"\bsquare (feet|footage)\b", r"\bsq\.? ?ft\b", r"\bstories\b",
                     r"\bnumber of (units|families|stories)\b", r"\bfoundation\b", r"\bsiding\b", r"\beifs\b",
                     r"\bstucco\b", r"\blog home\b", r"\bdome\b"),
    "pool depth": (r"\bpool depth\b", r"\bdepth of (the )?pool\b"),
    "solar mounting / permit": (r"\bsolar\b[^.;]{0,40}\b(mount\w*|ground|location|permit\w*|code)\b",
                                r"\b(ground|roof)[- ]mounted\b"),
    "animal details": (r"\bbite\b", r"\bbitten\b", r"\bvicious\b", r"\bexotic\b", r"\blivestock\b", r"\bhorses?\b",
                       r"\bfarm animals?\b"),
    "trampoline / play equipment": (r"\btrampoline", r"\bskateboard", r"\bplayground"),
    "business on premises": (r"\bbusiness (on|at) (the )?premises\b", r"\bhome business\b", r"\bdaycare\b",
                             r"\bday care\b"),
    # Round 31 step 3c: Haiku held Swyfft (SWY-043, Tesla solar roofs) on the panels' maker.
    # Round 35 step 3d: the form asks about Tesla equipment (solar_tesla), so an item naming Tesla is a form
    # field, never "not asked"; any other brand / maker question still is
    "product brand / maker": (r"^(?!.*\btesla\b).*\bbrand\b", r"^(?!.*\btesla\b).*\bmanufacturer\b",
                              r"^(?!.*\btesla\b).*\bmake (and|or) model\b"),
    # Round 36 step 4a: Liam's Railway check (2026-10-10) held Allied on "Insurance score" -- the guard had no
    # entry for it. The rest are the items the round 34-36 outputs held on that the form never asks.
    "insurance / credit score": (r"\binsurance[- ]scores?\b", r"\bcredit[- ]?(based|scores?|reports?|history|tiers?|checks?|rating)\b",
                                 r"\bcredit\b[^.;]{0,20}\binsurance\b"),
    # (never when the item also names Coverage A: that is a form field)
    "coverage B-F amounts": (r"^(?!.*\b(coverage|cov\.?) a\b).*\b(coverage|cov\.?) [b-f]\b",
                             r"\bpersonal property (limit|amount|coverage)\b", r"\bcontents (limit|amount|coverage)\b"),
    "firewalls / unit separation": (r"\bfire[- ]?walls?\b", r"\bfire divisions?\b", r"\bunit configuration\b"),
}
# An item asking for the guide's own rules is a retrieval gap, not a property fact: kept.
_GUIDE_GAP = re.compile(r"\b(eligibility|underwriting) (rules|criteria|guidelines|requirements)\b|"
                        r"\brequirements for this program\b|\bfrom (the )?full guide\b|\bnot retrieved\b", re.I)
_NOT_ASKED_RE = [(name, re.compile("|".join(p), re.I)) for name, p in NOT_ASKED.items()]
_FORM_RE = [(field, re.compile("|".join(p), re.I)) for field, p in intake_fields.FORM_FIELDS.items()]


def synonym_count():
    """(facts, patterns) in the not-asked table."""
    return len(NOT_ASKED), sum(len(p) for p in NOT_ASKED.values())


def classify(item, model_items=None):
    """("a" | "b" | "c" | "unknown", detail). unknown is treated as (a)."""
    text = str(item or "")
    if text.startswith(CODE_ITEM_PREFIXES) or ROW_ID.search(text):
        return "b", "code"
    if model_items is not None and text not in model_items:
        return "b", "added by code"
    if _GUIDE_GAP.search(text):
        return "unknown", "guide text not retrieved"
    for name, rx in _NOT_ASKED_RE:
        if rx.search(text):
            return "c", name
    for field, rx in _FORM_RE:
        if rx.search(text):
            return "a", field
    return "unknown", ""


def _held_by_code(r):
    return any(d.get("status") == "INSUFFICIENT_INFORMATION" for d in r.get("_code_decisions") or [])


def _cites_a_row(r):
    return any(ROW_ID.search(str(x)) for x in (r.get("reasons") or []) + (r.get("citations") or []))


BLANK_NOTE = ("Confirm (left blank on the form; for this carrier a blank answer is never a hold): ")


def apply(results, decide_by_code, append_note, stats=None, blank_notes=None):
    """The guard, in place. decide_by_code / append_note are eligibility_check's helpers.
    stats (optional dict) collects {"removed_items": [...], "released": n, "trimmed": n}.
    blank_notes (round 36 step 4b, optional): carrier -> the form fields left blank whose blank answer is a
    note, never a hold, for that carrier."""
    for r in results:
        model_items = r.pop("_model_missing_info", None)
        if (r.get("status") != "INSUFFICIENT_INFORMATION" or r.get("rules_table") or _held_by_code(r)
                or _cites_a_row(r)):
            continue
        items = list(r.get("missing_info") or [])
        if not items:
            continue
        classes = [(m, classify(m, model_items)) for m in items]
        blank = set(blank_notes(r.get("carrier", ""))) if blank_notes else set()
        confirm = [m for m, (c, _) in classes if c == "c"]
        blank_items = [m for m, (c, field) in classes if c == "a" and field in blank]
        if not confirm and not blank_items:
            continue
        keep = [m for m in items if m not in confirm and m not in blank_items]
        if confirm:
            append_note(r, "Confirm (not asked by the form; never a hold): " + "; ".join(confirm) + ".")
        if blank_items:
            append_note(r, BLANK_NOTE + "; ".join(blank_items) + ".")
        r["missing_info"] = keep
        if stats is not None:
            stats.setdefault("removed_items", []).extend(
                (r.get("carrier"), m, classify(m)[1]) for m in confirm + blank_items)
        if not keep:
            r["status"], r["flaw_count"] = "ELIGIBLE", 0
            decide_by_code(r, "ELIGIBLE", "Only facts the intake form does not ask, or left blank where a "
                                          "blank answer is never a hold, were open; they are listed to confirm.")
            if stats is not None:
                stats["released"] = stats.get("released", 0) + 1
        elif stats is not None:
            stats["trimmed"] = stats.get("trimmed", 0) + 1
