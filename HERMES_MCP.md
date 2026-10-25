# Carrier eligibility tool -> Hermes (CFIG-GPT)

`carrier_mcp.py` exposes this tool to Hermes as an MCP server (stdio). It is read-only: no uploads, reseeds or
writes to the carrier store, the rules data or `.env`. It imports the engine directly and makes no HTTP calls.

| Tool | What it returns | Cost |
|---|---|---|
| `list_carriers` | Indexed programs, forms, guide dates | Free |
| `search_guidelines(query, carrier?, k=4)` | Verbatim passages with file and page. The carrier filter runs inside the Chroma query | Free |
| `check_eligibility(profile, dwelling_type_quote)` | **Plain text**, the app's results page: Checked as / Not checked, "Where we usually place homes like this" (numbered top 3 with bullets and footer), "Things to confirm with the client", then Eligible / Refer / Insufficient information / Not eligible. It runs the website's engine call, `engine.api.check` with `rules_data/engine_manifest.json`, so its verdicts match the website's | Free: no model call, no network. About 0.3-0.9 s a check once the server is up (measured 2026-10-25, office laptop) |
| `carrier_details(carrier)` | One carrier's full card from the last check: missing, every item to confirm, coverage notes, citations, guide date | Free, no rerun |

Rules the server enforces:
- `occupancy_type`, `ownership_type` and `dwelling_type` are required (the form always sends them). A missing one is
  rejected so Hermes asks instead of assuming.
- `dwelling_type_quote` must be the agent's own words, and they must name House, Townhome or Condo ("home" names
  none of them). Otherwise the profile is rejected before any check runs.
- Any other topic is checked only when its field is given, the same as a ticked box on the form. Unticked County /
  Coverage A count as blank, as in the app.
- Every reply stays under ~8,000 characters (the results page is cut to 7,000). Hermes spills longer tool results
  to a file and the model then reads pieces of it, which is how an earlier version lost the placement panel.
- The placement panel follows `placement.enabled()`. It is on by default; the Hermes config below also sets
  `ELIGIBILITY_PLACEMENT: '1'`, because Hermes does not pass Windows environment variables.
- stdout carries only MCP: the real stdout is duplicated for the protocol and fd 1 / sys.stdout point at stderr.

## Install (once)

```powershell
cd C:\Users\Intern\carrier\carrier-eligibility-tool
.\venv\Scripts\pip install -r requirements-mcp.txt     # mcp==1.30.0 (2.x renamed FastMCP)
```

## Tests

```powershell
.\venv\Scripts\python -m pytest verification\test_carrier_mcp.py -q      # free, no API key; 36 tests
.\venv\Scripts\python verification\mcp_parity.py                          # free: the website's engine call vs MCP, 3 profiles
.\venv\Scripts\python -m pytest verification\test_parity_golden.py -q     # includes the connector against the golden file
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

No API key goes in this file, and the tools need none: checks make no model call and search is local. Fully quit and
reopen Hermes after any change to `carrier_mcp.py` or this block.

## Hermes skill (`carrier-eligibility`)

> Use the carrier-eligibility tools for any question about which carriers will write a property or what a carrier's
> rule says. Never answer carrier rules from memory or from earlier summaries.
> - **Eligibility check:**
>   - Dwelling type, occupancy and ownership must come from the agent in this chat. Ask if they haven't said them,
>     and never carry them over from another chat.
>   - Pass the agent's own words that state the dwelling type as `dwelling_type_quote` (e.g. "it's a house"). If
>     they only said "home", ask: House, Townhome or Condo?
>   - Offer to add ZIP or county, roof shape, pool, dogs and losses, but run without them if the agent skips.
> - **The reply:** check_eligibility returns the results page as plain text. Copy it to the agent exactly as
>   returned, from the first line to the last: every heading, numbered line and bullet, in order, including the
>   numbered "Where we usually place homes like this" ranking, its bullets and its footer. Then add at most two
>   sentences of your own. Don't add rules or verdicts the page doesn't state.
> - **Follow-up questions about one carrier:** carrier_details, not a rerun.
> - **Run the check again** if any input changed, a required field was missing last time, or the tool was restarted.
> - **One carrier's rule:** search_guidelines with that carrier. Quote the passage and cite file and page. If nothing
>   relevant comes back, say so.
> - **Unsure of a carrier's exact name, or whether CFIG has it:** list_carriers.

## Later: agency-wide

For the central CFIG-GPT, this connector runs as a Python process on the same server as the Hermes backend, from a
checkout of this repo (stdio as here, or `transport="streamable-http"` on that server). The website (Cloudflare)
needs nothing for it, and there is no Worker route for checks: the website runs the engine in the browser, and the
connector imports the same engine. Keep the server's checkout current (a `git pull` after rule changes), as on this
laptop.
