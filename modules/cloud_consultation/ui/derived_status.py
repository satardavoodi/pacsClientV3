"""Qt-free derived consultation capabilities (owner directive 2026-06-11).

ONE workstation login + ONE-time Google identity connection — everything else
is DERIVED. This module computes the derived consultation mode for the account
dropdown / Manage Account dialog and for the external-consultation UI gate:

* ``identity_linked``    — an ``aipacs_web`` identity exists (the Laravel link
  already implies an authorized consultation profile).
* ``consultation_active`` — same as ``identity_linked``.
* ``hub_available``      — a Google (Drive) identity exists for this user (the
  hub connect, ADR-0004 — deployment setup, not a user login).
* ``internal_enabled``   — consultation module available
  (``online_consultation_available()``) AND ``identity_linked``. NO hub
  requirement: internal consultations are license + identity only.
* ``external_enabled``   — ``internal_enabled`` AND ``hub_available``.
* ``status_text``        — the dropdown's one-line consultation status.

Presentation/derived state ONLY: nothing here touches the engine, transport,
poller, or state machine, and every probe is guarded — this module never
raises and imports nothing heavy (and no Qt) at module import time. All three
probes can be injected for headless unit tests.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

STATUS_ACTIVE = "Consultation: Active"
STATUS_INTERNAL_ONLY = "Consultation: Active (internal only — no cloud hub)"
STATUS_NOT_ENABLED = "Consultation: Not enabled"


# ── default probes (lazy imports, never raise) ────────────────────────────────
def _default_identity_linked(aipacs_user: str) -> bool:
    try:
        from modules.Identity.providers.aipacs_web import find_aipacs_web_identity

        return find_aipacs_web_identity(aipacs_user) is not None
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("identity-linked probe failed: %s", exc)
        return False


def _default_hub_available(aipacs_user: str) -> bool:
    """True when a Google (Drive hub) identity is linked. Never raises."""
    try:
        from database import identity_db

        for ident in identity_db.list_identities(aipacs_user):
            if getattr(ident, "provider", "") == "google":
                return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("hub-available probe failed: %s", exc)
    return False


def _default_module_available() -> bool:
    """The ADR-0003 triple gate; an import failure means the module is absent."""
    try:
        from modules.education.online_consultation import (
            online_consultation_available,
        )

        return bool(online_consultation_available())
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("consultation module gate probe failed: %s", exc)
        return False


# ── the derived-capability matrix ─────────────────────────────────────────────
def consultation_capabilities(
    aipacs_user: str,
    *,
    identity_linked: bool | None = None,
    hub_available: bool | None = None,
    module_available: bool | None = None,
) -> dict:
    """Derived consultation mode for ``aipacs_user``. Never raises.

    The keyword overrides replace the live probes (for unit tests, or when the
    caller already resolved an identity — e.g. the dropdown card passes
    ``identity_linked=True`` for the identity it is rendering).
    """
    if identity_linked is None:
        identity_linked = _default_identity_linked(aipacs_user)
    if hub_available is None:
        hub_available = _default_hub_available(aipacs_user)
    if module_available is None:
        module_available = _default_module_available()

    identity_linked = bool(identity_linked)
    hub_available = bool(hub_available)
    module_available = bool(module_available)

    internal_enabled = module_available and identity_linked
    external_enabled = internal_enabled and hub_available
    if not internal_enabled:
        status_text = STATUS_NOT_ENABLED
    elif hub_available:
        status_text = STATUS_ACTIVE
    else:
        status_text = STATUS_INTERNAL_ONLY

    return {
        "identity_linked": identity_linked,
        "consultation_active": identity_linked,
        "hub_available": hub_available,
        "internal_enabled": internal_enabled,
        "external_enabled": external_enabled,
        "status_text": status_text,
    }
