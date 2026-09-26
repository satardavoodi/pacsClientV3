"""Regression guards for the patient-tab representative thumbnail.

The title-bar thumbnail is presentation state owned by the Patient Widget.  It
must follow the same admitted-series stream as the sidebar, while excluding the
DICOMized clinical-history document (original SeriesNumber 100000).
"""

from pathlib import Path
from types import SimpleNamespace

import PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core._pw_metadata as metadata_module
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core._pw_metadata import (
    _PWMetadataMixin,
)


def _owner():
    owner = SimpleNamespace(
        logo_patient=None,
        metadata_fixed={"patient_name": "Synthetic", "patient_id": "SYNTHETIC"},
        study_uid="study-primary",
        tab_manager=None,
    )
    owner.update_tab_manager = lambda: None
    return owner


def test_header_thumbnail_rejects_history_document_and_accepts_first_image(monkeypatch):
    callbacks = []
    monkeypatch.setattr(
        metadata_module.QTimer,
        "singleShot",
        lambda _delay, callback: callbacks.append(callback),
    )
    owner = _owner()

    assert _PWMetadataMixin.check_logo_patient(
        owner,
        Path("100000.png"),
        {"series_number": "100000", "modality": "DOC"},
    ) is False
    assert owner.logo_patient is None

    assert _PWMetadataMixin.check_logo_patient(
        owner,
        Path("1.png"),
        {"series_number": "1", "modality": "MR"},
    ) is True
    assert owner.logo_patient == Path("1.png")
    assert len(callbacks) == 1


def test_header_thumbnail_uses_original_number_for_multistudy_document(monkeypatch):
    callbacks = []
    monkeypatch.setattr(
        metadata_module.QTimer,
        "singleShot",
        lambda _delay, callback: callbacks.append(callback),
    )
    owner = _owner()

    assert _PWMetadataMixin.check_logo_patient(
        owner,
        Path("100000.png"),
        {"series_number": "1100000", "_orig_series_number": "100000"},
    ) is False
    assert _PWMetadataMixin.check_logo_patient(
        owner,
        Path("1.png"),
        {"series_number": "1000001", "_orig_series_number": "1"},
    ) is True
    assert owner.logo_patient == Path("1.png")


def test_tab_update_targets_its_widget_not_the_current_tab():
    calls = []
    owner = _owner()
    other = object()
    manager = SimpleNamespace(
        patient_tabs={
            3: {"widget": other, "study_uid": "study-other"},
            7: {"widget": owner, "study_uid": owner.study_uid},
        },
        study_uid_to_tab={owner.study_uid: 7},
        tab_widget=SimpleNamespace(currentIndex=lambda: 3),
        update_patient_tab=lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    owner.tab_manager = manager
    owner.logo_patient = Path("1.png")

    _PWMetadataMixin.update_tab_manager(owner)

    assert len(calls) == 1
    assert calls[0][0][0] == 7
    assert calls[0][1]["thumbnail_path"] == Path("1.png")


def test_sidebar_card_admission_is_the_single_header_thumbnail_producer():
    root = Path(__file__).resolve().parents[3]
    core = root / "PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core"
    panels = (core / "_pw_panels.py").read_text(encoding="utf-8-sig")
    thumbnails = (core / "_pw_thumbnails.py").read_text(encoding="utf-8-sig")
    pipeline = (core / "_pw_pipeline.py").read_text(encoding="utf-8-sig")
    viewer_load = (
        root / "PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py"
    ).read_text(encoding="utf-8-sig")

    assert "logo_check(file_path_thumbnail, series_info)" in panels
    assert "check_logo_patient(" not in thumbnails
    assert "check_logo_patient(" not in pipeline
    assert ".logo_patient = file_path" not in pipeline
    assert ".logo_patient = thumbnail_path" not in pipeline
    assert ".logo_patient = file_path" not in viewer_load
