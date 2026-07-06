from dotenv import load_dotenv
load_dotenv()

import streamlit as st
from eligibility_check import check_eligibility

st.set_page_config(
    page_title="Carrier Eligibility Tool",
    page_icon="🏠",
    layout="wide"
)

st.title("🏠 Property Details")
st.caption("Enter your property information to check carrier eligibility")

# --- LOCATION ---
st.subheader("📍 Location")
col1, col2 = st.columns(2)

with col1:
    ppc = st.selectbox("PPC Number", [
        "N/A", "1", "2", "3", "4", "5",
        "6", "7", "8", "8A", "8B", "9", "10"
    ])

with col2:
    coastal_tier = st.selectbox(
        "Coastal Tier",
        [
            "Not Coastal",
            "Tier 1 - Closest to coast",
            "Tier 2 - Moderate coastal area",
            "Tier 3 - Outer coastal zone"
        ],
        help="Tier 1 is highest wind risk, typically within 1 mile of Gulf or bay waters."
    )
    occupancy_type = st.selectbox("Occupancy Type", [
        "Owner Occupied",
        "Tenant Occupied",
        "Seasonal",
        "Vacant",
        "Secondary Home"
    ])

st.divider()

# --- PROPERTY AGE ---
st.subheader("📅 Property Age")
col1, col2 = st.columns(2)

with col1:
    year_built = st.number_input(
        "Year Built",
        min_value=1800,
        max_value=2026,
        value=2000
    )

with col2:
    roof_age = st.number_input(
        "Roof Age (years)",
        min_value=0,
        max_value=100,
        value=10
    )

st.divider()

# --- CONSTRUCTION DETAILS ---
st.subheader("🛡️ Construction Details")
col1, col2 = st.columns(2)

with col1:
    roof_type = st.selectbox("Roof Type", [
        "Composition Shingle",
        "Architectural Shingle",
        "Metal",
        "Tile",
        "Slate",
        "Wood Shake",
        "Flat/Built-Up",
        "Other"
    ])
    construction_type = st.selectbox("Construction Type", [
        "Frame",
        "Masonry",
        "Masonry Veneer",
        "Superior",
        "Manufactured/Mobile"
    ])
    plumbing_type = st.selectbox("Plumbing Type", [
        "Copper",
        "PVC",
        "PEX",
        "Galvanized",
        "Polybutylene",
        "Unknown",
        "Other"
    ])

with col2:
    roof_shape = st.selectbox("Roof Shape", [
        "Gable",
        "Hip",
        "Flat",
        "Gambrel",
        "Mansard",
        "Other"
    ])
    swimming_pool = st.selectbox("Swimming Pool", [
        "No Pool",
        "Above Ground - Fenced",
        "Above Ground - Unfenced",
        "In Ground - Fenced",
        "In Ground - Unfenced"
    ])

    if swimming_pool != "No Pool":
        pool_accessories = st.selectbox("Pool Accessories", [
            "None",
            "Slide only",
            "Diving board only",
            "Both slide and diving board"
        ])
    else:
        pool_accessories = "None"

    solar_panels = st.toggle(
        "Solar Panels",
        help="Does the property have solar panels installed?"
    )

st.divider()

submitted = st.button(
    "Check Carrier Eligibility",
    type="primary",
    use_container_width=True
)

# --- OUTPUT ---
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
        "coastal_tier": coastal_clean,
        "swimming_pool": swimming_pool,
        "pool_accessories": pool_accessories,
        "solar_panels": "Yes" if solar_panels else "No",
        "ppc": ppc
    }

    with st.spinner("Analyzing carrier eligibility..."):
        results = check_eligibility(property_details)

    st.markdown("---")
    st.subheader("CARRIER ELIGIBILITY ANALYSIS")

    eligible = [r for r in results if r["status"] == "ELIGIBLE"]
    not_eligible = [r for r in results if r["status"] != "ELIGIBLE"]

    col_yes, col_no = st.columns(2)

    with col_yes:
        st.markdown("### Eligible")
        if eligible:
            for carrier in eligible:
                with st.expander(carrier["carrier"]):
                    if carrier["reasons"]:
                        st.markdown("**Analysis**")
                        for reason in carrier["reasons"]:
                            st.markdown("- " + reason)
                    if carrier["citations"]:
                        st.markdown("**Citations**")
                        for citation in carrier["citations"]:
                            st.markdown("> " + citation)
                    if carrier["missing_info"]:
                        st.markdown("**Missing Information**")
                        for item in carrier["missing_info"]:
                            st.markdown("- " + item)
        else:
            st.info("No carriers eligible based on provided information.")

    with col_no:
        st.markdown("### Not Eligible")
        if not_eligible:
            for carrier in not_eligible:
                label = carrier["status"].replace("_", " ")
                with st.expander(carrier["carrier"] + "  |  " + label):
                    if carrier["reasons"]:
                        st.markdown("**Analysis**")
                        for reason in carrier["reasons"]:
                            st.markdown("- " + reason)
                    if carrier["citations"]:
                        st.markdown("**Citations**")
                        for citation in carrier["citations"]:
                            st.markdown("> " + citation)
                    if carrier["missing_info"]:
                        st.markdown("**Missing Information**")
                        for item in carrier["missing_info"]:
                            st.markdown("- " + item)
        else:
            st.success("All carriers appear eligible.")

    st.markdown(result)
