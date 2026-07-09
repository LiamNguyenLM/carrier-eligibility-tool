from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import os

try:
    if "ANTHROPIC_API_KEY" in st.secrets:
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    pass

from eligibility_check import check_eligibility
from upload_carrier import (
    add_carrier_to_database,
    remove_carrier_from_database,
    list_carriers_in_database
)

st.set_page_config(
    page_title="Carrier Eligibility Tool",
    page_icon="🏠",
    layout="wide"
)


# ============================================================
# LOGIN
# ============================================================
def get_role(password):
    try:
        user_pwd = st.secrets.get("USER_PASSWORD", "") or os.environ.get("USER_PASSWORD", "")
        admin_pwd = st.secrets.get("ADMIN_PASSWORD", "") or os.environ.get("ADMIN_PASSWORD", "")
    except Exception:
        user_pwd = os.environ.get("USER_PASSWORD", "")
        admin_pwd = os.environ.get("ADMIN_PASSWORD", "")

    if admin_pwd and password == admin_pwd:
        return "admin"
    elif user_pwd and password == user_pwd:
        return "user"
    return None


if "role" not in st.session_state:
    st.session_state.role = None

if st.session_state.role is None:
    st.title("🏠 Carrier Eligibility Tool")
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.subheader("Sign In")
        password = st.text_input("Password", type="password", key="login_pw")
        if st.button("Log In", type="primary", use_container_width=True):
            role = get_role(password)
            if role:
                st.session_state.role = role
                st.rerun()
            else:
                st.error("Incorrect password. Please try again.")
    st.stop()


# ============================================================
# LOGGED IN — SHOW APP
# ============================================================
with st.sidebar:
    st.markdown("**Carrier Eligibility Tool**")
    st.caption("Role: " + st.session_state.role.capitalize())
    if st.button("Log Out", use_container_width=True):
        st.session_state.role = None
        st.rerun()

if st.session_state.role == "admin":
    tab1, tab2 = st.tabs(["Eligibility Check", "Manage Carriers"])
else:
    tab1 = st.tabs(["Eligibility Check"])[0]
    tab2 = None


