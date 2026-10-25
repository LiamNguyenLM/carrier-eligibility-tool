"""Round 42 step 4 (Liam, 2026-10-24): the parity golden file -- today's engine output on the Round 38 fuzz set
(3,409 profiles) and the named profiles, so a port of the engine (Pyodide, TypeScript, a Worker) can be checked
against it before Railway is switched off. Zero API: every rules-table batch is on, as live, and the model is a stub
that raises -- since round 41 B4 no live check calls it.

For each profile: its inputs (property details and checked topics), the "Things to confirm" box, and, in the order
check_eligibility returns them, each carrier's record and card -- what the app renders (first line, Missing, Confirm,
Details, row IDs; the warning line for a carrier that could not be checked).

The check (compare): exact on the carriers and their order, the status, the raw status, flaw_count, the deciding rows
(the row IDs in the reasons), the held fields (missing_info) and the confirm rows; every text compared after collapsing
whitespace. A rules-table change, a deliberate card change or a new year (ages are counted from today) changes the
golden on purpose: rerun export on the native engine, review `compare` old vs new (every difference should be the one
intended), commit the new golden with the change, then rerun the port against it.

usage (cwd = the repo):
  python verification/parity/export_golden.py export [out.json.xz] [--limit N] [--shard i/n]
  python verification/parity/export_golden.py merge <out.json.xz> <shard files...>
  python verification/parity/export_golden.py compare <golden.json.xz> <candidate.json.xz>
  python verification/parity/export_golden.py show <profile id>
  python verification/parity/export_golden.py export-engine <out.json.gz> [--shard i/n]
      (round 43: the same profiles through engine.api as the browser runs it -- only the bundle's data files,
       registered strictly, and rules_data/engine_manifest.json instead of the store; compare it with the golden)
  python verification/parity/export_golden.py inputs <golden.json.xz> <out.json>   (the profiles, for a port's runner)

The whole export takes about 30 minutes as 8 processes at once, then merge:
  for i in 0..7: export part<i>.json.gz --shard <i>/8   (in parallel; OMP_NUM_THREADS=2 each)
  merge verification/parity/golden.json.xz part0.json.gz ... part7.json.gz
A file is xz-compressed when its name ends .xz, else gzip.
"""
import datetime
import gzip
import hashlib
import json
import lzma
import os
import random
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
for p in (ROOT, os.path.join(ROOT, "verification"), os.path.join(ROOT, "verification", "fuzz"),
          os.path.join(ROOT, "rules_data")):
    sys.path.insert(0, p)
GOLDEN = os.path.join(HERE, "golden.json.xz")
SEEDS = [*range(0, 600), *range(1000, 1981), *range(5000, 5779), *range(9000, 9367), *range(12000, 12682)]
ROW = re.compile(r"\b[A-Z][A-Z0-9]{2}-\d{3}\b")
EXACT = ("status", "raw", "flaws", "rows", "held", "confirm_rows")
TEXTS = ("name", "first", "missing", "confirm", "details", "ids", "warning", "reasons", "citations", "notes",
         "also_confirm", "confirm_items")
HTML = ("confirm", "details", "ids")
LISTS = ("rows", "held", "confirm_rows")         # each distinct list stored once

def norm(s):
    return " ".join(str(s).split())


