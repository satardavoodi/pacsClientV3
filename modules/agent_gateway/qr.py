"""QR-code rendering for the pairing payload.

Renders the ``aipacs-agent://pair?d=..`` pairing URI (see :mod:`pairing`) to a
QR image the Settings tab can display and the phone can scan. Uses ``segno`` — a
zero-dependency pure-Python QR library (no Pillow required). All imports are
lazy so a build without ``segno`` degrades gracefully to "show the URI as text".
"""
from __future__ import annotations

import io
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def is_available() -> bool:
    try:
        import segno  # noqa: F401

        return True
    except Exception:
        return False


def qr_png_bytes(data: str, scale: int = 6, border: int = 3) -> Optional[bytes]:
    """PNG bytes for ``data`` as a QR code, or ``None`` if ``segno`` is missing.

    Dark/light are left at defaults (black on white) so it scans reliably
    regardless of the dark Settings theme — the widget frames it on a white card.
    """
    try:
        import segno

        buf = io.BytesIO()
        segno.make(data, error="m").save(
            buf, kind="png", scale=max(2, int(scale)), border=max(1, int(border))
        )
        return buf.getvalue()
    except Exception as exc:
        logger.debug("QR render failed: %s", exc)
        return None


def qr_svg_str(data: str, scale: int = 6, border: int = 3) -> Optional[str]:
    """SVG string for ``data`` (useful for crisp scaling), or ``None``."""
    try:
        import segno

        buf = io.BytesIO()
        segno.make(data, error="m").save(
            buf, kind="svg", scale=max(2, int(scale)), border=max(1, int(border))
        )
        return buf.getvalue().decode("utf-8")
    except Exception as exc:
        logger.debug("QR SVG render failed: %s", exc)
        return None


__all__ = ["is_available", "qr_png_bytes", "qr_svg_str"]
