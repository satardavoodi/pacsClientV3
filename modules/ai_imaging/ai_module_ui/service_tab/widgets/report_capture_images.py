"""Captured viewer images -> Medical Report Editor.

2026-08-18. The Patient tab's "Capture" tool writes PNG/JPG snapshots into the
study's attachment folder, and the viewer toolbar's "View Captured Images"
dropdown lists them. Until now there was no way to get one of those key images
INTO the report the physician writes in the Medical Report Editor.

This module is the non-GUI half of that feature, kept separate on purpose so it
can be unit-tested without a QApplication:

* :func:`list_captured_images` - pure pathlib; mirrors, byte for byte, what the
  viewer's ``ImageAttachmentsPanel._iter_files`` shows (same extensions, same
  newest-first order, same local/server duplicate collapsing), so the report
  picker and the viewer dropdown can never disagree about "what was captured".
* :func:`encode_capture_for_report` - QImage only (NOT QPixmap), which needs no
  QApplication, so this is headless-testable too.
* :class:`DataUriTextDocument` - the QTextDocument that makes an embedded
  ``data:`` image actually render, print, and survive a save/reload cycle.

WHY THE IMAGE IS EMBEDDED AND DOWNSCALED
----------------------------------------
The report is uploaded to the INO server as a single JSON field
(``POST /api/pacs/update-report``, ``content``). A ``file:///`` src would keep
the HTML small but the image would exist only on the machine that wrote it -
the server, and every other reader, would see a broken image. So the bytes have
to travel with the report.

A raw capture is a 2-6 MB PNG; base64 inflates that by ~33 %, and a report with
three of them would be a ~25 MB JSON POST. That is a real operational risk, not
a theoretical one. So captures are downscaled to :data:`DEFAULT_MAX_WIDTH` and
re-encoded as JPEG, which puts a typical key image at 100-250 KB. Diagnostic
reading still happens in the viewer on the original DICOM; this is a report
illustration.

:data:`DEFAULT_MAX_BYTES` is a hard ceiling on top of that. If an image somehow
still exceeds it, the encoder steps quality/width down and, failing that,
REFUSES rather than silently handing the upload path something it will choke
on. A visible "could not insert" beats a report that will not save.

Kill switches (all read at call time, so a site can tune without a rebuild):
  AIPACS_REPORT_IMAGE_MAX_WIDTH   default 1000  (px; 0 disables downscaling)
  AIPACS_REPORT_IMAGE_QUALITY     default 88    (JPEG quality 1-100)
  AIPACS_REPORT_IMAGE_MAX_BYTES   default 1500000 (encoded bytes, pre-base64)
"""
from __future__ import annotations

import base64
import binascii
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)


# Same tuple as ImageAttachmentsPanel.IMAGE_EXTS - keep them in step, or the
# report picker and the viewer's "Captured Images" dropdown will disagree.
IMAGE_EXTS: Iterable[str] = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")

DEFAULT_MAX_WIDTH = 1000
DEFAULT_QUALITY = 88
DEFAULT_MAX_BYTES = 1_500_000

# Quality/width ladder walked when the first encode overshoots MAX_BYTES.
_FALLBACK_LADDER = ((75, 1.0), (65, 0.8), (55, 0.6), (45, 0.45))


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    """Read an int env override. A garbled value falls back to the default
    rather than raising in the middle of a click handler."""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.debug("[REPORT_IMG] ignoring non-numeric %s=%r", name, raw)
        return default
    return value if value >= minimum else default


def max_width() -> int:
    """Longest edge (width) an inserted capture is downscaled to. 0 = no cap."""
    return _env_int("AIPACS_REPORT_IMAGE_MAX_WIDTH", DEFAULT_MAX_WIDTH)


def jpeg_quality() -> int:
    value = _env_int("AIPACS_REPORT_IMAGE_QUALITY", DEFAULT_QUALITY, minimum=1)
    return min(value, 100)


def max_bytes() -> int:
    return _env_int("AIPACS_REPORT_IMAGE_MAX_BYTES", DEFAULT_MAX_BYTES, minimum=1)


# ══════════════════════════════════════════════════════════════════════════
# Listing - pure pathlib, no Qt
# ══════════════════════════════════════════════════════════════════════════

