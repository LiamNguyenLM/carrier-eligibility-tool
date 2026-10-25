"""Round 43 step 1 (Liam, 2026-10-24): the eligibility check moved to engine/pipeline.py, which imports nothing
from Streamlit, LangChain / Chroma, FastEmbed, Anthropic or OpenAI. This file is the NATIVE app's entry: it loads
the .env (env_setup), copies Streamlit's secrets into the environment, builds the Anthropic client and the
retriever as the module used to at import, and makes `eligibility_check` the SAME module object as
engine.pipeline (sys.modules), so every import of and monkeypatch on eligibility_check reaches the pipeline."""
import os
import sys

from env_setup import load_env  # round 38d: ELIGIBILITY_DOTENV, else the .env here
load_env()

try:
    import streamlit as st
    if "ANTHROPIC_API_KEY" in st.secrets:
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
    if "OPENAI_API_KEY" in st.secrets:
        os.environ["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]
except Exception:
    pass

import engine.pipeline as _pipeline  # noqa: E402

_pipeline.client = _pipeline.make_anthropic_client()
_pipeline.retriever = _pipeline.load_retriever()
sys.modules[__name__] = _pipeline
