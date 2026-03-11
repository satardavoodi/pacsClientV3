"""
Canonical project-root resolver — zero dependencies, safe to import anywhere.

Usage::

    from _project_root import PROJECT_ROOT   # Path to the repo / PyInstaller bundle

All other modules should use this instead of computing their own root via
``Path(__file__).parents[N]``.  The logic mirrors ``PacsClient/utils/config.py``
but lives at the repo toplevel so:

* it never triggers circular imports;
* the ``parents[N]`` index is always 0 (this file *is* at the root);
* it handles PyInstaller (``sys._MEIPASS``) transparently.
"""

import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # Running inside a PyInstaller bundle
    PROJECT_ROOT: Path = Path(sys._MEIPASS)
else:
    # Running as a normal script — this file sits at the repository root
    PROJECT_ROOT: Path = Path(__file__).resolve().parent
