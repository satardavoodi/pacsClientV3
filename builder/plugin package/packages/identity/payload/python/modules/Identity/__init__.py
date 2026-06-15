"""AI-PACS ``Identity`` module — external identity providers (Google first).

This module is **additive** and **feature-flagged** (default **OFF**). It lets a
signed-in AI-PACS user attach *external* accounts (Google now; Telegram/Instagram
later) to their existing profile. It **never** modifies or replaces the existing
AI-PACS server/center login — it only *links* external identities to the current
user and stores their credentials securely.

Design/as-built reference:
    docs/plans/cloud-consultation/GOOGLE_DRIVE_CONSULTATION_PLAN_2026-05-31.md

Import safety
-------------
The package ``__init__`` intentionally does **not** import provider, UI, or Qt
code, nor any optional third-party dependency (google-auth, keyring, cryptography).
Those are imported lazily where used so that merely importing :mod:`modules.Identity`
is cheap and cannot fail when an optional dependency is absent.
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
