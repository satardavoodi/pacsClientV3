"""Robust file reading for optical media (CD/DVD).

Optical drives are slow and produce sporadic transient read errors (CRC,
seek timeouts) that usually succeed on a retry. They also punish repeated
small seeks. This module makes the Lite Viewer's reads from CD reliable
and efficient:

* ``read_bytes`` — read a whole file into memory in one sequential pass,
  with bounded retries on transient errors. pydicom then parses from a
  stable in-RAM buffer instead of seeking the disc repeatedly.
* ``is_optical_path`` — detect a CD/DVD drive so callers can stage a series
  to local temp for snappy scrolling.
* ``stage_files_to_temp`` — copy a set of files off the disc once (with
  retries) into a temp dir, returning a path map; subsequent reads are from
  fast, reliable local disk.

Pure std-lib (+ ctypes on Windows). No Qt. Headless-testable.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_RETRIES = 3
_RETRY_BASE_SLEEP = 0.15  # seconds, grows linearly per attempt
_DRIVE_CDROM = 5          # GetDriveTypeW return value


def read_bytes(path: str, retries: int = _DEFAULT_RETRIES, sleep: float = _RETRY_BASE_SLEEP) -> bytes:
    """Read an entire file into memory, retrying transient optical errors.

    Raises the last OSError if every attempt fails.
    """
    last_error: Optional[BaseException] = None
    for attempt in range(1, retries + 1):
        try:
            with open(path, "rb", buffering=0) as handle:
                data = handle.read()
            if data:
                return data
            # Zero-length read on a non-empty file is a transient optical
            # glitch — retry rather than accept truncation.
            if os.path.getsize(path) == 0:
                return data
            raise OSError("Empty read from a non-empty file")
        except OSError as exc:
            last_error = exc
            logger.warning("Optical read attempt %d/%d failed for %s: %s",
                           attempt, retries, path, exc)
            if attempt < retries:
                time.sleep(sleep * attempt)
    assert last_error is not None
    raise last_error


def is_optical_path(path: str) -> bool:
    """True when *path* lives on a CD/DVD drive (Windows only; else False)."""
    if os.name != "nt":
        return False
    try:
        import ctypes

        drive = os.path.splitdrive(os.path.abspath(path))[0]
        if not drive:
            return False
        root = drive + "\\"
        return ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)) == _DRIVE_CDROM
    except Exception:
        return False


def stage_files_to_temp(
    paths: Iterable[str],
    retries: int = _DEFAULT_RETRIES,
) -> Dict[str, str]:
    """Copy files off optical media into a temp dir once (with retries).

    Returns {original_path: staged_path}. Files that cannot be copied are
    omitted (the caller falls back to reading them in place). The temp dir
    is unique per call; the caller owns cleanup.
    """
    mapping: Dict[str, str] = {}
    paths = list(paths)
    if not paths:
        return mapping
    staging_root = Path(tempfile.mkdtemp(prefix="aipacs_cd_stage_"))
    for index, src in enumerate(paths):
        dest = staging_root / f"{index:06d}_{Path(src).name}"
        for attempt in range(1, retries + 1):
            try:
                data = read_bytes(src, retries=1)
                dest.write_bytes(data)
                mapping[src] = str(dest)
                break
            except OSError as exc:
                logger.warning("Staging attempt %d/%d failed for %s: %s",
                               attempt, retries, src, exc)
                if attempt < retries:
                    time.sleep(_RETRY_BASE_SLEEP * attempt)
    return mapping


def cleanup_temp_dir(staged_path_example: Optional[str]) -> None:
    """Remove the temp staging dir given any staged file path inside it."""
    if not staged_path_example:
        return
    try:
        parent = Path(staged_path_example).parent
        if parent.name.startswith("aipacs_cd_stage_") and parent.exists():
            shutil.rmtree(parent, ignore_errors=True)
    except Exception:
        pass
