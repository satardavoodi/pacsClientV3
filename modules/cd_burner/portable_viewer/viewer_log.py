"""Diagnostic logging for the AI-PACS Lite Viewer.

Why this exists
---------------
The viewer used to call ``logging.basicConfig(...)`` only, which writes to
**stderr**. The shipped viewer is built ``--windowed``, so there is no console:
stderr is discarded and **every diagnostic line was lost**. When a patient CD
misbehaved on a client PC there was nothing to read.

This module gives the viewer a real log FILE, so the whole import chain —
startup → media discovery → DICOM parsing → drop/import → decode → viewport —
can be reviewed on the client machine.

Hard rules
----------
* **Never write to the media.** The CD is read-only; a log file next to the
  images would fail (or, on a USB copy, pollute the patient's data). The log
  always goes to a per-user writable location.
* **Never raise.** Logging must not be able to stop the viewer from opening a
  patient's images. Every failure degrades silently to the next location, and
  finally to "no file logging".
* Pure stdlib, no Qt — importable from the frozen bundle and unit-testable.

Location (first writable wins):
    %LOCALAPPDATA%\\AIPacsLiteViewer\\logs\\lite_viewer.log
    %TEMP%\\AIPacsLiteViewer\\logs\\lite_viewer.log
    <no file logging>
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

APP_DIRNAME = "AIPacsLiteViewer"
LOG_FILENAME = "lite_viewer.log"
ENV_LEVEL = "AIPACS_LITE_LOG_LEVEL"
ENV_LOG_DIR = "AIPACS_LITE_LOG_DIR"

_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 3
_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"

_configured_path: Optional[str] = None


def candidate_log_dirs() -> List[Path]:
    """Writable locations to try, best first. NEVER the media/CD."""
    dirs: List[Path] = []

    override = os.environ.get(ENV_LOG_DIR, "").strip()
    if override:
        dirs.append(Path(override))

    local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
    if local_appdata:
        dirs.append(Path(local_appdata) / APP_DIRNAME / "logs")

    home = os.path.expanduser("~")
    if home and home != "~":
        dirs.append(Path(home) / f".{APP_DIRNAME.lower()}" / "logs")

    try:
        dirs.append(Path(tempfile.gettempdir()) / APP_DIRNAME / "logs")
    except Exception:
        pass

    return dirs


def _resolve_level(level: Optional[str]) -> int:
    raw = (level or os.environ.get(ENV_LEVEL, "") or "INFO").strip().upper()
    return getattr(logging, raw, logging.INFO) if raw else logging.INFO


def configure_logging(level: Optional[str] = None) -> Optional[str]:
    """Attach a rotating file handler to the root logger. Returns the log path.

    Returns ``None`` when no writable location could be found — the viewer then
    runs exactly as before (stderr only). Never raises.
    """
    global _configured_path

    root = logging.getLogger()
    root.setLevel(_resolve_level(level))

    # Keep stderr output for dev/console runs (harmless when windowed).
    if not any(isinstance(h, logging.StreamHandler) and
               not isinstance(h, logging.FileHandler) for h in root.handlers):
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(stream)

    if _configured_path:
        return _configured_path

    for directory in candidate_log_dirs():
        try:
            directory.mkdir(parents=True, exist_ok=True)
            log_path = directory / LOG_FILENAME
            handler = logging.handlers.RotatingFileHandler(
                str(log_path), maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT,
                encoding="utf-8", delay=False,
            )
            handler.setFormatter(logging.Formatter(_FORMAT))
            root.addHandler(handler)
            _configured_path = str(log_path)
            return _configured_path
        except Exception:
            continue  # not writable — try the next location

    return None


def _is_elevated() -> Optional[bool]:
    """True when running as administrator. The viewer should NOT be (asInvoker)."""
    if os.name != "nt":
        return None
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return None


def log_session_banner(media_root: Optional[str], version: str,
                       log_path: Optional[str]) -> None:
    """One block at startup answering 'what am I, where am I, what can I see'."""
    log = logging.getLogger("aipacs.lite")
    try:
        frozen = bool(getattr(sys, "frozen", False))
        exe = sys.executable if frozen else __file__
        elevated = _is_elevated()

        optical = False
        try:
            if media_root:
                if __package__:
                    from .optical_io import is_optical_path
                else:  # standalone build
                    from optical_io import is_optical_path  # type: ignore
                optical = bool(is_optical_path(media_root))
        except Exception:
            optical = False

        log.info("=" * 78)
        log.info("[LITE-START] AI-PACS Lite Viewer %s", version)
        log.info("[LITE-START] exe=%s frozen=%s", exe, frozen)
        log.info("[LITE-START] media_root=%s optical=%s", media_root or "(none)", optical)
        # asInvoker is deliberate: the viewer must NOT run elevated, or Windows
        # UIPI blocks drag-and-drop from a non-elevated File Explorer.
        log.info("[LITE-START] elevated=%s (expected: False — manifest is asInvoker; "
                 "an elevated viewer cannot receive Explorer drops)", elevated)
        log.info("[LITE-START] log_file=%s", log_path or "(none — stderr only)")
        try:
            import pydicom

            log.info("[LITE-START] python=%s pydicom=%s",
                     sys.version.split()[0], pydicom.__version__)
        except Exception:
            pass
        if elevated:
            log.warning(
                "[LITE-START] The viewer is running ELEVATED. Windows will block "
                "drag-and-drop from a normal (non-elevated) File Explorer. Start "
                "the viewer normally (do not use 'Run as administrator')."
            )
    except Exception:  # a banner must never break startup
        pass
