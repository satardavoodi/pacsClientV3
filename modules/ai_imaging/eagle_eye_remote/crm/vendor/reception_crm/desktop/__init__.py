"""Native desktop UI for the Reception CRM agent.

The core package stays dependency-free. This subpackage is the only place that
imports Qt, and it is an optional extra:

    pip install PySide6-Essentials

Qt is used instead of Tkinter because Tk 8.6 cannot shape Arabic/Persian
script (letters render disconnected), which is unusable for this app.

Entry point:

    python -m reception_crm.desktop
"""

from __future__ import annotations

__all__ = ["main"]


def main() -> int:
    from .app import main as _main

    return _main()
