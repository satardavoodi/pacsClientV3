from __future__ import annotations

import os

import database
import database.core
import database.manager
import modules.module_system

if os.environ.get("AIPACS_STAGE_SMOKE") == "1":
    print("AIPacs stage3 core bootstrap OK")
    raise SystemExit(0)
