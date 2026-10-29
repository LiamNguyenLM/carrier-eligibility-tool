"""Round 45: run Ask the Guides live (PAID; Haiku 5.5 costs about $0.001 a question) through the Worker's own code path.

    python verification/chat/run_live.py [--ids Q01,Q07] [--cap 2.00] [--model claude-sonnet-5-5] [--out FILE]

The key: env_setup.load_env() reads it into THIS process (ELIGIBILITY_DOTENV, as every live run here does), and the
Node child inherits it. Nothing prints it, and it is never set in a shell or a settings file. Without a key: exit 2.
"""
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

import env_setup  # noqa: E402

env_setup.load_env()
if not os.environ.get("ANTHROPIC_API_KEY"):
    print("no ANTHROPIC_API_KEY loaded (set ELIGIBILITY_DOTENV for this process)")
    sys.exit(2)
sys.exit(subprocess.call(["node", "cloudflare/scripts/chat_live.mjs", *sys.argv[1:]], cwd=ROOT))
