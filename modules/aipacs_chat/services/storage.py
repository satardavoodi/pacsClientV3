"""Where chat files live on disk.

ONE REGISTRY, LAZY CREATION. The paths come from
``PacsClient.utils.data_paths`` — the single registry of user-data locations,
which already knows the difference between a development checkout
(``PROJECT_ROOT/user_data/``) and an installed build (``{InstallDir}\\User
Data\\``, falling back to ``%LOCALAPPDATA%\\AIPacs\\user_data\\`` where the
install directory is not writable). This module never computes a path of its
own; it only creates the directories the first time something is actually
written, because a disabled chat module must leave no trace at startup.

FILENAMES FROM THE SERVER ARE UNTRUSTED. ``file_name`` reaches us from a
patient upload. It is sanitised before it becomes a path: no directory
separators, no traversal, no reserved Windows device names, no leading dot, and
capped in length. The stored name is only ever a LEAF inside the case folder.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Windows reserved device names — a file called ``CON`` or ``LPT1`` cannot be
# created and would fail in a way that looks like a permission bug.
_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MAX_NAME = 96


def _fallback_root() -> Path:
    """Used only when PacsClient is not importable (headless tools, tests)."""
    return Path.home() / ".aipacs" / "user_data" / "aipacs_chat"


def chat_root() -> Path:
    try:
        from PacsClient.utils.data_paths import CHAT_DIR

        return Path(CHAT_DIR)
    except Exception as exc:  # pragma: no cover - non-app contexts
        logger.debug("aipacs_chat: data_paths unavailable (%s); using fallback", exc)
        return _fallback_root()


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def files_dir(case_id: int | None = None) -> Path:
    """Where downloaded attachments are kept, partitioned by case.

    Per case rather than one flat folder: an operator asked "where is the file
    that patient sent me" has somewhere to look, and deleting one conversation's
    files never has to filter a shared directory.
    """
    try:
        from PacsClient.utils.data_paths import CHAT_FILES_DIR

        base = Path(CHAT_FILES_DIR)
    except Exception:
        base = _fallback_root() / "files"
    if case_id:
        base = base / f"case_{int(case_id)}"
    return _ensure(base)


def outbox_dir() -> Path:
    """Where a PASTED image is written before it can be attached.

    A clipboard image has no file behind it, and the upload needs one. It is
    kept rather than deleted after sending: an operator who pasted a screenshot
    into a consultation has no other copy of it, and "where did that go" is a
    worse problem than a folder that grows slowly.
    """
    return _ensure(chat_root() / "outbox")


def thumbs_dir() -> Path:
    """Decoded preview cache, keyed by file id."""
    try:
        from PacsClient.utils.data_paths import CHAT_THUMBS_DIR

        base = Path(CHAT_THUMBS_DIR)
    except Exception:
        base = _fallback_root() / "thumbnails"
    return _ensure(base)


def safe_name(raw: str, *, fallback: str = "attachment") -> str:
    """Turn a patient-supplied filename into a safe leaf name."""
    name = (raw or "").strip().replace("\r", " ").replace("\n", " ")
    # Take the leaf only: "..\\..\\etc\\passwd" and "/tmp/x" both collapse.
    name = name.replace("\\", "/").split("/")[-1]
    name = _UNSAFE.sub("_", name).strip(" .")
    if not name:
        return fallback
    stem, dot, suffix = name.rpartition(".")
    if not dot:
        stem, suffix = name, ""
    if stem.lower() in _RESERVED:
        stem = f"_{stem}"
    stem = stem[:MAX_NAME] or fallback
    return f"{stem}.{suffix[:16]}" if suffix else stem


def attachment_path(case_id: int, file_id: int, file_name: str) -> Path:
    """The on-disk location for one attachment.

    The file id prefixes the name so two patients sending ``report.pdf`` cannot
    collide, and so a cached copy can be found again without a database.
    """
    return files_dir(case_id) / f"{int(file_id)}_{safe_name(file_name)}"


def cached_attachment(case_id: int, file_id: int, file_name: str) -> Path | None:
    """An already-downloaded copy, or None. Never re-fetches a file twice."""
    path = attachment_path(case_id, file_id, file_name)
    try:
        if path.exists() and path.stat().st_size > 0:
            return path
    except Exception:  # pragma: no cover - defensive
        return None
    return None


def write_attachment(case_id: int, file_id: int, file_name: str, data: bytes) -> Path:
    """Write bytes to the case folder and return the path.

    Written to a temporary neighbour and renamed, so a download interrupted
    half-way never leaves a truncated file that `cached_attachment` would then
    hand back as complete.
    """
    path = attachment_path(case_id, file_id, file_name)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path


def thumbnail_path(file_id: int) -> Path:
    return thumbs_dir() / f"{int(file_id)}.png"
