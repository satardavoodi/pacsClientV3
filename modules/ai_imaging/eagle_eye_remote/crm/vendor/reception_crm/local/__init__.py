"""Direct access to the reception system's own storage on this machine.

This package exists only because the agent is installed ON the reception
server. It provides what the vendor's HTTP API cannot: retrieval and full-text
search of clinical report bodies, patient report history, and integrity checks
between records and files.

Two rules govern everything in here:

1. **Reads only.** Every write still goes through ``ino_api.InoClient``. A
   direct write would bypass the vendor's validation, business logic and audit
   trail, and could corrupt a clinical record in a way nobody could later
   explain. ``mongo.ReadOnlyDatabase`` makes that structural rather than a
   convention -- the write methods are simply not reachable.
2. **The API stays primary.** Anything the vendor already exposes and
   aggregates (daily summaries, financials, the reporting worklist,
   authentication) keeps going through the API. This package is for the gaps.
"""

from .html_text import html_to_text
from .mongo import LocalMongoUnavailable, ReadOnlyCollection, ReadOnlyDatabase, reception_db

__all__ = [
    "html_to_text",
    "reception_db",
    "ReadOnlyDatabase",
    "ReadOnlyCollection",
    "LocalMongoUnavailable",
]
