"""Consultation envelope (Phase 3).

Adds a deterministic, integrity-checked *consultation* layer on top of an existing
Offline Cloud package, stored as a sibling ``consultation.json`` file. The clinical
package itself (``manifest.json`` + ``package.db`` + ``patients/``) is never modified,
so the guarded offline-export/import engine stays byte-identical.
"""
