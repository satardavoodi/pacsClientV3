"""Guards: dragging a series loads EXACTLY that series.

Production complaint (2026-06-21, patient 44030 + merged previous exams): after
viewing a PREVIOUS exam, dragging a CURRENT series showed the previous study's
series in the viewport. Root cause: on a multi-study tab (current patient + previous
exams merged under DIFFERENT Patient IDs / Study UIDs), the viewer resolved the
right series IDENTITY but loaded pixels from the tab-level ``study_path``, which a
prior previous-exam load had left pointing at that previous study. Because the
previous study often ALSO has a same-numbered series, the old
"``study_path/<key>`` exists -> keep it" check loaded the WRONG study's series.

Fix (both in ``_vc_load.py``):
  (A) the ENTRY-AUTHORITY gate now resolves EVERY multi-study key — primary/current
      INCLUDED — from the series' own ``_server_series_info`` entry ``series_path``
      (it was previously gated to non-primary ``_study_slot > 0``, so current keys
      fell back to the poison-prone tab path);
  (B) ``_resolve_plain_series_study_path`` trusts the entry's ``series_path`` first.
Single-study tabs are byte-identical: the gate requires ``_orig_series_number``,
which ONLY the multi-study rebuild sets.

These tests pin the pure entry-authority resolver (``resolve_entry_study_location``)
AND that the fix is wired into the resolution path (so it can't pass as dead code).
``_vc_load`` pulls heavy Qt deps, so the function import is skip-guarded — matching
``test_dragdrop_coalesce.py``. The source-pin checks run everywhere.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_VC_LOAD = _REPO_ROOT / "PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py"
_VC_CACHE = _REPO_ROOT / "PacsClient/pacs/patient_tab/ui/patient_ui/_vc_cache.py"
_SRC_LOAD = _VC_LOAD.read_text(encoding="utf-8")
_SRC_CACHE = _VC_CACHE.read_text(encoding="utf-8")


def _resolver():
    try:
        from PacsClient.pacs.patient_tab.ui.patient_ui._vc_load import (
            resolve_entry_study_location,
        )
    except Exception as exc:  # heavy Qt/viewer deps absent in this shard
        pytest.skip(f"_vc_load import unavailable: {exc}")
    return resolve_entry_study_location


def _eq(result, exp_dir, exp_disk):
    """OS-agnostic compare (CI runs on Windows -> str() uses backslashes)."""
    got_dir, got_disk = result
    return Path(got_dir) == Path(exp_dir) and got_disk == exp_disk


# ---- pure entry-authority resolution ------------------------------------

def test_current_primary_series_loads_its_own_study():
    """A CURRENT primary-study series (slot 0) resolves to its OWN study folder.
    This is the core fix — the entry-authority path used to skip primary keys."""
    r = _resolver()
    entry = {"series_path": "/src/44030/2", "_orig_series_number": "2",
             "_study_slot": 0, "study_uid": "44030"}
    # tab study_path is poisoned to a previous exam (43373) -> must be ignored
    assert _eq(r(entry, "/src/43373"), "/src/44030", "2")


def test_previous_exam_series_loads_previous_study():
    """A PREVIOUS exam series (offset slot) resolves to the previous study's folder."""
    r = _resolver()
    entry = {"series_path": "/src/43373/5", "_orig_series_number": "5",
             "_study_slot": 1, "study_uid": "43373"}
    assert _eq(r(entry, "/src/44030"), "/src/43373", "5")


def test_poisoned_path_with_same_series_number_still_correct():
    """The exact bug trigger: the poisoned tab path (previous study) ALSO has a
    series 2 on disk. Entry authority must still load the CURRENT study's series 2,
    not the previous study's."""
    r = _resolver()
    entry = {"series_path": "/src/44030/2", "_orig_series_number": "2"}
    assert _eq(r(entry, "/src/43373"), "/src/44030", "2")


def test_correct_tab_path_resolves_consistently():
    r = _resolver()
    entry = {"series_path": "/src/44030/2", "_orig_series_number": "2"}
    assert _eq(r(entry, "/src/44030"), "/src/44030", "2")


def test_single_study_entry_returns_none_unchanged():
    """Single-study entries carry series_path but NOT _orig_series_number, so the
    resolver returns (None, None) and the caller keeps its original tab path
    (byte-identical legacy behaviour for single-study patients)."""
    r = _resolver()
    assert r({"series_path": "/src/single/2"}, "/src/single") == (None, None)


def test_missing_or_malformed_entry_returns_none():
    r = _resolver()
    assert r(None, "/src/x") == (None, None)
    assert r({}, "/src/x") == (None, None)
    assert r({"_orig_series_number": "2"}, "/src/x") == (None, None)  # no series_path
    assert r("not-a-dict", "/src/x") == (None, None)


# ---- wiring: the fix is live in the resolution path ---------------------

def test_entry_authority_gate_calls_resolver():
    """The multi-study gate must delegate to resolve_entry_study_location for EVERY
    key (so the pure logic above is the real production path, not dead code)."""
    assert "resolve_entry_study_location(_ms_entry" in _SRC_LOAD


def test_entry_authority_gate_not_primary_skipping():
    """The old gate skipped the primary study (`_study_slot ... > 0`), which is what
    let a current series fall through to the poisoned tab path. It must stay gone."""
    assert "_study_slot', 0) or 0) > 0" not in _SRC_LOAD


def test_plain_key_uses_entry_authority_first():
    """The plain-key fallback must trust the series' own entry series_path first
    (not the old `study_path/<key> exists -> keep` short-circuit)."""
    assert "plain-key ENTRY authority" in _SRC_LOAD


def test_cache_study_match_guard_present():
    """Layer 3: cached pixels keyed under a different study must be rejected."""
    assert "_cache_entry_study_matches" in _SRC_CACHE
    assert "CACHE-STUDY-MISMATCH" in _SRC_CACHE
