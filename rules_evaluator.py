"""The rules-table pilot (round 25, Liam 2026-10-03/04): decide a carrier's
structured rule rows from the form, in code, for the six pilot carriers.

Data (committed, see the header line of each file):
  rules_data/carrier_rules_pilot_v3.csv   the rows (pilot workbook version 3)
  rules_data/rule_field_map.csv           one map line per deciding row
  rules_data/RULE_FIELD_MAP.md            the expression grammar and the
                                          guide-word -> form-option table
Measured in rounds 23-24 on branches structured-rules-test / -eval
(experiments/STRUCTURED_RULES_EVAL_RESULTS.md there); this is condition C2.

Three-valued logic: true, false, unknown (None). A blank optional field, PPC
"N/A", plumbing "Unknown"/"Other", an unticked pool box and FACT(...) are
unknown. Row outcomes:
  SKIP  a topic the row needs is unchecked (round 21)
  N/A   the gate is false
  PASS  every reading of the test is true
  FAIL  every reading is false, gate true -> the row's effect
  OPEN  unknown, or the readings disagree (AMBIGUOUS): the model judges it
  NOTE  never a hold:
          - EVALUATE_CURE_IS_INSPECTION rows that FAIL or are OPEN: the cure
            is an inspection (round 24);
          - decision 1 (Liam, 2026-10-03): a row left open only because
            Coverage A or County is blank -- the rule is shown, "confirm".
            (The Sage county hold and the CHUBB Coverage A hold are separate
            pipeline checks and still fire.)
  NONE  the form has no field for the row: an "Also confirm" note
Rows that are CONDITION_STANDARD (decision 2) are "Also confirm" notes too.
IGNORE_INSPECTION and NOT_ELIGIBILITY rows are never used.

Carrier, from the code alone: any FAIL DECLINES -> INELIGIBLE; else FAIL
REFERS_TO_UW -> REFER; else FAIL CONDITION -> REFER; else OPEN ->
undecided (the model is asked); else ELIGIBLE.
"""
import csv
import datetime
import json
import os
import re

import intake_fields
from structured_rules import sage_county_in_territory

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_CSV = os.path.join(HERE, "rules_data", "carrier_rules_pilot_v3.csv")
MAP_CSV = os.path.join(HERE, "rules_data", "rule_field_map.csv")

# workbook carrier name -> pipeline carrier
PILOT_CARRIERS = {
    "Allied Trust HO3": "Allied_Trust_HO3",
    "Sage Auros HO3": "Sage_-_Auros_HO3",
    "Chubb HO": "CHUBB_HO_-_05.22.2026",
    "Mercury HO3": "Mercury_HO3_-_01.01.2026",
    "Progressive HO3": "Progressive_HO3_-_04.01.2026",
    "Swyfft Benchmark (Admitted) HO3": "Swyfft_-_Benchmark_(Admitted)_HO3",
}
CANON_TO_WB = {v: k for k, v in PILOT_CARRIERS.items()}

DECIDING = ("EVALUATE", "EVALUATE_CURE_IS_INSPECTION")
FIELD_TOPIC = {   # map field -> round 21 topic (always-on fields -> None)
    "ppc": "ppc", "coastal_tier": "coastal", "year_built": "home_age", "roof_age": "roof_age",
    "roof_type": "roof_type", "roof_shape": "roof_shape", "construction_type": "construction",
    "plumbing_type": "plumbing", "swimming_pool": "pool", "pool_accessories": "pool",
    "pool_fence_4ft": "pool", "pool_gate_locking": "pool", "has_dogs": "dogs", "aggressive_breed": "dogs",
    "solar_panels": "solar", "county": "county", "zip": "county", "dwelling_amount": "dwelling_amount",
    "occupancy_type": None, "ownership_type": None, "dwelling_type": None,
}
# Decision 1: an OPEN that rests only on these blank fields is a NOTE.
BLANK_IS_NOTE = {"dwelling_amount", "county", "zip", "sage_territory"}


# --------------------------------------------------------------------------- data
def _read_csv(path):
    with open(path, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(line for line in fh if not line.startswith("#")))


