"""Apply saved server / profile settings at runtime (no full app restart).

SCOPE RULE (2026-08-02, integration review of the ``satar`` UI branch)
---------------------------------------------------------------------
A **same-profile** edit (host / port / timeout of the ACTIVE centre) can be
applied live — that is what this module is for, and it is a real improvement
over the previous "nothing happens until restart".

A **profile switch** (a DIFFERENT centre) **cannot**. The clinical data root is
per-profile (``server_profiles.clinical_data_root`` → ``user_data/servers/<slug>``),
and ~33 production modules bind ``SOURCE_PATH`` / ``THUMBNAIL_PATH`` /
``ATTACHMENT_PATH`` **by value** at import time — all of them already imported
before the login screen exists (``main.py`` → ``app_handler`` → ``mainwindow_ui``
→ ``AIPacs_ui`` → ``home_ui/__init__`` → ``home_db_service``). Rebinding the
module attributes therefore reaches the DATABASE (``database/_pool.py`` resolves
``DATABASE_FILE`` with an in-function import) but **not** the file paths, so the
workstation would write rows into centre B's ``dicom.db`` while downloading
DICOM, thumbnails and attachments into centre A's tree.

So ``profile_switched=True`` returns :data:`RESTART_REQUIRED` and the caller must
close the app. That is the same contract the login window had before the branch
("AI-PACS will now close — please reopen it") and the same one
``server_profiles.set_feature_enabled`` documents ("Takes effect on the next app
start — the data root + socket target resolve at startup").

A restart-free centre switch is possible, but only AFTER the by-value importers
are converted to attribute access (``from PacsClient.utils import config`` →
``config.SOURCE_PATH``), guarded by a test that forbids module-level imports of
those names. That is a separate, test-gated piece of work — not a login-screen
feature. Same defect class as the voice-to-text ``AI_BASE`` note in CLAUDE.md.

Kill switch: ``AIPACS_PROFILE_SWITCH_RESTART=0`` restores the branch's original
runtime-rebind behaviour (legacy path preserved byte-identical, per the house
rule).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

#: Returned by :func:`apply_saved_server_settings_runtime` when the caller must
#: restart the application instead of continuing with live-applied settings.
RESTART_REQUIRED = "restart_required"

#: Returned when the settings were applied live and the session may continue.
APPLIED = "applied"


def _restart_on_profile_switch() -> bool:
    """Default ON. ``AIPACS_PROFILE_SWITCH_RESTART=0`` = legacy runtime rebind."""
    return os.environ.get("AIPACS_PROFILE_SWITCH_RESTART", "1") != "0"


def _apply_legacy_profile_runtime_rebind() -> None:
    """Legacy (branch-original) path — kept intact behind the kill switch.

    UNSAFE for a genuine profile switch: see the module docstring. Reachable only
    with ``AIPACS_PROFILE_SWITCH_RESTART=0``.
    """
    try:
        from PacsClient.utils.data_paths import reload_active_profile_paths

        reload_active_profile_paths()
    except Exception as exc:
        logger.warning("runtime server apply: path reload failed: %s", exc)
    try:
        from modules.network.reception_api_config import reload_reception_api_config

        reload_reception_api_config()
    except Exception as exc:
        logger.warning("runtime server apply: reception reload failed: %s", exc)
    try:
        # database.core re-exports this; prefer the public module over database._pool.
        from database.core import cleanup_connection_pools

        cleanup_connection_pools()
    except Exception as exc:
        logger.warning("runtime server apply: db pool cleanup failed: %s", exc)


def apply_saved_server_settings_runtime(*, profile_switched: bool = False) -> str:
    """Push persisted server settings into live in-memory targets.

    Call after the login gear or any writer that updates ``server_profiles`` and
    ``socket_config.json``. Never raises.

    Returns
    -------
    str
        :data:`RESTART_REQUIRED` when the caller must close the application (a
        different centre was selected), otherwise :data:`APPLIED`.
    """
    if profile_switched and _restart_on_profile_switch():
        # Do NOT rebind clinical paths or drop the DB pool here — a half-switched
        # process splits the database from the image/thumbnail/attachment tree.
        logger.info(
            "Runtime server settings: profile switched — restart required "
            "(clinical data root + socket target resolve at startup)."
        )
        return RESTART_REQUIRED

    try:
        from modules.network.socket_config import get_socket_config

        config = get_socket_config()
        host = str(config.get_socket_host())
        port = int(config.get_socket_port())
    except Exception as exc:
        logger.warning("runtime server apply: config read failed: %s", exc)
        return APPLIED

    if profile_switched:
        # Legacy kill-switch path only (AIPACS_PROFILE_SWITCH_RESTART=0).
        _apply_legacy_profile_runtime_rebind()

    try:
        from modules.network import socket_patient_service as sps

        # Deliberately the module-private singleton and NOT
        # get_socket_patient_service(): the public accessor CONSTRUCTS the service
        # when it does not exist yet, which at the login screen would spin up a
        # socket service the session does not otherwise need. We only refresh one
        # that is already live.
        svc = getattr(sps, "_socket_patient_service", None)
        if svc is not None:
            svc.update_server_settings(host, port, save_to_file=False)
    except Exception as exc:
        logger.warning("runtime server apply: patient service refresh failed: %s", exc)

    logger.info(
        "Runtime server settings applied (%s:%s profile_switched=%s)",
        host,
        port,
        profile_switched,
    )
    return APPLIED
