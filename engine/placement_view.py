"""Round 43 step 1: the placement panel as markdown (moved from placement.py, which imports it from here). The
Worker computes the panel from the placement tables (they never reach the browser); the browser renders it with
this, as the app does."""
from . import cards
from . import display_names


def panel_markdown(p):
    """The panel as one markdown block (the footer is shown separately, small)."""
    lines = [f"#### {p['title']}"]
    if p.get("basis"):
        lines.append(f"*{p['basis']}*")
        lines.append("")
    for i, pick in enumerate(p["picks"], 1):
        # round 36 step 5: the programs by their display names; round 37 step 2: the name once -- a market
        # whose label one of its programs' names starts with (or the other way round) shows only the names
        names = [display_names.display_name(prog) for prog in pick["programs"]]
        bases = [n.split(" (")[0] for n in names]
        if names and all(b.startswith(pick["market"]) or pick["market"].startswith(b) for b in bases):
            lines.append(f"{i}. **{', '.join(names)}**")
        else:
            lines.append(f"{i}. **{pick['market']}** — {', '.join(names)}")
        for extra in (pick["held"], pick["reason"], pick["fit"]):
            if extra:
                lines.append(f"    - {cards.agent_text(extra)}")
    if p["usual"]:
        lines.append("")
        lines.append(p["usual"])
    return "\n".join(lines)
