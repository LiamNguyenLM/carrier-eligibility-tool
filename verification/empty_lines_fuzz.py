"""Round 41 B7: over Round 38 fuzz profiles, the full pipeline (fake Eligible model, zero API): every card's lines
checked by the page invariant (checks._empty_items), and how many items the old rendering would have shown as an empty
or punctuation-only bullet (a non-blank raw line that agent_text empties). usage: python verification/empty_lines_fuzz.py <n>"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "fuzz"))
import cards  # noqa: E402
import checks  # noqa: E402
import gen  # noqa: E402

checks.configure()
N = int(sys.argv[1])
SEEDS = [*range(0, 600), *range(1000, 1981), *range(5000, 5779), *range(9000, 9367), *range(12000, 12682)]
step = max(1, len(SEEDS) // N)
cards_seen = fails = old_empty = 0
examples = []
for seed in SEEDS[::step][:N]:
    pd, checked = gen.profile(seed)
    for r in checks.run(pd, checked):
        cards_seen += 1
        f = checks._empty_items(r, pd, checked, r.get("carrier"))
        fails += len(f)
        for field in ("missing_info", "reasons", "citations"):
            for x in r.get(field) or []:
                if isinstance(x, str) and x.strip() and not cards.says_something(cards.agent_text(x)):
                    old_empty += 1
                    if len(examples) < 5:
                        examples.append((seed, r.get("carrier"), field, x[:100]))
print(f"{min(N, len(SEEDS))} profiles, {cards_seen} cards: {fails} empty lines now; {old_empty} raw lines the old "
      f"rendering would have shown empty")
for e in examples:
    print("  ", e)
