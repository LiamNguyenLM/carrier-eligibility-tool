from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import os

try:
    if "ANTHROPIC_API_KEY" in st.secrets:
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    pass

from eligibility_check import check_eligibility, assign_buckets, usable_answer_count
import eligibility_check
import intake_fields
import topics
import cards

FORM_SCOPE_CAPTION = "Only checked items are considered. Inspections and the condition of the home are not checked."
from upload_carrier import (
    add_carrier_to_database,
    remove_carrier_from_database,
    list_carriers_in_database,
    database_fingerprint,
)

st.set_page_config(
    page_title="Carrier Eligibility Tool",
    page_icon="🏠",
    layout="wide"
)


# ============================================================
# LOGIN
# ============================================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🏠 Carrier Eligibility Tool")
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.subheader("Sign In")
        password = st.text_input("Password", type="password", key="login_pw")
        if st.button("Log In", type="primary", use_container_width=True):
            app_password = os.environ.get("APP_PASSWORD", "")
            if app_password and password == app_password:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Incorrect password. Please try again.")
    st.stop()


# ============================================================
# LOGGED IN — SHOW APP
# ============================================================
with st.sidebar:
    st.markdown("**Carrier Eligibility Tool**")
    if st.button("Log Out", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()

tab1, tab3, tab2 = st.tabs(["Eligibility Check", "Ask the Guides", "Manage Carriers"])


# ============================================================
# TAB 1: ELIGIBILITY CHECK
# ============================================================
with tab1:
    st.title("🏠 Property Details")
    st.caption("Enter your property information to check carrier eligibility")

    # Round 21 (Liam, 2026-10-01/02): a "Check this" box beside each topic.
    # UNCHECKED means the topic is not considered at all. A box ticks itself
    # when its input is changed from the default; a deliberate default answer
    # ("No Pool", "Not Coastal") is made by ticking the box by hand.
    for _t in topics.TOPIC_KEYS:
        st.session_state.setdefault(f"chk_{_t}", False)

    def _autotick(topic, widget_key, default):
        """on_change: tick the topic's box when the value differs from the
        widget's default. Changing it back never unticks by itself."""
        if st.session_state.get(widget_key) != default:
            st.session_state[f"chk_{topic}"] = True

    def _zip_changed():
        """A ZIP sets County to the picked county and ticks the County box.
        Changing the ZIP clears any manual county pick and re-derives; a ZIP
        that does not resolve leaves County blank (unknown), never a guess."""
        zip_text = st.session_state.get("zip", "")
        st.session_state["county"] = intake_fields.county_for_zip(zip_text)[0]
        if str(zip_text).strip():
            st.session_state["chk_county"] = True

    def _set_all(value):
        for t in topics.TOPIC_KEYS:
            st.session_state[f"chk_{t}"] = value

    def _check_box(topic):
        st.checkbox("Check this", key=f"chk_{topic}",
                    help="Unchecked = not considered at all. It ticks itself when you change "
                         "the value; tick it by hand to check a default answer such as "
                         "\"No Pool\" or \"Not Coastal\".")
        if not st.session_state[f"chk_{topic}"]:
            st.caption("Not checked — ignored by this check.")

    sel1, sel2, _ = st.columns([1, 1, 4])
    sel1.button("Select All", key="select_all", on_click=_set_all, args=(True,))
    sel2.button("Clear", key="clear_all", on_click=_set_all, args=(False,))
    # Round 26 step 11 (Liam, 2026-10-05; decisions D and 2026-10-01).
    st.caption(FORM_SCOPE_CAPTION)

    st.subheader("📍 Location")
    col1, col2 = st.columns(2)

    with col1:
        ppc = st.selectbox("PPC Number", [
            "N/A", "1", "2", "3", "4", "5",
            "6", "7", "8", "8A", "8B", "9", "10"
        ], key="ppc", on_change=_autotick, args=("ppc", "ppc", "N/A"))
        # Round 26 (Liam, 2026-10-05, decision B): optional, part of the PPC
        # topic. Blank / Unknown means unknown -- never "no".
        station_text = st.text_input(
            "Distance to fire station (miles)", value="", key="station_miles", placeholder="blank = unknown",
            on_change=_autotick, args=("ppc", "station_miles", ""),
            help="Driving distance to the responding fire station. Leave blank if unknown.")
        hydrant_1000ft = st.selectbox(
            "Hydrant within 1,000 ft", list(intake_fields.HYDRANT_CHOICES), key="hydrant",
            on_change=_autotick, args=("ppc", "hydrant", "Unknown"),
            help="Unknown is not \"no\".")
        _check_box("ppc")

    with col2:
        coastal_tier = st.selectbox(
            "Coastal Tier",
            [
                "Not Coastal",
                "Tier 1 - Closest to coast",
                "Tier 2 - Moderate coastal area",
                "Tier 3 - Outer coastal zone"
            ],
            help="Tier 1 is highest wind risk, typically within 1 mile of Gulf or bay waters.",
            key="coastal", on_change=_autotick, args=("coastal", "coastal", "Not Coastal")
        )
        _check_box("coastal")
        # Always on: Occupancy, Ownership, Dwelling type.
        occupancy_type = st.selectbox("Occupancy Type", [
            "Owner Occupied", "Tenant Occupied", "Seasonal",
            "Vacant", "Secondary Home"
        ], key="occupancy")

        if occupancy_type == "Owner Occupied":
            ownership_type = st.radio(
                "Ownership Structure",
                options=["Individual Owner", "Trust", "LLC"],
                horizontal=True,
                key="ownership"
            )
        else:
            ownership_type = "Individual Owner"

        # Round 30 step 1 (Liam, 2026-10-08, decision 1): only for the owner's other homes;
        # hidden (and absent from property_details) for every other occupancy.
        primary_home_carrier = primary_home_miles = None
        if occupancy_type in intake_fields.OWNERS_OTHER_HOMES:
            primary_home_carrier = st.selectbox(
                "Primary home insured with", list(intake_fields.PRIMARY_HOME_CHOICES), key="primary_carrier",
                format_func=lambda v: v or "— pick one —",
                help="The carrier that insures the owner's primary home. Several guides write a "
                     "seasonal or secondary home only when they also insure the primary home.")
            primary_home_miles = intake_fields.parse_primary_home_miles(st.text_input(
                "Distance to the primary home (miles)", value="", key="primary_miles",
                placeholder="e.g. 40 — leave blank if unknown"))

    has_dogs = st.toggle("Dogs on Premises", key="dogs",
                         on_change=_autotick, args=("dogs", "dogs", False))
    if has_dogs:
        aggressive_breed = st.toggle(
            "Aggressive Breed?",
            help=(
                "Aggressive breeds typically include: Pit Bull, American Bulldog, "
                "Presa Canario, Cane Corso, Dogo Argentino (Gull Dong), Tosa Inu, "
                "Fila Brasileiro, American Bandogge, Belgian Shepherd, German Shepherd, "
                "Beauceron, Akita, Doberman Pinscher, Chow Chow, Rottweiler, Wolf Hybrid."
            ),
            key="aggressive", on_change=_autotick, args=("dogs", "aggressive", False)
        )
    else:
        aggressive_breed = False
    _check_box("dogs")

    st.divider()

    st.subheader("📅 Property Age")
    col1, col2 = st.columns(2)
    with col1:
        year_built = st.number_input("Year Built", min_value=1800,
            max_value=2026, value=2000, key="year",
            on_change=_autotick, args=("home_age", "year", 2000))
        _check_box("home_age")
    with col2:
        roof_age = st.number_input("Roof Age (years)", min_value=0,
            max_value=100, value=10, key="roofage",
            on_change=_autotick, args=("roof_age", "roofage", 10))
        _check_box("roof_age")

    st.divider()

    st.subheader("🛡️ Construction Details")
    col1, col2 = st.columns(2)
    with col1:
        roof_type = st.selectbox("Roof Type", [
            "Composition Shingle", "Architectural Shingle", "Metal",
            "Tile", "Slate", "Wood Shake", "Flat/Built-Up", "Other"
        ], key="rooftype", on_change=_autotick, args=("roof_type", "rooftype", "Composition Shingle"))
        _check_box("roof_type")
        construction_type = st.selectbox("Construction Type", [
            "Frame", "Masonry", "Masonry Veneer", "Superior", "Manufactured/Mobile"
        ], key="construction", on_change=_autotick, args=("construction", "construction", "Frame"))
        _check_box("construction")
        plumbing_type = st.selectbox("Plumbing Type", [
            "Copper", "PVC", "PEX", "Galvanized", "Polybutylene", "Unknown", "Other"
        ], key="plumbing", on_change=_autotick, args=("plumbing", "plumbing", "Copper"))
        _check_box("plumbing")
    with col2:
        roof_shape = st.selectbox("Roof Shape", [
            "Gable", "Hip", "Flat", "Gambrel", "Mansard", "Other"
        ], key="roofshape", on_change=_autotick, args=("roof_shape", "roofshape", "Gable"))
        _check_box("roof_shape")
        swimming_pool = st.selectbox("Swimming Pool", [
            "No Pool", "Above Ground - Fenced", "Above Ground - Unfenced",
            "In Ground - Fenced", "In Ground - Unfenced"
        ], key="pool", on_change=_autotick, args=("pool", "pool", "No Pool"))
        if swimming_pool != "No Pool":
            pool_accessories = st.selectbox("Pool Accessories", [
                "None", "Slide only", "Diving board only",
                "Both slide and diving board"
            ], key="poolacc", on_change=_autotick, args=("pool", "poolacc", "None"))
        else:
            pool_accessories = "None"
        # Round 20 (Liam, 2026-10-01). Shown only for a fenced pool; the key
        # includes the pool answer, so changing that answer starts the boxes
        # unticked again instead of carrying a stale tick across.
        pool_fence_4ft = pool_gate_locking = False
        if swimming_pool in intake_fields.FENCED_POOL_VALUES:
            _fk, _gk = f"pool_fence_4ft::{swimming_pool}", f"pool_gate_locking::{swimming_pool}"
            pool_fence_4ft = st.checkbox(
                "Fence confirmed 4 ft or higher", key=_fk,
                on_change=_autotick, args=("pool", _fk, False),
                help="Tick only if confirmed. Unchecked means UNKNOWN, not \"no\".")
            pool_gate_locking = st.checkbox(
                "Gate confirmed self-latching AND can be locked", key=_gk,
                on_change=_autotick, args=("pool", _gk, False),
                help="Tick only if the gate both latches by itself and can be locked. "
                     "Unchecked means UNKNOWN, not \"no\".")
        _check_box("pool")
        solar_panels = st.toggle("Solar Panels", key="solar",
            help="Does the property have solar panels installed?",
            on_change=_autotick, args=("solar", "solar", False))
        _check_box("solar")

    st.divider()

    # Optional (Liam, 2026-09-30). Blank means UNKNOWN: nothing here has a
    # default that could be mistaken for an answer, and a blank field adds
    # nothing to the check.
    st.subheader("📝 Optional — leave blank if unknown")
    col1, col2, col3 = st.columns(3)
    with col1:
        # Round 21 (Liam, 2026-10-02): agents almost always have the ZIP. The
        # ZIP never reaches the model -- only the county it is checked as.
        zip_text = st.text_input("ZIP", value="", key="zip", placeholder="e.g. 77002",
                                 on_change=_zip_changed,
                                 help="Sets County below. A ZIP in two counties is checked as the "
                                      "county with the larger share; change County if you know it.")
        zip_county, zip_message = intake_fields.county_for_zip(zip_text)
        county = st.selectbox(
            "County", [""] + intake_fields.TEXAS_COUNTIES, key="county",
            format_func=lambda v: v or "— not given —",
            help="Some carriers only write in certain counties.",
            on_change=_autotick, args=("county", "county", ""))
        if zip_county and county == zip_county:
            # Round 22 (Liam, 2026-10-02): show the pick so an agent can
            # overrule it. Display only -- none of this reaches the prompt.
            pick_caption, pick_warning = intake_fields.zip_pick_lines(zip_text)
            st.caption(pick_caption)
            if pick_warning:
                st.warning(pick_warning)
        elif zip_message and not zip_county:
            st.caption(zip_message)
        elif zip_county and county != zip_county:
            st.caption(f"Checked as {county or 'no county'} (set by hand; ZIP {zip_text.strip()[:5]} "
                       f"suggests {zip_county}).")
        _check_box("county")
    with col2:
        dwelling_amount_text = st.text_input(
            "Dwelling amount (Coverage A, $)", value="", key="dwelling_amount",
            placeholder="e.g. 450,000 — leave blank if unknown",
            on_change=_autotick, args=("dwelling_amount", "dwelling_amount", ""))
        dwelling_amount = intake_fields.parse_dwelling_amount(dwelling_amount_text)
        if dwelling_amount_text.strip() and dwelling_amount is None:
            st.warning("Couldn't read that amount, so it will be treated as not given.")
        _check_box("dwelling_amount")
    with col3:
        # Required (Liam, 2026-10-02): always on, and the agent must pick one.
        dwelling_type = st.selectbox(
            "Dwelling type (required)", list(intake_fields.DWELLING_TYPES), key="dwelling_type",
            format_func=lambda v: v or "— pick one —")

    st.divider()

    submitted = st.button("Check Carrier Eligibility", type="primary",
                          use_container_width=True, key="submit")
    checked_topics = [t for t in topics.TOPIC_KEYS if st.session_state.get(f"chk_{t}")]

    if submitted and not dwelling_type:
        st.error("Pick a Dwelling type (House, Townhome or Condo) before running the check.")
        submitted = False

    # Round 26 step 7: every result element lives in one placeholder, made
    # before the check runs. A rerun replaces it at once, so the previous
    # check's sections no longer stay on screen (Streamlit's stale-element
    # display) while a new check runs -- what made Liam's copy of the page
    # show sections two or three times.
    results_area = st.empty()
    if submitted:
        with results_area.container():
            coastal_clean = coastal_tier.split(" - ")[0]
            property_details = {
                "year_built": year_built,
                "roof_age": roof_age,
                "roof_type": roof_type,
                "roof_shape": roof_shape,
                "construction_type": construction_type,
                "plumbing_type": plumbing_type,
                "occupancy_type": occupancy_type,
                "ownership_type": ownership_type,
                "coastal_tier": coastal_clean,
                "swimming_pool": swimming_pool,
                "pool_accessories": pool_accessories,
                # ticked = a stated fact; unticked = unknown
                "pool_fence_4ft": pool_fence_4ft,
                "pool_gate_locking": pool_gate_locking,
                "has_dogs": "Yes" if has_dogs else "No",
                "aggressive_breed": "Yes" if aggressive_breed else "No",
                "solar_panels": "Yes" if solar_panels else "No",
                "ppc": ppc,
                # optional (decision B): None / "Unknown" mean unknown
                "fire_station_miles": intake_fields.parse_station_miles(station_text),
                "hydrant_1000ft": hydrant_1000ft,
                # optional: "" / None mean unknown. The ZIP never reaches the prompt.
                "zip": intake_fields.parse_zip(zip_text)[0] or "",
                "county": county,
                "dwelling_amount": dwelling_amount,
                "dwelling_type": dwelling_type,
            }
            # Round 30 step 1: present only when the question was shown, so every other
            # profile's property_details (and prompt) is byte-identical.
            if occupancy_type in intake_fields.OWNERS_OTHER_HOMES:
                property_details["primary_home_carrier"] = primary_home_carrier or ""
                property_details["primary_home_miles"] = primary_home_miles

            with st.spinner("Analyzing carrier eligibility..."):
                results = check_eligibility(property_details, checked_topics=checked_topics)
            partial = topics.is_partial(topics.normalize(checked_topics))

            st.markdown("---")
            st.subheader("CARRIER ELIGIBILITY ANALYSIS")
            # Liam, 2026-10-01: ELIGIBLE must never read as "no inspection needed".
            st.caption("Inspection requirements are not checked.")
            # Round 21 (Liam, 2026-10-02): say what was checked, partial mode only.
            if partial:
                st.info(topics.partial_check_line(topics.normalize(checked_topics)))

            # 2026-09-30: a live check returned records with no verdict at all,
            # and four empty columns were the only thing on screen. Never again
            # let "no carriers" read as an answer.
            if usable_answer_count(results) == 0:
                st.error("The check did not return usable answers. Run it again; if it repeats, tell Liam.")

            buckets = assign_buckets(results)
            eligible = buckets["eligible"]
            refer = buckets["refer"]
            insufficient_info = buckets["insufficient_info"]
            not_eligible = buckets["not_eligible"]

            def render_carrier(carrier):
                # Round 26 (Liam, 2026-10-05, decision C): a compact card -- the
                # status and the verdict in one line, the open items, and
                # everything else collapsed under "Details" (cards.py).
                # Round 25: the rules-table pilot's cards say so.
                if carrier.get("rules_table"):
                    st.caption("rules table")
                st.markdown(cards.first_line_markdown(carrier, property_details, checked_topics))
                missing = [m for m in carrier.get("missing_info") or [] if isinstance(m, str) and m.strip()]
                if missing:
                    st.markdown("**Missing:**\n" + "\n".join("- " + item for item in missing))
                details = cards.details_html(carrier)
                if details:
                    st.markdown(details, unsafe_allow_html=True)

            col_yes, col_refer, col_info, col_no = st.columns(4)

            with col_yes:
                st.markdown("### Eligible")
                if partial:
                    st.caption("No problem found on the checked items.")
                if eligible:
                    for carrier in eligible:
                        with st.expander(carrier["carrier"]):
                            render_carrier(carrier)
                else:
                    st.info("No carriers fully eligible.")

            # Liam, 2026-10-05 (decision A): this column holds referrals only;
            # every INELIGIBLE is under Not Eligible, whatever its flaw_count.
            # Each column now holds one status, so no card repeats it.
            with col_refer:
                st.markdown("### Refer to Underwriting")
                if refer:
                    for carrier in refer:
                        with st.expander(carrier["carrier"]):
                            render_carrier(carrier)
                else:
                    st.info("No carriers to refer to underwriting.")

            with col_info:
                st.markdown("### Insufficient Information")
                if insufficient_info:
                    for carrier in insufficient_info:
                        with st.expander(carrier["carrier"]):
                            render_carrier(carrier)
                else:
                    st.info("No carriers pending missing information.")

            with col_no:
                st.markdown("### Not Eligible")
                if not_eligible:
                    for carrier in not_eligible:
                        with st.expander(carrier["carrier"]):
                            render_carrier(carrier)
                else:
                    st.success("No carriers fully ineligible.")

            # Rows the pipeline writes for carriers it could not check -- a
            # wrong or unreadable guide on file, or no answer from the model.
            could_not_check = (buckets["unrecognised"] + buckets["guide_unavailable"]
                               + buckets["not_evaluated"])
            if could_not_check:
                st.markdown("### Could Not Be Checked")
                for carrier in could_not_check:
                    # Round 26 step 7: the warning line, and a Details toggle only
                    # when there is something beyond it (never an empty bullet).
                    st.warning(cards.warning_line(carrier))
                    details = cards.details_html(carrier)
                    if details:
                        st.markdown(details, unsafe_allow_html=True)


# ============================================================
# TAB 2: MANAGE CARRIERS
# ============================================================
with tab2:
    st.title("Manage Carrier Documents")

    st.subheader("Database Fingerprint")
    st.caption("Compare with the same panel in the local app. If they differ, the live "
               "database is not the committed seed -- see handoff.md, 'Updating carrier "
               "guides in production'.")
    try:
        fp = database_fingerprint()
        st.code(
            f"carriers  {fp['carriers']}\n"
            f"chunks    {fp['chunks']}\n"
            f"documents {fp['documents_sha256'][:16]}\n"
            f"metadata  {fp['metadata_sha256'][:16]}",
            language=None,
        )
    except Exception as e:
        st.warning("Could not compute the database fingerprint: " + str(e))
    # Round 27 step 3 (Liam, 2026-10-06): did the Railway variable take effect?
    st.markdown("**" + eligibility_check.rules_pilot_status_line() + "**",
                help=eligibility_check.RULES_PILOT_HELP)

    st.divider()

    st.subheader("Current Carriers In Database")
    try:
        carriers = list_carriers_in_database()
        if carriers:
            for carrier in carriers:
                st.markdown("- " + carrier)
        else:
            st.info("No carriers found in database.")
    except Exception as e:
        st.warning("Could not load carrier list: " + str(e))

    st.divider()

    st.subheader("Remove Carrier")
    st.caption("Permanently removes all document sections for the selected carrier.")
    try:
        carriers_for_removal = list_carriers_in_database()
        if carriers_for_removal:
            carrier_to_remove = st.selectbox(
                "Select carrier to remove",
                carriers_for_removal,
                key="remove_select"
            )
            if st.button("Remove From Database", key="remove_btn"):
                with st.spinner("Removing " + carrier_to_remove + "..."):
                    chunks_removed = remove_carrier_from_database(carrier_to_remove)
                if chunks_removed > 0:
                    st.success(carrier_to_remove + " removed. " +
                               str(chunks_removed) + " sections deleted.")
                else:
                    st.warning("No sections found for " + carrier_to_remove)
        else:
            st.info("No carriers in database to remove.")
    except Exception as e:
        st.warning("Could not load carriers for removal: " + str(e))

    st.divider()

    st.subheader("Upload New Carrier PDF")
    st.caption("Line of business is detected automatically from the file name.")

    uploaded_file = st.file_uploader("Select a carrier PDF",
        type="pdf", help="Upload an underwriting guideline or appetite guide PDF")

    if uploaded_file:
        default_name = uploaded_file.name.replace(".pdf", "").replace(".PDF", "")
        carrier_name = st.text_input("Carrier Name", value=default_name,
            help="This name will appear in eligibility results")

        name_upper = carrier_name.upper()
        if "DP3" in name_upper:
            detected_lob = "DP3"
        elif "HOA" in name_upper:
            detected_lob = "HOA"
        elif "HOB" in name_upper:
            detected_lob = "HOB"
        elif "HO3" in name_upper or "HOMEOWNERS" in name_upper:
            detected_lob = "HO3"
        else:
            detected_lob = "Unknown"

        st.caption("Detected line of business: **" + detected_lob + "**")

        if st.button("Process and Add to Database", type="primary", key="upload_btn"):
            with st.spinner("Processing PDF and updating database..."):
                pdf_bytes = uploaded_file.read()
                chunks_added, error = add_carrier_to_database(pdf_bytes, carrier_name)
            if error:
                st.error("Error processing PDF: " + error)
            else:
                st.success(carrier_name + " added successfully. " +
                           str(chunks_added) + " searchable sections created.")
                st.info("Switch to the Eligibility Check tab to use it.")


# ============================================================
# TAB 3: ASK THE GUIDES
# ============================================================
with tab3:
    import chat as chat_module

    st.title("Ask the Guides")
    st.caption(
        "One-off questions about a carrier's underwriting guide, answered with "
        "quotes from the guide on file. This does not run an eligibility report."
    )

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "chat_programs" not in st.session_state:
        st.session_state.chat_programs = []

    col_clear, col_note = st.columns([1, 4])
    with col_clear:
        if st.button("Clear chat", key="chat_clear", use_container_width=True):
            st.session_state.chat_history = []
            st.session_state.chat_programs = []
            st.rerun()
    with col_note:
        if st.session_state.chat_programs:
            st.caption(
                "Follow-up questions will stay on: "
                + ", ".join(st.session_state.chat_programs)
            )

    def _render_result(result):
        """One assistant turn. Warnings before the answer, never after."""
        for program, defect in result.get("blocked", []):
            st.error(
                "**{p}** — this guide cannot be answered from.\n\n{d}\n\n"
                "Upload the correct PDF on the Manage Carriers tab. This warning "
                "clears itself once the right document is in place.".format(
                    p=program, d=defect["detail"]
                )
            )

        if result["mode"] == "ambiguous":
            st.warning(
                "**\"{phrase}\" matches more than one carrier.** These are different "
                "insurers with different rules, so I'm not going to pick one for you. "
                "Which did you mean?".format(phrase=result["phrase"])
            )
            for candidate in result["candidates"]:
                st.markdown("- " + candidate)
            return

        if result["mode"] == "cross_carrier":
            grouped = result["grouped"]

            def _section(title, rows, empty):
                st.markdown("### " + title)
                if not rows:
                    st.caption(empty)
                    return
                for row in rows:
                    label = row["program"]
                    if row["date"]:
                        label += "  (guide dated " + row["date"] + ")"
                    with st.expander(label):
                        if row["detail"]:
                            st.markdown(row["detail"])
                        if row["quote"]:
                            st.markdown("> " + row["quote"])

            _section(
                "Guide says yes (check the conditions)", grouped["yes"],
                "No guide affirmatively addresses this.",
            )
            _section(
                "Guide says no", grouped["no"],
                "No guide excludes this.",
            )
            _section(
                "Guide doesn't address it", grouped["not_addressed"],
                "Every guide speaks to this.",
            )
            st.info(
                "A guide that doesn't address something has no rule about it. "
                "That is **not** the same as accepting it — confirm with the "
                "underwriter before relying on silence."
            )
            if result.get("skipped"):
                st.caption(
                    "Excluded (no usable document on file): "
                    + ", ".join(result["skipped"])
                )
            return

        if result.get("answer"):
            if result.get("quotes_verified") is False:
                st.error(
                    "**Some quotes below could not be found in the guide they are "
                    "attributed to.** Treat this answer as unverified and check the "
                    "PDF directly."
                )
                for problem in result["quote_problems"]:
                    st.markdown(
                        "- `{reason}` — {quote}".format(
                            reason=problem["reason"], quote=problem["quote"][:200]
                        )
                    )
            st.markdown(result["answer"])

    # Replay the conversation so far.
    for turn in st.session_state.chat_history:
        with st.chat_message(turn["role"]):
            if turn["role"] == "user":
                st.markdown(turn["content"])
            else:
                _render_result(turn["result"])

    question = st.chat_input("e.g. does Progressive take galvanized plumbing?")
    if question:
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("Reading the guides..."):
                result = chat_module.ask(
                    question,
                    history=[
                        {"role": t["role"], "content": t.get("content", "")}
                        for t in st.session_state.chat_history
                    ],
                    carried_forward=st.session_state.chat_programs,
                )
            _render_result(result)

        st.session_state.chat_history.append({"role": "user", "content": question})
        st.session_state.chat_history.append(
            {"role": "assistant", "content": result.get("answer") or "", "result": result}
        )
        if result.get("programs"):
            st.session_state.chat_programs = result["programs"]