def captures_dir(study_uid: str) -> Optional[Path]:
    """Attachment folder for *study_uid*, or None if it cannot be resolved.

    ``ATTACHMENT_PATH`` is imported lazily: it is rebound at login (see
    ``PacsClient/utils/data_paths.py``), so binding it at module import would
    pin whichever centre happened to be active first.
    """
    uid = (study_uid or "").strip()
    if not uid:
        return None
    try:
        from PacsClient.utils.config import ATTACHMENT_PATH
    except Exception:
        logger.debug("[REPORT_IMG] ATTACHMENT_PATH unavailable", exc_info=True)
        return None
    try:
        return Path(ATTACHMENT_PATH) / uid
    except Exception:
        logger.debug("[REPORT_IMG] bad study uid %r", study_uid, exc_info=True)
        return None


def list_captured_images(study_uid: str) -> List[Path]:
    """Captured images for *study_uid*, newest first.

    Deliberately identical in behaviour to
    ``ImageAttachmentsPanel._iter_files`` + ``_collapse_duplicate_attachment_files``:
    same extensions, same mtime-descending order, and the same collapsing of
    ``REC_x.png`` / ``<id>_REC_x.png`` local+server duplicate pairs. If the two
    ever drift, the physician sees one set of images in the viewer dropdown and
    a different set in the report picker.

    Never raises - a missing folder, a permission error or a file that vanished
    mid-scan all yield a (possibly shorter) list.
    """
    folder = captures_dir(study_uid)
    if folder is None:
        return []
    try:
        if not folder.is_dir():
            return []
    except OSError:
        return []

    found: List[Path] = []
    for ext in IMAGE_EXTS:
        try:
            found.extend(folder.glob(f"*{ext}"))
        except OSError:
            continue

    def _mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    found.sort(key=_mtime, reverse=True)
    return _collapse_duplicates(found)


def list_captured_images_for_studies(study_uids) -> List[tuple]:
    """``[(study_uid, path), ...]`` across several studies, newest first.

    Used when the report cannot name a single study and the UIDs had to be
    resolved from the patient (see :func:`resolve_study_uids`).
    """
    found: List[tuple] = []
    seen_uids = set()
    for uid in (study_uids or []):
        text = str(uid or "").strip()
        if not text or text in seen_uids:
            continue
        seen_uids.add(text)
        for path in list_captured_images(text):
            found.append((text, path))

    def _mtime(item) -> float:
        try:
            return item[1].stat().st_mtime
        except OSError:
            return 0.0

    found.sort(key=_mtime, reverse=True)
    return found


# ── Resolving WHICH studies a report covers ─────────────────────────────────

def _db_lookup_enabled() -> bool:
    """Fall back to the local DICOM DB when the report names no study.
    Kill switch: ``AIPACS_REPORT_IMAGE_DB_LOOKUP=0``."""
    return (os.getenv("AIPACS_REPORT_IMAGE_DB_LOOKUP", "1") or "1").strip() != "0"


# Identifier keys tried IN ORDER against ``patients.patient_id``. First one
# that resolves to a patient wins; the rest are not tried. Deliberate: unioning
# every match risks pulling a DIFFERENT patient's key images into this report,
# which is a clinical error, not a cosmetic one.
_PATIENT_ID_KEYS = (
    ("receptionId",), ("ReceptionID",),
    ("patient", "PatientID"), ("patient", "patientId"), ("patient", "ID"),
    ("patientId",), ("PatientID",),
    ("nationalCode",), ("patient", "NationalID"),
)


def _dig(data, path):
    node = data
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def candidate_patient_ids(patient_data) -> List[str]:
    """Patient identifiers to try against the DICOM DB, in precedence order."""
    if not isinstance(patient_data, dict):
        return []
    out: List[str] = []
    for path in _PATIENT_ID_KEYS:
        value = _dig(patient_data, path)
        if value in (None, ""):
            continue
        text = str(value).strip()
        if text and text not in out:
            out.append(text)
    return out


