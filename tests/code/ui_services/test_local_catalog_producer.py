"""Producer-owned Local catalog facts; synthetic files only, no live database."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]


def _scan_result(source_path):
    series = {
        "series_uid": "1.2.3.series",
        "series_number": "1",
        "series_description": "Synthetic cine",
        "modality": "US",
        "image_count": 1,
        "instance_count": 1,
        "frame_count": 420,
        "has_pixel_data": True,
        "files": [{
            "source_path": str(source_path),
            "instance_number": 1,
            "sop_uid": "1.2.3.instance",
            "is_compressed": False,
            "has_pixel_data": True,
            "frame_count": 420,
        }],
    }
    study = {
        "study_uid": "1.2.3.study",
        "patient_id": "SYNTHETIC",
        "patient_name": "Synthetic",
        "count_of_series": 1,
        "series": [series],
    }
    return {
        "study_count": 1,
        "dicom_file_count": 1,
        "studies": [study],
        "primary_study_uid": study["study_uid"],
    }


def test_fresh_import_publishes_distinct_object_and_frame_facts(tmp_path, monkeypatch):
    from PacsClient.pacs.workstation_ui.home_ui.import_preview_dialog import (
        import_scanned_dicom_studies,
    )

    monkeypatch.setenv("AIPACS_IMPORT_DECOMPRESS", "0")
    source = tmp_path / "source.dcm"
    source.write_bytes(b"synthetic-not-parsed-by-copy-stage")

    result = import_scanned_dicom_studies(_scan_result(source), tmp_path / "managed")
    series = result["studies"][0]["series"][0]

    assert series["local_inventory_verified"] is True
    assert series["local_instance_count"] == 1
    assert series["local_pixel_instance_count"] == 1
    assert series["local_frame_count"] == 420


def test_preexisting_destination_cannot_be_claimed_by_new_import_generation(tmp_path, monkeypatch):
    from PacsClient.pacs.workstation_ui.home_ui.import_preview_dialog import (
        import_scanned_dicom_studies,
    )

    monkeypatch.setenv("AIPACS_IMPORT_DECOMPRESS", "0")
    source = tmp_path / "source.dcm"
    source.write_bytes(b"new-source")
    output = tmp_path / "managed"
    destination = output / "1.2.3.study" / "1" / "00001_1.2.3.instance.dcm"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"older-unverified-destination")

    result = import_scanned_dicom_studies(deepcopy(_scan_result(source)), output)
    series = result["studies"][0]["series"][0]

    assert series["local_inventory_verified"] is False
    assert series["local_instance_count"] == 0
    assert destination.read_bytes() == b"older-unverified-destination"


def test_import_registration_publishes_summary_only_after_complete_index():
    source = (REPO / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_study_save.py").read_text(
        encoding="utf-8-sig"
    )
    assert "series.get('local_inventory_verified')" in source
    assert "len(instances_to_save) == len(dicom_files)" in source
    assert "mark_series_indexed(" in source
    assert "pixel_instance_count=(" in source
    assert "display_frame_count=(" in source


def test_unreadable_payload_probe_is_not_a_verified_nonpixel_object(tmp_path):
    from PacsClient.utils.dicom_displayability import try_dicom_file_pixel_facts

    assert try_dicom_file_pixel_facts(tmp_path / "missing.dcm") is None
