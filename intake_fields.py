"""Round 43 step 1 (Liam, 2026-10-24): moved to engine/intake_fields.py. This name is the SAME module object
(sys.modules), so `import intake_fields` and every monkeypatch on it reach the engine's code."""
import sys

import engine.intake_fields as _module

sys.modules[__name__] = _module
