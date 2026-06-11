"""Application-level autostart for the ConsultationPoller (idempotent singleton).

Called from the account-popup hook at startup and again after a Google account is
connected. Keeps exactly one poller alive per process, parented to the
QApplication instance so it survives window churn. No-ops (and is import-cheap)
when the cloud-consultation flag is off or no Google identity is linked.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_POLLER_ATTR = "_aipacs_consultation_poller"


def _google_identity(aipacs_user: str):
    from modules.Identity.identity_service import IdentityService

    for ident in IdentityService(aipacs_user).list_identities():
        if ident.provider == "google":
            return ident
    return None


def _make_transport_provider(aipacs_user: str, subject_id: str):
    def _provider():
        try:
            from modules.cloud_consultation.transport.google_drive import (
                build_google_drive_transport,
            )

            return build_google_drive_transport(aipacs_user, subject_id)
        except Exception as exc:
            logger.debug("poller transport build failed: %s", exc)
            return None

    return _provider


def ensure_consultation_poller(auth_user: dict | None = None) -> bool:
    """Start (or restart with a fresh identity) the consultation poller.

    Returns True when a poller is running after the call. Never raises.
    """
    try:
        from modules.cloud_consultation.feature_flags import cloud_consultation_enabled

        if not cloud_consultation_enabled():
            return False

        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return False

        from modules.Identity.identity_service import IdentityService

        aipacs_user = IdentityService.resolve_aipacs_user(auth_user or {})
        ident = _google_identity(aipacs_user)
        if ident is None or not ident.handle:
            return False  # nothing to poll for yet; call again after connect

        # Hub mode (2026-06-10): inbox matching uses the workstation's
        # consultation address, falling back to the Google handle so the
        # personal-account flow behaves exactly as before. ADR-0008 (2026-06-11):
        # a linked aipacs_web identity's attested Gmail slots in between the
        # flag file and the Google-handle default.
        from modules.cloud_consultation.feature_flags import consultation_address

        my_address = consultation_address(
            default=ident.handle, aipacs_user=aipacs_user
        )

        existing = getattr(app, _POLLER_ATTR, None)
        if existing is not None:
            # Same identity/address → keep the running poller; else replace it.
            if getattr(existing, "_my_email", None) == my_address:
                return True
            try:
                existing.stop()
            except Exception:  # pragma: no cover - defensive
                pass

        from .poller import ConsultationPoller

        poller = ConsultationPoller(
            _make_transport_provider(aipacs_user, ident.subject_id),
            my_address,
            parent=app,
        )
        poller.start()
        setattr(app, _POLLER_ATTR, poller)
        logger.info("consultation poller started for %s", my_address)
        return True
    except Exception as exc:  # pragma: no cover - must never break callers
        logger.debug("ensure_consultation_poller failed: %s", exc)
        return False
