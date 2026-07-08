"""verification — result verification for agent browser tasks.

Primary verification channel is the rendered page's TEXT
(``QWebEnginePage.toPlainText`` — deterministic, free, theme-proof),
with a PNG screenshot saved as a reviewable artifact. OCR is a
pluggable bonus for image-only content: it activates only when
pytesseract AND a Tesseract binary are present (bundled vendor dir →
``AIPACS_TESSERACT`` env → PATH) and silently stays off otherwise.

All widget access goes through ``ui_bridge.run_on_ui`` — these helpers
are called from agent worker threads.
"""
from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

from .ui_bridge import run_on_ui

logger = logging.getLogger(__name__)


def artifacts_dir() -> Path:
    try:
        from PacsClient.utils.data_paths import ECHOMIND_DIR
        d = Path(ECHOMIND_DIR) / "agent_artifacts"
    except Exception:
        try:
            from PacsClient.utils.data_paths import USER_DATA_ROOT
            d = Path(USER_DATA_ROOT) / "echomind" / "agent_artifacts"
        except Exception:
            d = Path.home() / ".aipacs_agent_artifacts"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── page load / text ─────────────────────────────────────────────────────

def wait_page_loaded(widget, timeout: float = 20.0,
                     poll: float = 0.5) -> bool:
    """Poll the browser widget's ``_is_loading`` flag from the worker."""
    deadline = time.time() + timeout
    # Give navigation a moment to actually start.
    time.sleep(min(0.8, timeout))
    while time.time() < deadline:
        ok, loading = run_on_ui(
            lambda: bool(getattr(widget, "_is_loading", False)), timeout=5.0)
        if ok and not loading:
            return True
        time.sleep(poll)
    return False


def get_page_text(widget, timeout: float = 10.0) -> str:
    """Extract the rendered page's plain text (worker-thread safe)."""
    import threading
    done = threading.Event()
    box: dict[str, str] = {}

    def _request():
        def _cb(text):
            box["text"] = text or ""
            done.set()
        try:
            widget.page.toPlainText(_cb)
        except Exception:
            logger.exception("verification: toPlainText failed")
            done.set()

    ok, _ = run_on_ui(_request, timeout=5.0)
    if not ok:
        return ""
    done.wait(timeout)
    return box.get("text", "")


def get_page_url(widget) -> str:
    ok, url = run_on_ui(
        lambda: widget.web_view.url().toString(), timeout=5.0)
    return url if ok and isinstance(url, str) else ""


def capture_screenshot(widget, name_hint: str = "agent") -> str:
    """Grab the browser view into a PNG artifact; '' on failure."""
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", name_hint)[:60] or "agent"
    out = artifacts_dir() / f"{safe}_{time.strftime('%Y%m%d_%H%M%S')}.png"

    def _grab():
        pixmap = widget.web_view.grab()
        return bool(pixmap and not pixmap.isNull()
                    and pixmap.save(str(out), "PNG"))

    ok, saved = run_on_ui(_grab, timeout=8.0)
    if ok and saved:
        return str(out)
    return ""


# ── term verification ────────────────────────────────────────────────────

_STOPWORDS = {"the", "and", "for", "with", "this", "that", "from", "into",
              "on", "in", "of", "a", "an", "to", "at", "is", "are"}


def significant_terms(query: str) -> list[str]:
    terms = [t for t in re.split(r"\W+", (query or "").lower())
             if len(t) > 2 and t not in _STOPWORDS]
    return terms or [t for t in re.split(r"\W+", (query or "").lower()) if t]


def verify_terms_in_text(text: str, query: str,
                         min_ratio: float = 0.5) -> tuple[bool, float]:
    """True when at least *min_ratio* of the query's significant terms
    appear in *text* (case-insensitive)."""
    terms = significant_terms(query)
    if not terms:
        return False, 0.0
    low = (text or "").lower()
    hit = sum(1 for t in terms if t in low)
    ratio = hit / len(terms)
    return ratio >= min_ratio, ratio


# ── pluggable OCR (bundled-first discovery) ──────────────────────────────

def _tesseract_binary() -> Optional[str]:
    """Bundled vendor dir → env override → PATH. None when absent."""
    try:
        from PacsClient.utils.data_paths import BASE_PATH
        vendored = Path(BASE_PATH) / "tools" / "vendor" / "tesseract" / "tesseract.exe"
        if vendored.exists():
            return str(vendored)
    except Exception:
        pass
    env = os.environ.get("AIPACS_TESSERACT", "").strip()
    if env and Path(env).exists():
        return env
    import shutil
    return shutil.which("tesseract")


def ocr_available() -> bool:
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return _tesseract_binary() is not None


def ocr_image(image_path: str) -> str:
    """OCR an image file to text. '' when OCR is unavailable or fails."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""
    binary = _tesseract_binary()
    if not binary:
        return ""
    try:
        pytesseract.pytesseract.tesseract_cmd = binary
        with Image.open(image_path) as img:
            return pytesseract.image_to_string(img) or ""
    except Exception:
        logger.exception("verification: OCR failed for %s", image_path)
        return ""


__all__ = [
    "artifacts_dir", "wait_page_loaded", "get_page_text", "get_page_url",
    "capture_screenshot", "significant_terms", "verify_terms_in_text",
    "ocr_available", "ocr_image",
]