_CACHE = {}


def load_rules():
    if "rules" not in _CACHE:
        _CACHE["rules"] = {r["Rule ID"]: r for r in _read_csv(RULES_CSV)}
    return _CACHE["rules"]


def load_map():
    if "map" not in _CACHE:
        _CACHE["map"] = {m["row_id"]: m for m in _read_csv(MAP_CSV)}
    return _CACHE["map"]


# --------------------------------------------------------------------------- facts
def facts(pd, today=None):
    """The values the grammar reads, from a property_details dict."""
    year = (today or datetime.date.today()).year
    f = dict(pd)
    yb = pd.get("year_built")
    f["home_age"] = year - int(yb) if yb not in (None, "") else None
    m = re.match(r"(\d+)", str(pd.get("ppc", "")).strip())
    f["ppc_num"] = int(m.group(1)) if m else None
    county = intake_fields.normalize_county(pd.get("county")) or None
    f["county"] = county
    t = sage_county_in_territory(county or "", intake_fields.COUNTY_MAX_LATITUDE, True)
    f["sage_territory"] = None if t == "UNKNOWN" else t
    f["dwelling_amount"] = intake_fields.parse_dwelling_amount(pd.get("dwelling_amount"))
    f["zip"] = intake_fields.parse_zip(pd.get("zip"))[0] or None
    f["dwelling_type"] = intake_fields.normalize_dwelling_type(pd.get("dwelling_type")) or None
    if f.get("plumbing_type") in ("Unknown", "Other"):
        f["plumbing_type"] = None
    if f.get("ppc") in ("N/A", ""):
        f["ppc"] = None
    for box in ("pool_fence_4ft", "pool_gate_locking"):      # unticked = unknown, never "no"
        f[box] = True if intake_fields.pool_box(pd, box) else None
    return f


# --------------------------------------------------------------------------- grammar
_TOKEN = re.compile(r"\s*(\(|\)|\{[^}]*\}|FACT\([^)]*\)|==|!=|<=|>=|<|>|[^\s(){}=!<>]+)")


def _tokens(s):
    out, i, s = [], 0, s.strip()
    while i < len(s):
        m = _TOKEN.match(s, i)
        if not m:
            raise ValueError(f"cannot parse at {s[i:]!r}")
        out.append(m.group(1))
        i = m.end()
    return out


def _and(vals):
    if any(v is False for v in vals):
        return False
    return None if any(v is None for v in vals) else True


def _or(vals):
    if any(v is True for v in vals):
        return True
    return None if any(v is None for v in vals) else False


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


class _Parser:
    def __init__(self, text, f):
        self.t, self.i, self.f, self.unknown = _tokens(text), 0, f, []

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else None

    def take(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def parse(self):
        v = self.or_expr()
        if self.peek() is not None:
            raise ValueError(f"unexpected {self.peek()!r}")
        return v

    def or_expr(self):
        vals = [self.and_expr()]
        while self.peek() == "or":
            self.take()
            vals.append(self.and_expr())
        return _or(vals)

    def and_expr(self):
        vals = [self.atom()]
        while self.peek() == "and":
            self.take()
            vals.append(self.atom())
        return _and(vals)

    def atom(self):
        tok = self.peek()
        if tok == "always":
            self.take()
            return True
        if tok == "not" and self.peek(1) != "in":
            self.take()
            v = self.atom()
            return None if v is None else (not v)
        if tok == "(":
            self.take()
            v = self.or_expr()
            if self.take() != ")":
                raise ValueError("missing )")
            return v
        if tok.startswith("FACT("):
            self.take()
            self.unknown.append(tok[5:-1])
            return None
        return self.comparison()

    def value_words(self):
        words = []
        while self.peek() not in (None, "and", "or", ")"):
            words.append(self.take())
        return " ".join(words)

    def comparison(self):
        name, op = self.take(), self.take()
        if op == "not" and self.peek() == "in":
            self.take()
            op = "not in"
        val = self.f.get(name, None)
        if op in ("in", "not in"):
            items = {x.strip() for x in self.take().strip("{}").split(",")}
            if val is None:
                self.unknown.append(name)
                return None
            hit = str(val) in items
            return hit if op == "in" else not hit
        if op == "between":
            lo = self.take()
            if self.take() != "and":
                raise ValueError("between needs and")
            hi = self.take()
            v = _num(val)
            if v is None:
                self.unknown.append(name)
                return None
            return float(lo) <= v <= float(hi)
        rhs = self.value_words()
        if val is None:
            self.unknown.append(name)
            return None
        if op in ("==", "!="):
            if rhs in ("True", "False"):
                eq = (val is True) == (rhs == "True")
            else:
                a, b = _num(val), _num(rhs)
                eq = (a == b) if a is not None and b is not None else (str(val) == rhs)
            return eq if op == "==" else not eq
        a, b = _num(val), _num(rhs)
        if a is None or b is None:
            self.unknown.append(name)
            return None
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]


