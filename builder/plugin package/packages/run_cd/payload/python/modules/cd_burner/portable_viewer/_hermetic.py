"""Hermetic sys.path enforcement for the frozen Lite Viewer.

On a customer PC the host may have its own Python install, a ``PYTHONPATH``,
or user site-packages that leak onto ``sys.path`` and shadow the bundled
dependencies — most dangerously a *different* numpy, whose compiled
extension then clashes with the bundled one and crashes startup. When
frozen, we keep ONLY sys.path entries that live inside the bundle so the
viewer always uses its own dependencies.

Tiny + numpy-free on purpose: the entry script imports and runs this BEFORE
importing the viewer (which pulls in numpy), and tests import the pure
filter directly.
"""

from __future__ import annotations

import os
import sys
from typing import List


def compute_hermetic_path(current_path: List[str], bundle_dirs: List[str]) -> List[str]:
    """Return ``current_path`` filtered to entries inside ``bundle_dirs``.

    Pure function (no globals) so it is unit-testable. Empty entries (''),
    which mean the current working directory, are always dropped so the
    host CWD cannot inject modules.
    """
    norm_bundles = [os.path.abspath(b) for b in bundle_dirs if b]
    kept: List[str] = []
    for entry in current_path:
        if not entry:
            continue  # '' = CWD — never trust the host's working dir
        try:
            absolute = os.path.abspath(entry)
        except Exception:
            continue
        if any(absolute == base or absolute.startswith(base + os.sep) for base in norm_bundles):
            kept.append(entry)
    return kept


def enforce_hermetic_path() -> None:
    """Frozen only: prune sys.path to bundle-internal entries. No-op in dev."""
    if not getattr(sys, "frozen", False):
        return
    bundle_dirs: List[str] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundle_dirs.append(str(meipass))
    try:
        bundle_dirs.append(os.path.dirname(os.path.abspath(sys.executable)))
    except Exception:
        pass
    if not bundle_dirs:
        return
    sys.path[:] = compute_hermetic_path(list(sys.path), bundle_dirs)
