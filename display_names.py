"""Round 36 step 5 (Liam, 2026-10-10): the names agents see.

Program names ("Sage_-_Auros_HO3", "Swyfft_-_Benchmark_(Admitted)_HO3") are file names. Everything an agent
reads -- the cards, the Could Not Be Checked lines, the placement panel, Ask the Guides -- shows the display
name instead ("SageSure Auros (HO3)"), and each card's Details names the guide's date and file. Prompts,
citations, the usage and feedback logs, the rules tables and the Manage Carriers tab keep program names.

A program not in the table (a new upload) gets a name made from its file name, never an error.
"""
import re

DISPLAY = {
    "ARI_(HOA+)": "ARI (HOA+)",
    "ARI_(HOB)": "ARI (HOB)",
    "Allied_Trust_HO3": "Allied Trust (HO3)",
    "CHUBB_HO_-_05.22.2026": "Chubb (HO)",
    "Centauri_-_DP3_-_11.16.2022": "Centauri (DP3)",
    "Centauri_-_HO3_-_05.01.2026": "Centauri (HO3)",
    "Foremost_DP3_and_HO3_-_07.01.2026": "Foremost Choice (DP3 and HO3)",
    "HOAIC_-_DP_Guide_DP3": "HOAIC (DP3)",
    "HOAIC_-_TX-HOMEOWNERS-0326_HO3": "HOAIC (HO3)",
    "Liberty_Mutual_DP3_-_02.21.2026": "Liberty Mutual (DP3)",
    "Liberty_Mutual_HO3_-_02.21.2026": "Liberty Mutual (HO3)",
    "Liberty_Mutual_HO6_-_02.21.2026": "Liberty Mutual (HO6)",
    "Mercury_HO3_-_01.01.2026": "Mercury (HO3)",
    "NatGen_Custom360_DP3_-_06.25.2026": "NatGen Custom360 (DP3)",
    "NatGen_Custom360_HO3_-_06.25.2026": "NatGen Custom360 (HO3)",
    "NatGen_Premier_OneChoice_DP3_-_02.26.2025": "NatGen Premier OneChoice (DP3)",
    "NatGen_Premier_OneChoice_HO3_-_02.26.2025": "NatGen Premier OneChoice (HO3)",
    "Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3": "Orion180 Flex (HO3)",
    "Progressive_DP3_-_10.01.2024": "Progressive (DP3)",
    "Progressive_HO3_-_04.01.2026": "Progressive (HO3)",
    "Progressive_HO6_-_10.01.2025": "Progressive (HO6)",
    "Sage_-_Auros_HO3": "SageSure Auros (HO3)",
    "Sage_-_Markel_DP3": "SageSure Markel (DP3)",
    "Sage_-_Markel_HO3": "SageSure Markel (HO3)",
    "Sage_-_Occidental_DP3": "SageSure Occidental (DP3)",
    "Sage_-_Occidental_HO3": "SageSure Occidental (HO3)",
    "Sage_-_SURE_DP-3_-_01.31.2026": "SageSure SURE (DP3)",
    "Sage_-_SURE_HO-3_-_01.31.2026": "SageSure SURE (HO3)",
    "Sage_-_SafePort_DP-3_-_01.31.2026": "SageSure SafePort (DP3)",
    "Sage_-_SafePort_HO-3_-_01.31.2026": "SageSure SafePort (HO3)",
    "Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5_-_02.24.2026": "SageSure Trium Lloyd's Non-Admitted (HO3 / HO5)",
    "Sage_-_Vave_DP3_-_07.01.2026": "SageSure Vave (DP3)",
    "Sage_-_Vave_HO3_-_07.01.2026": "SageSure Vave (HO3)",
    "Sage_-_Wilshire_HO3_-_12.02.2025": "SageSure Wilshire (HO3)",
    "Steadily_Underwriting_Guidelines_DP3": "Steadily (DP3)",
    "Swyfft_-_Benchmark_(Admitted)_HO3": "Swyfft Benchmark Admitted (HO3)",
    "Swyfft_-_Benchmark_(Surplus)_HO3": "Swyfft Benchmark Surplus (HO3)",
    "Swyfft_-_Lloyds_(Surplus)_HO3": "Swyfft Lloyds Surplus (HO3)",
    "Swyfft_-_Topa_(Surplus)_HO3": "Swyfft Topa Surplus (HO3)",
    "TWICO_HO3": "TWICO (HO3)",
    "Travelers_HO3_-_06.12.2026": "Travelers (HO3)",
}

# Dates the file name writes in a form data_defects.guide_date does not read (it reads MM.DD.YYYY).
OTHER_DATES = {
    "Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3": "07/06/2026",
    "HOAIC_-_TX-HOMEOWNERS-0326_HO3": "03/2026",
}
_FORM = re.compile(r"_?(HO-?3_HO5|HO-?\d|DP-?\d|HO)$")


def display_name(program):
    """The name an agent sees for a program (a file-name fallback for one not in the table)."""
    program = program or ""
    if program in DISPLAY:
        return DISPLAY[program]
    name = re.sub(r"_-_\d{2}\.\d{2}\.\d{2,4}", "", program)
    form = _FORM.search(name)
    base = name[:form.start()] if form else name
    base = re.sub(r"[_]+", " ", base).replace(" - ", " ").strip(" -")
    return f"{base} ({form.group(1).replace('-', '').replace('_', ' / ')})" if form else base or program


def guide_date(program):
    """MM/DD/YYYY (or MM/YYYY) from the file name, or None when the file name has no date."""
    if program in OTHER_DATES:
        return OTHER_DATES[program]
    m = re.search(r"(\d{2}\.\d{2}\.\d{4})", program or "")   # data_defects.guide_date's rule
    d = m.group(1) if m else None
    return d.replace(".", "/") if d else None


def guide_line(program):
    """The Details line: the guide's date and its file."""
    d = guide_date(program)
    return (f"Guide dated {d} (file: {program})" if d
            else f"Guide date: not in the file name (file: {program})")
