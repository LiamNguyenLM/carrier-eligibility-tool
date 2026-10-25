"""Round 43 step 1 (Liam, 2026-10-24): the check as the browser calls it -- the form's answers in (the dict app.py
builds), the results page out as JSON-ready data: the header lines, "Things to confirm with the client", the four
columns and "Could Not Be Checked", and each card's text exactly as app.py renders it (cards.py), with what a
"This looks wrong" report needs. Code only: no Streamlit, retrieval, model or store.

In the browser: load(files, manifest) once -- the bundle's data files (engine.data) and the store's facts
(rules_data/engine_manifest.json) -- then check(). Natively check() reads the store as the app does unless a
manifest was loaded."""
from . import cards
from . import confirm_topics
from . import data
from . import display_names
from . import pipeline
from . import topics

COLUMNS = ("eligible", "refer", "insufficient_info", "not_eligible")
SHOWN = ("ELIGIBLE", "REFER", "INSUFFICIENT_INFORMATION", "INELIGIBLE")


def load(files=None, manifest=None, strict=False):
    """files: {repo-relative path: text} for engine.data; manifest: the store's facts (pipeline.FACTS)."""
    if files:
        data.register(files, strict=strict)
    if manifest is not None:
        pipeline.FACTS = manifest


def card(r, pd, checked):
    """One carrier's card as app.py renders it (render_carrier; a carrier that could not be checked shows its
    warning line and Details without the guide's date), and the record's fields a feedback report carries."""
    shown = r.get("status") in SHOWN
    return {"carrier": r.get("carrier"), "status": r.get("status"), "raw_status": r.get("_raw_status"),
            "flaw_count": r.get("flaw_count"), "name": display_names.record_name(r), "shown": shown,
            "first": cards.first_line_markdown(r, pd, checked, label=False) if shown else "",
            "missing": cards.missing_lines(r.get("missing_info")) if shown else [],
            "confirm_html": (cards.confirm_html(r, pd, checked) or "") if shown else "",
            "details_html": cards.details_html(r, guide=shown) or "",
            "ids_html": (cards.rule_ids_html(r) or "") if shown else "",
            "warning": "" if shown else cards.warning_line(r),
            "reasons": list(r.get("reasons") or []), "citations": list(r.get("citations") or []),
            "missing_info": list(r.get("missing_info") or []), "notes": r.get("notes") or "",
            "also_confirm": list(r.get("also_confirm") or []), "confirm_items": list(r.get("confirm_items") or []),
            "rules_table": bool(r.get("rules_table")), "deciding_rows": deciding_rows(r),
            "model_fallback": bool(r.get("model_fallback"))}


def deciding_rows(record):
    """feedback.deciding_rows: the rules-table rows a card rests on, in order of first appearance."""
    from .feedback_fields import deciding_rows as rows
    return rows(record)


def page(results, pd, checked):
    """The results page for check_eligibility's records (app.py's order: assign_buckets keeps it)."""
    b = pipeline.assign_buckets(results)
    idx = {id(r): i for i, r in enumerate(results)}
    columns = {k: [idx[id(r)] for r in b[k]] for k in COLUMNS}
    columns["could_not_check"] = [idx[id(r)] for r in b["unrecognised"] + b["guide_unavailable"] + b["not_evaluated"]]
    norm = topics.normalize(checked)
    return {"property_details": pd, "checked_topics": checked,
            "header": {"partial_line": topics.partial_check_line(norm) if topics.is_partial(norm) else None,
                       "fallback": any(r.get("model_fallback") for r in results),
                       "usable_answers": pipeline.usable_answer_count(results),
                       "not_checked_names": [display_names.record_name(results[i])
                                             for i in columns["could_not_check"]]},
            "top_box": [list(t) for t in confirm_topics.top_box(results, pd, checked)],
            "columns": columns, "cards": [card(r, pd, checked) for r in results]}


def check(property_details, checked_topics=None):
    """The results page for one check: the form's property_details and ticked topics (None = everything)."""
    pd = dict(property_details)
    checked = None if checked_topics is None else list(checked_topics)
    results, _ = pipeline.run_check(dict(pd), checked_topics=checked)
    return page(results, pd, checked)


def placement_markdown(panel):
    """The placement panel (the dict the Worker returns, placement.panel's shape) as the app shows it."""
    from .placement_view import panel_markdown
    return panel_markdown(panel)
