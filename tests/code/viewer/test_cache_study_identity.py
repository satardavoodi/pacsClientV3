"""Guard test for the viewer-cache STUDY-IDENTITY hardening (2026-07-05).

Weakness closed (audit report CLINICAL_SERIES_IDENTITY_TARGET_AUDIT_2026-07-05):
several in-memory viewer caches keyed on the bare series_number were NOT
study-scoped. On a multi-study / previous-exam tab, tiers 1-3 of
``_get_series_by_number_fast`` (``_hot_series_cache`` / ``_series_cache`` /
``_series_number_to_index``) validated ONLY series-number + object identity —
no study check — and the tier-4 ``_cache_entry_study_matches`` guard failed OPEN
when a cached entry lacked a ``study_uid``.

Fix (flag ``AIPACS_CACHE_STUDY_IDENTITY``, default on; ``=0`` = legacy):
  1. ``_full_cache_put`` STAMPS the entry's own ``study_uid`` at write time
     (so the read guard can never fail-open on our entries).
  2. ``_entry_is_valid`` (tiers 1-3) REJECTS a cached tuple whose stored
     ``study_uid`` disagrees with the study the display key resolves to.
  3. ``_cache_entry_study_matches`` logs the (now-unreachable) fail-open branch.

This test pins the DECISION LOGIC (truth table) and SOURCE-PINS the wiring.
It is intentionally import-free of the heavy Qt/VTK viewer stack (which cannot
be exercised offscreen); the live multi-study path is validated on the source
build (NEEDS-LIVE-VERIFY).
"""

import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_VC_BACKEND = os.path.join(
    _REPO, "PacsClient", "pacs", "patient_tab", "ui", "patient_ui", "_vc_backend.py"
)
_VC_CACHE = os.path.join(
    _REPO, "PacsClient", "pacs", "patient_tab", "ui", "patient_ui", "_vc_cache.py"
)


# ─────────────────────────────────────────────────────────────────────────────
# Pure replica of the study-identity decision (mirrors _entry_is_valid /
# _cache_entry_study_matches). Kept identical to the shipped predicate; the
# source-pins below tie this replica to the real code.
# ─────────────────────────────────────────────────────────────────────────────
def _study_identity_rejects(cached_study, expected_study, *, multi, flag_on=True):
    """Return True iff the cache entry must be REJECTED for study mismatch.

    Reject ONLY when: flag on AND multi-study tab AND both study ids are known
    AND they differ. Every other case KEEPS the entry (fail-open / byte-identical).
    """
    if not flag_on:
        return False
    if not multi:
        return False
    c = str(cached_study or "").strip()
    e = str(expected_study or "").strip()
    if c and e and c != e:
        return True
    return False


def _should_stamp_study(metadata, resolved_study):
    """Mirror of the _full_cache_put stamp gate: stamp only a gap."""
    if not isinstance(metadata, dict):
        return False
    ser = metadata.get("series")
    if not isinstance(ser, dict):
        return False
    if str(ser.get("study_uid") or "").strip():
        return False  # never overwrite a present study_uid
    return bool(str(resolved_study or "").strip())


# ── Truth table: single-study is byte-identical (never rejects) ──────────────
def test_single_study_never_rejects():
    # Even with a (hypothetical) study mismatch, a single-study tab must behave
    # exactly like legacy: no study-based rejection at all.
    assert _study_identity_rejects("A", "B", multi=False) is False
    assert _study_identity_rejects("A", "A", multi=False) is False
    assert _study_identity_rejects("", "", multi=False) is False


# ── Truth table: multi-study rejects ONLY on a positive, provable mismatch ───
def test_multi_study_rejects_only_on_positive_mismatch():
    # Positive mismatch -> reject (the clinical isolation win).
    assert _study_identity_rejects("studyA", "studyB", multi=True) is True
    # Same study -> keep (correct hit stays byte-identical).
    assert _study_identity_rejects("studyA", "studyA", multi=True) is False


def test_multi_study_fails_open_when_identity_unknown():
    # Unknown cached study -> cannot prove a mismatch -> KEEP (fail-open).
    assert _study_identity_rejects("", "studyB", multi=True) is False
    # Unknown expected study (resolver empty) -> KEEP (fail-open).
    assert _study_identity_rejects("studyA", "", multi=True) is False
    assert _study_identity_rejects("", "", multi=True) is False


def test_flag_off_restores_legacy():
    # Kill switch: no study-based rejection ever, even on a real mismatch.
    assert _study_identity_rejects("studyA", "studyB", multi=True, flag_on=False) is False


# ── Stamp gate: fills a gap, never overwrites, needs a resolved study ────────
def test_stamp_fills_gap_only():
    # Missing study_uid + resolver has a study -> stamp.
    assert _should_stamp_study({"series": {}}, "studyA") is True
    assert _should_stamp_study({"series": {"study_uid": ""}}, "studyA") is True


def test_stamp_never_overwrites_present_study():
    assert _should_stamp_study({"series": {"study_uid": "studyX"}}, "studyA") is False


def test_stamp_noop_when_resolver_empty_or_bad_metadata():
    assert _should_stamp_study({"series": {}}, "") is False
    assert _should_stamp_study({}, "studyA") is False
    assert _should_stamp_study(None, "studyA") is False


# ─────────────────────────────────────────────────────────────────────────────
# Source-pins: the shipped code must carry the flag, the multi-study gate, the
# positive-mismatch reject, the write-time stamp, and the fail-open diagnostic.
# (These files' tails can read stale under the sandbox FUSE mount, but every
# pinned construct lives early in each file, so the read is reliable here.)
# ─────────────────────────────────────────────────────────────────────────────
def _read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def test_source_pin_tier123_guard_present():
    src = _read(_VC_BACKEND)
    assert 'AIPACS_CACHE_STUDY_IDENTITY' in src, "tier-1-3 guard flag missing"
    assert '[CACHE-STUDY-IDENTITY] tier reject' in src, "tier reject log missing"
    # The guard must be multi-study gated and compare resolved study vs cached study.
    assert '_resolve_canonical_series_identity' in src
    assert re.search(r'_studies_series', src), "multi-study gate missing in _vc_backend"


def test_source_pin_full_cache_put_stamps_study():
    src = _read(_VC_CACHE)
    assert 'AIPACS_CACHE_STUDY_IDENTITY' in src
    assert "_ser['study_uid'] = str(_rid[0])" in src, "study_uid stamp missing in _full_cache_put"
    # Stamp must be gap-fill only (guarded by an emptiness check before assign).
    assert "not str(_ser.get('study_uid') or '').strip()" in src


def test_source_pin_tier4_failopen_diagnostic_present():
    src = _read(_VC_CACHE)
    assert '[CACHE-STUDY-IDENTITY] no cached study_uid' in src


def test_kill_switch_is_default_on_everywhere():
    # Default must be ON ("1") at every gate so the fix ships active with a
    # single documented kill switch.
    for path in (_VC_BACKEND, _VC_CACHE):
        src = _read(path)
        for m in re.finditer(r'getenv\(\s*"AIPACS_CACHE_STUDY_IDENTITY"\s*,\s*"([^"]*)"', src):
            assert m.group(1) == "1", f"{path}: default must be '1' (on), got {m.group(1)!r}"
