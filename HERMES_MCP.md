# Carrier eligibility tool -> Hermes (CFIG-GPT)

`carrier_mcp.py` exposes this tool to Hermes as an MCP server (stdio). It is read-only: no uploads, reseeds or
writes to the carrier store.

| Tool | What it returns | Cost |
|---|---|---|
| `list_carriers` | Indexed programs, forms, guide dates | Free |
| `search_guidelines(query, carrier?, k=4)` | Verbatim passages with file and page. The carrier filter runs inside the Chroma query | Free |
| `check_eligibility(profile)` | `summary_markdown`: the app's results page (checked as / not checked, placement top 3, things to confirm, every carrier by status in the app's words) | Paid, 30-90 s, billed to this tool's `.env` keys |
| `carrier_details(carrier)` | One carrier's full card from the last check: missing, every item to confirm, coverage notes, citations, guide date | Free, no rerun |

Rules the server enforces:
- `occupancy_type`, `ownership_type` and `dwelling_type` are required (the form always sends them). A missing one is
  rejected so Hermes asks instead of assuming.
- Any other topic is checked only when its field is given -- the same as a ticked box on the form.
- Every reply stays under ~8,000 characters. Hermes spills longer tool results to a file and the model then reads
  pieces of it, which is how an earlier version lost the placement panel.
- The placement panel follows `placement.enabled()`; Hermes does not pass Windows environment variables, so the
  Hermes config sets `ELIGIBILITY_PLACEMENT: '1'` for this server.
- stdout carries only MCP: the real stdout is duplicated for the protocol and fd 1 / sys.stdout point at stderr.

## Install (once)

```powershell
cd C:\Users\Intern\carrier\carrier-eligibility-tool
.\venv\Scripts\pip install -r requirements-mcp.txt     # mcp==1.30.0 (2.x renamed FastMCP); not on Railway
```

## Tests

```powershell
.\venv\Scripts\python -m pytest verification\test_carrier_mcp.py -q      # free, no API key; 20 tests
.\venv\Scripts\python verification\mcp_parity.py                          # paid: app vs MCP on the 3 audit profiles
.\venv\Scripts\python verification\mcp_parity.py --runs 3                 # separates drift from wrapper bugs
```

## Hermes config

`C:\Users\Intern\AppData\Local\hermes\config.yaml`, under `mcp_servers:`:

```yaml
  carrier-eligibility:
    command: C:\Users\Intern\carrier\carrier-eligibility-tool\venv\Scripts\python.exe
    args:
      - C:\Users\Intern\carrier\carrier-eligibility-tool\carrier_mcp.py
    cwd: C:\Users\Intern\carrier\carrier-eligibility-tool
    env:
      TEMP: C:\Users\Intern\AppData\Local\Temp
      TMP: C:\Users\Intern\AppData\Local\Temp
      ELIGIBILITY_PLACEMENT: '1'
    timeout: 180
```

No API key goes in this file; the server loads the tool's own `.env` through `env_setup.load_env()`. Fully quit and
reopen Hermes after any change to `carrier_mcp.py` or this block.

## Hermes skill (`carrier-eligibility`)

> Use the carrier-eligibility tools for any question about which carriers will write a property or what a carrier's
> rule says. Never answer carrier rules from memory or from earlier summaries.
> - Eligibility check: dwelling type, occupancy and ownership must come from the agent in this chat. Ask if they
>   haven't said them, and never carry them over from another chat. Offer to add ZIP or county, roof shape, pool,
>   dogs and losses, but run without them if the agent skips.
> - After check_eligibility, show summary_markdown exactly as returned, then at most two sentences of your own.
> - Follow-up questions about one carrier: carrier_details, not a rerun.
> - Run the check again if any input changed, a required field was missing last time, or the tool was restarted.
> - One carrier's rule: search_guidelines with that carrier; quote the passage and cite file and page. If nothing
>   relevant comes back, say so.
> - Unsure of a carrier's exact name, or whether CFIG has it: list_carriers.

## Later: agency-wide

The same file can run as a second Railway service with `transport="streamable-http"` behind a bearer token, so every
Hermes or Teams client shares one index. Not before the local version passes parity.