def study_uids_for_patient_id(patient_id: str) -> List[str]:
    """Study UIDs owned by ``patients.patient_id == patient_id``, newest first.

    ``studies.patient_fk`` is a FOREIGN KEY to ``patients.patient_pk`` — it is
    NOT the DICOM PatientID, so the join through ``patients`` is required.
    Read-only and exception-proof: a locked or missing DB yields [].
    """
    text = (patient_id or "").strip()
    if not text:
        return []
    sql = (
        "SELECT s.study_uid FROM studies s "
        "JOIN patients p ON p.patient_pk = s.patient_fk "
        "WHERE CAST(p.patient_id AS TEXT) = ? "
        "ORDER BY s.study_date DESC, s.study_pk DESC"
    )
    try:
        from database._pool import get_db_connection
        with get_db_connection() as conn:
            rows = conn.cursor().execute(sql, (text,)).fetchall()
    except Exception:
        logger.debug("[REPORT_IMG] study lookup failed for %r", text, exc_info=True)
        return []
    uids: List[str] = []
    for row in rows or []:
        uid = str(row[0] or "").strip()
        if uid and uid not in uids:
            uids.append(uid)
    return uids


def resolve_study_uids(patient_data) -> List[str]:
    """Which studies' captures this report may show.

    A report opened from the Reception Data tab carries a RECEPTION record,
    which in this deployment has ``receptionId`` but no StudyInstanceUID —
    while captures on disk are keyed by study UID. Asking the report for
    ``studyUID`` therefore came back empty and the picker reported "not linked
    to a study" even when the patient plainly had captures.

    So: use an explicit study UID when the caller supplies one, otherwise walk
    the patient identifiers against the local DICOM DB and take the FIRST that
    resolves. Returns [] when nothing matches, which the caller must surface
    rather than silently showing another patient's images.
    """
    if not isinstance(patient_data, dict):
        return []

    explicit = str(
        patient_data.get("studyUID") or patient_data.get("study_uid") or ""
    ).strip()
    if explicit:
        return [explicit]

    if not _db_lookup_enabled():
        return []

    for candidate in candidate_patient_ids(patient_data):
        uids = study_uids_for_patient_id(candidate)
        if uids:
            logger.info(
                "[REPORT_IMG] report has no studyUID; resolved %d study(ies) "
                "from patient id %r", len(uids), candidate,
            )
            return uids
    logger.info("[REPORT_IMG] could not resolve any study for this report")
    return []


def _collapse_duplicates(files: List[Path]) -> List[Path]:
    """Hide local/server duplicates of the same capture. NON-DESTRUCTIVE and
    fail-open: if the de-dup helper is missing or disabled, every file is kept.
    Mirrors ``attachments_dropdown._collapse_duplicate_attachment_files``."""
    if not files:
        return files
    try:
        from modules.network.attachment_pending_sync import (
            attachment_dedup_enabled,
            choose_canonical_attachment_names,
        )
        if not attachment_dedup_enabled():
            return files
        keep = choose_canonical_attachment_names([p.name for p in files])
        return [p for p in files if p.name in keep]
    except Exception:
        return files


# ══════════════════════════════════════════════════════════════════════════
# Encoding - QImage only (no QPixmap), so this works with no QApplication
# ══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class EncodedReportImage:
    """A capture, ready to drop into the report document."""

    data_uri: str          # data:image/jpeg;base64,...  (goes straight into <img src>)
    width: int             # pixel width AFTER downscaling
    height: int
    encoded_bytes: int     # JPEG bytes before base64 - the number that matters for upload
    source: str            # original file path, for the tooltip and the log


