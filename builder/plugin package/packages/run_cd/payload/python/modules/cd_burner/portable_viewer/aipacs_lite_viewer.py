"""Standalone build entry for the AI-PACS Lite Viewer (PyInstaller/Nuitka).

Compiled by ``tools/build/build_lite_viewer.py``. The package directory is
put on ``sys.path`` so the sibling modules import as plain modules.

IMPORTANT: do NOT import ``modules.cd_burner...`` here (not even in a
try/except fallback) — freeze tools follow that import statically and drag
the whole workstation import chain (qtawesome/comtypes/extra Qt modules)
into the portable bundle. For dev runs inside the repo use
``python -m modules.cd_burner.portable_viewer`` instead.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Frozen-only: drop any host Python / PYTHONPATH / site-packages entries from
# sys.path BEFORE importing the viewer (which loads numpy), so a different
# numpy on the customer's machine can't clash with the bundled one. No-op in
# dev. Runs after the _HERE insert (which is inside the bundle, so kept).
from _hermetic import enforce_hermetic_path  # noqa: E402

enforce_hermetic_path()

from viewer_app import main  # noqa: E402  — standalone import — keep it this way

if __name__ == "__main__":
    sys.exit(main())
