"""The :class:`CloudTransport` abstraction + small transport data models.

The consultation engine depends only on this interface, never on a specific
provider. Google Drive is the first implementation; OneDrive / Dropbox / S3 can be
added later by implementing this same ABC, with no change to the package-sync engine
or higher layers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class RemoteEntry:
    id: str
    name: str
    is_folder: bool
    size: int = 0
    modified_time: str = ""
    md5: str = ""


@dataclass
class ShareInfo:
    permission_id: str
    email: str
    role: str


@dataclass
class RemoteChange:
    file_id: str
    removed: bool
    name: str = ""


@dataclass
class TransferProgress:
    path: str
    transferred: int
    total: int

    @property
    def fraction(self) -> float:
        return (self.transferred / self.total) if self.total else 0.0


# Progress callbacks receive a TransferProgress; they must be cheap and must not
# block (they may be called from a worker thread).
ProgressCb = Optional[Callable[[TransferProgress], None]]


class CloudTransport(ABC):
    """Move package files to/from a remote provider folder. Provider-agnostic."""

    name: str = ""

    @abstractmethod
    def ensure_app_folder(self) -> str:
        """Return the id of the app's root folder (e.g. "AI-PACS Consultations"),
        creating it if needed."""

    @abstractmethod
    def make_child_folder(self, parent_id: str, name: str) -> str:
        """Return the id of a child folder, creating it if missing (idempotent)."""

    @abstractmethod
    def find_child(self, parent_id: str, name: str) -> "RemoteEntry | None":
        """Return a direct child entry by name, or None."""

    @abstractmethod
    def list_folder(self, folder_id: str) -> list[RemoteEntry]:
        """List direct children of a folder."""

    @abstractmethod
    def upload_file(
        self, local_path: str, parent_id: str, name: str | None = None, *,
        progress_cb: ProgressCb = None,
    ) -> RemoteEntry:
        """Upload (resumably) a local file into a remote folder."""

    @abstractmethod
    def download_file(
        self, file_id: str, local_path: str, *, progress_cb: ProgressCb = None,
    ) -> None:
        """Download a remote file to a local path (atomic: temp + replace)."""

    @abstractmethod
    def delete(self, file_id: str) -> None:
        """Delete (trash) a remote file/folder."""

    @abstractmethod
    def share(self, file_id: str, email: str, role: str = "reader") -> ShareInfo:
        """Grant a recipient access to a file/folder."""

    # Optional (used by the Phase-5 notification poller). Default: unsupported.
    def start_change_cursor(self) -> str:
        raise NotImplementedError

    def changes_since(self, cursor: str) -> tuple[list[RemoteChange], str]:
        raise NotImplementedError