# ============================================================
# TAB 1: ELIGIBILITY CHECK
# ============================================================
with tab1:
    st.title("🏠 Property Details")
    st.caption("Enter your property information to check carrier eligibility")

    st.subheader("📍 Location")
    col1, col2 = st.columns(2)

    with col1:
        ppc = st.selectbox("PPC Number", [
            "N/A", "1", "2", "3", "4", "5",
            "6", "7", "8", "8A", "8B", "9", "10"
        ], key="ppc")

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
            key="coastal"
        )
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

    has_dogs = st.toggle("Dogs on Premises", key="dogs")
    if has_dogs:
        aggressive_breed = st.toggle(
            "Aggressive Breed?",
            help=(
                "Aggressive breeds typically include: Pit Bull, American Bulldog, "
                "Presa Canario, Cane Corso, Dogo Argentino (Gull Dong), Tosa Inu, "
                "Fila Brasileiro, American Bandogge, Belgian Shepherd, German Shepherd, "
                "Beauceron, Akita, Doberman Pinscher, Chow Chow, Rottweiler, Wolf Hybrid."
            ),
            key="aggressive"
        )
    else:
        aggressive_breed = False

    st.divider()

    st.subheader("📅 Property Age")
    col1, col2 = st.columns(2)
    with col1:
        year_built = st.number_input("Year Built", min_value=1800,
            max_value=2026, value=2000, key="year")
    with col2:
        roof_age = st.number_input("Roof Age (years)", min_value=0,
            max_value=100, value=10, key="roofage")

    st.divider()

    st.subheader("🛡️ Construction Details")
    col1, col2 = st.columns(2)
    with col1:
        roof_type = st.selectbox("Roof Type", [
            "Composition Shingle", "Architectural Shingle", "Metal",
            "Tile", "Slate", "Wood Shake", "Flat/Built-Up", "Other"
        ], key="rooftype")
        construction_type = st.selectbox("Construction Type", [
            "Frame", "Masonry", "Masonry Veneer", "Superior", "Manufactured/Mobile"
        ], key="construction")
        plumbing_type = st.selectbox("Plumbing Type", [
            "Copper", "PVC", "PEX", "Galvanized", "Polybutylene", "Unknown", "Other"
        ], key="plumbing")
    with col2:
        roof_shape = st.selectbox("Roof Shape", [
            "Gable", "Hip", "Flat", "Gambrel", "Mansard", "Other"
        ], key="roofshape")
        swimming_pool = st.selectbox("Swimming Pool", [
            "No Pool", "Above Ground - Fenced", "Above Ground - Unfenced",
            "In Ground - Fenced", "In Ground - Unfenced"
        ], key="pool")
        if swimming_pool != "No Pool":
            pool_accessories = st.selectbox("Pool Accessories", [
                "None", "Slide only", "Diving board only",
                "Both slide and diving board"
            ], key="poolacc")
        else:
            pool_accessories = "None"
        solar_panels = st.toggle("Solar Panels", key="solar",
            help="Does the property have solar panels installed?")

    st.divider()

    submitted = st.button("Check Carrier Eligibility", type="primary",
                          use_container_width=True, key="submit")

    if submitted:
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
            "has_dogs": "Yes" if has_dogs else "No",
            "aggressive_breed": "Yes" if aggressive_breed else "No",
            "solar_panels": "Yes" if solar_panels else "No",
            "ppc": ppc
        }

        with st.spinner("Analyzing carrier eligibility..."):
            results = check_eligibility(property_details)

        st.markdown("---")
        st.subheader("CARRIER ELIGIBILITY ANALYSIS")

        eligible = [r for r in results if r.get("status") == "ELIGIBLE"]
        one_issue = [
            r for r in results
            if (r.get("status") == "INELIGIBLE" and r.get("flaw_count", 0) == 1)
            or r.get("status") == "REFER"
        ]
        not_eligible = [
            r for r in results
            if r.get("status") not in ["ELIGIBLE"]
            and not (
                (r.get("status") == "INELIGIBLE" and r.get("flaw_count", 0) == 1)
                or r.get("status") == "REFER"
            )
        ]

        def render_carrier(carrier):
            if carrier.get("reasons"):
                st.markdown("**Analysis**")
                for reason in carrier["reasons"]:
                    st.markdown("- " + reason)
            if carrier.get("citations"):
                st.markdown("**Citations**")
                for citation in carrier["citations"]:
                    st.markdown("> " + citation)
            if carrier.get("notes"):
                st.markdown("**Notes**")
                st.markdown(carrier["notes"])
            if carrier.get("missing_info"):
                st.markdown("**Missing Information**")
                for item in carrier["missing_info"]:
                    st.markdown("- " + item)

        col_yes, col_one, col_no = st.columns(3)

        with col_yes:
            st.markdown("### Eligible")
            if eligible:
                for carrier in eligible:
                    with st.expander(carrier["carrier"]):
                        render_carrier(carrier)
            else:
                st.info("No carriers fully eligible.")

        with col_one:
            st.markdown("### One Issue")
            if one_issue:
                for carrier in one_issue:
                    label = carrier.get("status", "").replace("_", " ")
                    with st.expander(carrier["carrier"] + "  |  " + label):
                        render_carrier(carrier)
            else:
                st.info("No carriers with a single resolvable issue.")

        with col_no:
            st.markdown("### Not Eligible")
            if not_eligible:
                for carrier in not_eligible:
                    label = carrier.get("status", "").replace("_", " ")
                    with st.expander(carrier["carrier"] + "  |  " + label):
                        render_carrier(carrier)
            else:
                st.success("No carriers fully ineligible.")


# ============================================================
# TAB 2: MANAGE CARRIERS (ADMIN ONLY)
# ============================================================
if tab2 is not None:
    with tab2:
        st.title("Manage Carrier Documents")

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
