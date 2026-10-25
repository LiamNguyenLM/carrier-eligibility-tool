"""Round 43 step 1 (Liam, 2026-10-24): moved to engine/cards.py. This name is the SAME module object
(sys.modules), so `import cards` and every monkeypatch on it reach the engine's code."""
import sys

import engine.cards as _module

sys.modules[__name__] = _module
