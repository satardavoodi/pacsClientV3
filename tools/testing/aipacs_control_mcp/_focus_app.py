# -*- coding: utf-8 -*-
"""Bring the app main window to the foreground (pywinauto set_focus)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import lifecycle

best, area = None, -1
for w in lifecycle._app_windows():
    try:
        r = w.rectangle()
        a = max(0, r.width()) * max(0, r.height())
        if a > area:
            best, area = w, a
    except Exception:
        continue
if best is None:
    print("NO_WINDOW")
else:
    try:
        best.set_focus()
        print("FOCUSED:", best.window_text())
    except Exception as e:
        print("FOCUS_FAILED:", e)
