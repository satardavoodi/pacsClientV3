"""Guards: drag-before-download defers cleanly instead of a doomed ITK fallback.

Root cause (2026-06-08, patient 45644 series 301): dragging a server series into
a viewport before it has downloaded made the FAST loader find zero instances and
fall through to the ITK pipeline — which also has no files, wastes ~100 ms, risks
touching the heavy backend FAST mode must avoid, and logs the *normal* condition
as a recurring ERROR ("load-on-demand FAILED").

Fix:
  1. image_io.load_single_series_by_number — when the fast path produces no
     instances AND there are no DICOM files on disk (still downloading), end
     cleanly (skip the ITK fallback) instead of running a guaranteed-empty load.
     Files-present series keep the ITK fallback (genuine recovery).
  2. _vc_switch._finish_on_ui — the not-downloaded-yet branch logs at INFO
     ("awaiting download"), not ERROR, since it then shows the spinner and lets
     progressive display populate the viewer.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
IMAGE_IO = ROOT / "PacsClient" / "pacs" / "patient_tab" / "utils" / "image_io.py"
VC_SWITCH = ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui" / "_vc_switch.py"


def _io() -> str:
    return IMAGE_IO.read_text(encoding="utf-8")


def _sw() -> str:
    return VC_SWITCH.read_text(encoding="utf-8")


def test_image_io_skips_itk_when_no_disk_files():
    s = _io()
    # Uses the loader's own discovery helper so the "no files" notion matches.
    assert "_no_disk_files = not _list_unique_dicom_files(series_path)" in s
    # On the no-files branch it ends the generator (defers to progressive)…
    assert "skipped doomed ITK fallback" in s


def test_image_io_keeps_itk_fallback_when_files_present():
    """The ITK fallback warning must still exist for the files-present case."""
    s = _io()
    assert "falling back to ITK pipeline" in s
    # The skip must be gated: the early return is only under the no-files guard,
    # not unconditional, so the warning remains reachable when files exist.
    idx_guard = s.find("_no_disk_files = not _list_unique_dicom_files(series_path)")
    idx_warn = s.find("produced no instances for series %s")
    assert idx_guard != -1 and idx_warn != -1
    # the guard block precedes the still-present ITK warning
    assert idx_guard < idx_warn


def test_image_io_no_disk_files_defaults_safe_on_error():
    """Any exception while probing disk must keep the ITK fallback (False)."""
    s = _io()
    assert "_no_disk_files = False" in s  # the except branch


def test_vc_switch_await_download_logs_info_not_error():
    s = _sw()
    # The recurring false ERROR is gone…
    assert "async load-on-demand FAILED for series" not in s
    # …replaced by an accurate INFO on the awaiting-download branch.
    assert "not resident yet" in s
    assert "awaiting download, progressive display will populate" in s