def encode_capture_for_report(
    path,
    *,
    limit_width: Optional[int] = None,
    quality: Optional[int] = None,
    byte_ceiling: Optional[int] = None,
) -> Optional[EncodedReportImage]:
    """Load a captured image and return it as an embeddable JPEG data URI.

    Returns None when the file is missing/unreadable/not an image, or when even
    the most aggressive step of the fallback ladder cannot get under the byte
    ceiling. Callers must treat None as "tell the user, insert nothing" - never
    as "insert something approximate".

    Uses ``QImage``, never ``QPixmap``: QPixmap requires a running
    QGuiApplication, QImage does not, which keeps this testable headlessly and
    safe to call from a worker if it ever needs to be.
    """
    try:
        from PySide6.QtCore import QBuffer, QIODevice
        from PySide6.QtGui import QImage
    except Exception:
        logger.debug("[REPORT_IMG] Qt image support unavailable", exc_info=True)
        return None

    src = str(path)
    image = QImage(src)
    if image.isNull():
        logger.info("[REPORT_IMG] not a readable image: %s", src)
        return None

    cap = max_width() if limit_width is None else int(limit_width)
    base_quality = jpeg_quality() if quality is None else int(quality)
    ceiling = max_bytes() if byte_ceiling is None else int(byte_ceiling)

    def _encode(img, q: int) -> Optional[bytes]:
        # QBuffer() with its OWN internal buffer. Do NOT pass a freshly built
        # QByteArray: Qt keeps a pointer to it, the Python temporary is
        # collected, and the next write is a use-after-free (a hard abort with
        # no traceback — this bit once already).
        buf = QBuffer()
        if not buf.open(QIODevice.OpenModeFlag.WriteOnly):
            return None
        try:
            # JPEG: opaque screenshots, and it is what keeps the upload small.
            if not img.save(buf, "JPEG", q):
                return None
            return bytes(buf.data())
        finally:
            buf.close()

    scaled = image
    if cap > 0 and image.width() > cap:
        from PySide6.QtCore import Qt as _Qt
        scaled = image.scaledToWidth(cap, _Qt.TransformationMode.SmoothTransformation)
        if scaled.isNull():
            scaled = image

    payload = _encode(scaled, base_quality)
    final = scaled

    # Overshoot: step quality down, then width, rather than shipping a report
    # the upload endpoint will reject.
    if payload is not None and len(payload) > ceiling:
        for step_quality, width_factor in _FALLBACK_LADDER:
            candidate = scaled
            if width_factor < 1.0:
                target = max(200, int(scaled.width() * width_factor))
                from PySide6.QtCore import Qt as _Qt
                resized = scaled.scaledToWidth(
                    target, _Qt.TransformationMode.SmoothTransformation
                )
                if not resized.isNull():
                    candidate = resized
            attempt = _encode(candidate, step_quality)
            if attempt is not None and len(attempt) <= ceiling:
                logger.info(
                    "[REPORT_IMG] %s needed fallback q=%d w=%d to fit %d bytes",
                    os.path.basename(src), step_quality, candidate.width(), ceiling,
                )
                payload, final = attempt, candidate
                break
        else:
            logger.warning(
                "[REPORT_IMG] refusing to embed %s: %d bytes still over the "
                "%d byte ceiling after every fallback step",
                os.path.basename(src), len(payload), ceiling,
            )
            return None

    if not payload:
        logger.warning("[REPORT_IMG] JPEG encode produced nothing for %s", src)
        return None

    encoded = base64.b64encode(payload).decode("ascii")
    return EncodedReportImage(
        data_uri="data:image/jpeg;base64," + encoded,
        width=final.width(),
        height=final.height(),
        encoded_bytes=len(payload),
        source=src,
    )


def decode_data_uri_image(url: str):
    """``data:image/...;base64,...`` -> QImage, or None if it is not one.

    Tolerant by design: this runs inside ``loadResource`` during every paint of
    a report, so a malformed src must yield a blank image, never an exception
    that would take the editor down.
    """
    text = (url or "").strip()
    if not text.lower().startswith("data:image/"):
        return None
    head, _, payload = text.partition(",")
    if not payload or "base64" not in head.lower():
        return None
    try:
        raw = base64.b64decode(payload, validate=False)
    except (binascii.Error, ValueError):
        return None
    if not raw:
        return None
    try:
        from PySide6.QtGui import QImage
    except Exception:
        return None
    image = QImage()
    if not image.loadFromData(raw):
        return None
    return image if not image.isNull() else None


# ══════════════════════════════════════════════════════════════════════════
# The document that makes an embedded image actually render
# ══════════════════════════════════════════════════════════════════════════

_STOCK_SUPPORT: Optional[bool] = None

# 1x1 transparent GIF - the smallest thing that proves the resolver works.
_PROBE_URI = (
    "data:image/gif;base64,"
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)


