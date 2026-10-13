"""Round 38d step 1 (Liam, 2026-10-13): the one place that loads the .env file.

Worktrees under the Temp folder have no .env (it is git-ignored, so it lives only in the main checkout), and a bare
load_dotenv() there finds nothing. Liam set the Windows user variable ELIGIBILITY_DOTENV to the main checkout's .env:

  - ELIGIBILITY_DOTENV set and the file exists -> that file is loaded;
  - otherwise -> load_dotenv() exactly as before (the .env next to this code, if any).

Values already in the environment always win (override=False), so Railway -- which sets its own variables -- is
unchanged. This module never reads, returns, prints or logs a value from the file.
"""
import os

from dotenv import load_dotenv

ENV_VAR = "ELIGIBILITY_DOTENV"


def load_env():
    """Load the .env file; return the path loaded from ELIGIBILITY_DOTENV, or None when the default search ran."""
    path = os.environ.get(ENV_VAR, "").strip()
    if path and os.path.isfile(path):
        load_dotenv(path, override=False)
        return path
    load_dotenv(override=False)
    return None
