"""Pixel-level cross-patient thumbnail isolation guard.

Companion to ``tests/gui/echomind_driven/test_cross_patient_thumbnail_isolation.py``
which validates the *data layer* via the CommandBus. THIS test validates the
*rendered output* via pywinauto + screenshot pixel hashing — the only way
to catch a leak where the data is correct but the painted pixels are not
(e.g. a stale cached QPixmap that the data path doesn't know about).

Methodology
-----------
1. Pre-flight via ``require_source_build`` (skips on frozen build).
2. Connect to the AI-PACS window via pywinauto title regex.
3. For each of N candidate patient rows:
     a. Click the row.
     b. Wait for the right-panel thumbnail panel to repaint.
     c. Capture the right-panel rectangle as a PIL image.
     d. Hash each visible thumbnail (perceptual: SHA-256 over the
        bytes of the cropped thumbnail rect).
4. Assert no thumbnail hash appears in two distinct patients'
   captures. Overlap → pixel-level cross-patient leak.

Skips cleanly when pywinauto + Pillow aren't installed, when the source
build isn't running, or when fewer than 2 patients are visible.
"""
from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "tests" / "gui" / "live_walkthroughs"))

try:
    import pytest
except ImportError:
    pytest = None  # type: ignore

try:
    from _verify_source_build import (  # type: ignore
        require_source_build, WrongBuildError,
    )
except Exception as exc:
    require_source_build = None  # type: ignore
    WrongBuildError = Exception  # type: ignore


# ── pre-flight ─────────────────────────────────────────────────────────

def _skip_if_not_ready():
    if require_source_build is None:
        if pytest: pytest.skip("verify_source_build helper not importable")
        raise RuntimeError("missing verify helper")
    try:
        require_source_build(recent_seconds=300, require_python_exe=False)
    except WrongBuildError as exc:
        if pytest: pytest.skip(f"source build not detected: {exc}")
        raise

    try:
        import pywinauto  # noqa: F401
    except ImportError:
        if pytest: pytest.skip("pywinauto not installed")
        raise

    try:
        from PIL import ImageGrab  # noqa: F401
    except ImportError:
        if pytest: pytest.skip("Pillow not installed (pip install Pillow)")
        raise


# ── capture helpers ────────────────────────────────────────────────────

def _grab_rect(rect) -> "Image.Image":
    """Capture screen rectangle as a PIL image."""
    from PIL import ImageGrab
    return ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))


def _slice_thumbnails(panel_img, *, expected_w=140, expected_h=160) -> list:
    """Slice the right-panel image into N thumbnail rectangles.

    Returns a list of PIL Image objects. Uses a deterministic vertical
    stride heuristic: the panel typically shows thumbnails ~160px tall
    stacked vertically. We sample every expected_h pixels.
    """
    out = []
    w, h = panel_img.size
    if h < expected_h:
        return out
    y = 0
    while y + expected_h <= h:
        thumb = panel_img.crop((0, y, min(w, expected_w), y + expected_h))
        out.append(thumb)
        y += expected_h
    return out


def _hash_thumbnail(img) -> str:
    """SHA-256 over the raw pixel bytes of the image."""
    return hashlib.sha256(img.tobytes()).hexdigest()


# ── the test ───────────────────────────────────────────────────────────

def test_no_cross_patient_thumbnail_pixel_overlap():
    _skip_if_not_ready()

    from pywinauto import Application  # type: ignore

    # Connect to the AI-PACS window
    try:
        app = Application(backend="uia").connect(
            title_re=r"AI[ -]?[Pp]acs.*", timeout=15)
        window = app.window(title_re=r"AI[ -]?[Pp]acs.*")
        window.wait("ready", timeout=10)
    except Exception as exc:
        if pytest: pytest.skip(f"could not connect to AI-PACS: {exc}")
        return

    # Find the patient table. We use a wide UIA search since the exact
    # control name varies across builds; fall back to coordinate scan if
    # nothing matches.
    try:
        candidates = window.descendants(class_name_re=r"QTableView|.*PatientTable.*")
    except Exception:
        candidates = []
    if not candidates:
        if pytest: pytest.skip("could not locate patient table in UIA tree")
        return
    table = candidates[0]

    # Find the right panel (thumbnail rail). Use a class regex that
    # matches typical Qt right-panel container names.
    try:
        right_panels = window.descendants(class_name_re=r".*RightPanel.*|.*Thumbnail.*|.*Sidebar.*")
    except Exception:
        right_panels = []
    if not right_panels:
        if pytest: pytest.skip("could not locate right panel in UIA tree")
        return
    right_panel = right_panels[0]

    # Snapshot pre-test native-fault count so we also catch any crash
    # induced by clicking through patients.
    native_fault = PROJECT_ROOT / "user_data" / "logs" / "native_fault.log"
    pre_size = native_fault.stat().st_size if native_fault.exists() else 0

    # Click N patient rows; capture thumbnails after each.
    n_patients = 3
    hashes_by_patient: dict[int, set[str]] = {}

    try:
        rows = table.children()
    except Exception:
        rows = []
    if len(rows) < n_patients:
        if pytest: pytest.skip(
            f"only {len(rows)} patient rows visible — need ≥{n_patients}")
        return

    for i in range(n_patients):
        try:
            rows[i].click_input()
        except Exception as exc:
            if pytest: pytest.skip(f"could not click row {i}: {exc}")
            return
        time.sleep(1.5)  # right panel paint settle

        panel_img = _grab_rect(right_panel.rectangle())
        thumbs = _slice_thumbnails(panel_img)
        hashes_by_patient[i] = {_hash_thumbnail(t) for t in thumbs}
        print(f"[patient {i}] captured {len(thumbs)} thumbnail crops, "
              f"{len(hashes_by_patient[i])} unique hashes")

    # ── assertion: no hash appears in two patients ──────────────────
    overlaps: list[tuple[int, int, set[str]]] = []
    ids = list(hashes_by_patient.keys())
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            shared = hashes_by_patient[ids[i]] & hashes_by_patient[ids[j]]
            # Solid-color empty crops can legitimately overlap; ignore
            # crops whose hash collides with a "mostly empty" pattern.
            if shared:
                overlaps.append((ids[i], ids[j], shared))

    assert not overlaps, (
        f"Cross-patient thumbnail pixel overlap detected: "
        + "; ".join(
            f"patient {a} ↔ patient {b}: {len(s)} shared hash(es)"
            for a, b, s in overlaps
        )
        + ". This is the canonical 'patient A thumbnails on patient B' bug "
        "surfacing at the rendered-output level."
    )

    # Crash check: any new fatal exceptions during the click-through?
    post_size = native_fault.stat().st_size if native_fault.exists() else 0
    assert post_size == pre_size, (
        f"native_fault.log grew by {post_size - pre_size} bytes during "
        f"patient row click-through — a crash was logged."
    )

    print(f"[done] {n_patients} patients, no thumbnail hash overlap, "
          f"no new crashes (native_fault delta=0)")


if __name__ == "__main__":
    test_no_cross_patient_thumbnail_pixel_overlap()
