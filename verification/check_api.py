"""Round 38d step 1 (Liam, 2026-10-13): is the Anthropic API reachable from here (a worktree included)?

usage: python verification/check_api.py

Loads the key the way the app does (env_setup.load_env: ELIGIBILITY_DOTENV, else the .env here), makes ONE tiny
Claude Haiku 5.5 call and prints exactly one line:
  API OK: <model>, <n> tokens
  API FAILED: <auth | no credit | rate limit | network | no key | other: ExceptionType>
It never prints the key, any part of it, or any environment value."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from env_setup import load_env  # noqa: E402

MODEL = "claude-haiku-5-5"


def main():
    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return "API FAILED: no key"
    import anthropic
    try:
        resp = anthropic.Anthropic(max_retries=0).messages.create(
            model=MODEL, max_tokens=32, messages=[{"role": "user", "content": "Reply with the word OK."}])
    except anthropic.AuthenticationError:
        return "API FAILED: auth"
    except anthropic.PermissionDeniedError:
        return "API FAILED: auth"
    except anthropic.RateLimitError:
        return "API FAILED: rate limit"
    except anthropic.APIConnectionError:
        return "API FAILED: network"
    except anthropic.BadRequestError as e:
        return "API FAILED: no credit" if "credit" in str(getattr(e, "message", "")).lower() else "API FAILED: other: BadRequestError"
    except Exception as e:                                   # noqa: BLE001 -- only the type, never the text
        return f"API FAILED: other: {type(e).__name__}"
    return f"API OK: {resp.model}, {resp.usage.input_tokens + resp.usage.output_tokens} tokens"


if __name__ == "__main__":
    print(main())
