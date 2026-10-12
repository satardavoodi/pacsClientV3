"""Runtime location resolution — the one place that knows where we are installed.

Why this module exists
----------------------
Before this, several modules computed their base directory with
``Path(__file__).resolve().parents[N]``. That is correct when running from a
source checkout and **wrong once PyInstaller freezes the app**: ``__file__``
then points inside the extracted bundle (``sys._MEIPASS``), a temporary
directory that Windows deletes when the process exits. A packaged server would
have written patient data, logs, and manifests into that temp folder and lost
them on every restart.

Three distinct locations, deliberately kept separate:

``install_root()``   where the program lives      (read-only in Program Files)
``config_root()``    where operator config lives  (writable, survives upgrade)
``data_root()``      where clinical data lives    (writable, operator-chosen)

They are separate because an upgrade replaces the first and must never touch
the other two.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Reception CRM Server"

# The last-resort data location for a FROZEN install whose configuration could
# not be read.
#
# This used to be `D:\RAZI crm` -- one clinic's name, on a drive letter that
# machine happens to have. On a reception server without a D: drive the service
# could not create its data folder and would not start, and every other site
# would have been storing its patient data in a directory named after Razi.
#
# %ProgramData% always exists, is always writable by the service account, and
# survives an upgrade. It is a FALLBACK, not a recommendation: the data folder
# holds PHI and grows, so the installer asks the operator to site it
# deliberately on a data drive and the configured value always wins.
DEFAULT_DATA_ROOT = Path(os.getenv("ProgramData") or r"C:\ProgramData") / APP_NAME / "Data"


def is_frozen() -> bool:
    """True when running from a PyInstaller-built executable."""
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """Directory holding bundled read-only resources (templates, html).

    Under PyInstaller this is the extraction dir; from source it is the
    repository root.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def install_root() -> Path:
    """Directory containing the running program.

    Frozen: the folder holding the .exe (e.g. ``C:\\Program Files\\...``).
    Source: the repository root.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def config_root() -> Path:
    """Writable directory for operator configuration.

    Resolution order:
      1. ``RECEPTION_CRM_CONFIG_DIR``
      2. ``%ProgramData%\\Reception CRM Server`` when frozen (survives upgrade,
         and is writable by a service running as LocalSystem, unlike
         Program Files)
      3. ``<repo>/config`` when running from source
    """
    override = os.getenv("RECEPTION_CRM_CONFIG_DIR")
    if override:
        return Path(override)

    if is_frozen():
        program_data = os.getenv("ProgramData") or r"C:\ProgramData"
        return Path(program_data) / APP_NAME

    return install_root() / "config"


def data_root() -> Path:
    """Root of the clinical data tree (raw snapshots, reports, manifests).

    Never derived from ``__file__``: when frozen that would point at a temp
    directory. An explicit env var wins, then the configured default.
    """
    override = os.getenv("RECEPTION_CRM_DATA_ROOT")
    if override:
        return Path(override)

    if is_frozen():
        # A frozen install must be told where the data lives; falling back to
        # the exe folder would scatter patient data into Program Files.
        return DEFAULT_DATA_ROOT

    return install_root()


def log_root() -> Path:
    """Directory for service logs. Writable in every deployment mode."""
    override = os.getenv("RECEPTION_CRM_LOG_DIR")
    if override:
        return Path(override)
    return data_root() / "logs"


def ensure_dir(path: Path) -> Path:
    """Create ``path`` if missing and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def describe() -> dict[str, str]:
    """Diagnostic snapshot — surfaced by the ``server --describe`` command."""
    return {
        "frozen": str(is_frozen()),
        "executable": sys.executable,
        "bundle_dir": str(bundle_dir()),
        "install_root": str(install_root()),
        "config_root": str(config_root()),
        "data_root": str(data_root()),
        "log_root": str(log_root()),
    }
