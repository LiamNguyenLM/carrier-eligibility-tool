"""Round 41 B6: over the whole Round 38 fuzz set (3,409 profiles), every rules-table card's confirm items -- how many
quote a rule, and how many quoted rules have a condition the form rules out (must be 0). Zero API.
usage (cwd = repo root): python verification/confirm_quotes_fuzz.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "fuzz"))
import confirm_topics as ct  # noqa: E402
import gen  # noqa: E402
import rules_evaluator as rv  # noqa: E402

SEEDS = [*range(0, 600), *range(1000, 1981), *range(5000, 5779), *range(9000, 9367), *range(12000, 12682)]
on = set(rv.BATCHES) - {"pilot"}
quoted = threshold = 0
bad = []
for seed in SEEDS:
    pd, checked = gen.profile(seed)
    for canon in rv.WB_TO_CANON.values():
        wb = rv.rules_table_wb(canon, on, pd)
        if wb is None:
            continue
        rec = rv.code_record(canon, rv.evaluate_carrier(canon, pd, checked, wb=wb), pd)[0]
        for it in ct.card_items(rec, pd, checked):
            if " — guide: " not in it["text"]:
                continue
            q = it["text"].split(" — guide: ", 1)[1]
            quoted += 1
            threshold += "(only if Coverage A is" in q
            if ct.ruled_out(q, pd):
                bad.append((seed, canon, it["key"], q[:90]))
print(f"{len(SEEDS)} profiles, {quoted} quoted rules, {threshold} with a Coverage A threshold note, "
      f"{len(bad)} ruled out by the form")
for b in bad[:10]:
    print("  ", b)
