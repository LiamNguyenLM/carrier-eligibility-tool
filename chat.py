"""Ask the Guides -- one-off carrier questions, answered from guide text.

Separate from the eligibility pipeline and deliberately so: it shares the
embedding model, the Chroma store and carrier_programs(), but it does not
touch check_eligibility() or anything it calls. Nothing in this module can
change an eligibility verdict.

THE MODEL CALL IS ONE FUNCTION -- `_complete()`. Everything else builds a
prompt or checks an answer. Swapping providers (the GPT-6 Luna bake-off) is
a change to that function and the two constants above it, nothing more; no
other code in this module knows what a message block looks like.

Three answer paths, chosen by what the question names:

  1-3 named programs    FULL GUIDE text, one call. See guides.py for why.
  4+ named programs     per-program retrieval, one call (a whole Sage or
                        Swyfft family is too much text to send whole, and
                        those questions are comparative anyway).
  no carrier named      cross-carrier: one small call PER PROGRAM, in
                        parallel, grouped deterministically in code.
"""

import concurrent.futures
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import anthropic

import data_defects
import guides
from eligibility_check import carrier_programs

# --- the model, and the only two places its identity appears ---------------
CHAT_MODEL = os.environ.get("CHAT_MODEL", "claude-sonnet-4-5")

# Models that REJECT sampling parameters outright (HTTP 400) rather than
# ignoring them. The Claude 5 family removed temperature/top_p/top_k, so
# `temperature=0` -- which this tab wants, because CLAUDE.md treats an
# unmeasured failure rate as a bug rather than a caveat -- is not available
# on them. Sending it anyway would be a hard failure on every call, so the
# parameter is dropped for those models and the determinism has to come from
# measured pass rates instead. Listed by prefix because the family shares the
# behaviour.
_NO_SAMPLING_PARAMS = ("claude-opus-5", "claude-sonnet-5", "claude-fable-5", "claude-opus-4-")

_client = anthropic.Anthropic(max_retries=6)


