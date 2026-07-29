"""Apply saved server / profile settings at runtime (no full app restart)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def apply_saved_server_settings_runtime(*, profile_switched: bool = False) -> None:
    """Push persisted server settings into live in-memory targets.

    Call after the login gear or any writer that updates ``server_profiles`` and
    ``socket_config.json``. Never raises.
    """
    try:
        from modules.network.socket_config import get_socket_config

        config = get_socket_config()
        host = str(config.get_socket_host())
        port = int(config.get_socket_port())
    except Exception as exc:
        logger.warning("runtime server apply: config read failed: %s", exc)
        return

    if profile_switched:
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
            from database._pool import cleanup_connection_pools

            cleanup_connection_pools()
        except Exception as exc:
            logger.warning("runtime server apply: db pool cleanup failed: %s", exc)

    try:
        from modules.network import socket_patient_service as sps

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
