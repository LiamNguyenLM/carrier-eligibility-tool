"""Round 47 (Liam and Jonathan, 2026-11): every program's answer to a cross-carrier question, from the checker itself.

"Which carriers take an above-ground pool with no fence?" must name every program CFIG writes, each with the label the
eligibility check would give. Top-k search left most programs out. So, at build time, for every topic and form value
in rules_data/chat/sweep_topics.json and every scope (HO3 owner-occupied, DP3 rental, HO6 condo), this runs the
checker (engine.api.check, the browser's code) on a neutral profile -- the form's defaults with the scope's and the
value's answers, EVERY topic ticked (a full check: a rule that also needs the year built, such as Allied Trust's
galvanized decline, is skipped by a partial check) -- and on the same profile without the value, and writes

  rules_data/chat/outcomes.json    {scopes: {HO3: {programs: [{program, name}]}}, sweeps: {"pool/above_unfenced":
                                    {HO3: {program: {label, status, rows, why}}}}}

Label (what the chat shows; the model explains it, never decides it):
  Not eligible / Refer   the checker says so and the value is why (not something the neutral profile already lacked)
  Confirm                the checker needs a fact for this value (a fence height), or passes it with a new thing to
                         confirm (the loss types for "2 losses in 3 years")
  Eligible               the checker passes it and the program has a rule on it
  Coverage limited       passes, but the program's only rules on it limit coverage
  Guide silent           passes, and the program's rules table has no rule on it (or says the guide is silent)
  Closed                 closed to new business
  Not checked            the checker can't check it (a guide on file that isn't usable: Liberty Mutual HO6)
  Not eligible           also: the checker does not offer the program for this occupancy (a vacant home is routed
                         to the dwelling programs; the HO3 programs are not checked at all)
A value with no form answer (trampolines, wood stoves, acreage) is labelled from the program's matching rows: the
strictest effect (DECLINES, REFERS_TO_UW, CONDITION, COVERAGE_ONLY, ALLOWS), else Guide silent.

Committed like the chat corpus (the Cloudflare build has no Python); verification/test_chat_outcomes.py fails when it
is stale.  usage (cwd = repo root):  python cloudflare/scripts/export_chat_outcomes.py [--out DIR]
"""
import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
RULES = os.path.join(ROOT, "rules_data")
CHAT = os.path.join(RULES, "chat")

LABELS = ("Eligible", "Confirm", "Refer", "Not eligible", "Coverage limited", "Guide silent", "Closed", "Not checked")
EFFECT_LABEL = {"DECLINES": "Not eligible", "REFERS_TO_UW": "Refer", "CONDITION": "Confirm",
                "COVERAGE_ONLY": "Coverage limited", "ALLOWS": "Eligible"}
STRICT = ["Not eligible", "Refer", "Confirm", "Coverage limited", "Eligible"]
ROW_ID = re.compile(r"\b([A-Z]{2,4}-\d{3})\b")
MAX_ROWS = 4


def _csv(path):
    lines = [l for l in open(path, encoding="utf-8-sig") if not l.startswith("#")]
    return list(csv.DictReader(io.StringIO("".join(lines))))


def load_rows():
    """{program: [row]} from the rules tables, with each row's field-map fields."""
    programs = json.load(open(os.path.join(CHAT, "programs.json"), encoding="utf-8"))
    by_wb = {wb: p["program"] for p in programs for wb in p["workbook_names"]}
    fields = {}
    for f in sorted(os.listdir(RULES)):
        if f.endswith("field_map.csv"):
            for r in _csv(os.path.join(RULES, f)):
                if r.get("row_id"):
                    fields.setdefault(r["row_id"], set()).update(x for x in (r.get("field") or "").split(";") if x)
    rows = {}
    for f in sorted(os.listdir(RULES)):
        if f.startswith("carrier_rules_") and f.endswith(".csv"):
            for r in _csv(os.path.join(RULES, f)):
                prog = by_wb.get(r["Carrier"])
                if prog:
                    rows.setdefault(prog, []).append({
                        "id": r["Rule ID"], "topic": r["Topic"], "state": r["State"], "effect": r["Effect"],
                        "text": " ".join([r["Plain rule"], r["Verbatim quote from guide"], r["Applies when"]]),
                        "plain": r["Plain rule"], "cure": r["Exceptions / cure"],
                        "fields": fields.get(r["Rule ID"], set())})
    return programs, rows