def _complete(system, blocks, max_tokens=4000):
    """THE model call. Returns (text, usage_dict, latency_seconds).

    `blocks` is a list of (text, cacheable) pairs forming the single user
    message. Guide text goes first and cacheable; the question goes last and
    is never cached, so a follow-up about the same carrier reuses the guide
    prefix instead of paying for it again.
    """
    content = []
    for text, cacheable in blocks:
        block = {"type": "text", "text": text}
        if cacheable:
            block["cache_control"] = {"type": "ephemeral"}
        content.append(block)

    kwargs = dict(
        model=CHAT_MODEL,
        max_tokens=max_tokens,
        system=[{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": content}],
        # Explicit timeout, same reason as eligibility_check's call: the SDK
        # refuses a non-streaming request outright when its max_tokens-derived
        # worst-case estimate exceeds ten minutes, and passing a timeout skips
        # that heuristic entirely.
        timeout=300.0,
    )
    if not CHAT_MODEL.startswith(_NO_SAMPLING_PARAMS):
        kwargs["temperature"] = 0

    started = time.time()
    response = _client.messages.create(**kwargs)
    latency = time.time() - started

    usage = response.usage
    text = "".join(b.text for b in response.content if b.type == "text")
    return text, {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
    }, latency


# ---------------------------------------------------------------------------
# Resolving which programs a question is about
# ---------------------------------------------------------------------------

# Words that appear inside program names but carry no identifying power, so
# they must never become a searchable alias. "and" is the load-bearing one:
# Foremost_DP3_and_HO3 normalises to FOREMOSTDP3ANDHO3, which CONTAINS "AND",
# so without this list the question "galvanized and PEX" would resolve to
# Foremost.
_ALIAS_STOPWORDS = {
    "and", "the", "of", "or", "a", "an", "non", "admitted", "surplus", "tx",
    "guide", "guides", "underwriting", "guideline", "guidelines", "program",
    "programs", "homeowners", "dwelling", "fire", "landlord", "condo",
    "condominium", "unit", "owners", "insurance", "company", "dp", "ho",
}

_PRODUCT_TOKEN_RE = re.compile(r"^(ho-?[356]|dp-?[13])$", re.I)

# Back-references that make a question a follow-up about carriers already in
# play rather than a fresh cross-carrier question.
_FOLLOWUP_MARKERS = re.compile(
    r"\b(their|theirs|they|them|those|these|it|its|that one|same|also|what about|how about)\b",
    re.I,
)

_CROSS_CARRIER_MARKERS = re.compile(
    r"\b(which|who|any|anyone|all|every|everybody|list|compare|carriers?\b.*\b(take|accept|allow|write|cover))\b",
    re.I,
)


def _normalize(text):
    """Alphanumerics only, uppercased -- the project's existing convention
    (verification.profiles.normalize_carrier_name), so a needle typed with
    different spacing, punctuation or an apostrophe still matches."""
    return "".join(ch for ch in (text or "").upper() if ch.isalnum())


def _brand(program):
    """The insurer a program belongs to: the first token of its name.

    This is what separates "answer every program" from "ask which one you
    meant". "Progressive" matching three Progressive programs is not
    ambiguous -- they are one insurer's three products and the spec says to
    answer per program. "Lloyds" matching Swyfft Lloyds and Sage Trium
    Lloyd's IS ambiguous, because those are two unrelated insurers and
    picking either one is a coin flip.
    """
    first = re.split(r"[_\-\s(]", program, maxsplit=1)[0]
    return _normalize(first)


def known_programs():
    """Every program an agent could reasonably ask about.

    NOT the same as the programs that have text. A program whose PDF produced
    no chunks is absent from the store entirely, so building the name index
    from the store alone makes it unaskable -- and worse than unaskable:
    "Centauri HO3 roof age" then resolved to Centauri's DP3 guide, because
    Centauri HO3 was not a candidate and the product filter had nothing to
    narrow to. An agent would have been handed the landlord guide's roof rule
    for a homeowners question, with no indication anything was wrong.

    Including the defective programs here makes them nameable, so
    answer_programs() can refuse them by name instead of the resolver quietly
    substituting a sibling.
    """
    return sorted(set(guides.all_programs()) | set(data_defects.defective_programs()))


def _program_aliases():
    """{normalized alias: set(programs)} built from the program names."""
    aliases = {}
    for program in known_programs():
        # Drop the date and the product token; what remains identifies the
        # insurer and its sub-program.
        stem = re.sub(r"\d{2}\.\d{2}\.\d{4}", " ", program)
        stem = stem.replace("'", "")
        tokens = [t for t in re.split(r"[^A-Za-z0-9+]+", stem) if t]
        tokens = [
            t for t in tokens
            if t.lower() not in _ALIAS_STOPWORDS
            and not _PRODUCT_TOKEN_RE.match(t)
            and not t.isdigit()
        ]
        for size in (1, 2, 3):
            for i in range(len(tokens) - size + 1):
                alias = _normalize("".join(tokens[i:i + size]))
                if len(alias) >= 3:
                    aliases.setdefault(alias, set()).add(program)
    return aliases


def _named_programs(question):
    """Programs the question names, plus the phrase that named them.

    Two stages, and the second is the one that creates the ambiguity the spec
    demands. An n-gram of the question must first match a known alias exactly
    -- that keeps ordinary English out of the matcher. The matched alias is
    then expanded to every program whose full name CONTAINS it, which is what
    makes "HOA+" reach HOAIC as well as ARI (HOA+) and therefore get flagged
    ambiguous instead of silently resolving to one of them.
    """
    aliases = _program_aliases()
    all_programs = known_programs()
    words = [w for w in re.split(r"[^A-Za-z0-9+]+", question) if w]

    hits = {}
    for size in (4, 3, 2, 1):
        for i in range(len(words) - size + 1):
            phrase = " ".join(words[i:i + size])
            key = _normalize(phrase)
            if key not in aliases:
                continue
            matched = {p for p in all_programs if key in _normalize(p)}
            matched |= aliases[key]
            hits[phrase] = matched

    if not hits:
        return None, set()

    # Prefer the longest phrase that matched -- "Swyfft Lloyds" must win over
    # the bare "Lloyds" that is also present inside it, or every fully
    # qualified name would be reported as ambiguous.
    best = max(hits, key=lambda p: len(_normalize(p)))
    return best, hits[best]


def _narrow_by_product(programs, question):
    """Filter to a product the question explicitly names, if it names one."""
    lowered = question.lower()
    wants_dp = bool(re.search(r"\bdp-?3\b|\blandlord\b|\bdwelling fire\b|\brental\b", lowered))
    wants_condo = bool(re.search(r"\bho-?6\b|\bcondo\b|\bcondominium\b", lowered))
    wants_ho = bool(re.search(r"\bho-?3\b|\bhomeowners?\b", lowered))

    if not (wants_dp or wants_condo or wants_ho):
        return programs

    kept = set()
    for program in programs:
        is_ho, is_dp = carrier_programs(program)
        is_condo = "HO6" in _normalize(program)
        if wants_dp and is_dp:
            kept.add(program)
        if wants_condo and is_condo:
            kept.add(program)
        if wants_ho and is_ho and not is_condo:
            kept.add(program)
    return kept or programs


def resolve(question, carried_forward=()):
    """What this question is about.

    Returns a dict with "mode" in {"programs", "ambiguous", "cross_carrier"}.
    """
    phrase, matched = _named_programs(question)

    if matched:
        brands = {_brand(p) for p in matched}
        if len(brands) > 1:
            return {
                "mode": "ambiguous",
                "phrase": phrase,
                "candidates": sorted(matched),
                "programs": [],
            }
        return {
            "mode": "programs",
            "phrase": phrase,
            "programs": sorted(_narrow_by_product(matched, question)),
            "candidates": [],
        }

    # Nothing named. A back-reference continues the current carriers; anything
    # else is a genuine cross-carrier question.
    if carried_forward and _FOLLOWUP_MARKERS.search(question) and not _CROSS_CARRIER_MARKERS.search(question):
        return {
            "mode": "programs",
            "phrase": None,
            "programs": sorted(carried_forward),
            "candidates": [],
        }

    return {"mode": "cross_carrier", "phrase": None, "programs": [], "candidates": []}


# ---------------------------------------------------------------------------
# Quote verification
# ---------------------------------------------------------------------------

# The quote body must be allowed to span newlines (re.S). Guide text is full
# of them -- table rows especially -- and an earlier line-anchored version of
# this pattern silently matched NOTHING when a quote wrapped, which meant a
# multi-line quote skipped verification altogether and the answer was reported
# as verified. A verifier that quietly passes what it cannot parse is worse
# than no verifier. The label is kept on one line ([^\n:]) so the pattern
# cannot swallow preceding prose as a carrier name.
_SOURCE_LINE_RE = re.compile(
    r"^[ \t]*[-*]?[ \t]*([^\n:]{1,80}?)[ \t]*:[ \t]*[\"“](.+?)[\"”]",
    re.M | re.S,
)
_INLINE_QUOTE_RE = re.compile(r"[\"“]([^\"“”]{25,})[\"”]")


def _compare_key(text):
    """Alphanumerics only, lowercased.

    Deliberately ignores whitespace and punctuation, because this corpus's PDF
    extraction inserts both: Foremost's pool rule really is stored as "P ools
    with a deck", and the Liberty Mutual text carries U+FFFD where smart
    quotes and en-dashes were. A verifier that demanded those artifacts back
    verbatim would reject correct quotes. At 25+ characters the collision risk
    of a text-only comparison is negligible, and a fabricated sentence still
    fails it outright.
    """
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def _appears_in(quote, source, max_gap=300, min_segment=25, max_gaps=4):
    """Is `quote` present in `source`, allowing for page furniture?

    Both arguments are already _compare_key output.

    A plain substring test is the first thing tried and the common case. It is
    not sufficient on its own, and this is measured, not theoretical: asked
    about Progressive HO3's galvanized plumbing rule, the model quoted the
    ineligible-homes bullet list correctly -- but the PDF has a page footer
    ("3 Uploaded to system 2026-04 Texas Homeowners HO H Program ASI Lloyds")
    sitting between the second and third bullet. The model read across it, as
    it should; the quote is faithful to the document and matches no contiguous
    span of it. Rejecting that would train agents to ignore the verifier,
    which is worse than the failure it was built to catch.

    So a quote may also match as a handful of long, in-order segments
    separated by short gaps. The constraints are what keep this a verifier
    rather than a rubber stamp:

      min_segment  each piece must be a substantial run, so the matcher can
                   never assemble a quote word-by-word from scattered text
      max_gap      what is skipped must be small -- a footer, not a section
      max_gaps     few joins, so this cannot walk the whole document

    A fabricated sentence fails all three, because its words are not present
    in long runs anywhere.
    """
    if quote in source:
        return True

    # A short quote needs a shorter segment, or it can never be matched in
    # pieces at all. Measured on Swyfft Lloyds: the PDF lays its roof rule out
    # in two columns, so "No roofs older than 25 years." is stored as "No roofs
    # [Full Time Annual Rentals] older than 25 years." -- 23 alphanumeric
    # characters of quote interrupted by an unrelated column. With a flat
    # 25-character minimum the matcher demanded the whole thing contiguously
    # and rejected a quote that is verbatim correct.
    # 7 is measured, not picked. Swept 5/6/7/8 against the genuine Swyfft
    # quote and seven adversarial fabrications built from each guide's OWN
    # vocabulary (numeric swaps -- "40 years" for "25 years" -- and negation
    # flips -- "are eligible" for "are ineligible"). 8 rejects the genuine
    # quote; 5, 6 and 7 all accept it and all reject every fabrication, so 7
    # takes the most margin that still works.
    min_segment = max(7, min(min_segment, len(quote) // 3))

    i, pos, gaps = 0, 0, 0
    while i < len(quote):
        remaining = len(quote) - i
        seg_len = min(min_segment, remaining)
        found = source.find(quote[i:i + seg_len], pos)
        if found < 0:
            return False
        if i > 0:
            if found - pos > max_gap:
                return False
            if found > pos:
                gaps += 1
                if gaps > max_gaps:
                    return False
        # Extend the match as far as the two strings agree.
        end = seg_len
        while (i + end < len(quote) and found + end < len(source)
               and source[found + end] == quote[i + end]):
            end += 1
        i += end
        pos = found + end
    return True


def verify_quotes(answer, program_texts):
    """Check every quote in the answer against the guide it is attributed to.

    program_texts: {program: full source text}. A quote attributed to a
    carrier counts as unverified unless it appears in THAT carrier's text --
    the same rule as _strip_misattributed_citations in the pipeline, where a
    correctly-labelled quote applied to the wrong carrier was the actual
    measured failure, not fabrication.

    Returns (verified, problems) where problems is a list of dicts.
    """
    keys = {p: _compare_key(t) for p, t in program_texts.items()}
    problems = []

    def resolve_label(label, quote):
        """Which program a SOURCES line is claiming, or None if undecidable.

        A label that does not name a known program is NOT automatically a
        problem, and treating it as one made the verifier cry wolf on correct
        answers. Guides carry internal sub-form names, and the model labels
        with them: Foremost's pool rule is genuinely written per form, so its
        quotes came back labelled "TDP-1" and "Condominium Landlord (DF6)",
        and Swyfft's roof table came back labelled by roof material
        ("Asphalt Shingles"). Every one of those quotes was real text from the
        guide that was actually sent.

        What this check exists to catch is fabrication and MISattribution, so
        when a label is unrecognised the quote itself decides: if it appears
        in exactly one of the guides sent, attribution is not in doubt and
        that is the program. Only a quote that appears in none of them is a
        finding.
        """
        wanted = _normalize(label)
        if wanted:
            exact = [p for p in keys if _normalize(p) == wanted]
            if len(exact) == 1:
                return exact[0]
            partial = [p for p in keys if wanted in _normalize(p) or _normalize(p) in wanted]
            # Must land on exactly one program. An ambiguous label is treated
            # as unknown rather than guessed at, for the reason the pipeline's
            # own comment gives: stripping evidence must never rest on a coin
            # flip.
            if len(partial) == 1:
                return partial[0]

        # Fall back to where the text actually lives.
        holders = [p for p, k in keys.items() if _appears_in(_compare_key(quote), k)]
        if len(holders) == 1:
            return holders[0]
        if len(holders) > 1:
            # Boilerplate shared by sibling guides. Genuine either way, and
            # there is nothing to misattribute it to.
            return holders[0]
        return None

    seen = set()
    for label, quote in _SOURCE_LINE_RE.findall(answer):
        if len(_compare_key(quote)) < 12:
            continue
        seen.add(_compare_key(quote))
        program = resolve_label(label, quote)
        if program is None:
            problems.append({
                "quote": quote, "label": label, "reason": "not_in_any_guide",
            })
        elif not _appears_in(_compare_key(quote), keys[program]):
            # Is it real text, just filed under the wrong carrier?
            elsewhere = [p for p, k in keys.items() if _appears_in(_compare_key(quote), k)]
            problems.append({
                "quote": quote,
                "label": label,
                "reason": "wrong_carrier" if elsewhere else "not_in_guide",
                "actually_from": elsewhere,
            })

    for quote in _INLINE_QUOTE_RE.findall(answer):
        key = _compare_key(quote)
        if key in seen or len(key) < 25:
            continue
        if not any(_appears_in(key, k) for k in keys.values()):
            problems.append({
                "quote": quote, "label": None, "reason": "not_in_any_guide",
            })

    return (not problems), problems


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

ANSWER_RULES = """You are answering an insurance agent's question about specific Texas carrier underwriting guides.

ANSWER ONLY FROM THE GUIDE TEXT PROVIDED IN THIS MESSAGE. You have real general knowledge about insurance; it is not admissible here and must not influence the answer. If the provided guide text does not address the question, say exactly: "The [carrier] [program] guide on file doesn't address this." and suggest confirming with the underwriter. Never fill a gap from what is typical in the industry, and never present a guide's SILENCE as acceptance -- a guide that says nothing about trampolines has no trampoline rule, which is not the same as permitting them.

ANSWER EACH PROGRAM SEPARATELY. Two programs from the same insurer routinely have different rules, and a rule found under one program says nothing about another. Never apply one program's rule to another program, even when their names are nearly identical.

SEPARATE ELIGIBILITY FROM COVERAGE, AND NAME THE HEADING. These guides organise rules under headings, and the heading is what decides which kind of rule it is. Before answering, find the heading the rule sits under and SAY IT in your answer.
- A rule under a "Liability Exposure" heading (for example "Liability Exposure -- Swimming Pools") governs LIABILITY exposure and coverage for that feature. Say so explicitly -- "this sits under Liability Exposure, so it restricts pool liability, it does not decline the home" -- even when the rule's own wording uses the word "ineligible", because there that word applies to the liability exposure, not to the dwelling.
- A settlement, depreciation or payment schedule changes what the policy PAYS. It never declines the risk.
- Only a rule under an eligibility / ineligible-risk / unacceptable-risk heading declines the property itself.
Never report a coverage or liability restriction as a decline of the home.

FORMAT:
- Lead with the direct answer in one or two plain sentences per program. Agents want the answer first.
- Then a section headed exactly "SOURCES", with one line per supporting quote, formatted exactly:
  - <Program name>: "<verbatim quote>"
- The program name in a SOURCES line must be copied EXACTLY from the "--- GUIDE:" header the quote came from. Do not label a quote with a sub-form, form number, product name or table-row name found inside the guide (for example "TDP-1", "DF6", "Asphalt Shingles") -- those belong in the answer text, not in the label. One SOURCES line per quote; never nest a bulleted list of quotes under one label.
- Every factual claim must have a quote under SOURCES. Quotes must be copied EXACTLY from the provided text, character for character, including any odd spacing. Do not tidy, paraphrase, shorten with ellipses, or correct them.
- Do not quote text you were not given. If you cannot support a claim with a verbatim quote from the provided text, do not make the claim.
- Keep it short and in plain language. No preamble."""


def _guide_header(program):
    date = data_defects.guide_date(program)
    return "--- GUIDE: {p} (guide dated {d}) ---".format(
        p=program, d=date if date else "no date in filename"
    )


def _history_text(history, limit=6):
    if not history:
        return ""
    recent = history[-limit:]
    lines = ["EARLIER IN THIS CONVERSATION (for pronoun resolution only):"]
    for turn in recent:
        lines.append("{}: {}".format(turn["role"].upper(), turn["content"][:500]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Answer paths
# ---------------------------------------------------------------------------

FULL_GUIDE_MAX_PROGRAMS = 3
RETRIEVAL_K = 12


def _retrieved_text(program, question, k=RETRIEVAL_K):
    from shared_resources import get_vectorstore
    docs = get_vectorstore().similarity_search(question, k=k, filter={"carrier": program})
    return "\n\n".join(d.page_content for d in docs)


def answer_programs(question, programs, history=()):
    """Answer about a specific set of programs."""
    usable, blocked = [], []
    defects = data_defects.defective_programs()
    for program in programs:
        defect = defects.get(program)
        (blocked if defect else usable).append((program, defect))

    if not usable:
        return {
            "answer": None,
            "blocked": blocked,
            "programs": programs,
            "mode": "blocked",
            "usage": None,
            "latency": 0.0,
            "quotes_verified": None,
            "quote_problems": [],
        }

    use_full_guide = len(usable) <= FULL_GUIDE_MAX_PROGRAMS
    texts = {}
    for program, _ in usable:
        texts[program] = (
            guides.guide_text_with_pages(program) if use_full_guide
            else _retrieved_text(program, question)
        )

    blocks = []
    for program, _ in usable:
        # Each guide is its own cacheable block, so a follow-up about the same
        # carrier re-reads the prefix from cache instead of paying for it.
        blocks.append((_guide_header(program) + "\n" + texts[program], True))

    tail = []
    hist = _history_text(history)
    if hist:
        tail.append(hist)
    # Spell out the exact strings that may appear as SOURCES labels. Leaving
    # this implicit produced quotes labelled with the guides' own internal
    # form names ("TDP-1", "Asphalt Shingles"), which are real but unresolvable.
    tail.append(
        "THE ONLY VALID SOURCES LABELS ARE:\n"
        + "\n".join("- " + p for p, _ in usable)
    )
    tail.append("AGENT'S QUESTION: " + question)
    blocks.append(("\n\n".join(tail), False))

    answer, usage, latency = _complete(ANSWER_RULES, blocks)
    # Verified against the text actually sent, which is the only text the
    # answer could legitimately have come from.
    verified, problems = verify_quotes(answer, texts)

    return {
        "answer": answer,
        "blocked": blocked,
        "programs": [p for p, _ in usable],
        "mode": "full_guide" if use_full_guide else "retrieval",
        "usage": usage,
        "latency": latency,
        "quotes_verified": verified,
        "quote_problems": problems,
    }


CROSS_CARRIER_RULES = """You are checking ONE Texas carrier program's underwriting guide against an agent's question.

Use ONLY the guide text provided. Answer with a single JSON object and nothing else:

{"verdict": "YES" | "NO" | "NOT_ADDRESSED", "detail": "<one short sentence>", "quote": "<verbatim quote from the provided text, or empty string>"}

- "YES"  -- the guide affirmatively permits or accepts what is asked, possibly with conditions. Put the conditions in detail.
- "NO"   -- the guide excludes, declines or prohibits it.
- "NOT_ADDRESSED" -- the guide does not speak to it. This is the correct answer whenever the text is silent. Silence is NEVER acceptance; do not answer YES because nothing forbids it.
- quote must be copied EXACTLY from the provided text, character for character. Use "" when the verdict is NOT_ADDRESSED.
- If the rule restricts COVERAGE rather than eligibility, say so in detail."""


def _classify_one(program, question):
    text = _retrieved_text(program, question)
    if not text.strip():
        return program, {"verdict": "NOT_ADDRESSED", "detail": "No relevant text found in this guide.", "quote": ""}, None, 0.0
    blocks = [
        (_guide_header(program) + "\n" + text, False),
        ("AGENT'S QUESTION: " + question, False),
    ]
    raw, usage, latency = _complete(CROSS_CARRIER_RULES, blocks, max_tokens=700)
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return program, {"verdict": "NOT_ADDRESSED", "detail": "Could not read this guide's answer.", "quote": ""}, usage, latency
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return program, {"verdict": "NOT_ADDRESSED", "detail": "Could not read this guide's answer.", "quote": ""}, usage, latency

    # Deterministic backstop: a quote that is not in THIS program's text is
    # dropped and the verdict falls back to NOT_ADDRESSED when it was the only
    # support. A yes/no built on a fabricated quote is worse than no answer.
    quote = parsed.get("quote") or ""
    if quote and not _appears_in(_compare_key(quote), _compare_key(text)):
        parsed["quote"] = ""
        parsed["unverified_quote"] = quote
        if parsed.get("verdict") in ("YES", "NO"):
            parsed["verdict"] = "NOT_ADDRESSED"
            parsed["detail"] = (
                "Dropped: the supporting quote could not be found in this guide."
            )
    return program, parsed, usage, latency


def answer_cross_carrier(question, max_workers=8):
    """Every program, one small call each, grouped in code.

    One call per program rather than one call over all of them. The pipeline's
    own history is the argument: a single completion covering ~28 carriers is
    where cross-carrier bleed-through was measured (ARI HOA+ inheriting ARI
    HOB's age cap in 40% of runs), and it needed a whole post-generation
    attribution layer to contain it. One program per call makes that failure
    structurally impossible instead of detectable.
    """
    defects = data_defects.defective_programs()
    programs = [p for p in guides.all_programs() if p not in defects]

    results, usages, latencies = {}, [], []
    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_classify_one, p, question) for p in programs]
        for future in concurrent.futures.as_completed(futures):
            program, parsed, usage, latency = future.result()
            results[program] = parsed
            if usage:
                usages.append(usage)
                latencies.append(latency)
    wall = time.time() - started

    grouped = {"yes": [], "no": [], "not_addressed": []}
    for program in programs:
        parsed = results.get(program, {})
        bucket = {"YES": "yes", "NO": "no"}.get(parsed.get("verdict"), "not_addressed")
        grouped[bucket].append({
            "program": program,
            "date": data_defects.guide_date(program),
            "detail": parsed.get("detail", ""),
            "quote": parsed.get("quote", ""),
        })

    total = {
        "input_tokens": sum(u["input_tokens"] for u in usages),
        "output_tokens": sum(u["output_tokens"] for u in usages),
        "cache_read_input_tokens": sum(u["cache_read_input_tokens"] for u in usages),
        "cache_creation_input_tokens": sum(u["cache_creation_input_tokens"] for u in usages),
        "calls": len(usages),
    }
    return {
        "grouped": grouped,
        "skipped": sorted(defects),
        "usage": total,
        "latency": wall,
        "mode": "cross_carrier",
        "quotes_verified": True,
        "quote_problems": [],
    }


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
#
# JSON lines to stdout, which Railway captures, plus a file on the mounted
# volume when CHAT_LOG_PATH points at one (stdout alone is retained only as
# long as Railway's log window). Agents type customer names into these
# questions, so this never leaves the deployment -- no external sink, and
# nothing here makes a network call.

CHAT_LOG_PATH = os.environ.get("CHAT_LOG_PATH", "")


def log_interaction(record):
    record = dict(record)
    record["timestamp"] = datetime.now(timezone.utc).isoformat()
    line = json.dumps(record, ensure_ascii=False, default=str)

    print(line, file=sys.stdout, flush=True)
    if CHAT_LOG_PATH:
        try:
            with open(CHAT_LOG_PATH, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError as exc:
            # A broken log path must never take the answer down with it.
            print("chat log write failed: %s" % exc, file=sys.stderr, flush=True)


def ask(question, history=(), carried_forward=()):
    """Full path: resolve, answer, verify, log. Returns a result dict."""
    resolution = resolve(question, carried_forward)

    if resolution["mode"] == "ambiguous":
        result = {
            "mode": "ambiguous",
            "phrase": resolution["phrase"],
            "candidates": resolution["candidates"],
            "programs": [],
            "answer": None,
            "usage": None,
            "latency": 0.0,
            "quotes_verified": None,
            "quote_problems": [],
            "blocked": [],
        }
    elif resolution["mode"] == "cross_carrier":
        result = answer_cross_carrier(question)
        result["programs"] = []
        result["candidates"] = []
        result["blocked"] = []
    else:
        result = answer_programs(question, resolution["programs"], history)
        result["candidates"] = []

    log_interaction({
        "question": question,
        "mode": result.get("mode"),
        "resolved_programs": result.get("programs", []),
        "candidates": result.get("candidates", []),
        "blocked": [p for p, _ in result.get("blocked", [])],
        "quotes_verified": result.get("quotes_verified"),
        "quote_problems": result.get("quote_problems", []),
        "usage": result.get("usage"),
        "latency_seconds": round(result.get("latency", 0.0), 2),
        "answer": result.get("answer"),
    })
    return result
