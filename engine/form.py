"""Round 43 step 2 (Liam, 2026-10-24): the form, as data and as behaviour, in ONE place -- app.py (Streamlit) and
the static page (web/) both build their form from it and both turn the answers into property_details with
form_request(), so the two forms cannot drift.

    form_spec()                 every choice list, label, default, help text and show-when rule, in app.py's layout
    zip_changed(zip_text)       app.py _zip_changed: the County a ZIP sets, and whether it ticks the County box
    form_messages(values)       the captions / warnings under ZIP, Dwelling amount and Solar
    form_request(values)        {ok, error, property_details, checked_topics} from the widgets' values
    feedback_record(...)        feedback.record()'s line for one "This looks wrong" report (no model: model "")
    usage_record(...)           the POST /api/usage body
    placement_request(result)   the POST /api/placement body (the fields placement.panel reads)

`values` holds the widgets' values by app.py's widget keys (ppc, station_miles, hydrant, coastal, occupancy,
ownership, trust_type, primary_carrier, primary_miles, owner_home_carrier, rental_units, rental_term, dogs, dog_breeds,
year, roofage, rooftype, construction, plumbing, roofshape, pool, poolacc, pool_fence_4ft, pool_gate_locking, solar,
solar_type, solar_tesla, zip, county, harris_east_146, dwelling_amount, dwelling_type, units_in_building, losses_5yr,
loss_types, loss_year, losses_3yr, electrical) plus "chk": {topic: bool}. A value of a widget that is not shown is
ignored, the way app.py only reads a follow-up widget when its question is on screen. (Drafted with the page.)
"""
import datetime
import json

from . import intake_fields
from . import topics
from .feedback_fields import CHOICES as FEEDBACK_CHOICES

SPEC_VERSION = 1

# ---------------------------------------------------------------------------------------------------------------
# The strings and choice lists of the form (app.py reads them from here since round 43 step 2).
# ---------------------------------------------------------------------------------------------------------------
FORM_SCOPE_CAPTION = ("Only checked items are considered. Inspections and the condition of the home are not "
                      "checked.")
TESTER_NOTE = (
    "- **What it checks:** your property against each carrier's own underwriting guide. Every verdict comes "
    "from the guide's rules.\n"
    "- **Blank means unknown.** A field you leave blank (or a topic you don't tick) is never read as a yes "
    "or a no.\n"
    "- **Held** (Insufficient Information): the guide's answer depends on something you didn't give. Fill it "
    "in and check again.\n"
    "- **Confirm:** a rule the form doesn't ask about. The card can still be Eligible; check it with the "
    "client or the guide before you bind.\n"
    "- **Where we usually place homes like this** is our own placement history, not prices or quotes.\n"
    "- If a card looks wrong, open **This looks wrong** on it and say why.")
CHECK_HELP = ("Unchecked = not considered at all. It ticks itself when you change "
              "the value; tick it by hand to check a default answer such as "
              "\"No Pool\" or \"Not Coastal\".")
COASTAL_CHOICES = ("Not Coastal", "Tier 1 - Closest to coast", "Tier 2 - Moderate coastal area",
                   "Tier 3 - Outer coastal zone")
OCCUPANCY_CHOICES = ("Owner Occupied", "Tenant Occupied", "Seasonal", "Vacant", "Secondary Home")
CONSTRUCTION_CHOICES = ("Frame", "Masonry", "Masonry Veneer", "Superior", "Manufactured/Mobile")
ROOF_SHAPE_CHOICES = ("Gable", "Hip", "Flat", "Gambrel", "Mansard", "Other")
POOL_CHOICES = ("No Pool", "Above Ground - Fenced", "Above Ground - Unfenced", "In Ground - Fenced",
                "In Ground - Unfenced")
POOL_ACCESSORY_CHOICES = ("None", "Slide only", "Diving board only", "Both slide and diving board")
LOSS_FOLLOW_UP = ("1", "2", "3 or more")
# Round 43 step 2: the year built's maximum is this year (app.py had 2026 written in, which needed a bump each January)
YEAR_MIN, YEAR_MAX, YEAR_DEFAULT = 1800, datetime.date.today().year, 2000
ROOF_AGE_MIN, ROOF_AGE_MAX, ROOF_AGE_DEFAULT = 0, 100, 10
FEEDBACK_SENT = "Sent -- thank you."
DWELLING_TYPE_REQUIRED = "Pick a Dwelling type (House, Townhome or Condo) before running the check."
DWELLING_AMOUNT_UNREADABLE = "Couldn't read that amount, so it will be treated as not given."
FALLBACK_LINE = "Checked with the fallback model (Anthropic unavailable)"       # pipeline.FALLBACK_LINE (a test)

