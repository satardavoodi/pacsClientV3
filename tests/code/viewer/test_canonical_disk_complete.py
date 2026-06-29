"""Guard: multi-study colliding series bind to their TRUE on-disk images (48296, 2026-06-29).

A 3-study patient has series numbers that collide across studies (e.g. study-0 and
study-2 both have a "series 6"). The secondary study's series gets an OFFSET display key
(2000006). Its offset-key metadata can carry a WRONG server ``expected`` image count (it
does not describe the true on-disk series), so the disk-ready resume's strict
``count >= expected`` never trips even when all 30 true images are on disk — and the live
progress bridge is primary-study-bound and cannot grow a secondary-study series. Result:
the viewport stayed stuck on 1 image though 30 were on disk.

Fix: the disk-ready resume resolves the series' OWN canonical folder
(``SOURCE_PATH/<study_uid>/<orig_series>`` — collision-free) and treats it as complete
when it has SETTLED (stable .dcm count across two ticks AND no in-flight .part),
regardless of a mismatched ``expected``. This binds the series to its TRUE images on
disk. Flag AIPACS_CANONICAL_DISK_COMPLETE (default on; =0 = legacy expected-only).

Pure-function tests for the decision + source-pins for the wiring.
"""
from pathlib import Path

import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _src() -> str:
    return (
        _repo_root() / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "_vc_progressive.py"
    ).read_text(encoding="utf-8")


def _load_funcs():
    """Import the two pure module-level helpers without importing the whole Qt module.

    `_vc_progressive` imports PySide6/VTK at module load; the helpers are pure. Extract
    and exec just their source so the test stays headless + dependency-free.
    """
    import re
    src = _src()

    def _extract(name):
        m = re.search(r"\ndef %s\(.*?\n(?=\ndef |\nclass )" % re.escape(name), src, re.S)
        assert m, "function %s not found" % name
        return m.group(0)

    ns = {}
    exec("import os\n" + _extract("_disk_ready_complete") + "\n" + _extract("_disk_series_settled"), ns)
    return ns["_disk_ready_complete"], ns["_disk_series_settled"]


def test_settled_pure_logic():
    _complete, _settled = _load_funcs()

    # Settled: positive, stable across two ticks, no .part.
    assert _settled(30, 30, False) is True
    # Not settled while a .part is in flight (DM still writing this folder).
    assert _settled(30, 30, True) is False
    # Not settled while the count is still changing (download growing).
    assert _settled(30, 20, False) is False
    # Never settled with no files.
    assert _settled(0, 0, False) is False
    # First observation (prev unknown) is not yet settled.
    assert _settled(30, None, False) is False


def test_override_recovers_poisoned_expected():
    _complete, _settled = _load_funcs()
    # The bug: a colliding secondary series has a WRONG-HIGH server expected (192) while
    # its TRUE on-disk series is 30 images. Strict completeness never trips...
    assert _complete(30, 192, 30) is False
    # ...but the canonical on-disk folder HAS settled (30 stable, no .part), so the
    # override path makes it complete — binding to the true on-disk images.
    assert _settled(30, 30, False) is True
    # A wrong-LOW expected already loaded everything (30 >= 1) — unaffected.
    assert _complete(30, 1, 30) is True


def test_wiring_source_pins():
    src = _src()
    assert 'os.getenv("AIPACS_CANONICAL_DISK_COMPLETE"' in src
    assert "def _disk_series_settled(" in src
    # the resume detects in-flight .part files and feeds the override
    assert '_nm.endswith(".part")' in src
    assert "_has_part = True" in src
    # override only ADDS a completeness route (never weakens the strict path)
    assert "if (not _complete) and _CANON_DISK_COMPLETE and _disk_series_settled(count, prev, _has_part):" in src
    assert "canonical-disk-settled" in src