def _norm_obj(o):
    if isinstance(o, str):
        return norm(o)
    if isinstance(o, dict):
        return {k: _norm_obj(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_norm_obj(v) for v in o]
    return o


def named_profiles():
    """(id, property_details, checked_topics) for the named profiles: the audit profiles, LANDLORD / HOME, Liam's
    Harris check, The Hartford's cases a-k (test_hartford.py), the Round 40 base, and the two deep checks' first
    60 profiles each (hartford_deep seed 39, new_guides_deep seed 40)."""
    import hartford_deep
    import new_guides_deep
    import profiles as P
    from test_hartford import OWN, POOL_A, RENT
    from test_held_reasons import HOME, LANDLORD
    from test_natgen_c360_occidental import BASE as R40
    out = [("LIVE", P.LIVE_PROFILE, P.LIVE_CHECKED), ("STANDARD", P.STANDARD_PROFILE, None),
           ("ALT", P.ALT_PROFILE, None), ("COASTAL_PPC4", P.COASTAL_PPC4_PROFILE, None),
           ("LANDLORD", LANDLORD, None), ("HOME", HOME, None), ("HARRIS", P.HARRIS_PROFILE, P.HARRIS_CHECKED)]
    nh = dict(zip="", harris_east_146=None)
    hartford = {
        "a_fenced_pool": dict(OWN, **POOL_A),
        "a_pool_no_boxes": dict(OWN, **dict(POOL_A, pool_fence_4ft=False, pool_gate_locking=False)),
        "b_slide": dict(OWN, **dict(POOL_A, pool_accessories="Slide only")),
        "c_unfenced_in_ground": dict(OWN, swimming_pool="In Ground - Unfenced", pool_accessories="None"),
        "c_unfenced_above_ground": dict(OWN, swimming_pool="Above Ground - Unfenced", pool_accessories="None"),
        "d_llc": dict(OWN, ownership_type="LLC"),
        "d_family_trust": dict(OWN, ownership_type="Trust", trust_type="Family trust"),
        "d_corporate_trust": dict(OWN, ownership_type="Trust", trust_type="Corporate or business trust"),
        "d_estate": dict(OWN, ownership_type="Estate"),
        "e_rpp": RENT,
        "e_rpp_home_elsewhere": dict(RENT, primary_home_carrier="Travelers"),
        "e_rpp_home_blank": dict(RENT, primary_home_carrier=""),
        "e_rpp_5_units": dict(RENT, rental_units_total="5 or more"),
        "e_rpp_short_term": dict(RENT, rental_term="Short-term"),
        "e_rpp_class_10": dict(RENT, ppc="10", fire_station_miles=9.0),
        "e_rpp_fuses": dict(RENT, electrical=["Fuses"]),
        "e_rpp_family_trust": dict(RENT, ownership_type="Trust", trust_type="Family trust"),
        "f_seasonal_primary_hartford": dict(OWN, occupancy_type="Seasonal", primary_home_carrier="The Hartford"),
        "f_seasonal_primary_elsewhere": dict(OWN, occupancy_type="Seasonal", primary_home_carrier="Travelers"),
        "g_dallas_fuses": dict(OWN, county="Dallas", electrical=["Fuses"], **nh),
        "g_dallas_breakers": dict(OWN, county="Dallas", electrical=["Circuit breakers"], **nh),
        "h_flat_roof": dict(OWN, roof_shape="Flat"),
        "i_1_5m": dict(OWN, dwelling_amount=1500000),
        "i_2m": dict(OWN, dwelling_amount=2000000),
        "i_3m": dict(OWN, dwelling_amount=3000000),
        "j_galveston": dict(OWN, county="Galveston", coastal_tier="Tier 1", **nh),
        "j_inland": dict(OWN, county="Travis", coastal_tier="Not Coastal", **nh),
        "k_1_water": dict(OWN, losses_5yr="1", losses_3yr="1", loss_types=["Water"], loss_year=2025),
        "k_1_fire": dict(OWN, losses_5yr="1", losses_3yr="1", loss_types=["Fire"], loss_year=2025),
        "k_1_liability": dict(OWN, losses_5yr="1", losses_3yr="1", loss_types=["Liability"], loss_year=2025),
        "k_class_10_theft": dict(OWN, ppc="10", fire_station_miles=9.0, losses_5yr="1", losses_3yr="1",
                                 loss_types=["Theft"], loss_year=2025),
    }
    out += [(f"HARTFORD_{k}", pd, None) for k, pd in hartford.items()]
    out += [("R40_BASE", R40, None), ("R40_BASE_not_harris", dict(R40, county="Montgomery", **nh), None)]
    rng = random.Random(39)
    out += [(f"HARTFORD_DEEP_{i}", hartford_deep.build(hartford_deep.random_choice(rng)), None) for i in range(60)]
    rng = random.Random(40)
    out += [(f"R40_DEEP_{i}", new_guides_deep.build(new_guides_deep.random_choice(rng)), None) for i in range(60)]
    return out


def all_profiles(limit=None):
    import gen
    named = named_profiles()
    fuzz = [(f"fuzz_{s}", *gen.profile(s)) for s in SEEDS]
    if limit:
        return named[:limit] + fuzz[:limit]
    return named + fuzz



class Table:
    """Distinct values (strings or lists), each stored once; a card holds indices (the same lines and row lists
    recur on every card that asks them)."""

    def __init__(self):
        self.table, self.index = [], {}

    def __call__(self, s):
        key = json.dumps(s, ensure_ascii=False) if isinstance(s, list) else s
        if key not in self.index:
            self.index[key] = len(self.table)
            self.table.append(s)
        return self.index[key]


def canonical(k, v):
    """A field's comparable form: whitespace collapsed; the HTML fields split after each list item."""
    if k in HTML:
        return [x for x in re.split(r"(?<=</li>)", norm(v or "")) if x]
    if k == "confirm_items":
        return [json.dumps(_norm_obj(x), sort_keys=True, ensure_ascii=False) for x in v]
    return [norm(x) for x in v] if isinstance(v, list) else norm(v)


def digest(v):
    """The hash a port computes too: sha1 of the canonical value as compact sorted JSON, first 12 hex digits."""
    return hashlib.sha1(json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                        .encode("utf-8")).hexdigest()[:12]


def card_texts(rec, pd, checked):
    """What the app shows for one carrier (app.py render_carrier / Could Not Be Checked) and the record's texts."""
    import cards
    import display_names
    shown = rec.get("status") in ("ELIGIBLE", "REFER", "INSUFFICIENT_INFORMATION", "INELIGIBLE")
    raw = {"name": display_names.record_name(rec),
           "first": cards.first_line_markdown(rec, pd, checked, label=False) if shown else "",
           "missing": cards.missing_lines(rec.get("missing_info")) if shown else [],
           "confirm": cards.confirm_html(rec, pd, checked) if shown else "",
           "details": cards.details_html(rec, guide=shown) or "",
           "ids": (cards.rule_ids_html(rec) or "") if shown else "",
           "warning": "" if shown else cards.warning_line(rec),
           "reasons": rec.get("reasons") or [], "citations": rec.get("citations") or [],
           "notes": rec.get("notes") or "", "also_confirm": rec.get("also_confirm") or [],
           "confirm_items": rec.get("confirm_items") or []}
    return {k: canonical(k, raw[k]) for k in TEXTS}


def page_texts(c):
    """A card of engine.api's results page (api.card) in card_texts' terms."""
    raw = {"name": c["name"], "first": c["first"], "missing": c["missing"], "confirm": c["confirm_html"],
           "details": c["details_html"], "ids": c["ids_html"], "warning": c["warning"], "reasons": c["reasons"],
           "citations": c["citations"], "notes": c["notes"], "also_confirm": c["also_confirm"],
           "confirm_items": c["confirm_items"]}
    return {k: canonical(k, raw[k]) for k in TEXTS}


def doc_from_pages(pages):
    """A golden document from engine.api results pages ({profile id: page}), to compare with the golden."""
    S, H, L, profiles = Table(), Table(), Table(), {}
    for pid, pg in pages.items():
        full = not pid.startswith("fuzz_")
        cards_ = []
        for c in pg["cards"]:
            out = {"carrier": c["carrier"], "status": c["status"], "raw": c["raw_status"], "flaws": c["flaw_count"],
                   "rows": L(sorted(set(ROW.findall(" ".join(map(str, c["reasons"])))))),
                   "held": L([norm(x) for x in c["missing_info"]]),
                   "confirm_rows": L(sorted({i.get("row") or "" for i in c["confirm_items"]}))}
            for k, v in page_texts(c).items():
                out[k] = ([S(x) for x in v] if isinstance(v, list) else S(v)) if full else H(digest(v))
            out["full"] = full
            cards_.append(out)
        profiles[pid] = {"pd": pg["property_details"], "checked": pg["checked_topics"],
                         "top_box": [[S(norm(t)), a, b] for t, a, b in pg["top_box"]], "cards": cards_}
    return {"meta": {"made": datetime.date.today().isoformat(), "year": datetime.date.today().year,
                     "profiles": len(profiles), "exact": list(EXACT), "texts": list(TEXTS),
                     "note": "from engine.api results pages"},
            "strings": S.table, "hashes": H.table, "lists": L.table, "profiles": profiles}


def export_engine(path, shard=None):
    """The golden's profiles through engine.api as the browser runs it: this process registers ONLY the bundle's
    data files (engine.bundle.data_files(), strictly -- a read of any other file raises) before any engine module
    loads, and the manifest replaces the store. Shards and merges like export."""
    import subprocess
    files = json.loads(subprocess.run(
        [sys.executable, "-c", "import json, engine.bundle as b; print(json.dumps(b.data_files()))"],
        cwd=ROOT, capture_output=True, text=True, check=True).stdout)
    from engine import data
    data.register({p: open(os.path.join(ROOT, p), encoding="utf-8").read() for p in files}, strict=True)
    import engine.api as api
    with open(os.path.join(ROOT, "rules_data", "engine_manifest.json"), encoding="utf-8") as fh:
        api.load(manifest=json.load(fh))
    golden = load(GOLDEN)
    todo = list(golden["profiles"].items())
    if shard:
        i, n = map(int, shard.split("/"))
        todo = todo[i::n]
    write(doc_from_pages({pid: api.check(p["pd"], p["checked"]) for pid, p in todo}), path)


def card(rec, pd, checked, S, H, L, full):
    """One carrier: the exact fields in full (the lists in a table); the texts in full (named profiles) or as
    hashes (the fuzz set)."""
    out = {"carrier": rec.get("carrier"), "status": rec.get("status"), "raw": rec.get("_raw_status"),
           "flaws": rec.get("flaw_count"),
           "rows": L(sorted(set(ROW.findall(" ".join(map(str, rec.get("reasons") or [])))))),
           "held": L([norm(x) for x in rec.get("missing_info") or []]),
           "confirm_rows": L(sorted({i.get("row") or "" for i in rec.get("confirm_items") or []}))}
    for k, v in card_texts(rec, pd, checked).items():
        out[k] = ([S(x) for x in v] if isinstance(v, list) else S(v)) if full else H(digest(v))
    out["full"] = full
    return out


FLAGS = ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH")


def run_check(pd, checked):
    """One check in the live configuration, then everything put back as it was: the batch flags, the model call and
    the usage-log variable (the tests import this module, and later tests in the same process expect the defaults)."""
    os.environ.pop("ELIGIBILITY_DOTENV", None)
    import eligibility_check as ec
    saved = {f: getattr(ec, f) for f in FLAGS}, ec._complete, os.environ.get("ELIGIBILITY_USAGE_LOG")

    def no_model(*a, **k):
        raise RuntimeError("parity export: a check tried to call the model")
    try:
        for f in FLAGS:
            setattr(ec, f, True)
        ec._complete = no_model
        if saved[2] is None:
            os.environ["ELIGIBILITY_USAGE_LOG"] = os.path.join(tempfile.gettempdir(), "parity_export_usage.jsonl")
        return ec.check_eligibility(dict(pd), checked_topics=checked, log_usage=False)
    finally:
        for f, v in saved[0].items():
            setattr(ec, f, v)
        ec._complete = saved[1]
        if saved[2] is None:
            os.environ.pop("ELIGIBILITY_USAGE_LOG", None)


def build(todo):
    """The golden document for a list of (id, property details, checked topics)."""
    import confirm_topics
    S, H, L, profiles = Table(), Table(), Table(), {}
    for n, (pid, pd, checked) in enumerate(todo, 1):
        res = run_check(pd, checked)
        full = not pid.startswith("fuzz_")
        profiles[pid] = {"pd": pd, "checked": checked,
                         "top_box": [[S(norm(t)), a, b] for t, a, b in confirm_topics.top_box(res, pd, checked)],
                         "cards": [card(r, pd, checked, S, H, L, full) for r in res]}
        if n % 250 == 0:
            print(f"{n}/{len(todo)}", flush=True)
    doc = {"meta": {"made": datetime.date.today().isoformat(), "year": datetime.date.today().year,
                    "profiles": len(profiles), "exact": list(EXACT), "texts": list(TEXTS),
                    "note": "full cards: texts index strings; fuzz cards: texts index hashes (digest of the "
                            "canonical text); rows, held, confirm_rows index lists; top_box indexes strings"},
           "strings": S.table, "hashes": H.table, "lists": L.table, "profiles": profiles}
    return doc


def export(path, limit=None, shard=None):
    """shard "i/n": only every n-th profile from the i-th (0-based), to run n processes at once and merge."""
    todo = all_profiles(limit)
    if shard:
        i, n = map(int, shard.split("/"))
        todo = todo[i::n]
    write(build(todo), path)


def merge(path, parts):
    """One golden file from the shards' files: every index re-pointed into one table, in the profiles' own order
    (the same profiles and values as a single export)."""
    docs = [load(p) for p in parts]
    S, H, L, profiles = Table(), Table(), Table(), {}
    src = {pid: d for d in docs for pid in d["profiles"]}
    order = [pid for pid, _, _ in all_profiles()]
    for pid in [p for p in order if p in src] + sorted(set(src) - set(order)):
        d = src[pid]
        p = d["profiles"][pid]

        def s(i, d=d):
            return S(d["strings"][i])
        top_box = [[s(t), a, b] for t, a, b in p["top_box"]]           # interned in build()'s order
        cards = []
        for c in p["cards"]:
            c = dict(c, **{k: L(d["lists"][c[k]]) for k in LISTS})
            for k in TEXTS:
                if c["full"]:
                    c[k] = [s(i) for i in c[k]] if isinstance(c[k], list) else s(c[k])
                else:
                    c[k] = H(d["hashes"][c[k]])
            cards.append(c)
        profiles[pid] = dict(p, top_box=top_box, cards=cards)
    doc = dict(docs[0], strings=S.table, hashes=H.table, lists=L.table, profiles=profiles)
    doc["meta"] = dict(doc["meta"], profiles=len(profiles))
    write(doc, path)


def write(doc, path):
    profiles = doc["profiles"]
    raw = json.dumps(doc, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")
    with open(path, "wb") as fh:
        fh.write(lzma.compress(raw, preset=9) if path.endswith(".xz") else gzip.compress(raw, 9, mtime=0))
    print(f"{len(profiles)} profiles, {sum(len(p['cards']) for p in profiles.values())} cards, "
          f"{len(doc['strings'])} texts, {len(doc['hashes'])} hashes, {len(doc['lists'])} lists -> {path} "
          f"({len(raw) // 1024} KB raw, {os.path.getsize(path) // 1024} KB compressed)")


def load(path):
    if isinstance(path, dict):
        return path
    with (lzma.open if path.endswith(".xz") else gzip.open)(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def compare(a_path, b_path, show=20, partial=False):
    """Every difference between two golden files (the native one and a port's; a path or a loaded document). A text
    stored in full on one side and as a hash on the other is compared by hash. partial: only the profiles in b."""
    a, b = load(a_path), load(b_path)
    if a["meta"]["year"] != b["meta"]["year"]:
        print(f"WARNING: made in {a['meta']['year']} vs {b['meta']['year']} -- ages differ; re-export both the same year")

    def value(doc, c, k):
        v = c[k]
        if c.get("full"):
            v = [doc["strings"][i] for i in v] if isinstance(v, list) else doc["strings"][v]
        return v

    def same(x, y, k):
        vx, vy = value(a, x, k), value(b, y, k)
        if x.get("full") and y.get("full"):
            return vx == vy, vx, vy
        hx = vx if not x.get("full") else digest(vx)
        hy = vy if not y.get("full") else digest(vy)
        hx = a["hashes"][hx] if not x.get("full") else hx
        hy = b["hashes"][hy] if not y.get("full") else hy
        return hx == hy, hx, hy
    diffs = []
    for pid in sorted(set(b["profiles"]) if partial else set(a["profiles"]) | set(b["profiles"])):
        pa, pb = a["profiles"].get(pid), b["profiles"].get(pid)
        if pa is None or pb is None:
            diffs.append((pid, "-", "profile", pa is not None, pb is not None))
            continue
        ia = json.loads(json.dumps([pa["pd"], pa["checked"]], default=str))
        ib = json.loads(json.dumps([pb["pd"], pb["checked"]], default=str))
        if ia != ib:
            diffs.append((pid, "-", "inputs", ia, ib))
        ta = [[a["strings"][t], x, y] for t, x, y in pa["top_box"]]
        tb = [[b["strings"][t], x, y] for t, x, y in pb["top_box"]]
        if ta != tb:
            diffs.append((pid, "-", "top_box", ta, tb))
        ca, cb = [c["carrier"] for c in pa["cards"]], [c["carrier"] for c in pb["cards"]]
        if ca != cb:
            diffs.append((pid, "-", "carriers", ca, cb))
        for x, y in zip(pa["cards"], pb["cards"]):
            if x["carrier"] != y["carrier"]:
                continue
            for k in EXACT:
                vx, vy = x.get(k), y.get(k)
                if k in LISTS:
                    vx, vy = a["lists"][vx], b["lists"][vy]
                if vx != vy:
                    diffs.append((pid, x["carrier"], k, vx, vy))
            for k in TEXTS:
                ok, vx, vy = same(x, y, k)
                if not ok:
                    diffs.append((pid, x["carrier"], k, vx, vy))
    n_cards = sum(len(p["cards"]) for p in (b if partial else a)["profiles"].values())
    print(f"{len((b if partial else a)['profiles'])} profiles, {n_cards} cards: {len(diffs)} difference(s)")
    for d in diffs[:show]:
        print("  " + json.dumps(d, ensure_ascii=False, default=str)[:600])
    if any(not c.get("full") for p in a["profiles"].values() for c in p["cards"]) and diffs:
        print("a fuzz card's texts are hashes: `show <profile id>` prints the native card in full")
    return diffs


def inputs(golden, out):
    """Every profile's inputs, in the golden's order, as [{"id", "pd", "checked"}] -- what a port's runner reads."""
    doc = load(golden)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump([{"id": pid, "pd": p["pd"], "checked": p["checked"]} for pid, p in doc["profiles"].items()], fh)
    print(f"{len(doc['profiles'])} profiles -> {out}")


def show(pid):
    """The native engine's cards for one profile, every text in full (to read a hashed difference)."""
    prof = {p: (pd, ch) for p, pd, ch in all_profiles()}[pid]
    for rec in run_check(*prof):
        print(json.dumps({"carrier": rec.get("carrier"), "status": rec.get("status"),
                          **card_texts(rec, *prof)}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "export"
    argv, opts = sys.argv[2:], {}
    for flag in ("--limit", "--shard"):
        if flag in argv:
            k = argv.index(flag)
            opts[flag] = argv[k + 1]
            del argv[k:k + 2]
    if cmd == "export":
        export(argv[0] if argv else GOLDEN, int(opts.get("--limit", 0)) or None, opts.get("--shard"))
    elif cmd == "merge":
        merge(argv[0], argv[1:])
    elif cmd == "compare":
        sys.exit(1 if compare(sys.argv[2], sys.argv[3]) else 0)
    elif cmd == "show":
        show(sys.argv[2])
    elif cmd == "inputs":
        inputs(argv[0], argv[1])
    elif cmd == "export-engine":
        export_engine(argv[0], opts.get("--shard"))
    else:
        sys.exit(__doc__)
