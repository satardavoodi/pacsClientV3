"""Guard: I1 resume-control unification + flag wiring (OPT-04 / DM resume,
2026-07-08).

Source-pin (no live widget): the selected-Start handler must, under
AIPACS_DM_UNIFY_RESUME, delegate to the SAME `_on_per_patient_resume` the row
Resume uses, and the legacy inline path must remain as the default-off kill
switch. Also pins the flag names for the auto-resume feature so they can't be
renamed silently.
"""
from pathlib import Path

import modules.download_manager.ui.widget._dm_controls as C
import modules.download_manager.ui.widget._dm_workers as W


def test_start_selected_delegates_to_canonical_resume_under_flag():
    src = Path(C.__file__).read_text(encoding="utf-8")
    assert "AIPACS_DM_UNIFY_RESUME" in src
    assert "_on_per_patient_resume(self._selected_study_uid)" in src
    # Legacy inline path preserved (default-off kill switch): the old
    # "Start Selected button clicked" log line still exists below the branch.
    assert "Start Selected button clicked" in src


def test_net_resume_flags_present_in_workers():
    src = Path(W.__file__).read_text(encoding="utf-8")
    assert "AIPACS_DM_NET_RESUME" in src
    assert "_rearm_network_failed_studies" in src
    # Structured logging markers land in the workers mixin.
    assert "[DM-RETRY-EXHAUSTED]" in src
    assert "[DM-STATE]" in src
