"""Transport-agnostic mirroring of an Offline Cloud *package folder* to/from a cloud
provider.

These functions take any :class:`CloudTransport`, so the same code drives Google
Drive today and OneDrive/Dropbox/S3 later. They reuse the existing on-disk package
format unchanged (``manifest.json`` + ``package.db`` + ``patients/...``) — the cloud
is purely a transport.

Phase 2 scope: faithful folder round-trip (upload all files, recreate the directory
tree; download reconstructs it). The *resumable, state-tracked* sync engine and the
consultation envelope/assignment/notifications are Phases 3-5.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .transport.base import CloudTransport, ProgressCb

logger = logging.getLogger(__name__)


def _ensure_remote_dir(transport: CloudTransport, root_id: str, rel: Path, cache: dict) -> str:
    """Resolve (creating as needed) the remote folder id for a relative dir path."""
    key = rel.as_posix()
    if key in ("", "."):
        return root_id
    if key in cache:
        return cache[key]
    parent_id = _ensure_remote_dir(transport, root_id, rel.parent, cache)
    folder_id = transport.make_child_folder(parent_id, rel.name)
    cache[key] = folder_id
    return folder_id


def mirror_folder_to_remote(
    transport: CloudTransport, local_dir, remote_parent_id: str, *, progress_cb: ProgressCb = None,
) -> str:
    """Create a folder named after ``local_dir`` under ``remote_parent_id`` and upload
    the whole tree into it. Returns the new remote folder id."""
    local_dir = Path(local_dir)
    if not local_dir.is_dir():
        raise NotADirectoryError(str(local_dir))

    root_id = transport.make_child_folder(remote_parent_id, local_dir.name)
    cache: dict[str, str] = {}
    for path in sorted(local_dir.rglob("*"), key=lambda p: p.as_posix()):
        rel = path.relative_to(local_dir)
        if path.is_dir():
            _ensure_remote_dir(transport, root_id, rel, cache)
        elif path.is_file():
            parent_id = _ensure_remote_dir(transport, root_id, rel.parent, cache)
            transport.upload_file(str(path), parent_id, path.name, progress_cb=progress_cb)
    return root_id


def mirror_remote_to_folder(
    transport: CloudTransport, remote_folder_id: str, local_dir, *, progress_cb: ProgressCb = None,
) -> Path:
    """Download the contents of a remote folder into ``local_dir`` (created if needed)."""
    local_dir = Path(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)

    def _recurse(folder_id: str, dest: Path) -> None:
        for entry in transport.list_folder(folder_id):
            target = dest / entry.name
            if entry.is_folder:
                target.mkdir(parents=True, exist_ok=True)
                _recurse(entry.id, target)
            else:
                transport.download_file(entry.id, str(target), progress_cb=progress_cb)

    _recurse(remote_folder_id, local_dir)
    return local_dir


def upload_offline_package(transport: CloudTransport, package_root, *, progress_cb: ProgressCb = None) -> str:
    """Mirror a local Offline Cloud package folder into the app's cloud folder.

    Returns the remote package-folder id (share this with the assignee in Phase 5).
    """
    app_folder_id = transport.ensure_app_folder()
    return mirror_folder_to_remote(transport, package_root, app_folder_id, progress_cb=progress_cb)


def download_offline_package(
    transport: CloudTransport, remote_folder_id: str, dest_package_dir, *, progress_cb: ProgressCb = None,
) -> Path:
    """Download a remote package folder's contents into ``dest_package_dir``.

    The result is a normal Offline Cloud package directory that the EXISTING engine
    (``validate_offline_cloud_package`` / ``sync_offline_cloud_study_to_local``) can
    ingest unchanged.
    """
    return mirror_remote_to_folder(transport, remote_folder_id, dest_package_dir, progress_cb=progress_cb)
