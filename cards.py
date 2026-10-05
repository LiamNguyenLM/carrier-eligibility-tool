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
from datetime import date

STATUS_LABEL = {
    "ELIGIBLE": "Eligible",
    "INELIGIBLE": "Not eligible",
    "REFER": "Refer to underwriting",
    "INSUFFICIENT_INFORMATION": "Insufficient information",
}


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
                   ("aggressive breed" if pd.get("aggressive_breed") == "Yes" else "dogs"))
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
    return reasons[0] if reasons else STATUS_LABEL.get(rec.get("status"), rec.get("status") or "")


def first_line_markdown(rec, property_details, checked=None):
    label = STATUS_LABEL.get(rec.get("status"), rec.get("status") or "")
    return f"**{label}** — {verdict_line(rec, property_details, checked)}"


def details_items(rec):
    """(heading, [items]) groups for the Details toggle, empty groups dropped.
    ELIGIBLE keeps every reason here (its first line is the checked facts);
    any other status keeps the reasons after the first."""
    reasons = rec.get("reasons") or []
    rest = reasons if rec.get("status") == "ELIGIBLE" else reasons[1:]
    groups = [("Analysis", rest), ("Citations", rec.get("citations") or []),
              ("Notes", [rec["notes"]] if (rec.get("notes") or "").strip() else []),
              ("Also confirm", rec.get("also_confirm") or [])]
    return [(h, items) for h, items in groups if items]


def details_html(rec):
    """The collapsed <details> block, or "" when there is nothing to show."""
    groups = details_items(rec)
    if not groups:
        return ""
    body = "".join(
        f"<p><b>{h}</b></p><ul>" + "".join(f"<li>{html.escape(x, quote=False)}</li>" for x in items) + "</ul>"
        for h, items in groups)
    return f"<details><summary>Details</summary>{body}</details>"
