"""Carrier eligibility tool as an MCP server (stdio), for Hermes / CFIG-GPT (Liam, 2026-10-16).

Read-only by design: three tools, no uploads, no reseeds, nothing that writes to the carrier store.

  list_carriers        the indexed programs, with forms and guide dates
  search_guidelines    raw passages from one carrier's guide (or all), with file and page -- no LLM call
  check_eligibility    the full pipeline the Streamlit app runs; a compact reply (the app's results page)
  carrier_details      one carrier's full card from the last check (free, no rerun)

Run:   venv\\Scripts\\python.exe carrier_mcp.py          (stdio; Hermes launches it)
Needs: pip install -r requirements-mcp.txt             (kept out of requirements.txt so Railway is unchanged)

Notes
- Startup loads the index, embedding model and pipeline modules first (about 30 s on the office laptop), then serves.
  Loading must not overlap a pending stdin read on Windows (see _serve).
- stdout is the MCP channel. At start the real stdout is duplicated for the protocol alone, and file
  descriptor 1 / sys.stdout are pointed at stderr for the whole process -- eligibility_check prints in places,
  and a stray print (from any thread or from C code) can never corrupt the protocol.
- The working directory is forced to this folder: shared_resources.DB_FOLDER is the relative ./carrier_docs_db,
  and env_setup.load_env() finds the .env next to this code. No key goes in the Hermes config.
- A topic is "checked" exactly when the caller gives at least one of its fields -- the same meaning as a ticked
  box on the form. Unchecked topics are not considered at all, so ELIGIBLE means "no problem found on what was
  checked"; every reply says which topics were and were not checked.
"""
import contextlib
import difflib
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("carrier-eligibility")

_lock = threading.Lock()
_mods = {}


_SERVER_MODE = False


def _quiet():
    """Send anything printed during a call to stderr. In server mode stdout already IS stderr (see _serve), so
    this is a no-op there: contextlib.redirect_stdout swaps a process-global and would race between threads."""
    return contextlib.nullcontext() if _SERVER_MODE else contextlib.redirect_stdout(sys.stderr)


def _load():
    """Import the pipeline once (Chroma + embeddings load here: a few seconds)."""
    with _lock:
        if not _mods:
            with _quiet():
                import cards
                import confirm_topics
                import display_names
                import eligibility_check
                import intake_fields
                import topics
                from shared_resources import get_vectorstore
                import placement
                store = get_vectorstore()
                store._collection.count()          # open the index now, not on the first request
                if placement.enabled():
                    placement.load_tables()
                _mods.update(ec=eligibility_check, intake=intake_fields, topics=topics, cards=cards,
                             confirm=confirm_topics, names=display_names, store=store)
    return _mods


# ---------------------------------------------------------------------------
# Carrier names
# ---------------------------------------------------------------------------

def _resolve_carrier(name):
    """(canonical program name, None) or (None, error dict listing candidates). Exact, then case-insensitive
    substring, then fuzzy. Several substring matches are returned as a choice, never guessed."""
    carriers = sorted(_load()["ec"].get_all_carriers())
    if name in carriers:
        return name, None
    flat = lambda s: "".join(ch for ch in s.lower() if ch.isalnum())  # noqa: E731
    hits = [c for c in carriers if flat(name) and flat(name) in flat(c)]
    if len(hits) == 1:
        return hits[0], None
    if not hits:
        hits = difflib.get_close_matches(name, carriers, n=5, cutoff=0.5)
        if len(hits) == 1:
            return hits[0], None
    return None, {"error": f"Carrier '{name}' is not one exact program in the index.",
                  "candidates": hits or carriers,
                  "hint": "Call again with one of the candidate names exactly as written."}


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def list_carriers() -> list[dict]:
    """List every carrier program in the eligibility index: its exact name (use it in the other tools), forms
    (homeowners / dwelling fire) and the guide's edition date when known. Call this first when unsure
    of a carrier's exact name, or to say a carrier is NOT in the index rather than guessing."""
    m = _load()
    ec = m["ec"]
    with _quiet():
        settings = ec.upload_settings()
        out = []
        for c in sorted(ec.get_all_carriers()):
            ho, dp = ec.carrier_programs(c)
            s = settings.get(c, {})
            forms = "/".join(f for f, on in (("homeowners", ho), ("dwelling fire", dp)) if on) or "other"
            out.append({"carrier": c, "forms": forms, "guide_date": s.get("guide_date") or "not recorded"})
    return out


