"""AI-PACS automatic incremental update system (OPT-38, 2026-07-16).

Layers (keep the import discipline — tests pin it):

- ``manifest``  : PURE stdlib. Hashing, file-level manifest build/parse/validate,
                  path-safety guard, diff plan, content-addressed store I/O,
                  local hash-index cache.
- ``client``    : PURE stdlib (urllib). Multi-source failover check, manifest
                  fetch + verify, plan, chunked downloads with progress +
                  retries, staging, installer-fallback decision.
- ``apply``     : Plan validation + PowerShell helper generation + launch +
                  boot-time version reconcile / maintenance. No Qt at import.
- ``service``   : Qt startup service (delayed, off-thread check). GUI thread is
                  never blocked.
- ``ui``        : Qt dialogs (notification, progress, restart prompt).

Design + guardrails: docs/plans/architecture/AUTO_UPDATE_SYSTEM_2026-07-16.md.
The updater must NEVER touch center-specific state (%APPDATA% config,
User Data, ProgramData profile except the best-effort app_version stamp).
"""

from __future__ import annotations

__all__ = [
    "manifest",
    "client",
    "apply",
]