PICK_ONE, OPTIONAL, NOT_GIVEN = "— pick one —", "— optional —", "— not given —"
# The widgets' keys form_request reads (app.py's st.session_state keys; the page's field keys). The pool boxes'
# Streamlit keys carry the pool answer ("pool_fence_4ft::<pool>"), so app.py passes their two values itself.
VALUE_KEYS = ("ppc", "station_miles", "hydrant", "coastal", "occupancy", "ownership", "trust_type", "primary_carrier",
              "primary_miles", "owner_home_carrier", "rental_units", "rental_term", "dogs", "dog_breeds", "year",
              "roofage", "rooftype", "construction", "plumbing", "roofshape", "pool", "poolacc", "solar",
              "solar_type", "solar_tesla", "zip", "county", "harris_east_146", "dwelling_amount", "dwelling_type",
              "units_in_building", "losses_5yr", "loss_types", "loss_year", "losses_3yr", "electrical")


def _labels(choices, fmt=None):
    return [fmt(c) if fmt else c for c in choices]


def _field(key, kind, label, choices=None, labels=None, default=None, help=None, placeholder=None, topic=None,
           show_if=None, **extra):
    out = {"key": key, "kind": kind, "label": label}
    if choices is not None:
        out["choices"] = list(choices)
        out["labels"] = list(labels) if labels is not None else list(choices)
    out.update(default=default, help=help, placeholder=placeholder, topic=topic, show_if=show_if)
    out.update(extra)
    return out


