"""Guard: a voice recording attaches to the SAME study the attachments UI reads.

Regression test for the multi-study "voice never appears after the green
checkmark" bug (2026-06-16, patient 46472: DX + MR).

Root cause: the recorder's ``VoiceWidget._resolve_study_uid`` resolved the study
in the INVERSE order of the toolbar's display resolver
(``ToolbarManager._get_study_uid``):

    recorder (pre-fix):  active-series study  -> patient_widget.study_uid
    display:             patient_widget.study_uid -> active-series study

For a multi-study patient, recording while viewing a NON-primary series wrote the
WAV under that series' study folder (e.g. MR) while the mic counter / audio
dropdown listed the tab's primary study (e.g. DX). The file reached disk but
never appeared in the UI. Single-study patients always matched, which is why the
bug was intermittent.

The fix makes the recorder resolve ``patient_widget.study_uid`` FIRST, so a new
recording always lands where the counter/dropdown look. These tests pin that
order. They construct the widget with ``__new__`` to bypass the Qt/audio
``__init__`` (``_resolve_study_uid`` only reads ``self.patient_widget`` and its
argument), and skip cleanly in environments without PySide6.
"""

import types

import pytest


def _make_voice_widget():
    try:
        from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar.voice_tool_ui import (
            VoiceWidget,
        )
    except Exception as exc:  # PySide6 / audio libs absent (e.g. headless CI shard)
        pytest.skip(f"VoiceWidget import unavailable in this environment: {exc}")
    return VoiceWidget.__new__(VoiceWidget)  # bypass Qt/sounddevice __init__


def _selected_widget_with_study(uid):
    return types.SimpleNamespace(
        image_viewer=types.SimpleNamespace(metadata_fixed={"study_uid": uid})
    )


def test_multistudy_recording_uses_tab_primary_study():
    """The bug case: tab primary (DX) differs from the active series' study (MR)."""
    vw = _make_voice_widget()
    vw.patient_widget = types.SimpleNamespace(study_uid="STUDY_PRIMARY_DX")
    selected = _selected_widget_with_study("STUDY_OTHER_MR")
    # Must resolve to the tab's primary study — where the mic counter / audio
    # dropdown look — NOT the active series' study (the pre-fix behaviour that
    # silently hid the recording).
    assert vw._resolve_study_uid(selected) == "STUDY_PRIMARY_DX"


def test_single_study_patient_unchanged():
    """Common path: both sources agree, so behaviour is byte-identical."""
    vw = _make_voice_widget()
    vw.patient_widget = types.SimpleNamespace(study_uid="STUDY_ONLY")
    selected = _selected_widget_with_study("STUDY_ONLY")
    assert vw._resolve_study_uid(selected) == "STUDY_ONLY"


def test_falls_back_to_active_series_when_tab_primary_missing():
    """If the tab has no study_uid yet, fall back to the loaded series' study."""
    vw = _make_voice_widget()
    vw.patient_widget = types.SimpleNamespace(study_uid=None)
    selected = _selected_widget_with_study("STUDY_FROM_SERIES")
    assert vw._resolve_study_uid(selected) == "STUDY_FROM_SERIES"


def test_returns_none_when_no_study_anywhere():
    """No primary and no loaded series → None (caller shows 'No Study')."""
    vw = _make_voice_widget()
    vw.patient_widget = types.SimpleNamespace(study_uid=None)
    selected = types.SimpleNamespace(image_viewer=None)
    assert vw._resolve_study_uid(selected) is None