# Round 47 step 3 (the graded rerun): how a row is read for a label.
#   NEG      "attractive nuisances (except trampolines) are ineligible" is no trampoline decline (SAG-064)
#   GENERIC  a damaged / dilapidated structure rule names trampolines among many things (ORI-076): not a trampoline rule
#   COND     a decline that hangs on a condition is a Confirm: "accepted only with safety netting" (HAR-061), "cannot
#            be the primary heat source" (LIB-025), "without a safety net" (MER-050)
# A row that names the value in its plain rule outranks one that only lists it in its quote or context (MER-051's
# catch-all "any attractive nuisance" vs MER-050's trampoline row).
NEG = re.compile(r"\b(except|other than|excluding|not including|but not)\b[^.;]{0,40}$", re.I)
GENERIC = re.compile(r"\b(damaged|deteriorat|dilapidat|dangerous|disrepair|poor condition|unsafe|unrepaired)", re.I)
COND = re.compile(r"\b(only (with|if|when|in)|without|unless|primary|sole|must (be|have)|if|when|under \d+|over \d+|more than|"
                  r"less than|at least|within|exceed|in protection class|protection class (9|10)|in pc ?\d+|tenant|"
                  r"outbuilding|garage|not professionally|not factory|not installed|only (heat )?source|only heat|as the only|"
                  r"rental|held for rent|for rent)\b", re.I)
# ... but "declined even if not the primary source of heat" (TWI-040) hangs on nothing
UNCOND = re.compile(r"\b(even if|even when|regardless|in any case)\b", re.I)


def matching_rows(prog_rows, codes, pattern, pd_fields):
    """A program's rows on this topic and value: in the topic's codes and about this value (the pattern, not in an
    "except ..."), or mapped to a field the value changes. Each row is marked: "about" (its text is about this value)
    and "named" (its plain rule names it)."""
    rx = re.compile(pattern, re.I) if pattern else None
    out = []
    for r in prog_rows:
        mapped = bool(r["fields"] & pd_fields)
        hit = rx.search(r["text"]) if rx else None
        plain_hit = rx.search(r["plain"]) if rx else None
        negated = bool(plain_hit and NEG.search(r["plain"][:plain_hit.start()]))
        generic = r["effect"] in ("DECLINES", "REFERS_TO_UW") and GENERIC.search(r["plain"])   # ORI-114 (coverage) stays
        about = bool(hit) and not negated and not generic
        if not (mapped or (r["topic"] in codes and about)):
            continue
        out.append(dict(r, about=about, named=bool(plain_hit) and about))
    return out


def row_label(r):
    """One rule row's label: a decline that hangs on a condition, or that the guide lets a cure lift (its Exceptions /
    cure column: MER-043 "unless professionally installed or approved"), is a Confirm."""
    if r["effect"] == "DECLINES" and not UNCOND.search(r["plain"]) and (COND.search(r["plain"]) or r.get("cure", "").strip()):
        return "Confirm"
    return EFFECT_LABEL[r["effect"]]


def rows_label(rows):
    """The strictest label among the program's rules about this value (those naming it in their rule first), else
    Guide silent."""
    about = [r for r in rows if r.get("about", True) and r["state"] in ("RULE", "NO_RESTRICTION") and r["effect"] in EFFECT_LABEL]
    named = [r for r in about if r.get("named")]
    found = {row_label(r) for r in (named or about)}
    for lab in STRICT:
        if lab in found:
            return lab
    return "Guide silent"


def evidence(rows, extra_ids, label):
    """Up to MAX_ROWS row ids: the checker's own deciding rows first, then the program's rows on it (strictest first;
    a silent row when that is all there is)."""
    order = {lab: i for i, lab in enumerate(STRICT)}
    ranked = sorted(rows, key=lambda r: (r["state"] not in ("RULE", "NO_RESTRICTION"),
                                         order.get(EFFECT_LABEL.get(r["effect"], ""), 9)))
    ids = []
    for i in list(extra_ids) + [r["id"] for r in ranked]:
        if i not in ids:
            ids.append(i)
    return ids[:MAX_ROWS]