def form_spec():
    """The form, as data: texts, topics, fields (in form order) and the layout. JSON-serialisable."""
    I = intake_fields
    fields = [
        # -- Location, left column
        _field("ppc", "select", "PPC Number", I.PPC_CHOICES, default="N/A", topic="ppc"),
        _field("station_miles", "text", "Distance to fire station (miles)", default="",
               placeholder="blank = unknown", topic="ppc",
               help="Driving distance to the responding fire station. Leave blank if unknown."),
        _field("hydrant", "select", "Hydrant within 1,000 ft", I.HYDRANT_CHOICES, default="Unknown", topic="ppc",
               help="Unknown is not \"no\"."),
        # -- Location, right column
        _field("coastal", "select", "Coastal Tier", COASTAL_CHOICES, default="Not Coastal", topic="coastal",
               help="Tier 1 is highest wind risk, typically within 1 mile of Gulf or bay waters.",
               pd_values=[c.split(" - ")[0] for c in COASTAL_CHOICES]),  #coastal_clean
        _field("occupancy", "select", "Occupancy Type", OCCUPANCY_CHOICES, default="Owner Occupied"),
        _field("ownership", "radio", "Ownership Structure", I.OWNERSHIP_TYPES, default=I.OWNERSHIP_TYPES[0]),
        _field("trust_type", "select", "Trust type", I.TRUST_TYPES, default=I.TRUST_TYPES[0],
               help="Several guides decide on the kind of trust (family-held, land trust, corporate trust). "
                    "Unknown is not a guess: those carriers hold.",
               show_if={"field": "ownership", "in": ["Trust"]}),
        _field("primary_carrier", "select", "Primary home insured with", I.PRIMARY_HOME_CHOICES,
               _labels(I.PRIMARY_HOME_CHOICES, lambda v: v or PICK_ONE), default="",
               help="The carrier that insures the owner's primary home. Several guides write a "
                    "seasonal or secondary home only when they also insure the primary home.",
               show_if={"field": "occupancy", "in": list(I.OWNERS_OTHER_HOMES)}),
        _field("primary_miles", "text", "Distance to the primary home (miles)", default="",
               placeholder="e.g. 40 — leave blank if unknown",
               show_if={"field": "occupancy", "in": list(I.OWNERS_OTHER_HOMES)}),
        _field("owner_home_carrier", "select", "Where is the owner's own home insured?", I.PRIMARY_HOME_CHOICES,
               _labels(I.PRIMARY_HOME_CHOICES, lambda v: v or PICK_ONE), default="",
               help="The Hartford writes a rental (Rental Property Protection Plus) only when it insures the "
                    "owner's own home. Blank holds The Hartford only.",
               show_if={"field": "occupancy", "in": [I.RENTAL_OCCUPANCY]}),
        _field("rental_units", "select", "Rental units the owner has in total (a duplex counts as 2)",
               I.RENTAL_UNITS_CHOICES, _labels(I.RENTAL_UNITS_CHOICES, lambda v: v or OPTIONAL), default="",
               show_if={"field": "occupancy", "in": [I.RENTAL_OCCUPANCY]}),
        _field("rental_term", "select", "Rented to", I.RENTAL_TERM_CHOICES,
               _labels(I.RENTAL_TERM_CHOICES, lambda v: I.RENTAL_TERM_LABELS.get(v, v) or OPTIONAL), default="",
               show_if={"field": "occupancy", "in": [I.RENTAL_OCCUPANCY]}),
        # -- Dogs
        _field("dogs", "toggle", "Dogs on Premises", default=False, topic="dogs"),
        _field("dog_breeds", "multiselect", "Breed(s) on the property", I.DOG_CHOICES, default=[], topic="dogs",
               placeholder="Pick every breed (a mix counts as the breed), None of these, or Not sure",
               help="Every breed any carrier bans or names. A dog that is a mix of a listed breed counts as that "
                    "breed. Blank or Not sure is unknown, never 'none'.",
               show_if={"field": "dogs", "in": [True]}),
        # -- Property Age
        _field("year", "number", "Year Built", default=YEAR_DEFAULT, topic="home_age",
               min=YEAR_MIN, max=YEAR_MAX, step=1),
        _field("roofage", "number", "Roof Age (years)", default=ROOF_AGE_DEFAULT, topic="roof_age",
               min=ROOF_AGE_MIN, max=ROOF_AGE_MAX, step=1),
        # -- Construction Details
        _field("rooftype", "select", "Roof Type", I.ROOF_TYPES, _labels(I.ROOF_TYPES, lambda v: I.ROOF_LABELS.get(v, v)),
               default="Composition Shingle", topic="roof_type"),
        _field("construction", "select", "Construction Type", CONSTRUCTION_CHOICES, default="Frame",
               topic="construction"),
        _field("plumbing", "select", "Plumbing Type", I.PLUMBING_TYPES,
               _labels(I.PLUMBING_TYPES, lambda v: I.PLUMBING_LABELS.get(v, v)), default="Copper", topic="plumbing"),
        _field("roofshape", "select", "Roof Shape", ROOF_SHAPE_CHOICES, default="Gable", topic="roof_shape"),
        _field("pool", "select", "Swimming Pool", POOL_CHOICES, default="No Pool", topic="pool"),
        _field("poolacc", "select", "Pool Accessories", POOL_ACCESSORY_CHOICES, default="None", topic="pool",
               show_if={"field": "pool", "not_in": ["No Pool"]}),
        # the box's key holds the pool answer, so a new pool answer starts it unticked (reset_on)
        _field("pool_fence_4ft", "checkbox", "Fence confirmed 4 ft or higher", default=False, topic="pool",
               help="Tick only if confirmed. Unchecked means UNKNOWN, not \"no\".",
               show_if={"field": "pool", "in": list(I.FENCED_POOL_VALUES)}, reset_on="pool"),
        _field("pool_gate_locking", "checkbox", "Gate confirmed self-latching AND can be locked", default=False,
               topic="pool", help="Tick only if the gate both latches by itself and can be locked. "
                                  "Unchecked means UNKNOWN, not \"no\".",
               show_if={"field": "pool", "in": list(I.FENCED_POOL_VALUES)}, reset_on="pool"),
        _field("solar", "toggle", "Solar Panels", default=False, topic="solar",
               help="Does the property have solar panels installed?"),
        _field("solar_type", "select", "Solar type", I.SOLAR_TYPES, _labels(I.SOLAR_TYPES, lambda v: v or PICK_ONE),
               default="", topic="solar", show_if={"field": "solar", "in": [True]}),
        _field("solar_tesla", "select", "Tesla equipment (Solar Roof, Powerwall or other Tesla parts)?",
               I.TESLA_CHOICES, default="Unknown", topic="solar", show_if={"field": "solar", "in": [True]}),
        # -- Optional
        _field("zip", "text", "ZIP", default="", placeholder="e.g. 77002",
               help="Sets County below. A ZIP in two counties is checked as the "
                    "county with the larger share; change County if you know it."),
        _field("county", "select", "County", [""] + list(I.TEXAS_COUNTIES),
               _labels([""] + list(I.TEXAS_COUNTIES), lambda v: v or NOT_GIVEN), default="", topic="county",
               help="Some carriers only write in certain counties."),
        _field("harris_east_146", "select", "East of Highway 146 (TWIA designated area)?", I.HARRIS_146_CHOICES,
               default="Unknown", topic="county", show_if={"field": "county", "in": ["Harris"]}),
        _field("dwelling_amount", "text", "Dwelling amount (Coverage A, $)", default="",
               placeholder="e.g. 450,000 — leave blank if unknown", topic="dwelling_amount"),
        _field("dwelling_type", "select", "Dwelling type (required)", I.DWELLING_TYPES,
               _labels(I.DWELLING_TYPES, lambda v: v or PICK_ONE), default=""),
        _field("units_in_building", "select", "Units in the building", I.UNITS_CHOICES,
               _labels(I.UNITS_CHOICES, lambda v: v or OPTIONAL), default="",
               help="A duplex is 2. Several guides decide on the number of units or families; blank is a confirm.",
               show_if={"field": "dwelling_type", "in": ["House"]}),
        # -- Losses and electrical
        _field("losses_5yr", "select", "Losses in the last 5 years", I.LOSS_COUNTS,
               _labels(I.LOSS_COUNTS, lambda v: v or NOT_GIVEN), default=""),
        _field("loss_types", "multiselect", "Types", I.LOSS_TYPES, default=[],
               show_if={"field": "losses_5yr", "in": list(LOSS_FOLLOW_UP)}),
        _field("loss_year", "number", "Most recent loss year", default=None, min=datetime.date.today().year - 5,
               max=datetime.date.today().year, step=1, show_if={"field": "losses_5yr", "in": list(LOSS_FOLLOW_UP)}),
        _field("losses_3yr", "select", "How many of them in the last 3 years?", I.LOSS_3YR_COUNTS,
               _labels(I.LOSS_3YR_COUNTS, lambda v: v or NOT_GIVEN), default="",
               help="Some guides count losses over 3 years.",
               show_if={"field": "losses_5yr", "in": list(LOSS_FOLLOW_UP)}),
        _field("electrical", "multiselect", "Electrical", I.ELECTRICAL_CHOICES,
               _labels(I.ELECTRICAL_CHOICES, lambda v: I.ELECTRICAL_LABELS.get(v, v)), default=[],
               help="Pick all that apply (a home can have breakers and aluminum wiring)."),
    ]
    chk = lambda t: {"check": t}                                                       # noqa: E731
    layout = [
        {"type": "section", "title": "📍 Location", "columns": [
            ["ppc", "station_miles", "hydrant", chk("ppc")],
            ["coastal", chk("coastal"), "occupancy", "ownership", "trust_type", "primary_carrier", "primary_miles",
             "owner_home_carrier", "rental_units", "rental_term"]]},
        {"type": "row", "items": ["dogs", "dog_breeds", chk("dogs")]},
        {"type": "divider"},
        {"type": "section", "title": "📅 Property Age", "columns": [
            ["year", chk("home_age")], ["roofage", chk("roof_age")]]},
        {"type": "divider"},
        {"type": "section", "title": "🛡️ Construction Details", "columns": [
            ["rooftype", chk("roof_type"), "construction", chk("construction"), "plumbing", chk("plumbing")],
            ["roofshape", chk("roof_shape"), "pool", "poolacc", "pool_fence_4ft", "pool_gate_locking", chk("pool"),
             "solar", "solar_type", "solar_tesla", {"messages": "solar"}, chk("solar")]]},
        {"type": "divider"},
        {"type": "section", "title": "📝 Optional — leave blank if unknown", "columns": [
            ["zip", "county", "harris_east_146", {"messages": "zip"}, chk("county")],
            ["dwelling_amount", {"messages": "dwelling_amount"}, chk("dwelling_amount")],
            ["dwelling_type", {"caption": intake_fields.DWELLING_TYPE_HELP}, "units_in_building"]]},
        {"type": "columns", "columns": [["losses_5yr", "loss_types", "loss_year", "losses_3yr"], ["electrical"]]},
        {"type": "divider"},
    ]
    texts = {
        "page_title": "Carrier Eligibility Tool",
        "title": "🏠 Property Details",
        "caption": "Enter your property information to check carrier eligibility",
        "about_label": "About this tool (testing)",
        "tester_note": TESTER_NOTE,
        "name_label": "Your name (optional)",
        "name_help": "Goes only into your \"This looks wrong\" reports, so we can ask you about them.",
        "select_all": "Select All", "clear": "Clear",
        "scope_caption": FORM_SCOPE_CAPTION,
        "check_label": "Check this", "check_help": CHECK_HELP,
        "not_checked": "Not checked — ignored by this check.",
        "submit": "Check Carrier Eligibility",
        "dwelling_type_required": DWELLING_TYPE_REQUIRED,
        "spinner": "Analyzing carrier eligibility...",
        "feedback_label": "This looks wrong",
        "feedback_radio": "It should be",
        "feedback_comment": "Comment (optional)",
        "feedback_send": "Send",
        "feedback_sent": FEEDBACK_SENT,
    }
    # The results page. Markdown as app.py writes it ("### Eligible" is the column header).
    results = {
        "analysis": "CARRIER ELIGIBILITY ANALYSIS",
        "inspection": "Inspection requirements are not checked.",
        "fallback": FALLBACK_LINE,
        "unusable": "The check did not return usable answers. Run it again; if it repeats, tell Liam.",
        "not_checked_tail": " — see \"Could Not Be Checked\" at the bottom of the results.",
        "top_box_title": "#### Things to confirm with the client\n",
        "top_box_caption": "Asked by at least half of the Eligible and Refer carriers, most common first.",
        "partial_eligible": "No problem found on the checked items.",
        "missing": "**Missing:**\n",
        "could_not_title": "### Could Not Be Checked",
        "columns": [
            {"key": "eligible", "title": "### Eligible", "empty": "No carriers fully eligible.", "kind": "info"},
            {"key": "refer", "title": "### Refer to Underwriting", "empty": "No carriers to refer to underwriting.",
             "kind": "info"},
            {"key": "insufficient_info", "title": "### Insufficient Information",
             "empty": "No carriers pending missing information.", "kind": "info"},
            {"key": "not_eligible", "title": "### Not Eligible", "empty": "No carriers fully ineligible.",
             "kind": "success"}],
    }
    return {"version": SPEC_VERSION, "texts": texts, "results": results,
            "topics": [{"key": t.key, "label": t.label, "short": t.short} for t in topics.TOPICS],
            "feedback_choices": list(FEEDBACK_CHOICES), "fields": fields, "layout": layout}


