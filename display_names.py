"""Round 43 step 1 (Liam, 2026-10-24): moved to engine/display_names.py. This name is the SAME module object
(sys.modules), so `import display_names` and every monkeypatch on it reach the engine's code."""
import sys

import engine.display_names as _module

sys.modules[__name__] = _module
