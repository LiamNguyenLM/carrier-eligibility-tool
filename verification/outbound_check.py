"""Round 42 step 0b: every outbound network connection a normal check makes (live configuration: pilot + all batches,
placement ON, Haiku 5.5 low; the key loaded from ELIGIBILITY_DOTENV, never printed), on Liam's Harris HO3 profile and
LANDLORD. Logs socket connects and DNS lookups with the calling module, and counts the retrieval (Chroma) searches.
Round 42 result: 0 connections and 0 lookups at import and in every run; the model was not called (test_no_network.py
keeps it so, zero API). This script makes a live run: PowerShell sets ELIGIBILITY_DOTENV from the user variable.
usage (cwd = the repo): python verification/outbound_check.py"""
import collections
import os
import socket
import sys
import time
import traceback

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "verification"))
for k in ("ELIGIBILITY_RULES_PILOT", "ELIGIBILITY_RULES_SAGE_BATCH", "ELIGIBILITY_RULES_HO3_BATCH",
          "ELIGIBILITY_RULES_DP_BATCH", "ELIGIBILITY_PLACEMENT"):
    os.environ[k] = "1"
os.environ["ELIGIBILITY_MODEL"], os.environ["ELIGIBILITY_EFFORT"] = "claude-haiku-5-5", "low"
os.environ["ELIGIBILITY_USAGE_LOG"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".outbound_usage.jsonl")

LOG = []
PHASE = ["import"]


def _who():
    for f in reversed(traceback.extract_stack()[:-2]):
        p = f.filename.replace("\\", "/")
        if "/venv/" not in p and "site-packages" not in p and "/lib/python" not in p.lower():
            return f"{os.path.basename(p)}:{f.lineno} {f.name}"
    return "?"


_real_connect = socket.socket.connect
_real_gai = socket.getaddrinfo


def connect(self, address):
    LOG.append((PHASE[0], "connect", str(address)[:80], _who()))
    return _real_connect(self, address)


def gai(host, *a, **kw):
    LOG.append((PHASE[0], "dns", str(host), _who()))
    return _real_gai(host, *a, **kw)


socket.socket.connect = connect
socket.getaddrinfo = gai

from env_setup import load_env  # noqa: E402
load_env()
import eligibility_check as ec  # noqa: E402

searches = collections.Counter()
search_s = [0.0]
vs = ec.get_vectorstore()
for name in ("similarity_search", "similarity_search_with_score", "max_marginal_relevance_search", "get"):
    if hasattr(vs, name):
        real = getattr(vs, name)

        def wrap(*a, _real=real, _n=name, **kw):
            t = time.perf_counter()
            try:
                return _real(*a, **kw)
            finally:
                searches[(PHASE[0], _n)] += 1
                search_s[0] += time.perf_counter() - t
        setattr(vs, name, wrap)

import profiles as P  # noqa: E402
from test_held_reasons import LANDLORD  # noqa: E402
print("import-time network:", [(k, a) for p, k, a, w in LOG if p == "import"][:5])
for name, (pd, checked) in (("Harris HO3 (Liam)", (P.HARRIS_PROFILE, P.HARRIS_CHECKED)), ("LANDLORD", (LANDLORD, None))):
    for run in (1, 2):                                      # run 1 warms the store; run 2 is a normal check
        PHASE[0] = f"{name} run {run}"
        n0, s0 = len(LOG), search_s[0]
        t = time.perf_counter()
        res = ec.check_eligibility(dict(pd), checked_topics=checked)
        wall = time.perf_counter() - t
        hits = LOG[n0:]
        print(f"== {PHASE[0]}: {wall:.1f}s, {len(res)} cards; outbound: {len(hits)}; "
              f"retrieval searches: {sum(v for (p, _), v in searches.items() if p == PHASE[0])} "
              f"({search_s[0] - s0:.2f}s); model usage: {ec.LAST_CALL_USAGE}")
        for kind, addr, who in sorted(set((k, a, w) for _, k, a, w in hits)):
            print(f"     {kind:7s} {addr:45s} from {who}")
