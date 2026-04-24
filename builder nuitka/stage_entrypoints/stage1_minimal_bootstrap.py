from __future__ import annotations

import os
import sys
from pathlib import Path

if os.environ.get("AIPACS_STAGE_SMOKE") == "1":
    print("AIPacs stage1 smoke bootstrap OK")
    raise SystemExit(0)

print(f"Python executable: {sys.executable}")
print(f"Running from: {Path.cwd()}")
print("AIPacs stage1 bootstrap executable generated successfully.")
