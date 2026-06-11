"""One-click ingest of a downloaded consultation package (B4 / ADR-0003).

Qt-free. Reuses the EXISTING Offline Cloud import engine
(``sync_offline_cloud_study_to_local``) — no fork: a downloaded consultation
package IS an offline-cloud package (the envelope ``consultation.json`` is a
sibling file). The page's import worker calls :func:`import_consultation_package`
on a QThread; the function is blocking.

Safety: the consultation download path has already verified envelope integrity
before this runs (verify-before-ingest invariant) and the offline engine
re-validates the package manifest/db before touching the local library.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def find_package_root(local_path: str) -> str | None:
    """Locate the offline-cloud package root at ``local_path`` or one level down."""
    if not local_path or not os.path.isdir(local_path):
        return None
    candidates = [local_path] + sorted(
        os.path.join(local_path, d)
        for d in os.listdir(local_path)
        if os.path.isdir(os.path.join(local_path, d))
    )
    from PacsClient.utils.offline_cloud import list_offline_cloud_studies

    for cand in candidates:
        try:
            rows = list_offline_cloud_studies({"folder_path": cand, "name": "online-consultation"})
        except Exception as exc:
            logger.debug("package probe failed for %s: %s", cand, exc)
            rows = []
        if rows:
            return cand
    return None


def import_consultation_package(local_path: str, actor: dict | None = None) -> dict:
    """Import every study of the downloaded package into the local library.

    Returns ``{"ok": bool, "imported": [uids], "errors": [msgs]}``. BLOCKING —
    run it on a worker thread. Never raises for per-study failures; raises only
    when no importable package is found at ``local_path``.
    """
    root = find_package_root(local_path)
    if not root:
        raise RuntimeError(
            "No importable study package was found in the downloaded consultation."
        )

    from PacsClient.utils.offline_cloud import (
        list_offline_cloud_studies,
        sync_offline_cloud_study_to_local,
    )

    server = {"folder_path": root, "name": "online-consultation"}
    imported: list[str] = []
    errors: list[str] = []
    for row in list_offline_cloud_studies(server):
        uid = str(row.get("study_uid") or "").strip()
        if not uid:
            continue
        try:
            res = sync_offline_cloud_study_to_local(server, uid, actor=actor)
        except Exception as exc:
            res = {"ok": False, "error": str(exc)}
        if res.get("ok"):
            imported.append(uid)
        else:
            errors.append(f"{uid}: {res.get('error') or 'import failed'}")
            logger.warning("consultation package import failed for %s: %s", uid, res.get("error"))

    return {"ok": bool(imported) and not errors, "imported": imported, "errors": errors}
