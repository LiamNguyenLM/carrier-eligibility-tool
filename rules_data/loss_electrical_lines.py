"""Round 37 step 4 (Liam, 2026-10-10): the loss-history and electrical rows decided from two new optional form
questions. Shared by the four map builders (build_rule_field_map.py, build_sage_batch_map.py,
build_ho3_batch_map.py, build_remaining_batch_map.py): each takes LINES for a row it leaves NONE.

The form (intake_fields):
  losses_5yr       "Losses in the last 5 years": 0 / 1 / 2 / 3 or more / Unknown
  loss_types       if 1 or more: Water / Fire / Liability / Wind or hail / Theft / Other (any that apply)
  loss_year        if 1 or more: the most recent loss's year
  losses_3yr       if 1 or more: how many of them in the last 3 years (0 / 1 / 2 / 3 or more) -- the one extra
                   question, asked because the 3-year rules (e.g. "3 or more claims in the last 3 years") need it.
                   rules_evaluator.facts() reads 0 for it when the 5-year answer is 0, or when the most recent
                   loss is more than 3 years old.
  electrical       Circuit breakers / Fuses / Federal Pacific or Zinsco panel / Knob-and-tube wiring / Aluminum
                   branch wiring / Unknown (any that apply)

Blank or Unknown is never a hold: these fields are in rules_evaluator.CONFIRM_FIELDS, so a row left open by them
(alone or with a FACT) is a "Confirm:" note.

How a rule reads the answers (the templates below), following each guide's own words:
  - a count over 5 years reads losses_5yr; over 3 years (or 36 months) losses_3yr; over 12 months it passes only
    on 0 in 3 years and is otherwise a confirm. "3 or more" decides a "3 or more" rule; a rule that allows 3 is a
    confirm on that answer.
  - a loss type is read from loss_types: "Act of Nature" / weather / CAT is Wind or hail; "Other" might be any
    peril the options do not name, so it never proves a type -- it leaves a confirm, never a decline.
  - a rule over a longer window ("6 years", "ever", "any prior", no window) can be failed by what the 5 years
    show, and is otherwise a confirm: the form does not ask about older losses.
  - a dollar amount ("over $25,000") is never asked: such a rule passes on 0 losses, else it is a confirm.
Rows the new answers cannot decide stay NONE (UNDECIDED below, with the reason): prior insurance, cancellations
and lapses, open or disputed claims, fraud and misrepresentation, repairs and remediation, mold, sinkholes,
appliance and animal-bite claims, same-peril / similar losses, renewals, multiple locations, electrical service
amps, panel brands the form does not name (Square D, Pushmatic), double-tapped / cloth wiring, and rows that only
mention a loss or a panel (smoke detectors near the breaker panel, aluminum siding).
"""

W, F, L, H, T, O = "Water", "Fire", "Liability", "Wind or hail", "Theft", "Other"
ALL_TYPES = (W, F, L, H, T, O)
COUNTS = ("0", "1", "2", "3 or more")
BREAKERS, FUSES, FPE, KT, AL = ("Circuit breakers", "Fuses", "Federal Pacific or Zinsco panel", "Knob-and-tube wiring",
                                "Aluminum branch wiring")


def _set(xs):
    return "{" + ", ".join(xs) + "}"


def _below(var, k, fact):
    """True when the count in var is under k; "3 or more" with k >= 4 is a confirm (fact)."""
    ok = [c for c in COUNTS[:3] if int(c) < k]
    test = f"{var} in {_set(ok)}" if ok else ""
    if k >= 4:
        test = f"{test} or ({var} in {{3 or more}} and FACT({fact}))" if test else f"FACT({fact})"
    return test


def _var(window):
    return {5: "losses_5yr", 3: "losses_3yr"}[window]


def count(window, k, fact, types=None, maybe=(O,)):
    """Fewer than k losses (of `types`, default any) in `window` years passes.

    With types: passes when the types answered hold none of `types` (nor a `maybe` type); fails only when every
    loss answered is of `types` (so all k+ of them count); anything else is a confirm."""
    if types is None:
        return _below(_var(window), k, fact)
    maybe = tuple(m for m in maybe if m not in types)
    others = tuple(t for t in ALL_TYPES if t not in types)
    base = _below(_var(window), k, fact)
    if k == 1:
        # one loss of the type is enough to fail
        cond = f"loss_types none_of {_set(types)}"
        if maybe:
            cond += f" and (loss_types none_of {_set(maybe)} or FACT({fact}))"
        return f"{base} or ({cond})"
    return (f"{base} or loss_types none_of {_set(types + maybe)} or "
            f"(not (loss_types none_of {_set(others)}) and FACT({fact}))")


def amount(window, fact, types=None):
    """A dollar threshold the form never asks: passes on 0 losses (of `types`) in the window, else a confirm."""
    base = f"{_var(window)} in {{0}}"
    if types:
        base += f" or loss_types none_of {_set(types + ((O,) if O not in types else ()))}"
    return f"{base} or FACT({fact})"


def ever(inner, fact):
    """A rule with no window (or one longer than 5 years): the 5 years can fail it; passing needs the older
    history, which the form does not ask."""
    return f"({inner}) and FACT({fact})"


def months12(fact, types=None):
    """A 12-month rule: passes on no loss (of `types`) in 3 years, else a confirm."""
    base = "losses_3yr in {0}"
    if types:
        base += f" or loss_types none_of {_set(types + ((O,) if O not in types else ()))}"
    return f"{base} or FACT({fact})"


NON_WEATHER = (W, F, L, T)        # Other might be weather or not: never proves either
WEATHER = (H,)
ALL_OTHER = (H, O)                # "All Other Losses": anything but water, fire, theft or liability

LOSS_FIELDS = "losses_5yr;losses_3yr;loss_types"

