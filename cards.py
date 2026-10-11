"""What one carrier card says (Liam, 2026-10-05, decision C: cards must be
much more compact). Pure functions, so the layout is testable without a
Streamlit session; app.py only renders what these return.

A card is:
  first line   the status in bold, then the verdict in one sentence -- the
               first reason (for a code-decided verdict, the rule's reason with
               the guide's quote), or, for ELIGIBLE, "No issue on: <the
               checked facts>"
  Missing      the open items, as a short list (INSUFFICIENT / REFER)
  Details      everything else -- the other reason, citations, notes, the
               rules table's "Also confirm" -- collapsed under one <details>
               toggle (cards already sit in an expander, and expanders
               cannot nest)
"""
import html
import re
from datetime import date

import intake_fields

STATUS_LABEL = {
    "ELIGIBLE": "Eligible",
    "INELIGIBLE": "Not eligible",
    "REFER": "Refer to underwriting",
    "INSUFFICIENT_INFORMATION": "Insufficient information",
}


# Statuses whose card shows missing_info as its own "Missing:" list; any other
# row (GUIDE_UNAVAILABLE, NOT_EVALUATED, an unrecognised verdict) keeps it
# under Details.
MODEL_LABELLED = tuple(STATUS_LABEL)


# Round 37 step 2 (Liam, 2026-10-10): what an agent reads carries no row IDs (they are on the card's collapsed
# "Rule IDs" line), no program / file names (display names instead) and none of the engine's own words.
_ROW = r"[A-Z]{3}-\d{3}"
_RULES_TABLE_LINE = re.compile(r"Rules table: (\d+) rule\(s\) decided from the form pass; none fails\.")
_LABELLED_ROW = re.compile(rf"\[{_ROW}\]\s*(declines|refers to underwriting|condition not met):\s*")
_ITEM_ROW = re.compile(rf"\s+--\s+\[{_ROW}\]\s*")
_ANY_ROW = re.compile(rf"\s*\[{_ROW}\]|\s*\(\b{_ROW}\b\)|\b{_ROW}\b,?\s*")


def agent_text(text):
    """One line as an agent should read it."""
    import display_names
    s = str(text or "")
    s = _RULES_TABLE_LINE.sub(lambda m: f"{m.group(1)} of this guide's rules were checked against the form; "
                                         "none rules it out.", s)
    s = _LABELLED_ROW.sub(lambda m: "Condition not met: " if m.group(1) == "condition not met" else "", s)
    s = _ITEM_ROW.sub(": ", s)
    s = _ANY_ROW.sub(lambda m: " " if m.group(0).startswith(" ") and not m.group(0).strip().startswith("[") else "", s)
    for program in sorted(display_names.DISPLAY, key=len, reverse=True):
        if program in s:
            s = s.replace(program, display_names.DISPLAY[program])
    s = re.sub(r"\s*\(\s*(rows?|see|rules?)?[\s,;]*\)", "", s)        # a parenthesis that held only row IDs
    return re.sub(r"\s{2,}", " ", s).replace(" .", ".").replace(" ,", ",").strip()


def rule_ids(rec):
    """Every row ID the card rests on or lists to confirm, for the collapsed "Rule IDs" line."""
    ids = set()
    for field in ("reasons", "citations", "missing_info", "also_confirm"):
        for x in rec.get(field) or []:
            ids.update(re.findall(rf"\b{_ROW}\b", str(x)))
    ids.update(re.findall(rf"\b{_ROW}\b", str(rec.get("notes") or "")))
    ids.update(x.get("row") for x in rec.get("confirm_items") or [] if x.get("row"))
    return sorted(ids)


def rule_ids_html(rec):
    """Round 37 steps 1-2: the row IDs, collapsed -- for us, not the agent. "" when there are none."""
    ids = rule_ids(rec)
    return f"<details><summary>Rule IDs</summary><small>{', '.join(ids)}</small></details>" if ids else ""


def warning_line(rec):
    """A Could Not Be Checked row's one line: the carrier (its display name, round 36 step 5) and its reason."""
    import display_names
    reasons = [x for x in (rec.get("reasons") or []) if isinstance(x, str) and x.strip()]
    return f"**{display_names.display_name(rec.get('carrier', ''))}** — " + (
        agent_text(reasons[0]) if reasons else "could not be checked.")


def _on(topic, checked):
    return checked is None or topic in checked