def stock_qt_resolves_data_uris() -> bool:
    """Does THIS Qt build already resolve ``data:`` image sources itself?

    Measured, not assumed: on Qt 6.10.2 (the version this ships against)
    ``QTextDocument`` resolves data URIs natively, so swapping in a subclass
    would be pure risk for no benefit. On a Qt that does not, the subclass is
    the difference between a key image and a broken-image box. Probing costs
    one throwaway document, once per process.
    """
    global _STOCK_SUPPORT
    if _STOCK_SUPPORT is not None:
        return _STOCK_SUPPORT
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QImage, QPixmap, QTextDocument

        probe = QTextDocument()
        probe.setHtml(f'<img src="{_PROBE_URI}">')
        resource = probe.resource(QTextDocument.ResourceType.ImageResource, QUrl(_PROBE_URI))
        if isinstance(resource, QPixmap):
            resource = resource.toImage()
        _STOCK_SUPPORT = isinstance(resource, QImage) and not resource.isNull()
    except Exception:
        logger.debug("[REPORT_IMG] data-URI capability probe failed", exc_info=True)
        _STOCK_SUPPORT = False
    logger.info("[REPORT_IMG] stock QTextDocument resolves data URIs: %s",
                _STOCK_SUPPORT)
    return _STOCK_SUPPORT


def install_data_uri_image_support(text_edit) -> bool:
    """Make sure *text_edit* can render ``data:`` image sources.

    An embedded capture has to survive more than the insert: ``_save_report``
    emits ``toHtml()``, reopening the report calls ``setHtml()``, and printing
    re-renders the same document. All three resolve ``<img src=...>`` through
    ``QTextDocument.loadResource()``. If that cannot decode a data URI, the
    image is a broken box on reopen and blank on paper - registering the
    resource at insert time only lasts until the next ``setHtml``.

    SELF-LIMITING BY DESIGN: when the running Qt already handles data URIs
    (it does on 6.10.2, verified by
    ``tools/analysis/oneoff/report_image_roundtrip_2026_08_18.py``) this is a
    no-op and the editor keeps its stock document. The subclass is a
    compatibility net for an older/regressed Qt, not the mechanism - so the
    common path carries none of the risk of swapping a live document.

    Returns True only when a document was actually swapped in. Never raises:
    on any failure the editor keeps its stock document, which is exactly the
    pre-feature behaviour rather than a crash.

    Kill switch: ``AIPACS_REPORT_IMAGE_DATA_URI=0`` skips the install,
    ``=force`` installs even when Qt does not need it (for testing the net).
    """
    mode = (os.getenv("AIPACS_REPORT_IMAGE_DATA_URI", "1") or "1").strip().lower()
    if mode == "0":
        logger.info("[REPORT_IMG] data-URI image support disabled by env")
        return False
    if mode != "force" and stock_qt_resolves_data_uris():
        return False          # nothing to fix on this Qt
    try:
        document = _make_data_uri_document(text_edit)
    except Exception:
        logger.warning("[REPORT_IMG] could not build the image-aware document",
                       exc_info=True)
        return False
    if document is None:
        return False
    try:
        previous = text_edit.document()
        # Carry the default stylesheet over: the editor sets its RTL/LTR CSS on
        # the document, and dropping it would silently un-style every report.
        if previous is not None:
            try:
                document.setDefaultStyleSheet(previous.defaultStyleSheet())
            except Exception:
                pass
        text_edit.setDocument(document)
        # setDocument() hands ownership to the widget; keep our own reference
        # too so the Python wrapper is not collected out from under Qt.
        setattr(text_edit, "_aipacs_image_document", document)
        return True
    except Exception:
        logger.warning("[REPORT_IMG] setDocument failed", exc_info=True)
        return False


def _make_data_uri_document(parent=None):
    """Build the QTextDocument subclass. Separate so the class is only defined
    when Qt is importable (this module is also imported by headless tests)."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QTextDocument

    class DataUriTextDocument(QTextDocument):
        """QTextDocument that resolves ``data:image/...;base64,...`` sources."""

        def loadResource(self, resource_type, name):  # noqa: N802 (Qt override)
            try:
                url = name.toString() if isinstance(name, QUrl) else str(name)
            except Exception:
                url = ""
            if url.lower().startswith("data:image/"):
                image = decode_data_uri_image(url)
                if image is not None:
                    # Cache it, or every repaint re-decodes the base64.
                    try:
                        self.addResource(resource_type, name, image)
                    except Exception:
                        pass
                    return image
                logger.debug("[REPORT_IMG] undecodable data URI in report html")
            return super().loadResource(resource_type, name)

    return DataUriTextDocument(parent)


# Re-exported for tests that want the class without a widget.
def make_data_uri_document(parent=None):
    """Public wrapper around :func:`_make_data_uri_document`."""
    return _make_data_uri_document(parent)