# ---------------------------------------------------------------------------------------------------------------
# The form's behaviour (app.py callbacks and the submit block)
# ---------------------------------------------------------------------------------------------------------------
def _shown(values, key):
    """Is a follow-up question on screen? (the same show_if rules form_spec gives the page)"""
    I = intake_fields
    v = values.get
    rules = {"trust_type": v("ownership") == "Trust",
             "primary_carrier": v("occupancy") in I.OWNERS_OTHER_HOMES,
             "primary_miles": v("occupancy") in I.OWNERS_OTHER_HOMES,
             "owner_home_carrier": v("occupancy") == I.RENTAL_OCCUPANCY,
             "rental_units": v("occupancy") == I.RENTAL_OCCUPANCY,
             "rental_term": v("occupancy") == I.RENTAL_OCCUPANCY,
             "dog_breeds": bool(v("dogs")),
             "poolacc": v("pool") != "No Pool",
             "pool_fence_4ft": v("pool") in I.FENCED_POOL_VALUES,
             "pool_gate_locking": v("pool") in I.FENCED_POOL_VALUES,
             "solar_type": bool(v("solar")), "solar_tesla": bool(v("solar")),
             "harris_east_146": v("county") == "Harris",
             "units_in_building": v("dwelling_type") == "House",
             "loss_types": v("losses_5yr") in LOSS_FOLLOW_UP, "loss_year": v("losses_5yr") in LOSS_FOLLOW_UP,
             "losses_3yr": v("losses_5yr") in LOSS_FOLLOW_UP}
    return rules.get(key, True)