@mcp.tool()
def search_guidelines(query: str, carrier: str | None = None, k: int = 4) -> dict:
    """Search carrier underwriting guides and return the matching passages verbatim, each with its carrier,
    source file and page. Use for questions about one rule ("Allied Trust roof age rules", "which carriers
    allow trampolines"). Pass `carrier` to search one program only -- results are filtered inside the vector
    query, so another carrier's text can never appear. Answer only from the returned text and cite the
    carrier, file and page. A passage marked header_only is a table header without its rows: say the rule
    could not be read, do not infer it."""
    m = _load()
    ec, store = m["ec"], m["store"]
    k = max(1, min(int(k or 4), 8))
    where = None
    if carrier:
        resolved, err = _resolve_carrier(carrier)
        if err:
            return err
        carrier, where = resolved, {"carrier": resolved}
    with _quiet():
        docs = store.similarity_search(query, k=k, filter=where)
        passages = []
        for d in docs:
            md = d.metadata or {}
            c = md.get("carrier", "")
            if carrier and c != carrier:               # belt and braces: never return another carrier's text
                continue
            text = d.page_content
            try:
                text = ec.stitched_text(c, text, bool(md.get("is_table")))
            except Exception:
                pass
            try:
                header_only = bool(md.get("is_table")) and ec._is_header_only_table(d.page_content)
            except Exception:
                header_only = False
            page = md.get("page")
            passages.append({"carrier": c, "file": md.get("source_file", ""),
                             "page": page + 1 if isinstance(page, int) else page,
                             "section": md.get("section", ""), "is_table": bool(md.get("is_table")),
                             "header_only": header_only, "text": text})
    # Hermes spills tool results over ~8,000 characters to a file; keep the reply under that so it is read whole.
    budget = 6500
    for p in passages:
        room = max(400, budget // max(1, len(passages)))
        if len(p["text"]) > room:
            p["text"] = p["text"][:room].rsplit(" ", 1)[0] + " [...]"
    return {"query": query, "carrier": carrier or "all", "passages": passages,
            "note": "Verbatim guide text. Page numbers are 1-based PDF pages."}


# The form's own choices. A field's default is used only to fill an UNCHECKED topic (never read by the check).
def _choices(intake):
    return {
        "occupancy_type": ("Owner Occupied", "Tenant Occupied", "Seasonal", "Vacant", "Secondary Home"),
        "ownership_type": intake.OWNERSHIP_TYPES,
        "trust_type": intake.TRUST_TYPES,
        "dwelling_type": intake.DWELLING_TYPES,
        "units_in_building": intake.UNITS_CHOICES,
        "ppc": ("N/A", "1", "2", "3", "4", "5", "6", "7", "8", "8A", "8B", "9", "10"),
        "hydrant_1000ft": intake.HYDRANT_CHOICES,
        "coastal_tier": ("Not Coastal", "Tier 1", "Tier 2", "Tier 3"),
        "roof_type": intake.ROOF_TYPES,
        "roof_shape": ("Gable", "Hip", "Flat", "Gambrel", "Mansard", "Other"),
        "construction_type": ("Frame", "Masonry", "Masonry Veneer", "Superior", "Manufactured/Mobile"),
        "plumbing_type": intake.PLUMBING_TYPES,
        "swimming_pool": ("No Pool", "Above Ground - Fenced", "Above Ground - Unfenced",
                          "In Ground - Fenced", "In Ground - Unfenced"),
        "pool_accessories": ("None", "Slide only", "Diving board only", "Both slide and diving board"),
        "has_dogs": ("Yes", "No"),
        "solar_panels": ("Yes", "No"),
        "solar_type": intake.SOLAR_TYPES,
        "solar_tesla": intake.TESLA_CHOICES,
        "county": tuple([""] + list(intake.TEXAS_COUNTIES)),
        "losses_5yr": intake.LOSS_COUNTS,
        "losses_3yr": intake.LOSS_3YR_COUNTS,
    }


_LIST_CHOICES = {"dog_breeds": "DOG_CHOICES", "loss_types": "LOSS_TYPES", "electrical": "ELECTRICAL_CHOICES"}

_UNCHECKED_FILL = {
    "year_built": 2000, "roof_age": 10, "roof_type": "Composition Shingle", "roof_shape": "Gable",
    "construction_type": "Frame", "plumbing_type": "Copper", "coastal_tier": "Not Coastal",
    "swimming_pool": "No Pool", "pool_accessories": "None", "pool_fence_4ft": False, "pool_gate_locking": False,
    "has_dogs": "No", "dog_breeds": [], "solar_panels": "No", "ppc": "N/A", "fire_station_miles": None,
    "hydrant_1000ft": "Unknown", "zip": "", "county": "", "dwelling_amount": None, "dwelling_type": "",
}


def build_property_details(profile):
    """(property_details, checked_topics, errors) from a caller's partial profile. Exposed for tests."""
    m = _load()
    intake, tp = m["intake"], m["topics"]
    choices = _choices(intake)
    errors = []
    given = {k: v for k, v in (profile or {}).items() if v is not None and v != ""}

    if "coastal_tier" in given:
        given["coastal_tier"] = str(given["coastal_tier"]).split(" - ")[0]
    for key in ("ppc",):
        if key in given:
            given[key] = str(given[key])
    for key in ("year_built", "roof_age", "loss_year"):
        if key in given:
            try:
                given[key] = int(given[key])
            except (TypeError, ValueError):
                errors.append(f"{key} must be a whole number")
    if "dwelling_amount" in given:
        given["dwelling_amount"] = intake.parse_dwelling_amount(str(given["dwelling_amount"]))
        if given["dwelling_amount"] is None:
            errors.append("dwelling_amount could not be read as dollars")
    if "fire_station_miles" in given:
        given["fire_station_miles"] = intake.parse_station_miles(str(given["fire_station_miles"]))
    if "zip" in given:
        z, msg = intake.parse_zip(given["zip"])
        if msg:
            errors.append(f"zip: {msg}")
        given["zip"] = z or ""
        if z and "county" not in given:
            county, _ = intake.county_for_zip(z)
            if county:
                given["county"] = county
    for key in ("pool_fence_4ft", "pool_gate_locking"):
        if key in given:
            given[key] = str(given[key]).lower() in ("true", "yes", "1")

    for key, allowed in choices.items():
        if key in given and given[key] not in allowed:
            errors.append(f"{key}={given[key]!r} is not a form choice; use one of {list(allowed)}")
    for key, const in _LIST_CHOICES.items():
        if key in given:
            vals = given[key] if isinstance(given[key], (list, tuple)) else [given[key]]
            allowed = getattr(intake, const)
            bad = [v for v in vals if v not in allowed]
            if bad:
                errors.append(f"{key} has {bad}, not form choices; use any of {list(allowed)}")
            given[key] = list(vals)
    for key in ("occupancy_type", "ownership_type", "dwelling_type"):
        if key not in given:
            errors.append(f"{key} is required (always checked on the form) -- ask the agent; do not assume it")

    known = set(_UNCHECKED_FILL) | set(choices) | set(_LIST_CHOICES) | {
        "occupancy_type", "ownership_type", "trust_type", "harris_east_146", "loss_year",
        "primary_home_carrier", "primary_home_miles", "rental_units_total", "rental_term", "units_in_building"}
    unknown = sorted(set(given) - known)
    if unknown:
        errors.append(f"unknown fields {unknown}")

    pd = dict(_UNCHECKED_FILL)
    pd.update(given)
    if pd.get("has_dogs") != "Yes":
        pd["dog_breeds"] = []
    checked = [t.key for t in tp.TOPICS if any(k in given for k in t.owns)]
    return pd, checked, errors


# What an agent's own words must say for each dwelling type. "home" / "property" / "place" name none of them.
_DWELLING_WORDS = {
    "House": r"\b(house|single[- ]family|sfh|stand[- ]?alone|detached)\b",
    "Townhome": r"\b(town ?homes?|town ?houses?|row ?homes?|row ?houses?|duplex)\b",
    "Condo": r"\b(condos?|condominiums?|apartments?|unit owner|ho-?6)\b",
}


def dwelling_quote_problem(dwelling_type, quote):
    """None when the agent's quoted words state this dwelling type; else the reason to ask. Live run 2026-10-24:
    with the skill saying "ask", Haiku 5.5 still read "owner-occupied home" as a House -- so the server checks."""
    import re
    q = (quote or "").strip()
    if not q:
        return ("dwelling_type_quote is empty: quote the agent's own words from this chat that say House, Townhome "
                "or Condo. If they have not said it, ASK them -- do not choose for them.")
    pattern = _DWELLING_WORDS.get(dwelling_type)
    if pattern and re.search(pattern, q, re.I):
        return None
    return (f"the agent's words {q!r} do not say the dwelling is a {dwelling_type} (\"home\" could be a house, "
            "townhome or condo). ASK the agent which it is, then call again with their answer as dwelling_type_quote.")


@mcp.tool(structured_output=False)
def check_eligibility(profile: dict, dwelling_type_quote: str = "") -> str:
    """Run the full carrier eligibility check (the same pipeline as the agency's Streamlit tool) for one Texas
    property. Give only the facts you actually know -- a topic left out is NOT considered, exactly like an
    unticked box on the form, so ELIGIBLE means "no problem found on the topics that were checked".

    Required: occupancy_type, ownership_type, dwelling_type (House / Townhome / Condo) -- the app's form always
    sends these. Ask the agent for any that are missing; never assume "House".
    dwelling_type_quote (required): the agent's own words from this chat that state the dwelling type, e.g. "it's a
    house" or "Townhome". The server checks them: "home" alone does not say which, so ask first.
    Optional (each one turns its topic on): year_built, roof_age, roof_type, roof_shape, construction_type,
    plumbing_type, coastal_tier, swimming_pool, pool_accessories, pool_fence_4ft, pool_gate_locking, has_dogs,
    dog_breeds, solar_panels, solar_type, solar_tesla, ppc, fire_station_miles, hydrant_1000ft, zip, county,
    dwelling_amount, units_in_building, trust_type, losses_5yr, loss_types, loss_year, losses_3yr, electrical.
    Values must be the form's choices; a wrong value returns the allowed list -- fix it and call again.

    Returns, per carrier, the same card the agency's tool shows: status (ELIGIBLE / REFER /
    INSUFFICIENT_INFORMATION / INELIGIBLE, or GUIDE_UNAVAILABLE / NOT_EVALUATED), the verdict line, what is missing,
    what to confirm before quoting, coverage notes (loss settlement, not eligibility) and citations; plus the
    questions most carriers want answered and where CFIG usually places homes like this (top 3).

    Returns the app's results page as plain markdown. Your reply to the agent IS that page: copy it from the first
    line to the last, every heading, numbered line and bullet, in order -- especially the numbered "Where we usually
    place homes like this" ranking with its bullet lines and footer. Then add at most two sentences of your own. For one carrier's full card, call carrier_details (free). dwelling_type, occupancy_type and
    ownership_type must come from the agent in THIS conversation -- ask if they have not said them. Relay these in the tool's words -- do not re-derive or add rules. Takes 30-90 s and
    makes paid model calls: run it once per property, not per question."""
    pd, checked, errors = build_property_details(profile)
    if not errors:
        why = dwelling_quote_problem(pd.get("dwelling_type"), dwelling_type_quote)
        if why:
            errors.append(why)
    if errors:
        return ("PROFILE NOT ACCEPTED -- nothing was checked. Fix these and call again (ask the agent for anything "
                "they have not said):\n" + "\n".join(f"- {e}" for e in errors))
    m = _load()
    ec, tp = m["ec"], m["topics"]
    with _quiet():
        results = ec.check_eligibility(pd, checked_topics=checked)
    with _quiet():
        cards_out = [card(r, pd, checked) for r in results]
        top = m["confirm"].top_box(results, pd, checked)
        placement_out = _placement(results, pd)
    order = {"ELIGIBLE": 0, "REFER": 1, "INSUFFICIENT_INFORMATION": 2, "INELIGIBLE": 3}
    cards_out.sort(key=lambda c: (order.get(c["status"], 4), c["carrier"]))
    with _quiet():
        summary = summary_markdown(pd, checked, top, placement_out, cards_out)
        if len(summary) > 7000:      # stay under Hermes's ~8,000-character spill limit; details stay on the cards
            summary = "\n".join(l for l in summary.split("\n") if not l.startswith("    - Missing: "))
    _LAST.update(cards={c["carrier"]: c for c in cards_out}, checked_as=summary.split("\n", 1)[0])
    # Plain text, not a JSON field: models pass a page of text along far more faithfully than a value they unpack
    # (2026-10-24: Haiku 5.5 kept condensing summary_markdown, dropping the ranking's lines and footer).
    return (summary + "\n\n---\n(For the assistant, not the agent: the page above is the reply -- copy it whole, "
            "then add at most two sentences. For one carrier's full card call carrier_details. Never add claims the "
            "page does not make.)")


def _clip(text, n):
    """At most n characters, cut at a word; the full text is on carrier_details."""
    text = str(text or "")
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "..."


_SECTIONS = (("ELIGIBLE", "Eligible", "No problem found on the checked items."),
             ("REFER", "Refer to underwriting", "Underwriting must approve before binding."),
             ("INSUFFICIENT_INFORMATION", "Insufficient information", "Needs a fact before a verdict."),
             ("INELIGIBLE", "Not eligible", ""))


def summary_markdown(pd, checked, top, placement_out, cards_out):
    """The results page as the app lays it out, ready to show an agent as-is: what was checked, where CFIG usually
    places homes like this, what to confirm with the client, then every carrier by status in the app's words."""
    m = _load()
    cards, tp = m["cards"], m["topics"]
    facts = [pd.get("dwelling_type"), pd.get("occupancy_type"), pd.get("ownership_type")]
    facts += cards.checked_facts(pd, checked)
    lines = ["**Checked as:** " + ", ".join(str(f) for f in facts if f),
             "**Not checked:** " + (", ".join(t.label for t in tp.TOPICS if t.key not in checked) or "nothing"),
             ""]
    if placement_out.get("shown"):
        lines += [placement_out["markdown"].replace("#### ", "### "), "", f"*{placement_out['footer']}*", ""]
    if top:
        lines.append("### Things to confirm with the client")
        lines += [f"- {label} -- asked by {n} of {of} carriers" for label, n, of in top]
        lines.append("")
    by_status = {}
    for c in cards_out:
        by_status.setdefault(c["status"], []).append(c)
    for status, title, blurb in _SECTIONS:
        group = by_status.pop(status, [])
        lines.append(f"### {title} ({len(group)})")
        if blurb:
            lines.append(f"*{blurb}*")
        if not group:
            lines.append("- None.")
        for c in group:
            if status == "ELIGIBLE":
                n = len(c.get("confirm_before_quote", [])) + c.get("more_to_confirm", 0)
                extra = f" -- {n} item{'s' if n != 1 else ''} to confirm before quoting" if n else ""
                lines.append(f"- **{c['carrier']}**{extra}")
            else:
                lines.append(f"- **{c['carrier']}** -- {_clip(c.get('verdict', ''), 220)}")
                for miss in c.get("missing", [])[:1]:
                    lines.append(f"    - Missing: {_clip(miss, 140)}")
        lines.append("")
    for status, group in by_status.items():          # GUIDE_UNAVAILABLE, NOT_EVALUATED, anything new
        lines.append(f"### {status.replace('_', ' ').title()} ({len(group)})")
        lines += [f"- **{c['carrier']}** -- {c.get('verdict', '')}" for c in group]
        lines.append("")
    lines.append("*Eligible means no problem on the checked items only. Coverage notes on a card are about how a loss "
                 "is settled, not eligibility.*")
    return "\n".join(lines)


_LAST = {}


@mcp.tool()
def carrier_details(carrier: str) -> dict:
    """One carrier's full card from the most recent check_eligibility in this session: verdict, what is missing,
    every item to confirm before quoting, coverage notes (loss settlement, not eligibility), citations, guide date.
    Use it for follow-up questions about a carrier; it costs nothing and does not rerun the check."""
    cards_by_name = _LAST.get("cards")
    if not cards_by_name:
        return {"error": "No eligibility check has run since the tool started. Run check_eligibility first."}
    flat = lambda x: "".join(ch for ch in x.lower() if ch.isalnum())  # noqa: E731
    hits = [n for n in cards_by_name if flat(carrier) and flat(carrier) in flat(n)]
    if len(hits) != 1:
        exact = [n for n in hits if flat(n) == flat(carrier)]
        if len(exact) == 1:
            hits = exact
        else:
            return {"error": f"'{carrier}' matches {len(hits)} carriers in the last check.",
                    "candidates": hits or sorted(cards_by_name)}
    c = dict(cards_by_name[hits[0]])
    if c.get("more_to_confirm"):
        c["confirm_before_quote"] = c.get("all_to_confirm", c.get("confirm_before_quote"))
    c.pop("all_to_confirm", None)
    c.pop("more_to_confirm", None)
    return {"checked_as": _LAST.get("checked_as", ""), **c}


def _placement(results, pd):
    """The app's "Where we usually place homes like this" panel (placement.py), in the app's own words. It ranks the
    markets the check did not rule out from CFIG's HawkSoft placement history; it never changes a verdict. Off,
    unavailable or too few candidates is said plainly -- never a reason to fail the check."""
    import placement
    if not placement.enabled():
        return {"shown": False, "why": "The placement panel is off (ELIGIBILITY_PLACEMENT is not 1)."}
    try:
        p = placement.panel(results, pd)
    except Exception as exc:                       # noqa: BLE001 -- the app shows a caption and carries on
        return {"shown": False, "why": f"Placement panel unavailable: {type(exc).__name__}"}
    if not p:
        return {"shown": False, "why": "Fewer than 2 carrier markets are still open, so there is nothing to rank."}
    return {"shown": True, "markdown": placement.panel_markdown(p), "footer": p["footer"],
            "note": "A ranking of where CFIG has placed similar homes, not a price comparison or a verdict."}


def card(rec, pd, checked):
    """One carrier as the app's results card says it, in the app's own words (cards.py / confirm_topics.py), so
    Hermes relays the same text an agent sees in the tool instead of re-deriving it from raw fields."""
    m = _load()
    cards, confirm, names = m["cards"], m["confirm"], m["names"]
    shown, more, _ids = confirm.card_list(rec, pd, checked)
    out = {
        "carrier": names.record_name(rec),
        "program": rec.get("carrier", ""),
        "status": rec.get("status", ""),
        "verdict": cards.first_line_markdown(rec, pd, checked, label=False),
        "missing": cards.missing_lines(rec.get("missing_info")) if rec.get("status") != "ELIGIBLE" else [],
        "confirm_before_quote": [it["text"] for it in shown],
        "all_to_confirm": [it["text"] for it in shown + more],
        "more_to_confirm": len(more),
        "coverage_notes": cards.shown_items([rec.get("notes") or ""]),
        "citations": cards.shown_items(rec.get("citations")),
        # the app's Details line: an upload's stored date, else the date in the file name (display_names.guide_line)
        "guide_date": names.guide_line(rec.get("carrier", ""), rec.get("guide_date"),
                                       rec.get("guide_date_source")).replace("Guide date: ", ""),
        "rule_ids": cards.rule_ids(rec),
    }
    return {k: v for k, v in out.items() if v not in ([], "", None)}


def _log(msg):
    """One timestamped line on stderr (Hermes's MCP log; never stdout, which carries the protocol)."""
    import time
    print(f"[carrier_mcp {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def _warm():
    import time
    t = time.perf_counter()
    _log("warm-up started (index + embedding model)")
    try:
        _load()
        _log(f"warm-up done in {time.perf_counter() - t:.1f} s")
    except Exception as exc:                       # surfaced on the first tool call instead
        _log(f"warm-up failed after {time.perf_counter() - t:.1f} s: {type(exc).__name__}: {exc}")


def _serve():
    """mcp.run() over a private copy of the real stdout; everything else written to stdout lands on stderr."""
    global _SERVER_MODE
    import io
    import anyio
    from mcp.server.stdio import stdio_server

    proto = io.TextIOWrapper(os.fdopen(os.dup(1), "wb"), encoding="utf-8", write_through=True)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    _SERVER_MODE = True

    async def main():
        async with stdio_server(stdout=anyio.wrap_file(proto)) as (read, write):
            await mcp._mcp_server.run(read, write, mcp._mcp_server.create_initialization_options())

    # Load everything BEFORE reading stdin, never in a background thread while a read is pending. On Windows a
    # synchronous read waiting on a pipe handle blocks other threads' calls on the process's standard handles (e.g.
    # handle duplication when a library starts a helper process), so a background warm-up stalled for 10-20 minutes
    # on the office laptop (2026-10-24) -- yet loaded in 27 s single-threaded. Hermes allows 60 s to connect; requests
    # that arrive meanwhile wait in the pipe and are answered once serving starts.
    _warm()
    _log("serving on stdio")
    anyio.run(main)


if __name__ == "__main__":
    _serve()