def checked_facts(property_details, checked=None):
    """The checked facts in a short phrase each, in form order; an unchecked
    topic (checked is a list) is left out. checked=None means everything."""
    pd = property_details
    out = []
    if _on("ppc", checked) and pd.get("ppc") not in (None, "", "N/A"):
        out.append(f"PPC {pd['ppc']}")
    if _on("home_age", checked) and pd.get("year_built"):
        out.append(f"age {date.today().year - int(pd['year_built'])}")
    if _on("roof_age", checked) and pd.get("roof_age") not in (None, ""):
        out.append(f"roof {pd['roof_age']} yrs")
    if _on("roof_type", checked) and pd.get("roof_type"):
        out.append(pd["roof_type"])
    if _on("roof_shape", checked) and pd.get("roof_shape"):
        out.append(f"{pd['roof_shape']} roof")
    if _on("construction", checked) and pd.get("construction_type"):
        out.append(pd["construction_type"])
    if _on("plumbing", checked) and pd.get("plumbing_type"):
        out.append(pd["plumbing_type"])
    if _on("pool", checked) and pd.get("swimming_pool"):
        out.append("no pool" if pd["swimming_pool"] == "No Pool" else pd["swimming_pool"].lower())
    if _on("dogs", checked) and pd.get("has_dogs"):
        out.append("no dogs" if pd["has_dogs"] != "Yes" else
                   ("aggressive breed" if intake_fields.aggressive_breed_answer(pd) == "Yes" else "dogs"))
    if _on("solar", checked) and pd.get("solar_panels"):
        out.append("solar panels" if pd["solar_panels"] == "Yes" else "no solar panels")
    if _on("coastal", checked) and pd.get("coastal_tier"):
        out.append(pd["coastal_tier"])
    if _on("county", checked) and pd.get("county"):
        out.append(f"{pd['county']} County")
    if _on("dwelling_amount", checked) and pd.get("dwelling_amount"):
        try:
            out.append(f"Coverage A ${int(pd['dwelling_amount']):,}")
        except (TypeError, ValueError):
            pass
    return out


def verdict_line(rec, property_details, checked=None):
    """The card's first line, without the status label."""
    if rec.get("status") == "ELIGIBLE":
        facts = checked_facts(property_details, checked)
        return "No issue on: " + ", ".join(facts) if facts else "No issue found."
    reasons = rec.get("reasons") or []
    return agent_text(reasons[0]) if reasons else STATUS_LABEL.get(rec.get("status"), rec.get("status") or "")


def first_line_markdown(rec, property_details, checked=None):
    label = STATUS_LABEL.get(rec.get("status"), rec.get("status") or "")
    return f"**{label}** — {verdict_line(rec, property_details, checked)}"


def details_items(rec, guide=False):
    """(heading, [items]) groups for the Details toggle, empty groups dropped.
    ELIGIBLE keeps every reason here (its first line is the checked facts);
    any other status keeps the reasons after the first. guide=True (round 36 step 5, the verdict cards) adds
    the guide's date and file."""
    def clean(items):
        # Never an empty bullet (round 26 step 7: Could Not Be Checked showed one).
        return [x for x in items if isinstance(x, str) and x.strip()]

    reasons = clean(rec.get("reasons") or [])
    rest = reasons if rec.get("status") == "ELIGIBLE" else reasons[1:]
    groups = [("Analysis", rest), ("Citations", clean(rec.get("citations") or [])),
              ("Notes", clean([rec.get("notes") or ""])),
              ("Missing", clean(rec.get("missing_info") or []) if rec.get("status") not in MODEL_LABELLED else [])]
    # Round 37 step 1: "Also confirm" (row-ID dumps) is replaced by confirm_html's plain list
    if guide and rec.get("carrier"):
        import display_names
        groups.append(("Guide", [display_names.guide_line(rec["carrier"])]))
    return [(h, items) for h, items in groups if items]


def confirm_html(rec):
    """Round 37 step 1 (Liam, 2026-10-10): "Before you quote, confirm:" -- at most confirm_topics.CARD_MAX plain
    items, the rest under "+N more", the rule IDs on a collapsed line. "" when there is nothing to confirm."""
    import confirm_topics
    shown, more, ids = confirm_topics.card_list(rec)
    if not shown:
        return ""

    def ul(items):
        return "<ul>" + "".join(f"<li>{html.escape(it['text'], quote=False)}</li>" for it in items) + "</ul>"
    out = "<p><b>Before you quote, confirm:</b></p>" + ul(shown)
    if more:
        out += f"<details><summary>+{len(more)} more</summary>{ul(more)}</details>"
    # (round 37 step 2: the row IDs moved to the card's own collapsed line, rule_ids_html)
    return out


def details_html(rec, guide=False):
    """The collapsed <details> block, or "" when there is nothing to show."""
    groups = details_items(rec, guide)
    if not groups:
        return ""
    body = "".join(
        f"<p><b>{h}</b></p><ul>" + "".join(f"<li>{html.escape(agent_text(x), quote=False)}</li>" for x in items)
        + "</ul>"
        for h, items in groups)
    return f"<details><summary>Details</summary>{body}</details>"