def zip_changed(zip_text):
    """app.py _zip_changed: {county, tick_county}. A ZIP that does not resolve leaves County blank."""
    return {"county": intake_fields.county_for_zip(zip_text)[0], "tick_county": bool(str(zip_text or "").strip())}


def form_messages(values):
    """{"zip": [...], "dwelling_amount": [...], "solar": [...]}: each [{"kind": "caption" | "warning", "text"}], the
    lines app.py shows under those fields on this rerun."""
    I = intake_fields
    zip_text, county = values.get("zip") or "", values.get("county") or ""
    out = {"zip": [], "dwelling_amount": [], "solar": []}
    zip_county, zip_message = I.county_for_zip(zip_text)
    if zip_county and county == zip_county:
        pick_caption, pick_warning = I.zip_pick_lines(zip_text)
        if pick_caption or zip_message:
            out["zip"].append({"kind": "caption", "text": pick_caption or zip_message})
        if pick_warning:
            out["zip"].append({"kind": "warning", "text": pick_warning})
    elif zip_message and not zip_county:
        out["zip"].append({"kind": "caption", "text": zip_message})
    elif zip_county and county != zip_county:
        out["zip"].append({"kind": "caption", "text": f"Checked as {county or 'no county'} (set by hand; ZIP "
                                                      f"{zip_text.strip()[:5]} suggests {zip_county})."})
    text = values.get("dwelling_amount") or ""
    if text.strip() and I.parse_dwelling_amount(text) is None:
        out["dwelling_amount"].append({"kind": "warning", "text": DWELLING_AMOUNT_UNREADABLE})
    if values.get("solar"):
        out["solar"].append({"kind": "caption", "text": I.solar_hold_hint(values.get("occupancy"))})
    return out


