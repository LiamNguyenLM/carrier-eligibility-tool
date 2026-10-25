"""Round 43 step 1 (Liam, 2026-10-24): the eligibility engine as one package -- everything a check needs (routing,
the rules tables and their map lines, the post-processing that changes 2.9% of statuses, card text, confirm lists,
notes), with no Streamlit, retrieval, model or file-system dependency. engine.api is the entry: the form's answers
in, the cards out as JSON. Streamlit (app.py, through eligibility_check.py) and the browser (web/) both call it.
The old module names at the repo root (rules_evaluator, cards, ...) are the same module objects."""