# row -> test. Every line's field is LOSS_FIELDS and its gate "always".
LOSS = {
    # ---- Allied Trust HO3 (pilot)
    "ALL-142": count(5, 1, "no liability claim in the last 5 years", (L,), ()),
    "ALL-143": count(5, 1, "no fire claim in the last 5 years", (F,), ()),
    "ALL-144": count(3, 3, "fewer than 3 claims in the last 3 years"),
    "ALL-145": count(5, 1, "no liability claim in the previous 5 years", (L,), ()),
    "ALL-146": count(5, 1, "no fire or smoke claim in the previous 5 years", (F,), ()),
    "ALL-147": count(5, 2, "fewer than 2 losses in 5 years other than natural causes", NON_WEATHER),
    "ALL-150": count(5, 2, "no more than 1 theft or vandalism claim in 5 years", (T,)),
    "ALL-151": amount(3, "no non-weather loss of $20000 or more in the previous 3 years", NON_WEATHER),
    # ---- Sage Auros (pilot) and the Sage family's 3-year / 6-year counts
    "SAG-112": count(3, 3, "no more than 2 losses in the prior 3 years"),
    "SAG-113": ever(count(5, 4, "no more than 3 losses in the last 6 years"), "no more than 3 losses in the last 6 years"),
    "SUR-083": count(3, 3, "no more than 2 losses in the prior 3 years"),
    "SUR-084": ever(count(5, 4, "no more than 3 losses in the last 6 years"), "no more than 3 losses in the last 6 years"),
    "SFP-088": count(3, 3, "no more than 2 losses in the prior 3 years"),
    "SFP-089": ever(count(5, 4, "no more than 3 losses in the last 6 years"), "no more than 3 losses in the last 6 years"),
    "WIL-089": count(3, 3, "no more than 2 losses in the prior 3 years"),
    "WIL-090": ever(count(5, 4, "no more than 3 losses in the last 6 years"), "no more than 3 losses in the last 6 years"),
    "TRI-129": count(3, 3, "no more than 2 losses in the prior 3 years"),
    "TRI-130": ever(count(5, 4, "no more than 3 losses in the last 6 years"), "no more than 3 losses in the last 6 years"),
    "ODP-126": count(3, 3, "no more than 2 losses in the prior 3 years"),
    "ODP-127": ever(count(5, 4, "no more than 3 losses in the last 6 years"), "no more than 3 losses in the last 6 years"),
    "SDP-063": ever(count(3, 3, "no more than 2 losses in 3 years or 3 in 6 years"),
                    "no more than 3 losses in the last 6 years"),
    "FDP-084": count(3, 3, "no more than 2 losses in the prior 3 years"),
    "FDP-085": ever(count(5, 4, "no more than 3 losses in the last 6 years"), "no more than 3 losses in the last 6 years"),
    # ---- Chubb
    "CHU-062": count(3, 1, "no negligence-based liability claim in the previous 3 years", (), (L,)),
    "CHU-063": count(3, 2, "fewer than 2 paid non-weather non-water claims in 3 years", (F, L, T)),
    "CHU-067": amount(5, "no non-water paid claim over $50000 in 5 years", (F, L, H, T)),
    "CHU-073": ever(count(5, 1, "no loss history"), "no losses before the last 5 years"),
    # ---- Mercury
    "MER-087": count(5, 1, "no non-weather loss in the last 5 years", NON_WEATHER),
    "MER-088": count(5, 2, "fewer than 2 losses in the last 5 years"),
    "MER-089": count(3, 2, "no more than 1 paid non-appliance water claim in 3 years", (), (W,)),
    # ---- Progressive HO3 / DP3 / HO6
    "PRO-094": count(5, 3, "fewer than 3 claims in 5 years"),
    "PRO-096": count(5, 2, "fewer than 2 claims in 5 years"),
    "PRO-097": count(5, 1, "no liability claim in 5 years", (L,), ()),
    "PDP-058": count(5, 3, "fewer than 3 claims in 5 years"),
    "PDP-060": count(5, 2, "fewer than 2 claims in 5 years"),
    "PDP-061": count(5, 1, "no liability claim in 5 years", (L,), ()),
    "PH6-038": count(5, 3, "fewer than 3 claims in 5 years"),
    "PH6-040": count(5, 2, "fewer than 2 claims in 5 years"),
    "PH6-041": count(5, 1, "no liability claim in the last 5 years", (L,), ()),
    # ---- Swyfft / Steadily family (same wording)
    "SWY-047": count(3, 5, "no more than 4 non-weather losses in 3 years", NON_WEATHER),
    "SWY-051": ever(count(5, 1, "no prior liability or fire loss", (L, F), ()), "no liability or fire loss before the last 5 years"),
    "SBS-050": ever(count(5, 2, "no more than 1 non-weather loss", NON_WEATHER), "no more than 1 non-weather loss before the last 5 years"),
    "SBS-056": ever(count(5, 1, "no prior liability or fire loss", (L, F), ()), "no liability or fire loss before the last 5 years"),
    "SLL-071": count(3, 2, "no more than 1 non-weather loss in 3 years", NON_WEATHER),
    "SLL-081": ever(count(5, 1, "no prior liability or fire loss", (L, F), ()), "no liability or fire loss before the last 5 years"),
    "STO-053": ever(count(5, 2, "no more than 1 non-weather loss", NON_WEATHER), "no more than 1 non-weather loss before the last 5 years"),
    "STO-059": ever(count(5, 1, "no prior liability or fire loss", (L, F), ()), "no liability or fire loss before the last 5 years"),
    # ---- Markel
    "MKL-104": amount(5, "no fire loss over $25000 in the past 5 years", (F,)),
    "MKL-105": amount(5, "no loss over $100000 in the last 5 years"),
    "MKL-106": count(5, 4, "fewer than 4 losses in the last 5 years"),
    "MDP-087": amount(5, "no fire loss over $25000 in the past 5 years", (F,)),
    "MDP-088": amount(5, "no loss over $100000 in the last 5 years"),
    "MDP-089": count(5, 4, "fewer than 4 losses in the last 5 years"),
    # ---- Vave
    "VAV-089": amount(3, "no non-cat or liability loss over $25000 in the last 3 years", NON_WEATHER),
    "VAV-090": count(3, 2, "fewer than 2 non-cat or liability losses in 3 years", NON_WEATHER),
    "VAV-093": amount(3, "no water loss over $25000 in the last 3 years", (W,)),
    "VAV-094": amount(3, "no water loss over $25000 in the last 3 years", (W,)),
    "VDP-051": amount(3, "no non-cat loss or liability claim over $25000 in the last 3 years", NON_WEATHER),
    "VDP-052": count(3, 2, "fewer than 2 non-cat losses or liability claims in 3 years", NON_WEATHER),
    "VDP-055": amount(3, "no water loss over $25000 in the last 3 years", (W,)),
    # ---- ARI HOA+ / HOB
    "ARA-065": count(5, 2, "at most 1 Act of Nature claim in the past 5 years", WEATHER),
    "ARA-066": count(3, 1, "no All Other Losses in the past 3 years", ALL_OTHER, ()),
    "ARA-067": count(5, 2, "fewer than 2 All Other Losses in the past 5 years", ALL_OTHER, ()),
    "ARA-068": count(3, 2, "fewer than 2 losses under $15000 in 3 years", (), ALL_TYPES),
    "ARA-069": count(5, 3, "fewer than 3 losses under $15000 in the past 5 years", (), ALL_TYPES),
    "ARA-071": count(5, 1, "no water fire theft or liability loss in the past 5 years", (W, F, T, L)),
    "ARA-072": amount(5, "no loss paying $15000 or more within 5 years"),
    "ARB-064": count(5, 1, "no liability claim within 5 years", (L,), ()),
    "ARB-065": count(3, 2, "fewer than 2 water losses within 3 years", (W,)),
    "ARB-066": amount(5, "no fire loss with a payout of $10000 or more within 5 years", (F,)),
    "ARB-067": count(5, 1, "no theft loss within 5 years", (T,)),
    "ARB-068": count(5, 2, "fewer than 2 Act of Nature claims within 5 years", WEATHER),
    "ARB-069": count(3, 1, "no All Other Losses within 3 years", ALL_OTHER, ()),
    "ARB-070": count(5, 2, "fewer than 2 All Other Losses within 5 years", ALL_OTHER, ()),
    "ARB-071": count(3, 2, "fewer than 2 losses under $15000 within 3 years", (), ALL_TYPES),
    "ARB-072": count(5, 3, "fewer than 3 losses under $15000 within 5 years", (), ALL_TYPES),
    "ARB-074": count(5, 1, "no water fire theft or liability loss in the past 5 years", (W, F, T, L)),
    "ARB-075": amount(5, "no loss with a payout of $15000 or more within 5 years"),
    # ---- Foremost (new business)
    "FOR-106": ever(count(5, 1, "no fire or smoke paid loss", (F,)), "no fire or smoke paid loss before the last 5 years"),
    "FOR-107": ever(count(5, 3, "fewer than 3 paid losses"), "fewer than 3 paid losses counting losses before the last 5 years"),
    "FOR-117": count(5, 1, "no intentional or careless fire loss in the past 5 years", (), (F,)),
    "FOR-121": count(5, 2, "no loss severity or multiple losses in the past 5 years"),
    "FOR-123": amount(5, "no fire loss over $5000 in the past 5 years", (F,)),
    "FOD-035": ever(count(5, 3, "fewer than 3 paid losses and fewer than 2 fire or water losses"),
                    "fewer than 3 paid losses and fewer than 2 fire smoke or water losses at this location"),
    "FOD-036": ever(count(5, 3, "fewer than 3 paid losses and fewer than 2 fire or water losses"),
                    "fewer than 3 paid losses and fewer than 2 fire smoke or water losses at this location"),
    # ---- Liberty Mutual
    "LIB-055": count(5, 2, "no more than 1 loss in the prior 5 years"),
    "LDP-062": count(5, 2, "no more than 1 loss in the prior 5 years"),
    "LDP-063": count(5, 2, "no multiple property claims in the last 5 years", (W, F, H, T)),
    # ---- Orion180
    "ORI-037": count(5, 2, "fewer than 2 liability fire or water claims in the past 5 years", (L, F, W)),
    "ORI-038": count(5, 3, "fewer than 3 property claims in the past 5 years", (W, F, H, T)),
    # ---- TWICO
    "TWI-021": ever(amount(5, "no non-weather loss over $30000", NON_WEATHER), "no non-weather loss over $30000 before the last 5 years"),
    "TWI-023": count(3, 3, "fewer than 3 claims within 3 years"),
    # ---- Travelers
    "TRV-012": count(3, 2, "no more than 1 paid water damage claim in the past 3 years", (W,)),
    "TRV-063": amount(3, "no weather loss of $100000 or more in the past 3 years", WEATHER),
    "TRV-066": count(5, 1, "no water damage claim or non-catastrophe weather water loss in the past 5 years", (W,)),
    # ---- Centauri DP3
    "CDP-099": count(3, 3, "fewer than 3 paid claims within 3 years"),
    "CDP-100": count(3, 1, "no paid liability claim within 3 years", (L,), ()),
    "CDP-102": count(5, 2, "fewer than 2 paid claims within 5 years"),
    "CHO-031": ever(count(5, 2, "no more than 1 non-weather loss", NON_WEATHER), "no more than 1 non-weather loss before the last 5 years"),
    "CHO-034": ever(count(5, 1, "no liability or fire claim", (L, F), ()), "no liability or fire claim before the last 5 years"),
    # ---- NatGen DP3 / Premier
    "NCD-145": count(3, 3, "at most 2 paid losses in 3 years across all landlord properties"),
    "NCD-146": count(3, 2, "no more than 1 loss at this location in 3 years"),
    "NCD-150": count(5, 1, "no non-remediated mold fire vandalism theft or flood loss in the last 5 years", (F, T), (W, O)),
    # ---- Stillwater (single location)
    "STD-141": ever(count(5, 3, "no more than 2 water losses", (W,)), "no more than 2 water losses counting older losses"),
    "STD-142": ever(count(5, 2, "no more than 1 fire loss", (F,)), "no more than 1 fire loss counting older losses"),
    "STD-143": ever(count(5, 3, "no more than 2 wind or hail losses", (H,)), "no more than 2 wind or hail losses counting older losses"),
    "STD-144": ever(count(5, 2, "no more than 1 theft loss", (T,)), "no more than 1 theft loss counting older losses"),
    "STD-145": ever(count(5, 2, "no more than 1 liability loss", (L,)), "no more than 1 liability loss counting older losses"),
    "STD-146": ever(count(5, 3, "no more than 2 other losses", (O,), ()), "no more than 2 other losses counting older losses"),
    "STD-154": ever(amount(5, "no non-weather loss over $100000", NON_WEATHER), "no non-weather loss over $100000 before the last 5 years"),
    "STD-155": ever(amount(5, "no fire loss over $30000", (F,)), "no fire loss over $30000 before the last 5 years"),
    "STD-156": ever(amount(5, "no theft liability or water loss over $15000", (T, L, W)),
                    "no theft liability or water loss over $15000 before the last 5 years"),
    "SLL-021": ever(amount(5, "no water loss over $25000", (W,)), "no water loss over $25000 before the last 5 years"),
}
# Round 38 step 3 (Liam, 2026-10-11): a row decides from count, type and years only where the guide's condition
# is just those. Where it also turns on paid / $0, an amount, remediated or open, negligence, weather vs non-weather
# (a Water loss can be either) or same-peril / per-location counts, an answer that could fail is a confirm naming
# the condition; 0 losses still passes. Audited row by row against the guides' pages (four reviewers, one per
# table; every proposed line checked to never fail where the extra condition is unknown). Steadily counts
# exactly 5 years (p.6), so its rows lose the "counting older losses" confirm. CHU-073: a confirm, never a
# referral -- the form's loss types cover 5 years, its rule 3.
ROUND38_LOSS = {
    'ALL-146': 'losses_5yr in {0} or (loss_types none_of {Fire} and (loss_types none_of {Other} or FACT(no fire or smoke claim in the previous 5 years)))',  # other: smoke claims are not a named form type and may be entered as Other
    'ALL-147': 'losses_5yr in {0, 1} or loss_types none_of {Water, Fire, Liability, Theft, Other} or (not (loss_types none_of {Water, Fire, Wind or hail, Other}) and FACT(fewer than 2 losses in 5 years other than natural causes such as weather or lightning))',  # weather_vs_nonweather
    'ALL-151': 'losses_3yr in {0} or loss_types none_of {Fire, Liability, Theft, Other} or FACT(no non-weather loss paying $20000 or more in the previous 3 years, other than water, mold or appliance-related claims)',  # amount,paid,weather_vs_nonweather
    'ARA-065': 'losses_5yr in {0, 1} or loss_types none_of {Wind or hail, Water, Other} or (not (loss_types none_of {Fire, Liability, Theft, Water, Other}) and FACT(at most 1 Act of Nature claim in the past 5 years))',  # weather_vs_nonweather
    'ARA-066': 'losses_3yr in {0} or loss_types none_of {Wind or hail, Other} or FACT(no All Other Losses in the past 3 years - ARI defines these as losses other than water, fire, theft or liability; confirm whether ARI counts a wind or hail claim here)',  # other: unclear whether Act of Nature wind/hail claims count as All Other Losses, since ARI
    'ARA-067': 'losses_5yr in {0, 1} or loss_types none_of {Wind or hail, Other} or FACT(fewer than 2 All Other Losses in the past 5 years - losses other than water, fire, theft or liability; confirm whether ARI counts wind or hail claims here)',  # other: unclear whether Act of Nature wind/hail claims count as All Other Losses, since ARI
    'ARB-068': 'losses_5yr in {0, 1} or loss_types none_of {Wind or hail, Water, Other} or (not (loss_types none_of {Fire, Liability, Theft, Water, Other}) and FACT(fewer than 2 Act of Nature claims within 5 years))',  # weather_vs_nonweather
    'ARB-069': 'losses_3yr in {0} or loss_types none_of {Wind or hail, Other} or FACT(no All Other Losses within 3 years - ARI defines these as losses other than water, fire, theft or liability; confirm whether ARI counts a wind or hail claim here)',  # other: unclear whether Act of Nature wind/hail claims count as All Other Losses, since ARI
    'ARB-070': 'losses_5yr in {0, 1} or loss_types none_of {Wind or hail, Other} or FACT(fewer than 2 All Other Losses within 5 years - losses other than water, fire, theft or liability; confirm whether ARI counts wind or hail claims here)',  # other: unclear whether Act of Nature wind/hail claims count as All Other Losses, since ARI
    'CDP-099': 'losses_3yr in {0, 1, 2} or FACT(fewer than 3 paid claims in the last 3 years)',  # paid
    'CDP-100': 'losses_3yr in {0} or loss_types none_of {Liability} or FACT(no paid liability claim in the last 3 years)',  # paid,other: the form's loss types cover 5 years, so a Liability pick may be older than 3 y
    'CDP-102': 'losses_5yr in {0, 1} or FACT(fewer than 2 paid claims in the last 5 years)',  # paid
    'CHO-031': '(losses_5yr in {0, 1} or loss_types none_of {Water, Fire, Liability, Theft, Other} or (not (loss_types none_of {Water, Wind or hail, Other}) and FACT(no more than 1 non-weather loss))) and FACT(no more than 1 non-weather loss before the last 5 years)',  # weather_vs_nonweather
    'CHU-063': 'losses_3yr in {0, 1} or loss_types none_of {Fire, Liability, Theft, Other} or FACT(fewer than 2 paid non-weather non-water claims in 3 years)',  # paid,weather_vs_nonweather
    'CHU-073': 'losses_3yr in {0} or (losses_3yr in {1} and loss_types none_of {Fire, Liability, Wind or hail, Theft, Other}) or FACT(no loss in the last 3 years other than a single water loss, properly remediated mold or appliance claims, or CAT losses at another location)',  # remediated,weather,3-year window,single water loss accepted
    'FDP-084': 'losses_3yr in {0, 1, 2} or FACT(no more than 2 non-zero losses in the prior 3 years not counting WDR-1 or MDR-1 certified claims)',  # paid,other: appliance water claims certified on WDR-1 and mold claims certified on MDR-1 a
    'FOD-035': 'losses_5yr in {0, 1} or (losses_5yr in {2} and loss_types none_of {Water, Fire, Other}) or FACT(fewer than 3 paid losses and fewer than 2 paid fire smoke water appliance water plumbing or accidental discharge losses in the last 5 years not counting WDR-1 or MDR-1 certified claims)',  # paid,weather_vs_nonweather,other: WDR-1 and MDR-1 certified losses do not count
    'FOD-036': 'losses_5yr in {0, 1} or (losses_5yr in {2} and loss_types none_of {Water, Fire, Other}) or FACT(fewer than 3 paid losses and fewer than 2 paid fire smoke water appliance water plumbing or accidental discharge losses in the last 5 years not counting WDR-1 or MDR-1 certified claims)',  # paid,weather_vs_nonweather,other: WDR-1 and MDR-1 certified losses do not count
    'FOR-106': 'losses_5yr in {0} or loss_types none_of {Fire, Other} or FACT(no paid fire or smoke loss in the past 5 years)',  # paid
    'FOR-107': 'losses_5yr in {0, 1, 2} or FACT(fewer than 3 paid losses in the past 5 years, not counting appliance-related water or mold losses with a WDR-1 or MDR-1 remediation certificate)',  # paid,remediated_or_open,other: appliance-related water and mold losses with a WDR-1/MDR-1 
    'FOR-121': 'losses_5yr in {0} or (losses_5yr in {1} and FACT(the one loss in the past 5 years was not a severe loss))',  # amount,remediated_or_open
    'MER-087': 'losses_5yr in {0} or (losses_5yr in {1} and loss_types none_of {Fire, Liability, Wind or hail, Theft, Other}) or loss_types none_of {Water, Fire, Liability, Theft, Other} or FACT(no paid non-weather loss to the home or personal possessions in the last 5 years other than a single non-weather water loss or remediated appliance water or mold losses)',  # paid,weather_vs_nonweather,remediated_or_open,other: a single non-weather water loss alone
    'MER-088': 'losses_5yr in {0, 1} or FACT(fewer than 2 paid losses to the home or personal possessions in the last 5 years, not counting remediated appliance water or mold losses)',  # paid,remediated_or_open,other: only losses to the home or personal possessions count
    'MKL-104': 'losses_5yr in {0} or loss_types none_of {Fire, Other} or FACT(no fire loss over $25000 in the past 5 years other than one caused by wildfire or lightning)',  # amount,other: fire excluding wildfire or lightning cause
    'NCD-145': 'losses_3yr in {0, 1, 2} or FACT(no more than 2 paid losses in the last 3 years across all landlord properties of the applicant)',  # paid,other: only losses at landlord properties count; equipment breakdown, identity theft 
    'NCD-146': 'losses_3yr in {0, 1} or FACT(no more than 1 loss at any one landlord property in the last 3 years)',  # other: per risk location; losses at the applicant's own non-landlord homes are not counted
    'NCD-150': 'losses_5yr in {0} or loss_types none_of {Fire, Theft, Water, Other} or FACT(any mold fire vandalism theft or flood loss in the last 5 years was fully remediated)',  # remediated_or_open,at_fault_or_negligence
    'ODP-126': 'losses_3yr in {0, 1, 2} or FACT(no more than 2 non-zero losses in the prior 3 years not counting WDR-1 or MDR-1 certified claims)',  # paid,other: appliance water claims certified on WDR-1 and mold claims certified on MDR-1 a
    'SAG-112': 'losses_3yr in {0, 1, 2} or FACT(no more than 2 non-zero losses in the prior 3 years, not counting appliance water or mold claims certified by TDI form WDR-1 or MDR-1)',  # paid,remediated_or_open,other: WDR-1 / MDR-1 certified appliance-water and mold claims are
    'SBS-050': '(losses_5yr in {0, 1} or loss_types none_of {Water, Fire, Liability, Theft, Other} or (not (loss_types none_of {Water, Wind or hail, Other}) and FACT(no more than 1 non-weather loss))) and FACT(no more than 1 non-weather loss before the last 5 years)',  # weather_vs_nonweather,other: no time window, older losses count
    'SDP-063': '(losses_3yr in {0, 1, 2} or FACT(no more than 2 non-zero losses in the prior 3 years not counting WDR-1 or MDR-1 certified claims)) and FACT(no more than 3 non-zero losses in the last 6 years not counting WDR-1 or MDR-1 certified claims)',  # paid,other: appliance water claims certified on WDR-1 and mold claims certified on MDR-1 a
    'SFP-088': 'losses_3yr in {0, 1, 2} or FACT(no more than 2 non-zero paid losses of any type in the prior 3 years, not counting appliance water claims certified on TDI form WDR-1 or mold claims certified on TDI form MDR-1)',  # paid,other: WDR-1 / MDR-1 certified appliance-water and mold claims are not counted
    'SFP-089': 'FACT(no more than 3 non-zero paid losses of any type in the last 6 years, not counting appliance water claims certified on TDI form WDR-1 or mold claims certified on TDI form MDR-1)',  # paid,other: 6-year window, form only asks 5 years,other: WDR-1 / MDR-1 certified claims no
    'SLL-071': 'losses_3yr in {0, 1} or loss_types none_of {Water, Fire, Liability, Theft, Other} or (not (loss_types none_of {Water, Wind or hail, Other}) and FACT(no more than 1 non-weather loss in 3 years, counting $0 paid claims))',  # weather_vs_nonweather
    'STD-141': 'losses_5yr in {0, 1, 2} or loss_types none_of {Water, Other} or (not (loss_types none_of {Fire, Liability, Wind or hail, Theft, Other}) and FACT(no more than 2 water losses in the last 5 years))',  # 
    'STD-142': 'losses_5yr in {0, 1} or loss_types none_of {Fire, Other} or (not (loss_types none_of {Water, Liability, Wind or hail, Theft, Other}) and FACT(no more than 1 fire loss in the last 5 years))',  # 
    'STD-143': 'losses_5yr in {0, 1, 2} or loss_types none_of {Wind or hail, Other} or FACT(no more than 2 wind or hail losses at the insured location in the last 5 years)',  # other: only wind or hail losses at the insured location count
    'STD-144': 'losses_5yr in {0, 1} or loss_types none_of {Theft, Other} or (not (loss_types none_of {Water, Fire, Liability, Wind or hail, Other}) and FACT(no more than 1 theft loss in the last 5 years))',  # 
    'STD-145': 'losses_5yr in {0, 1} or loss_types none_of {Liability, Other} or (not (loss_types none_of {Water, Fire, Wind or hail, Theft, Other}) and FACT(no more than 1 liability loss in the last 5 years))',  # 
    'STD-146': 'losses_5yr in {0, 1, 2} or loss_types none_of {Other} or (not (loss_types none_of {Water, Fire, Liability, Wind or hail, Theft}) and FACT(no more than 2 other losses in the last 5 years))',  # 
    'STD-154': 'losses_5yr in {0} or loss_types none_of {Water, Fire, Liability, Theft, Other} or FACT(no non-weather loss over $100000 in the last 5 years)',  # amount,weather_vs_nonweather
    'STD-155': 'losses_5yr in {0} or loss_types none_of {Fire, Other} or FACT(no fire loss over $30000 in the last 5 years)',  # amount
    'STD-156': 'losses_5yr in {0} or loss_types none_of {Theft, Liability, Water, Other} or FACT(no theft liability or water loss over $15000 in the last 5 years)',  # amount
    'STO-053': '(losses_5yr in {0, 1} or loss_types none_of {Water, Fire, Liability, Theft, Other} or (not (loss_types none_of {Water, Wind or hail, Other}) and FACT(no more than 1 non-weather loss))) and FACT(no more than 1 non-weather loss before the last 5 years)',  # weather_vs_nonweather,other: no time window, older losses count
    'SUR-083': 'losses_3yr in {0, 1, 2} or FACT(no more than 2 non-zero paid losses of any type in the prior 3 years, not counting appliance water claims certified on TDI form WDR-1 or mold claims certified on TDI form MDR-1)',  # paid,other: WDR-1 / MDR-1 certified appliance-water and mold claims are not counted
    'SUR-084': 'FACT(no more than 3 non-zero paid losses of any type in the last 6 years, not counting appliance water claims certified on TDI form WDR-1 or mold claims certified on TDI form MDR-1)',  # paid,other: 6-year window, form only asks 5 years,other: WDR-1 / MDR-1 certified claims no
    'TRI-129': 'losses_3yr in {0, 1, 2} or FACT(no more than 2 non-zero paid losses of any type in the prior 3 years, not counting appliance water claims certified on TDI form WDR-1 or mold claims certified on TDI form MDR-1)',  # paid,other: WDR-1 / MDR-1 certified appliance-water and mold claims are not counted
    'TRI-130': 'FACT(no more than 3 non-zero paid losses of any type in the last 6 years, not counting appliance water claims certified on TDI form WDR-1 or mold claims certified on TDI form MDR-1)',  # paid,other: 6-year window, form only asks 5 years,other: WDR-1 / MDR-1 certified claims no
    'TRV-012': 'losses_3yr in {0, 1} or loss_types none_of {Water, Other} or FACT(no more than 1 paid plumbing-failure water damage claim in the past 3 years, by the applicant or at the risk location, not counting appliance-related claims)',  # paid,weather_vs_nonweather,other: appliance-related water claims are a separate category a
    'TRV-063': 'losses_3yr in {0} or loss_types none_of {Wind or hail, Water, Other} or FACT(no weather loss of $100000 or more in the past 3 years, including CATs)',  # amount,weather_vs_nonweather
    'TRV-066': 'losses_5yr in {0} or loss_types none_of {Water, Other} or FACT(no water damage claim and no non-catastrophe weather water loss in the past 5 years at the premises, including before ownership)',  # weather_vs_nonweather,other: CAT vs non-CAT weather water loss,other: appliance-related wa
    'VAV-090': 'losses_3yr in {0, 1} or loss_types none_of {Water, Fire, Liability, Theft, Other} or (not (loss_types none_of {Water, Fire, Wind or hail, Other}) and FACT(fewer than 2 losses from non-cat causes or liability claims in the last 3 years))',  # weather_vs_nonweather
    'VDP-052': 'losses_3yr in {0, 1} or loss_types none_of {Water, Fire, Liability, Theft, Other} or (not (loss_types none_of {Water, Wind or hail, Other}) and FACT(fewer than 2 non-cat losses or liability claims in the last 3 years))',  # weather_vs_nonweather
    'WIL-089': 'losses_3yr in {0, 1, 2} or FACT(no more than 2 non-zero paid losses of any type in the prior 3 years, not counting appliance water claims certified on TDI form WDR-1 or mold claims certified on TDI form MDR-1)',  # paid,other: WDR-1 / MDR-1 certified appliance-water and mold claims are not counted
    'WIL-090': 'FACT(no more than 3 non-zero paid losses of any type in the last 6 years, not counting appliance water claims certified on TDI form WDR-1 or mold claims certified on TDI form MDR-1)',  # paid,other: 6-year window, form only asks 5 years,other: WDR-1 / MDR-1 certified claims no
}
LOSS.update(ROUND38_LOSS)