def checker_label(scen, base, rows, closed):
    """The label from the checker's card for the value (scen) and without it (base)."""
    if closed:
        return "Closed", []
    if scen is None:
        return "Not eligible", []          # not offered for this occupancy: the checker routed the home elsewhere
    s, b = scen["status"], (base or {}).get("status")
    new_reasons = [r for r in scen["reasons"] if r not in (base or {}).get("reasons", [])]
    new_missing = [m for m in scen["missing_info"] if m not in (base or {}).get("missing_info", [])]
    # the card's "things to confirm" the value adds (loss types for "2 losses"): eligible only if they check out
    new_confirm = [c for c in scen.get("also_confirm", []) if c not in (base or {}).get("also_confirm", [])]
    why = new_reasons + new_missing + new_confirm
    ids = [i for t in why for i in ROW_ID.findall(t)]
    if s not in ("ELIGIBLE", "REFER", "INSUFFICIENT_INFORMATION", "INELIGIBLE"):
        return "Not checked", ids
    if s == "INELIGIBLE" and (b != "INELIGIBLE" or new_reasons):
        return "Not eligible", ids
    if s == "REFER" and (b not in ("REFER", "INELIGIBLE") or new_reasons):
        return "Refer", ids
    if (s == "INSUFFICIENT_INFORMATION" and new_missing) or new_confirm:
        return "Confirm", ids
    lab = rows_label(rows)
    return ("Eligible" if lab in ("Not eligible", "Refer", "Confirm") else lab), ids


class Checker:
    """engine.api.check on form answers, cached (a base is shared by many values)."""

    def __init__(self):
        from engine import api, form, topics
        self.api, self.form, self.topics = api, form, topics
        spec = form.form_spec()
        self.defaults = {f["key"]: f.get("default") for f in spec["fields"]}
        self.breeds = next(f for f in spec["fields"] if f["key"] == "dog_breeds")["choices"]
        self.cache = {}

    def run(self, answers, topic):
        key = json.dumps([answers, topic], sort_keys=True)
        if key not in self.cache:
            values = dict(self.defaults)
            values.update(answers)
            values["chk"] = {t: True for t in self.topics.TOPIC_KEYS}      # a full check (see the module doc)
            req = self.form.form_request(values)
            if not req["ok"]:
                raise ValueError(f"{answers}: {req['error']}")
            page = self.api.check(req["property_details"], req["checked_topics"])
            cards = {c["carrier"]: {"status": c["status"], "name": c["name"], "reasons": c["reasons"],
                                    "missing_info": c["missing_info"], "notes": c["notes"] or "",
                                    "also_confirm": c["also_confirm"]} for c in page["cards"]}
            self.cache[key] = (req["property_details"], cards)
        return self.cache[key]


def values_of(topic, checker):
    """The topic's values: listed, numeric (one per number) or the form's dog breeds."""
    if "values" in topic:
        return topic["values"]
    if topic.get("numeric"):
        n = topic["numeric"]
        out = []
        for k in range(n["min"], n["max"] + 1):
            if n["field"] == "losses":
                v = "3 or more" if k >= 3 else str(k)
                form = {"losses_5yr": v, "losses_3yr": v}
            else:
                form = {n["field"]: k}
            out.append({"id": str(k), "text": n["text"].replace("{n}", str(k)), "rows": topic["rows"], "form": form,
                        "base": {} if n["field"] == "losses" else {n["field"]: n["base"]}})
        return out
    if topic.get("breeds"):
        out = [{"id": "any", "text": "a dog (breed not on any list)", "rows": topic["rows"],
                "form": {"dogs": True, "dog_breeds": []}}]
        for b in checker.breeds:
            out.append({"id": b, "text": f"a {b}", "rows": topic["rows"] + "|" + re.escape(b.split(" (")[0]),
                        "form": {"dogs": True, "dog_breeds": [b]}, "base": {"dogs": True, "dog_breeds": []}})
        return out
    raise ValueError(f"topic {topic['id']} has no values")


