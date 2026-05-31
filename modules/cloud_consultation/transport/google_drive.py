"""GoogleDriveTransport — :class:`CloudTransport` over the Google Drive v3 API.

Receives an authenticated ``googleapiclient`` Drive service (built by the Identity
module from a connected Google account) and implements folder/file operations with
resumable uploads and atomic downloads. All ``googleapiclient`` imports are local so
this module imports cheaply even when the library is absent.

Scope note: works entirely within ``drive.file`` — every file/folder is created or
opened by this app, so it only ever sees its own consultation data.
"""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path

from .base import (
    CloudTransport,
    ProgressCb,
    RemoteChange,
    RemoteEntry,
    ShareInfo,
    TransferProgress,
)

logger = logging.getLogger(__name__)

_FOLDER_MIME = "application/vnd.google-apps.folder"
APP_FOLDER_NAME = "AI-PACS Consultations"
_FILE_FIELDS = "id, name, mimeType, size, modifiedTime, md5Checksum"


def _q_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class GoogleDriveTransport(CloudTransport):
    name = "google_drive"

    def __init__(self, service, app_folder_name: str = APP_FOLDER_NAME):
        self._service = service
        self._app_folder_name = app_folder_name

    # ── helpers ──────────────────────────────────────────────────────────────
    def _to_entry(self, f: dict) -> RemoteEntry:
        return RemoteEntry(
            id=f.get("id", ""),
            name=f.get("name", ""),
            is_folder=(f.get("mimeType") == _FOLDER_MIME),
            size=int(f.get("size") or 0),
            modified_time=f.get("modifiedTime", "") or "",
            md5=f.get("md5Checksum", "") or "",
        )

    # ── folder / listing ─────────────────────────────────────────────────────
    def ensure_app_folder(self) -> str:
        q = (
            f"name = '{_q_escape(self._app_folder_name)}' "
            f"and mimeType = '{_FOLDER_MIME}' and trashed = false"
        )
        resp = self._service.files().list(
            q=q, spaces="drive", fields=f"files({_FILE_FIELDS})", pageSize=10
        ).execute()
        files = resp.get("files", [])
        if files:
            return files[0]["id"]
        created = self._service.files().create(
            body={"name": self._app_folder_name, "mimeType": _FOLDER_MIME},
            fields="id",
        ).execute()
        return created["id"]

    def find_child(self, parent_id: str, name: str):
        q = (
            f"name = '{_q_escape(name)}' and '{parent_id}' in parents "
            f"and trashed = false"
        )
        resp = self._service.files().list(
            q=q, spaces="drive", fields=f"files({_FILE_FIELDS})", pageSize=10
        ).execute()
        files = resp.get("files", [])
        return self._to_entry(files[0]) if files else None

    def make_child_folder(self, parent_id: str, name: str) -> str:
        existing = self.find_child(parent_id, name)
        if existing is not None and existing.is_folder:
            return existing.id
        created = self._service.files().create(
            body={"name": name, "mimeType": _FOLDER_MIME, "parents": [parent_id]},
            fields="id",
        ).execute()
        return created["id"]

    def list_folder(self, folder_id: str) -> list[RemoteEntry]:
        entries: list[RemoteEntry] = []
        page_token = None
        while True:
            resp = self._service.files().list(
                q=f"'{folder_id}' in parents and trashed = false",
                spaces="drive",
                fields=f"nextPageToken, files({_FILE_FIELDS})",
                pageSize=200,
                pageToken=page_token,
            ).execute()
            for f in resp.get("files", []):
                entries.append(self._to_entry(f))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return entries

    # ── transfer ─────────────────────────────────────────────────────────────
    def upload_file(
        self, local_path: str, parent_id: str, name: str | None = None, *,
        progress_cb: ProgressCb = None,
    ) -> RemoteEntry:
        from googleapiclient.http import MediaFileUpload

        local_path = str(local_path)
        name = name or os.path.basename(local_path)
        total = os.path.getsize(local_path) if os.path.exists(local_path) else 0
        media = MediaFileUpload(local_path, resumable=True)
        request = self._service.files().create(
            body={"name": name, "parents": [parent_id]},
            media_body=media,
            fields=_FILE_FIELDS,
        )
        response = None
        while response is None:
            status, response = request.next_chunk()
            if progress_cb and status is not None:
                progress_cb(TransferProgress(
                    path=name, transferred=int(status.resumable_progress), total=total))
        if progress_cb:
            progress_cb(TransferProgress(path=name, transferred=total, total=total))
        return self._to_entry(response)

    def download_file(self, file_id: str, local_path: str, *, progress_cb: ProgressCb = None) -> None:
        from googleapiclient.http import MediaIoBaseDownload

        target = Path(local_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        request = self._service.files().get_media(fileId=file_id)
        with io.FileIO(str(part), "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if progress_cb and status is not None:
                    progress_cb(TransferProgress(
                        path=str(target),
                        transferred=int(status.resumable_progress),
                        total=int(getattr(status, "total_size", 0) or 0),
                    ))
        os.replace(str(part), str(target))  # atomic publish

    def delete(self, file_id: str) -> None:
        self._service.files().delete(fileId=file_id).execute()

    def share(self, file_id: str, email: str, role: str = "reader") -> ShareInfo:
        perm = self._service.permissions().create(
            fileId=file_id,
            body={"type": "user", "role": role, "emailAddress": email},
            sendNotificationEmail=True,
            fields="id",
        ).execute()
        return ShareInfo(permission_id=perm.get("id", ""), email=email, role=role)

    # ── change feed (used by the Phase-5 notification poller) ──────────────────
    def start_change_cursor(self) -> str:
        resp = self._service.changes().getStartPageToken().execute()
        return resp.get("startPageToken", "")

    def changes_since(self, cursor: str) -> tuple[list[RemoteChange], str]:
        changes: list[RemoteChange] = []
        token = cursor
        while True:
            resp = self._service.changes().list(
                pageToken=token,
                spaces="drive",
                fields="newStartPageToken, nextPageToken, changes(fileId, removed, file(name))",
            ).execute()
            for ch in resp.get("changes", []):
                f = ch.get("file") or {}
                changes.append(RemoteChange(
                    file_id=ch.get("fileId", ""),
                    removed=bool(ch.get("removed")),
                    name=f.get("name", ""),
                ))
            if resp.get("nextPageToken"):
                token = resp["nextPageToken"]
                continue
            return changes, resp.get("newStartPageToken", token)


def build_google_drive_transport(aipacs_user: str, subject_id: str) -> GoogleDriveTransport:
    """Build a Drive transport for a connected Google identity via the Identity module.

    Raises if no Google identity with ``subject_id`` is linked to ``aipacs_user`` or
    the stored token cannot be refreshed (the caller should prompt to (re)connect).
    """
    from modules.Identity.identity_service import IdentityService
    from modules.Identity.models import Capability

    service = IdentityService(aipacs_user).get_capability_client(
        "google", subject_id, Capability.CLOUD_STORAGE
    )
    return GoogleDriveTransport(service)
