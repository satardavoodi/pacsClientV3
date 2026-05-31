"""CloudSyncEngine — resumable, state-tracked transfer of a consultation package.

Transport-agnostic (drives any :class:`CloudTransport`) and DB-backed: every file's
transfer is recorded in ``consultation_files`` so an interrupted upload/download
resumes by skipping files already marked ``done`` with a matching hash. Synchronous
core (no Qt); the optional ``worker.SyncWorker`` runs it off the UI thread.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

from .models import SyncDirection, SyncProgress

logger = logging.getLogger(__name__)


def _sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_remote_dir(transport, root_id: str, rel: Path, cache: dict) -> str:
    key = rel.as_posix()
    if key in ("", "."):
        return root_id
    if key in cache:
        return cache[key]
    parent_id = _ensure_remote_dir(transport, root_id, rel.parent, cache)
    folder_id = transport.make_child_folder(parent_id, rel.name)
    cache[key] = folder_id
    return folder_id


class CloudSyncEngine:
    def __init__(self, transport, *, progress_cb=None):
        self.transport = transport
        self.progress_cb = progress_cb

    def _emit(self, progress: SyncProgress) -> None:
        if self.progress_cb:
            try:
                self.progress_cb(progress)
            except Exception as exc:  # never let a UI callback break a transfer
                logger.debug("sync progress callback error: %s", exc)

    # ── upload ───────────────────────────────────────────────────────────────
    def upload(
        self, consultation_id: str, local_root, *,
        app_folder_id: str | None = None, root_remote_id: str | None = None,
    ) -> str:
        """Mirror a local package folder to the provider; returns the remote folder id.

        Resumable: files previously marked ``done`` with a matching sha256 are skipped.
        If ``root_remote_id`` is given, upload INTO that folder (used to write a
        response back into the originator's shared folder); otherwise create
        ``<app folder>/<consultation_id>``.
        """
        from database import consultation_db

        root = Path(local_root)
        if not root.is_dir():
            raise NotADirectoryError(str(root))

        if root_remote_id:
            root_remote = root_remote_id
        else:
            app_id = app_folder_id or self.transport.ensure_app_folder()
            root_remote = self.transport.make_child_folder(app_id, consultation_id)
        consultation_db.update_consultation_fields(consultation_id, remote_folder_id=root_remote)

        files = [p for p in sorted(root.rglob("*"), key=lambda x: x.as_posix()) if p.is_file()]
        progress = SyncProgress(
            direction=SyncDirection.UPLOAD.value,
            files_total=len(files),
            bytes_total=sum(p.stat().st_size for p in files),
        )
        folder_cache: dict[str, str] = {"": root_remote}

        for p in files:
            rel = p.relative_to(root).as_posix()
            size = p.stat().st_size
            sha = _sha256_file(p)
            st = consultation_db.get_file_state(consultation_id, rel)
            if st and st.get("state") == "done" and st.get("sha256") == sha and st.get("remote_file_id"):
                progress.files_done += 1
                progress.bytes_done += size
                progress.current_path = rel
                self._emit(progress)
                continue

            parent_id = _ensure_remote_dir(self.transport, root_remote, Path(rel).parent, folder_cache)
            try:
                entry = self.transport.upload_file(str(p), parent_id, p.name)
            except Exception as exc:
                consultation_db.set_file_state(
                    consultation_id, rel, state="failed", sha256=sha, bytes_total=size, bytes_done=0
                )
                consultation_db.add_event(consultation_id, "error", details=f"upload failed {rel}: {exc}")
                raise
            consultation_db.set_file_state(
                consultation_id, rel, remote_file_id=getattr(entry, "id", ""), sha256=sha,
                bytes_total=size, bytes_done=size, state="done",
            )
            progress.files_done += 1
            progress.bytes_done += size
            progress.current_path = rel
            self._emit(progress)

        consultation_db.update_consultation_fields(
            consultation_id, status="uploaded", last_synced_at=_now_iso()
        )
        consultation_db.add_event(consultation_id, "uploaded", details=f"{len(files)} files")
        return root_remote

    # ── download ─────────────────────────────────────────────────────────────
    def download(self, consultation_id: str, remote_folder_id: str, dest_root) -> Path:
        """Download a remote package folder into ``dest_root`` (resumable)."""
        from database import consultation_db

        dest = Path(dest_root)
        dest.mkdir(parents=True, exist_ok=True)
        remote_files = self._walk_remote(remote_folder_id)
        progress = SyncProgress(
            direction=SyncDirection.DOWNLOAD.value,
            files_total=len(remote_files),
            bytes_total=sum(sz for _, _, sz in remote_files),
        )

        for rel, file_id, size in remote_files:
            local_path = dest / rel
            st = consultation_db.get_file_state(consultation_id, rel)
            if (
                local_path.exists()
                and st
                and st.get("state") == "done"
                and st.get("remote_file_id") == file_id
            ):
                progress.files_done += 1
                progress.bytes_done += size
                progress.current_path = rel
                self._emit(progress)
                continue

            try:
                self.transport.download_file(file_id, str(local_path))
            except Exception as exc:
                consultation_db.set_file_state(consultation_id, rel, state="failed", remote_file_id=file_id)
                consultation_db.add_event(consultation_id, "error", details=f"download failed {rel}: {exc}")
                raise
            sha = _sha256_file(local_path)
            consultation_db.set_file_state(
                consultation_id, rel, remote_file_id=file_id, sha256=sha,
                bytes_total=size, bytes_done=size, state="done",
            )
            progress.files_done += 1
            progress.bytes_done += size
            progress.current_path = rel
            self._emit(progress)

        consultation_db.update_consultation_fields(
            consultation_id, status="downloaded", local_path=str(dest), last_synced_at=_now_iso()
        )
        consultation_db.add_event(consultation_id, "downloaded", details=f"{len(remote_files)} files")
        return dest

    def _walk_remote(self, folder_id: str, prefix: str = "") -> list[tuple[str, str, int]]:
        out: list[tuple[str, str, int]] = []
        for entry in self.transport.list_folder(folder_id):
            rel = f"{prefix}/{entry.name}" if prefix else entry.name
            if entry.is_folder:
                out.extend(self._walk_remote(entry.id, rel))
            else:
                out.append((rel, entry.id, int(getattr(entry, "size", 0) or 0)))
        return out