def evaluate_expr(text, f):
    """(value, [unknown names / facts]) for one reading."""
    p = _Parser(text, f)
    return p.parse(), p.unknown


# --------------------------------------------------------------------------- rows
def row_topics(m):
    if m["field"] == "NONE":
        return set()
    return {FIELD_TOPIC[x] for x in m["field"].split(";") if FIELD_TOPIC.get(x)}


def evaluate_row(m, f, checked=None):
    """(outcome, detail) for one map line."""
    if checked is not None and m["field"] != "NONE" and not row_topics(m) <= set(checked):
        return "SKIP", ""
    if m["field"] == "NONE":
        return "NONE", m["map_note"]
    gate, gate_unknown = evaluate_expr(m["gate"] or "always", f)
    if gate is False:
        return "N/A", ""
    readings = [evaluate_expr(t, f) for t in m["test"].split("||")]
    vals = [v for v, _ in readings]
    unknown = [u for _, us in readings for u in us] + (gate_unknown if gate is None else [])
    if all(v is True for v in vals):
        result = "PASS"
    elif all(v is False for v in vals) and gate is True:
        result = "FAIL"
    else:
        result = "OPEN"
    ambiguous = result == "OPEN" and len(vals) > 1 and None not in vals
    detail = ("ambiguous: " + (m["map_note"] or "the readings disagree")) if ambiguous else \
        (m["open_fact"] or "; ".join(dict.fromkeys(unknown)))
    if m["outcome_if_fail"] == "NOTE" and result in ("FAIL", "OPEN"):
        return "NOTE", "cure is an inspection (not checked)"
    # Decision 1: the row hinges on a blank Coverage A or County -- either the
    # whole unknown is that field, or the gate (which decides whether the row
    # applies at all) is unknown only because of it.
    blank = set(gate_unknown) if gate is None and gate_unknown and set(gate_unknown) <= BLANK_IS_NOTE \
        else (set(unknown) if unknown and set(unknown) <= BLANK_IS_NOTE else None)
    if result == "OPEN" and not ambiguous and blank:
        return "NOTE", "blank " + " / ".join(sorted({"Coverage A" if u == "dwelling_amount" else "County"
                                                     for u in blank})) + "; confirm"
    if result == "FAIL" and m["outcome_if_fail"] == "UNKNOWN":
        return "OPEN", "the row's effect is UNKNOWN"
    return result, detail


def _page(r):
    try:
        return str(int(float(r["PDF page"])))
    except (TypeError, ValueError):
        return "?"


def citation(r):
    """The citation code attaches for a row: id + page + the workbook quote."""
    return f"{PILOT_CARRIERS[r['Carrier']]}: [{r['Rule ID']}] p.{_page(r)}: \"{r['Verbatim quote from guide']}\""


def evaluate_carrier(canon, pd, checked=None):
    """{row_id: (outcome, detail)} for one pilot carrier's deciding rows."""
    rules, fmap = load_rules(), load_map()
    wb = CANON_TO_WB[canon]
    f = facts(pd)
    return {rid: evaluate_row(m, f, checked) for rid, m in fmap.items()
            if rules[rid]["Carrier"] == wb and rules[rid]["Tool handling"] in DECIDING}


