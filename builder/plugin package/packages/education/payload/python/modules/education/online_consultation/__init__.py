"""Online Consultation — Education submodule (Drive-backed physician consultation).

This package is the **user-facing home** of the cloud-consultation workflow inside
the Education module. It is intentionally thin: identities/credentials live in
``modules/Identity`` and the engine (transport, envelope, sync, notifications) lives
in ``modules/cloud_consultation``. This submodule only composes them into an
Education tab:

* ``consultation_page.py`` — the "Online Consultation" tab (compose / inbox / sent /
  notifications) embedded in :class:`EducationModuleRedesigned`.
* ``study_select.py``    — multi-select local-study picker that stages an Offline
  Cloud package via the EXISTING export engine (``export_studies_to_offline_cloud``).
* ``respond_dialog.py``  — the assignee's "write opinion → upload response" flow.
* ``status_labels.py``   — maps internal engine statuses to the clinical lifecycle
  labels (Pending / Sent / Received / Answered / Closed).
* ``launcher.py``        — opens the Education tab + this subtab from anywhere
  (e.g. the account popup under the top-right user pill).

Availability is gated on BOTH feature flags (Identity + cloud consultation); when
either is off the Education module renders byte-identically to before.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _consultation_module_enabled() -> bool:
    """Commercial gate: the ``consultation`` entry in the module registry (ADR-0003).

    Source/dev runs are unaffected (``module_enabled_map()`` returns the
    development defaults — all modules enabled). In frozen/packaged builds the
    installer-written runtime profile decides, exactly like the other optional
    modules (printing, run_cd, ...).

    FAILS OPEN (returns True) when the runtime registry cannot be consulted:
    a registry malfunction must never strip a clinically enabled workflow; the
    two feature flags below remain the operational kill switch.
    """
    try:
        from aipacs_runtime import is_module_enabled

        return bool(is_module_enabled("consultation"))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("consultation module-registry check failed (failing open): %s", exc)
        return True


def online_consultation_available() -> bool:
    """True only when both feature flags AND the module registry allow it.

    Gate formula (ADR-0003): Identity flag AND cloud-consultation flag AND
    ``is_module_enabled("consultation")``. This function remains the SINGLE gate
    for the feature — don't bypass it. Never raises and imports nothing heavy,
    so callers may use it unconditionally (e.g. while building the Education
    tab bar).
    """
    try:
        from modules.Identity.feature_flags import identity_module_enabled
        from modules.cloud_consultation.feature_flags import cloud_consultation_enabled

        return bool(
            identity_module_enabled()
            and cloud_consultation_enabled()
            and _consultation_module_enabled()
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("online consultation availability check failed: %s", exc)
        return False
