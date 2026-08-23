"""Outgoing attachments: what may be sent, checked before anything is sent.

ALL-OR-NOTHING, AND BEFORE THE FIRST BYTE LEAVES. The operator selects five
files; one of them is 40 MB. If the check happened per file, four would arrive,
the fifth would fail, and the operator would believe the patient had all five —
which in a consultation is the difference between "here is the whole study" and
"here is most of it". So the whole selection is inspected first and either all
of it is sendable or none of it is, with one sentence saying why.

THE LIMITS ARE THE SERVER'S, MIRRORED. They are duplicated here so the refusal
is instant and legible rather than a 413 after a two-minute upload. If the
server ever loosens them, this file is the one place to change — and being
stricter than the server only ever costs a message the server would have
accepted, which is the safe direction.

NO QT, NO NETWORK. This module is pure Python so it can be exercised without a
display and called from a worker thread without a second thought.
"""

from __future__ import annotations

import logging
import mimetypes
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_FILES = 5
MAX_TOTAL_BYTES = 20 * 1024 * 1024      # 20 MB across the whole selection
MAX_FILE_BYTES = 20 * 1024 * 1024       # and no single file may fill it alone

# An upload is not a poll. The JSON timeout is sized for an 800 ms cadence; a
# clinic sending 20 MB over ADSL needs minutes, and timing that out would retry
# an upload that was in fact still running.
UPLOAD_TIMEOUT_SEC = 180

DEFAULT_MIME = "application/octet-stream"


@dataclass(frozen=True)
class Attachment:
    """One file, already read off disk.

    THE BYTES ARE HELD, NOT A HANDLE. An open file handle on Windows stops the
    operator from moving or renaming the file while the upload runs, and a
    handle that outlives a failed request leaks. Twenty megabytes in memory for
    the length of one POST is the cheaper problem.
    """

    name: str
    data: bytes
    mime: str
    source: str = ""

    @property
    def size(self) -> int:
        return len(self.data)


def guess_mime(path: Path | str) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or DEFAULT_MIME


def human_size(size: int) -> str:
    value = float(max(0, int(size)))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} GB"


def inspect(paths) -> tuple[tuple[Attachment, ...], str]:
    """Read and check a whole selection.

    Returns ``(attachments, error)``. Exactly one of them is meaningful: on any
    problem the attachments are EMPTY and the error is one sentence for the
    operator. Nothing is ever half-accepted.
    """
    candidates = [Path(p) for p in (paths or []) if str(p).strip()]
    if not candidates:
        return (), ""

    if len(candidates) > MAX_FILES:
        return (), (
            f"Up to {MAX_FILES} files can be sent at once — "
            f"{len(candidates)} were selected."
        )

    loaded: list[Attachment] = []
    total = 0
    for path in candidates:
        try:
            if not path.is_file():
                return (), f"{path.name} is not a file that can be sent."
            size = path.stat().st_size
        except OSError as exc:
            return (), f"{path.name} could not be read ({exc.strerror or exc})."

        if size <= 0:
            return (), f"{path.name} is empty."
        if size > MAX_FILE_BYTES:
            return (), (
                f"{path.name} is {human_size(size)} — the limit is "
                f"{human_size(MAX_FILE_BYTES)} per file."
            )
        total += size
        if total > MAX_TOTAL_BYTES:
            return (), (
                f"Those files come to more than {human_size(MAX_TOTAL_BYTES)} "
                "together. Send them in two messages."
            )

        try:
            data = path.read_bytes()
        except OSError as exc:
            return (), f"{path.name} could not be read ({exc.strerror or exc})."

        loaded.append(
            Attachment(
                name=path.name,
                data=data,
                mime=guess_mime(path),
                source=str(path),
            )
        )

    return tuple(loaded), ""