def also_confirm(canon, outcomes):
    """The carrier's never-a-hold notes: NONE rows and CONDITION_STANDARD rows
    grouped by topic, then each NOTE row with its reason."""
    rules = load_rules()
    wb = CANON_TO_WB[canon]
    groups = {}
    for rid, (o, _) in outcomes.items():
        if o == "NONE":
            groups.setdefault(rules[rid]["Topic"], []).append(rid)
    for r in rules.values():
        if r["Carrier"] == wb and r["Tool handling"] == "CONDITION_STANDARD":
            groups.setdefault(r["Topic"], []).append(r["Rule ID"])
    notes = [f"[{rid}] {rules[rid]['Plain rule']} ({d})" for rid, (o, d) in outcomes.items() if o == "NOTE"]
    if groups:
        notes.append("Also confirm (not asked by the form; never a hold): " + "; ".join(
            f"{t}: {', '.join(ids)}" for t, ids in sorted(groups.items())) + ".")
    return notes


def code_record(canon, outcomes):
    """The record when code decides alone. Returns (record, decided):
    decided is False when OPEN rows are left for the model."""
    rules, fmap = load_rules(), load_map()
    fails = {e: [rid for rid, (o, _) in outcomes.items() if o == "FAIL" and fmap[rid]["outcome_if_fail"] == e]
             for e in ("DECLINES", "REFERS_TO_UW", "CONDITION")}
    opens = [rid for rid, (o, _) in outcomes.items() if o == "OPEN"]
    if fails["DECLINES"]:
        status, flaws, cited = "INELIGIBLE", len(fails["DECLINES"]), fails["DECLINES"]
    elif fails["REFERS_TO_UW"]:
        status, flaws, cited = "REFER", 0, fails["REFERS_TO_UW"]
    elif fails["CONDITION"]:
        status, flaws, cited = "REFER", 0, fails["CONDITION"]
    elif opens:
        status, flaws, cited = "INSUFFICIENT_INFORMATION", 0, []
    else:
        status, flaws, cited = "ELIGIBLE", 0, []
    label = {"DECLINES": "declines", "REFERS_TO_UW": "refers to underwriting", "CONDITION": "condition not met"}
    reasons = [f"[{rid}] {label[fmap[rid]['outcome_if_fail']]}: {rules[rid]['Plain rule']}" for rid in cited]
    npass = sum(1 for o, _ in outcomes.values() if o == "PASS")
    if not reasons:
        reasons = [f"Rules table: {npass} rule(s) decided from the form pass; none fails."]
    rec = {"carrier": canon, "status": status, "flaw_count": flaws, "reasons": reasons,
           "citations": [citation(rules[rid]) for rid in cited],
           "missing_info": [f"{outcomes[rid][1]} -- [{rid}] {rules[rid]['Plain rule']}" for rid in opens],
           "notes": "", "rules_table": True, "also_confirm": also_confirm(canon, outcomes)}
    return rec, not (opens and not cited)


# --------------------------------------------------------------------------- the model's part
PILOT_INSTRUCTION = (
    "RULE CHECK: for each carrier below, code has already checked the carrier's rules against PROPERTY "
    "DETAILS. Its results are facts. Judge only the rules listed under \"Not decided by code\": a rule that "
    "needs a fact PROPERTY DETAILS does not give makes the carrier INSUFFICIENT_INFORMATION; a fact that is "
    "given and breaks a rule decides by that rule's effect (DECLINES -> INELIGIBLE, REFERS_TO_UW or "
    "CONDITION -> REFER). Unknown is not a failure. Cite a rule as \"<carrier>: [row id] <rule>\".")


def _cell(v):
    return " ".join(str(v or "").split())


def _row_line(r, extra=""):
    value = " ".join(x for x in (_cell(r["Value"]), _cell(r["Unit"])) if x)
    return " | ".join([f"[{r['Rule ID']}] {_cell(r['Topic'])}", _cell(r["Effect"]), _cell(r["Plain rule"]),
                       value or "-", _cell(r["Applies when"]) or "-", _cell(r["Exceptions / cure"]) or "-"]) + extra