# The checker as it runs live: the rules-table switches and the placement panel at their defaults (ON), never a test
# suite's OFF (verification/conftest.py), and no model (the live configuration decides every rules-table program in
# code; a guide-only program would need a model and is labelled from its rows).
LIVE_SWITCHES = ("ELIGIBILITY_RULES_PILOT", "ELIGIBILITY_RULES_SAGE_BATCH", "ELIGIBILITY_RULES_HO3_BATCH",
                 "ELIGIBILITY_RULES_DP_BATCH", "ELIGIBILITY_PLACEMENT")


def export(out_dir):
    for k in LIVE_SWITCHES:
        os.environ.pop(k, None)
    spec = json.load(open(os.path.join(CHAT, "sweep_topics.json"), encoding="utf-8"))
    programs, rows = load_rows()
    closed = {p["program"] for p in programs if p["closed"]}
    # ids a card's text names that are rows (a form number such as "PC-327" is not)
    known = {r["id"] for rs in rows.values() for r in rs} | {r["Rule ID"] for r in _csv(os.path.join(RULES, "cfig_knowledge.csv"))}
    checker = Checker()
    scopes = {}
    for sid, sc in spec["scopes"].items():
        _, cards = checker.run(sc["form"], None)
        scopes[sid] = {"label": sc["label"], "programs": [{"program": c, "name": cards[c]["name"]} for c in cards]}
    sweeps = {}
    for topic in spec["topics"]:
        for value in values_of(topic, checker):
            key = f"{topic['id']}/{value['id']}"
            sweeps[key] = {}
            for sid in ([topic["scope"]] if topic.get("scope") else spec["scopes"]):
                sc = spec["scopes"][sid]
                per = {}
                form = value.get("form")
                if form:
                    pd, scen = checker.run({**sc["form"], **value.get("base", {}), **form}, topic.get("check"))
                    bpd, base = checker.run({**sc["form"], **value.get("base", {})}, topic.get("check"))
                    changed = {k for k in set(pd) | set(bpd) if pd.get(k) != bpd.get(k)}
                progs = list(scopes[sid]["programs"])
                if form:          # a program the value routes in (a vacant home -> the dwelling programs)
                    seen = {p["program"] for p in progs}
                    progs += [{"program": c, "name": v["name"]} for c, v in scen.items() if c not in seen]
                for p in progs:
                    prog = p["program"]
                    mrows = matching_rows(rows.get(prog, []), topic["codes"], value.get("rows"),
                                          changed if form else set())
                    mine = {r["id"] for r in mrows}
                    if form:
                        card = scen.get(prog)
                        label, ids = checker_label(card, base.get(prog), mrows, prog in closed)
                        status = card["status"] if card else "NOT_OFFERED"
                        ids += ROW_ID.findall((card or {}).get("notes", ""))   # its coverage notes (ACV over 15 years)
                    else:
                        label, ids, status = ("Closed" if prog in closed else rows_label(mrows)), [], ""
                    # rows the card names that are about this (OCC-037, a rental row in Occidental's pool notes, is not)
                    ids = [i for i in ids if i in known and (i in mine or i.startswith("CFG-"))]
                    per[prog] = {"label": label, "status": status, "rows": evidence(mrows, ids, label), "name": p["name"]}
                sweeps[key][sid] = per
    src = hashlib.sha256()
    for f in ["chat/sweep_topics.json", "chat/programs.json"] + sorted(
            f for f in os.listdir(RULES) if f.startswith("carrier_rules_") or f.endswith("field_map.csv")):
        src.update(f.encode())
        # line endings normalised: a fresh Windows checkout writes CRLF (the step-1 fast tier's shard did), an edit LF
        src.update(open(os.path.join(RULES, f), "rb").read().replace(b"\r\n", b"\n"))
    data = {"format": 1, "inputs_sha": src.hexdigest()[:16], "labels": list(LABELS), "scopes": scopes, "sweeps": sweeps}
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "outcomes.json")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=0, sort_keys=True)
        fh.write("\n")
    return path, data


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=CHAT)
    a = ap.parse_args()
    path, data = export(a.out)
    n = sum(len(s) for s in data["sweeps"].values())
    print(f"chat outcomes: wrote {path} ({os.path.getsize(path) // 1024} KB); {len(data['sweeps'])} values, {n} value x scope")
