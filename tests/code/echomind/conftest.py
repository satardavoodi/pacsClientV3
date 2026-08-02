"""Test fixtures for the EchoMind Command Layer unit tests.

Keeps the project root on ``sys.path`` so ``from modules.EchoMind.secretary
import ...`` resolves.

── Qt stub pollution (fixed 2026-07-28) ─────────────────────────────────────
Four test modules in this directory inject placeholder Qt modules so they can
run headless:

    test_ct_reporter.py          -> PySide6, .QtCore, .QtWidgets, .QtGui,
                                    .QtNetwork, .QtMultimedia
    test_gapgpt_connection.py    -> PySide6, .QtCore, .QtWidgets, .QtGui
    test_mammography_reporter.py -> (same idea)
    test_mri_reporter.py         -> (same idea)

Each does ``if name not in sys.modules: sys.modules[name] = ModuleType(name)``
at IMPORT time and never restores it. All four sort alphabetically BEFORE
``test_test_server.py``, so in any directory-level run that file's

    from PySide6.QtNetwork import QLocalSocket

resolved against an EMPTY stub package and raised

    ImportError: cannot import name 'QLocalSocket' ... (unknown location)

— which aborted collection for the whole directory and silently cost us the 4
EchoMind IPC control-server guards. Run alone, that file passes; only the
directory run was broken, so the merge gate reported green while covering less
than it claimed.

THE FIX IS CENTRAL, NOT PER-FILE: import the REAL PySide6 submodules here,
before any test module is imported. Every ``if name not in sys.modules`` guard
then sees the genuine module and installs nothing, so the stubs revert to what
they were always meant to be — a fallback for an environment where PySide6 is
actually absent. Nothing in those four files needed to change.

Do NOT "optimise" this away: without it, adding any new Qt-dependent test to
this directory is a coin flip on collection order.
"""
import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _preload_real_qt() -> None:
    """Populate sys.modules with the REAL PySide6 submodules when available.

    Import-only: this creates no QApplication and needs no display. If PySide6
    is genuinely missing (headless CI without Qt), every import fails quietly
    and the per-file stubs behave exactly as before.
    """
    for name in (
        "PySide6",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PySide6.QtNetwork",
        "PySide6.QtMultimedia",
    ):
        try:
            __import__(name)
        except Exception:
            # Absent or unbuildable in this environment — leave it to the stubs.
            pass


_preload_real_qt()
