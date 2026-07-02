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

with st.form("eligibility_form"):

    # LOCATION
    st.subheader("📍 Location")
    col1, col2 = st.columns(2)

    with col1:
        state = st.selectbox("State", [
            "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA",
            "HI","ID","IL","IN","IA","KS","KY","LA","ME","MD",
            "MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
            "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC",
            "SD","TN","TX","UT","VT","VA","WA","WV","WI","WY"
        ])
        ppc = st.selectbox("PPC Number", [
            "1","2","3","4","5","6","7","8","8A","8B","9","10"
        ])

    with col2:
        coastal = st.toggle("Coastal Property",
            help="Within 1 mile of coastline or tidal waters")
        occupancy_type = st.selectbox("Occupancy Type", [
            "Owner Occupied",
            "Tenant Occupied",
            "Seasonal",
            "Vacant",
            "Secondary Home"
        ])

    st.divider()

    # PROPERTY AGE
    st.subheader("📅 Property Age")
    col1, col2 = st.columns(2)

    with col1:
        year_built = st.number_input("Year Built",
            min_value=1800, max_value=2026, value=2000)

    with col2:
        roof_age = st.number_input("Roof Age (years)",
            min_value=0, max_value=100, value=10,
            placeholder="e.g. 10")

    st.divider()

    # CONSTRUCTION DETAILS
    st.subheader("🛡️ Construction Details")
    col1, col2 = st.columns(2)

    with col1:
        roof_type = st.selectbox("Roof Type", [
            "Composition Shingle",
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
        solar_panels = st.toggle("Solar Panels",
            help="Does the property have solar panels installed?")

    st.divider()

    submitted = st.form_submit_button(
        "Check Carrier Eligibility",
        use_container_width=True,
        type="primary"
    )

# Run eligibility check when form is submitted
if submitted:
    property_details = {
        "state": state,
        "year_built": year_built,
        "roof_age": roof_age,
        "roof_type": roof_type,
        "roof_shape": roof_shape,
        "construction_type": construction_type,
        "plumbing_type": plumbing_type,
        "occupancy_type": occupancy_type,
        "coastal": "Yes" if coastal else "No",
        "swimming_pool": swimming_pool,
        "solar_panels": "Yes" if solar_panels else "No",
        "ppc": ppc
    }

    with st.spinner("Analyzing carrier eligibility..."):
        result = check_eligibility(property_details)

    st.success("Analysis Complete")
    st.markdown("---")
    st.markdown(result)
