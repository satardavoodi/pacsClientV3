# -*- coding: utf-8 -*-
"""Debug: dump UIA children of the Disk Space Alert dialog."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import lifecycle

for w in lifecycle._app_windows():
    try:
        t = w.window_text() or ""
    except Exception:
        continue
    if "Disk Space" not in t:
        continue
    print("WINDOW:", t)
    try:
        for d in w.descendants():
            try:
                print("  type=%-12s name=%r auto_id=%r" % (
                    d.element_info.control_type, d.window_text(),
                    getattr(d.element_info, "automation_id", "")))
            except Exception as e:
                print("  <err>", e)
    except Exception as e:
        print("descendants failed:", e)