# ---- electrical: row -> test
def none_of(*xs):
    return f"electrical none_of {_set(xs)}"


ELECTRICAL = {
    "ALL-062": f"{none_of(FUSES)} and (not ({none_of(BREAKERS)}) or FACT(the home has circuit breakers)) "
               "and FACT(at least 150-amp service)",
    "ALL-063": f"{none_of(AL, KT, FUSES)} and FACT(no cloth wiring or fusible pullouts)",
    "ALL-064": f"{none_of(FPE)} and FACT(no Sylvania or Challenger or recalled breaker panel)",
    "SAG-045": none_of(AL, KT, FUSES),
    "SAG-046": f"{none_of(FPE)} and FACT(no Challenger or Sylvania panel)",
    "MER-034": f"{none_of(FUSES)} and (not ({none_of(BREAKERS)}) or FACT(the system is all circuit breakers))",
    "MER-035": f"{none_of(FPE)} and FACT(no Magnetrip or Sylvania or Challenger panel)",
    "MER-036": none_of(AL),
    # Round 38 step 7 (self-audit F15, 2026-10-11): Progressive names Federal Pacific only, and the form's answer is
    # "Federal Pacific or Zinsco panel" -- that answer alone is a confirm (as FOR-041), never a decline
    "PRO-040": none_of(KT, AL, FUSES) + " and (" + none_of(FPE) + " or FACT(the panel is Zinsco not Federal Pacific))",
    "SWY-027": f"{none_of(AL)} or FACT(aluminum wiring retrofitted with AlumiConn or COPALUM connectors)",
    "SWY-028": f"{none_of(KT)} and FACT(no carbon tetrachloride wiring or cloth wiring without a romex layer)",
    "SWY-029": f"{none_of(FUSES, FPE)} and FACT(no split bus or GTE Sylvania or Challenger panel)",
    "SUR-137": f"{none_of(FPE)} and FACT(no Magnetrip or Challenger or Sylvania panel)",
    "SUR-138": none_of(AL, KT, FUSES),
    "SFP-144": f"{none_of(FPE)} and FACT(no Magnetrip or Challenger or Sylvania panel)",
    "SFP-145": none_of(AL, KT, FUSES),
    "WIL-142": f"{none_of(FPE)} and FACT(no Magnetrip or Challenger or Sylvania panel)",
    "WIL-143": none_of(AL, KT, FUSES),
    "TRI-055": f"{none_of(FPE)} and FACT(no Magnetrip or Challenger or Sylvania panel)",
    "TRI-056": none_of(AL, KT, FUSES),
    "MKL-038": none_of(FUSES, KT, AL),
    "MKL-040": f"{none_of(FPE)} and FACT(no Sylvania or Challenger panel)",
    "VAV-048": none_of(FUSES, AL, KT),
    "VAV-050": f"{none_of(FPE)} and FACT(no Challenger or Pushmatic panel)",
    "ARA-021": none_of(AL),
    "ARA-047": f"{none_of(FUSES)} and (not ({none_of(BREAKERS)}) or FACT(the home has circuit breaker boxes))",
    "ARA-048": none_of(AL, KT, FUSES),
    "ARB-019": none_of(AL),
    "ARB-044": f"{none_of(FUSES)} and (not ({none_of(BREAKERS)}) or FACT(the home has breaker boxes))",
    "ARB-045": none_of(AL, KT, FUSES),
    "FOR-040": none_of(AL, KT),
    "FOR-041": none_of(FPE) + " or FACT(the panel is Zinsco not Stab-Lok)",
    "ORI-064": none_of(KT),
    "ORI-065": none_of(AL),
    "ORI-067": f"{none_of(FUSES, FPE)} and FACT(no GTE Sylvania or Challenger or other unsafe panel)",
    "SBS-034": f"{none_of(AL)} or FACT(aluminum wiring retrofitted with AlumiConn or COPALUM connectors)",
    "SBS-035": f"{none_of(KT)} and FACT(no cloth wiring without a Romex layer)",
    "SBS-036": f"{none_of(FUSES, FPE)} and FACT(no split-bus or GTE Sylvania or Challenger panel)",
    "SLL-046": f"{none_of(AL)} or FACT(aluminum wiring retrofitted with Alumicon or Copalum connectors)",
    "SLL-047": f"{none_of(KT)} and FACT(no carbon tetrachloride wiring or cloth wiring without a Romex layer)",
    "SLL-048": f"{none_of(FUSES, FPE)} and FACT(no split bus or GTE Sylvania or Challenger panel)",
    "STO-036": f"{none_of(AL)} or FACT(aluminum wiring retrofitted with AlumiCon or COPALUM connectors)",
    "STO-037": f"{none_of(KT)} and FACT(no cloth wiring without a romex layer)",
    "STO-038": f"{none_of(FUSES, FPE)} and FACT(no split bus or GTE Sylvania or Challenger panel)",
    "TRV-052": none_of(KT),
    "TRV-053": f"{none_of(FUSES)} and (not ({none_of(BREAKERS)}) or FACT(the home has circuit breakers throughout))",
    "CDP-030": none_of(AL),
    "CDP-031": none_of(FUSES, KT),
    "CHO-039": f"{none_of(FUSES, KT, AL)} and FACT(no cloth or double-tap wiring)",
    "CHO-040": f"{none_of(FPE)} and FACT(no GTE Sylvania or Challenger panel)",
    "NCD-086": none_of(KT, AL),
    "NCD-087": none_of(FPE),
    "PDP-087": none_of(FUSES, AL, KT) + " and (" + none_of(FPE) + " or FACT(the panel is Zinsco not Federal Pacific))",
    "PH6-073": none_of(KT, AL, FUSES) + " and (" + none_of(FPE) + " or FACT(the panel is Zinsco not Federal Pacific))",
    "MDP-037": none_of(FUSES, KT, AL),
    "MDP-039": f"{none_of(FPE)} and FACT(no Sylvania or Challenger panel)",
    "ODP-084": f"{none_of(FPE)} and FACT(no Magnetrip or Challenger or Sylvania panel)",
    "ODP-085": none_of(AL, KT, FUSES),
    "SDP-102": f"{none_of(FPE)} and FACT(no Magnetrip or Challenger or Sylvania panel)",
    "SDP-103": none_of(AL, KT, FUSES),
    "FDP-127": f"{none_of(FPE)} and FACT(no Magnetrip or Challenger or Sylvania panel)",
    "FDP-128": none_of(AL, KT, FUSES),
    "VDP-035": none_of(FUSES, AL, KT),
    "VDP-037": f"{none_of(FPE)} and FACT(no Challenger or Pushmatic panel)",
    "STD-072": f"{none_of(KT, AL, FPE, FUSES)} and FACT(no polybutylene plumbing)",
}
ELECTRICAL_GATES = {
    "LDP-048": "year_built < 1976",
}
ELECTRICAL["LDP-048"] = none_of(FUSES, KT, AL)