def evidence_text(open_carriers):
    """The user-message section for the separate pilot call: for each
    carrier the code could not decide, the code's results and its OPEN rows."""
    rules = load_rules()
    out = [PILOT_INSTRUCTION, ""]
    for canon, outcomes in open_carriers.items():
        npass = sum(1 for o, _ in outcomes.values() if o == "PASS")
        nna = sum(1 for o, _ in outcomes.values() if o == "N/A")
        out.append(f"--- {canon} (rule check) ---")
        out.append(f"Decided by code: {npass} rule(s) PASS, {nna} do not apply; none fails.")
        out.append("Not decided by code:")
        out += [_row_line(rules[rid], f" | open: {d}") for rid, (o, d) in outcomes.items() if o == "OPEN"]
        out.append("")
    return "\n".join(out)


_ROW_ID = re.compile(r"\b(?:ALL|SAG|CHU|MER|PRO|SWY)-\d{3}\b")


def finish_model_record(rec, canon, outcomes):
    """A model record for a pilot carrier: attach id + page + quote for every
    row id it names, keep its reasons, add the never-a-hold notes, mark it."""
    rules = load_rules()
    wb = CANON_TO_WB[canon]
    text = " ".join((rec.get("reasons") or []) + (rec.get("citations") or []) + (rec.get("missing_info") or []))
    ids = [rid for rid in dict.fromkeys(_ROW_ID.findall(text)) if rid in rules and rules[rid]["Carrier"] == wb]
    rec["citations"] = [citation(rules[rid]) for rid in ids]
    rec["carrier"] = canon
    rec["rules_table"] = True
    rec["also_confirm"] = also_confirm(canon, outcomes)
    _hold_unknown_as_insufficient(rec, outcomes, ids)
    return rec


def _model_can_decide(detail):
    """An OPEN row the pilot call can legitimately fail: its readings disagree
    on known facts, or a known fact breaks it and only the effect is unknown.
    Every other OPEN row is open because the form does not give a fact."""
    return detail.startswith("ambiguous:") or detail == "the row's effect is UNKNOWN"


def _hold_unknown_as_insufficient(rec, outcomes, cited_ids):
    """Round 25 step 4 (2026-10-04). On the same open pool-fence rows -- facts
    the form does not give -- Luna answered REFER in one set of runs and
    ELIGIBLE in the next, with reasons saying the fence was unknown. Code
    knows why each row is open, so it decides these, both ways:
    - REFER / INELIGIBLE stands only when it cites a row the model can decide
      (readings disagree, or a known fact with an UNKNOWN effect);
    - otherwise, while any row is open on a fact the form does not give, the
      carrier is INSUFFICIENT_INFORMATION on those facts -- never ELIGIBLE,
      as code_record already does when it decides alone.
    An INSUFFICIENT_INFORMATION answer is left as the model wrote it."""
    status = rec.get("status")
    if status == "INSUFFICIENT_INFORMATION":
        return
    if status in ("REFER", "INELIGIBLE") and any(
            outcomes.get(rid, ("", ""))[0] == "OPEN" and _model_can_decide(outcomes[rid][1]) for rid in cited_ids):
        return
    rules = load_rules()
    opens = [rid for rid, (o, d) in outcomes.items() if o == "OPEN" and not _model_can_decide(d)]
    if status not in ("REFER", "INELIGIBLE") and not opens:
        return
    rec["notes"] = ((rec.get("notes") or "") + f" Rules table: the pilot answer said {status}, but these rows "
                    "depend on facts the form does not give; code holds the carrier as Insufficient.").strip()
    rec["status"], rec["flaw_count"] = "INSUFFICIENT_INFORMATION", 0
    opens = opens or [rid for rid, (o, _) in outcomes.items() if o == "OPEN"]   # an uncited decidable row
    rec["missing_info"] = [f"{outcomes[rid][1]} -- [{rid}] {rules[rid]['Plain rule']}" for rid in opens]
    rec["citations"] = rec["citations"] or [citation(rules[rid]) for rid in opens]


def is_pilot(carrier):
    return carrier in CANON_TO_WB