def _int_in(value, lo, hi, default):
    """A number_input's value: an int clamped to [lo, hi] (Streamlit never returns one outside); blank -> default."""
    if value in (None, ""):
        return default
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return min(max(n, lo), hi)


def form_request(values):
    """{ok, error, property_details, checked_topics}. The keys, their order and when each one is
    present are app.py's: a follow-up question's key exists only when the question was shown (or answered)."""
    I = intake_fields
    v = values.get
    shown = lambda k: _shown(values, k)                                                # noqa: E731
    chk = v("chk") or {}
    checked_topics = [t for t in topics.TOPIC_KEYS if chk.get(t)]
    dwelling_type = v("dwelling_type") or ""
    if not dwelling_type:
        return {"ok": False, "error": DWELLING_TYPE_REQUIRED, "property_details": None,
                "checked_topics": checked_topics}
    occupancy_type, ownership_type = v("occupancy"), v("ownership")
    swimming_pool, has_dogs, solar_panels, county = v("pool"), bool(v("dogs")), bool(v("solar")), v("county") or ""
    pool_accessories = v("poolacc") if shown("poolacc") else "None"
    fenced = shown("pool_fence_4ft")
    pd = {
        "year_built": _int_in(v("year"), YEAR_MIN, YEAR_MAX, YEAR_DEFAULT),
        "roof_age": _int_in(v("roofage"), ROOF_AGE_MIN, ROOF_AGE_MAX, ROOF_AGE_DEFAULT),
        "roof_type": v("rooftype"),
        "roof_shape": v("roofshape"),
        "construction_type": v("construction"),
        "plumbing_type": v("plumbing"),
        "occupancy_type": occupancy_type,
        "ownership_type": ownership_type,
        "coastal_tier": str(v("coastal") or "").split(" - ")[0],
        "swimming_pool": swimming_pool,
        "pool_accessories": pool_accessories,
        "pool_fence_4ft": bool(v("pool_fence_4ft")) if fenced else False,
        "pool_gate_locking": bool(v("pool_gate_locking")) if fenced else False,
        "has_dogs": "Yes" if has_dogs else "No",
        "dog_breeds": list(v("dog_breeds") or []) if has_dogs else [],
        "solar_panels": "Yes" if solar_panels else "No",
        "ppc": v("ppc"),
        "fire_station_miles": I.parse_station_miles(v("station_miles") or ""),
        "hydrant_1000ft": v("hydrant"),
        "zip": I.parse_zip(v("zip") or "")[0] or "",
        "county": county,
        "dwelling_amount": I.parse_dwelling_amount(v("dwelling_amount") or ""),
        "dwelling_type": dwelling_type,
    }
    if occupancy_type in I.OWNERS_OTHER_HOMES:
        pd["primary_home_carrier"] = v("primary_carrier") or ""
        pd["primary_home_miles"] = I.parse_primary_home_miles(v("primary_miles") or "")
    if occupancy_type == I.RENTAL_OCCUPANCY:
        pd["primary_home_carrier"] = v("owner_home_carrier") or ""
        if v("rental_units"):
            pd["rental_units_total"] = v("rental_units")
        if v("rental_term"):
            pd["rental_term"] = v("rental_term")
    if ownership_type == "Trust":
        pd["trust_type"] = v("trust_type")
    if solar_panels:
        pd["solar_type"] = v("solar_type") or ""
        pd["solar_tesla"] = v("solar_tesla")
    if county == "Harris":
        pd["harris_east_146"] = v("harris_east_146")
    losses_5yr = v("losses_5yr") or ""
    if losses_5yr:
        pd["losses_5yr"] = losses_5yr
        if shown("loss_types"):
            loss_types = list(v("loss_types") or [])
            today = datetime.date.today().year
            loss_year = _int_in(v("loss_year"), today - 5, today, None)
            if loss_types:
                pd["loss_types"] = loss_types
            if loss_year:
                pd["loss_year"] = int(loss_year)
            if v("losses_3yr"):
                pd["losses_3yr"] = v("losses_3yr")
    if v("electrical"):
        pd["electrical"] = list(v("electrical"))
    if shown("units_in_building") and v("units_in_building"):
        pd["units_in_building"] = v("units_in_building")
    # property_details_json: the page passes THIS string to check_json, never its JS copy -- JavaScript cannot tell
    # 9.0 from 9, and a whole-number station distance would read "9 mi" where the app reads "9.0 mi" (round 43)
    return {"ok": True, "error": None, "property_details": pd, "checked_topics": checked_topics,
            "property_details_json": json.dumps(pd, ensure_ascii=False)}