# Rows these questions leave NONE, by reason (reported; tested in verification/test_loss_electrical.py).
UNDECIDED = {
    "prior insurance, cancellation or lapse": "ALL-153 ALL-154 ALL-155 SAG-149 SAG-150 CHU-069 MER-093 PRO-098 PRO-099 "
        "PRO-100 SWY-049 SWY-050 SUR-129 SUR-130 SFP-136 SFP-137 WIL-134 WIL-135 TRI-169 TRI-170 MKL-108 ARA-075 "
        "ARB-084 FOR-120 LIB-053 SBS-055 SLL-050 SLL-052 STO-056 STO-058 TWI-028 TRV-068 CDP-104 LDP-065 NCD-026 "
        "NPD-078 NPD-079 NPD-080 PDP-054 PDP-055 PDP-056 PH6-034 PH6-035 PH6-036 MDP-094 ODP-136 ODP-137 SDP-096 "
        "FDP-091 STD-161 STD-162 STD-163 STD-164",
    "open or disputed claim": "ALL-148 SWY-063 VAV-092 ORI-039 SBS-051 SLL-072 STO-054 TWI-022 TRV-065 CHO-033 "
        "NCD-144 NCD-154 VDP-054 STD-140 FOR-122",
    "fraud or misrepresentation": "SAG-119 CHU-068 SUR-082 SFP-087 WIL-088 TRI-137 VAV-097 FOR-118 FOR-119 ODP-130 "
        "SDP-062 FDP-083 VDP-020 STD-160",
    "repairs, remediation or mold": "SAG-114 SAG-115 SAG-116 CHU-070 CHU-071 MER-090 PRO-093 SUR-073 SUR-085 "
        "SUR-086 SUR-087 SFP-078 SFP-090 SFP-091 SFP-092 WIL-079 WIL-091 WIL-092 WIL-093 TRI-131 TRI-132 TRI-133 "
        "TRI-134 ARA-070 ARB-073 TRV-013 NCD-148 NCD-149 NPD-075 PDP-057 PH6-037 ODP-128 SDP-059 FDP-081 FOR-124",
    "sinkhole, appliance, animal-bite or mysterious-disappearance claims": "SWY-048 SBS-052 SLL-073 STO-055 "
        "ALL-152 CHU-064 MER-091 TRV-014 TRV-064 NCD-152 NCD-153 VAV-062 VAV-096 VDP-017 VDP-056 MKL-109",
    "same peril, similar, negligence or a multi-peril combination the options cannot count": "SAG-117 SUR-088 "
        "SFP-093 WIL-094 TRI-135 ODP-132 SDP-065 FDP-087 MKL-107 MDP-090 CHU-065 CHU-066 CDP-101 NCD-151 TRV-006 "
        "TRV-007 TRV-008 TRV-009 FOR-109 FOR-110 FOR-111 FOD-039 FOD-040 FOD-041",
    "renewal, more than one location or a vacant home": "CHU-074 FOR-108 FOD-037 FOD-038 STD-148 STD-149 STD-150 "
        "STD-151 STD-152 STD-153 MDP-086 STD-157 STD-158 STD-159",
    "electrical service amps, an unnamed panel brand or other wiring": "SAG-044 SUR-136 SFP-143 WIL-141 TRI-054 "
        "MKL-039 VAV-051 VDP-038 ARA-046 ARB-042 FOR-039 ORI-066 MDP-038 ODP-083 SDP-101 FDP-126 FOR-038 FOR-067 "
        "NPD-022 STD-071 VAV-028",
    "a fire loss in a higher-risk protection row: the row's own gate needs the station and hydrant answers, and a "
    "blank distance must not create a hold": "SAG-080 SUR-118 SFP-126 TRI-138 PDP-059 PH6-039",
    "closed program (NatGen Premier OneChoice DP3 is never checked)": "NPD-071 NPD-072 NPD-073 NPD-074 NPD-043",
    "mentions a loss or a panel but is about something else": "ALL-041 ALL-046 ALL-160 ALL-206 CHU-029 CHU-042 "
        "MER-020 MKL-031 MDP-022 LIB-030 SBS-004 TWI-032 TRV-058 CHO-054 LDP-044 NPD-037 NPD-060 STD-068 STD-011 "
        "ARB-062 NCD-020",
}


def lines():
    """{row: (field, test, gate, open_fact, note)} for every row these questions decide."""
    out = {}
    for rid, test in LOSS.items():
        out[rid] = (LOSS_FIELDS, test, "always", "",
                    "round 37 step 4: decided from the losses questions; blank or Unknown is a confirm")
    for rid, test in ELECTRICAL.items():
        gate = ELECTRICAL_GATES.get(rid, "always")
        out[rid] = ("electrical" + (";year_built" if rid in ELECTRICAL_GATES else ""), test, gate, "",
                    "round 37 step 4: decided from the electrical question; blank or Unknown is a confirm")
    return out


LINES = lines()
