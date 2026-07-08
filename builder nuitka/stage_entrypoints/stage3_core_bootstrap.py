from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import database._pool
import modules.module_system

if os.environ.get("AIPACS_STAGE_SMOKE") == "1":
    print("AIPacs stage3 core bootstrap OK")
    raise SystemExit(0)
