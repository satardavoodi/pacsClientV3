"""Guard for the wrong-study bucketer fix (2026-06-21).

A series that reaches ``set_server_series_info`` WITHOUT an explicit ``study_uid`` must
be attributed to THIS tab's primary study (``self.study_uid``), not dropped. Dropping
it left the primary study's slot-0 entries out of the rebuilt ``_server_series_info``,
so a primary-key drag fell back to a previous-exam-poisoned tab ``study_path`` and
loaded the WRONG study (analysis:
docs/reports/PIPELINE_DRAG_EXACT_SERIES_ANALYSIS_2026-06-21.md).

Source-pin (the bucketing is inline in a Qt mixin that pulls heavy deps), matching the
style of test_drag_loads_exact_series.py.
"""
from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC = (
    _REPO_ROOT
    / "PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_thumbnails.py"
).read_text(encoding="utf-8")


def test_primary_bucket_flag_default_on():
    # Correctness fix shipped default-ON with a kill switch (=0).
    assert 'AIPACS_PRIMARY_BUCKET_FALLBACK", "1"' in _SRC
    assert "_PRIMARY_BUCKET_FALLBACK = (os.getenv(" in _SRC


def test_no_study_uid_series_attributed_to_primary_then_drop():
    # In the no-study_uid branch: fall back to self.study_uid (the primary) FIRST,
    # then keep the legacy drop only if there is still no study (no primary either).
    assert "if _PRIMARY_BUCKET_FALLBACK:" in _SRC
    i = _SRC.index("if _PRIMARY_BUCKET_FALLBACK:")
    seg = _SRC[i : i + 400]
    assert "getattr(self, 'study_uid'" in seg   # attribute to the primary study
    assert "continue" in seg                     # legacy drop still reachable


def test_rebuild_still_stamps_primary_slot0():
    # The fix's whole point is that the primary (slot 0) entry gets stamped with its
    # own series_path/_orig_series_number so entry-authority resolves it — that
    # stamping must remain in the multi-study rebuild.
    assert "_rebuild_multistudy_series_index" in _SRC
    assert "entry['series_path']" in _SRC
    assert "entry['_orig_series_number']" in _SRC
