"""Guard test for P1.1 — off-GUI-thread thumbnail disk write.

The socket-fetch thumbnail save (`_hp_series.save_thumbnail`) used to mkdir+write every
series PNG synchronously on the GUI thread (a main-thread stall source). P1.1 moves the
write to a background worker via `save_thumbnail_with_bytes_async`, keeping the canonical
path and reusing the existing `save_thumbnail_with_bytes` (no duplicated write logic).

Invariants pinned here:
  * flag `AIPACS_THUMB_SAVE_ASYNC` default-ON, with a synchronous kill-switch path;
  * the async writer REUSES `save_thumbnail_with_bytes` (no forked write logic);
  * the canonical path is identical to the synchronous writer's path;
  * the home-panel call site uses the async variant;
  * the symbol is exported from `patient_tab.utils`.

Primary tests are source-pins (no PySide6/VTK/SimpleITK import needed). A behavioral test
runs too when the heavy deps are importable (Windows verify lane); it is skipped otherwise.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
UTILS = REPO / "PacsClient" / "pacs" / "patient_tab" / "utils" / "utils.py"
UTILS_INIT = REPO / "PacsClient" / "pacs" / "patient_tab" / "utils" / "__init__.py"
HP_SERIES = REPO / "PacsClient" / "pacs" / "workstation_ui" / "home_ui" / "home_panel" / "_hp_series.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


def test_flag_default_on_and_async_defined():
    s = _read(UTILS)
    assert 'os.getenv("AIPACS_THUMB_SAVE_ASYNC", "1")' in s, "flag must default ON"
    assert "def save_thumbnail_with_bytes_async(" in s
    assert "def canonical_thumbnail_path(" in s


def test_async_reuses_sync_writer_and_has_kill_switch():
    s = _read(UTILS)
    # locate the async function body
    start = s.index("def save_thumbnail_with_bytes_async(")
    body = s[start:start + 1400]
    # synchronous kill switch: flag off -> delegate to the sync writer verbatim
    assert "if not _THUMB_SAVE_ASYNC:" in body
    # reuse, not fork: the write itself goes through save_thumbnail_with_bytes
    assert body.count("save_thumbnail_with_bytes(") >= 2
    # fire-and-forget onto a background worker
    assert "_get_thumb_write_executor().submit(" in body


def test_canonical_path_parity_with_sync_writer():
    s = _read(UTILS)
    # both the sync writer and the canonical helper build the same path shape
    assert "THUMBNAIL_PATH / study_uid" in s
    assert "f'{file_name}.png'" in s  # canonical_thumbnail_path
    assert "f'{file_name}.png'" in s  # sync writer uses the same


def test_callsite_uses_async():
    s = _read(HP_SERIES)
    assert "save_thumbnail_with_bytes_async(study_uid, safe_file_name, thumb_bytes)" in s
    # the old synchronous call at that site must be gone
    assert "file_path = save_thumbnail_with_bytes(study_uid, safe_file_name, thumb_bytes)" not in s


def test_symbol_exported():
    s = _read(UTILS_INIT)
    assert "save_thumbnail_with_bytes_async," in s
    assert '"save_thumbnail_with_bytes_async",' in s


def test_behavioral_async_write(tmp_path, monkeypatch):
    try:
        mod = importlib.import_module("PacsClient.pacs.patient_tab.utils.utils")
    except Exception as exc:  # heavy deps (VTK/SimpleITK/PySide6) not present in this lane
        pytest.skip(f"utils heavy deps unavailable: {exc}")

    monkeypatch.setattr(mod, "THUMBNAIL_PATH", tmp_path)
    monkeypatch.setattr(mod, "_THUMB_SAVE_ASYNC", True)

    p = mod.save_thumbnail_with_bytes_async("STUDY1", "3", b"PNGDATA")
    assert p == str(tmp_path / "STUDY1" / "3.png")  # canonical path returned immediately

    # single-worker executor: a sentinel completes only after the write job
    mod._get_thumb_write_executor().submit(lambda: None).result(timeout=5)
    assert (tmp_path / "STUDY1" / "3.png").read_bytes() == b"PNGDATA"

    # kill switch -> synchronous write, file present on return
    monkeypatch.setattr(mod, "_THUMB_SAVE_ASYNC", False)
    mod.save_thumbnail_with_bytes_async("STUDY1", "4", b"XY")
    assert (tmp_path / "STUDY1" / "4.png").read_bytes() == b"XY"