# ---------------------------------------------------------------------------------------------------------------
# Worker payloads
# ---------------------------------------------------------------------------------------------------------------
def now_iso():
    """feedback.record's timestamp format: UTC, seconds, "+00:00"."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def feedback_record(card, property_details, choice, comment="", name="", checked_topics=None, app_version="unknown"):
    """feedback.record()'s line (feedback.py 64-76; keep in step), from one card of engine.api.check(): the card
    already holds carrier, status, reasons, deciding_rows, rules_table and its display name. model is "" -- the
    static page makes no model call."""
    return {"ts": now_iso(), "app_version": app_version or "unknown", "name": (name or "").strip(),
            "property_details": dict(property_details or {}), "carrier": card.get("carrier", ""),
            "display_name": card.get("name") or "", "verdict": card.get("status", ""),
            "reasons": list(card.get("reasons") or []), "deciding_rows": list(card.get("deciding_rows") or []),
            "model": "", "rules_table": bool(card.get("rules_table")),
            "checked_topics": None if checked_topics is None else list(checked_topics),
            "choice": choice if choice in FEEDBACK_CHOICES else "Not sure", "comment": (comment or "").strip()}


def usage_record(app_version, wall_s, carriers, engine_s, render_s, placement_s):
    r = lambda x: round(float(x or 0), 3)                                              # noqa: E731
    return {"ts": now_iso(), "app_version": app_version or "unknown", "wall_s": r(wall_s), "carriers": int(carriers),
            "timings": {"engine_s": r(engine_s), "render_s": r(render_s), "placement_s": r(placement_s)}}


def _first(items):
    """The first item that says something (placement.panel reads the first non-blank missing_info item)."""
    return [x for x in (items or []) if isinstance(x, str) and x.strip()][:1]


def placement_request(result):
    """POST /api/placement's body from engine.api.check()'s result: the property fields placement.panel reads and,
    for every carrier, its status and first missing item / reason (the panel's "Held: confirm ..." line)."""
    pd = result.get("property_details") or {}
    return {"pd": {k: pd.get(k) for k in ("zip", "county", "year_built", "dwelling_amount", "occupancy_type")},
            "results": [{"carrier": c.get("carrier"), "status": c.get("status"),
                         "missing_info": _first(c.get("missing_info")), "reasons": _first(c.get("reasons"))}
                        for c in result.get("cards") or []]}


def to_json(obj):
    return json.dumps(obj, ensure_ascii=False, default=str)
