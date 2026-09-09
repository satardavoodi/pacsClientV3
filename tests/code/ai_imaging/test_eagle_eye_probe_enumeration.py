def test_probe_enumerates_each_series_folder_once(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_lumbar import series_probe

    study = tmp_path / "study"
    series = study / "1"
    series.mkdir(parents=True)
    dicom = series / "one.dcm"
    dicom.write_bytes(b"synthetic")

    calls = []
    original = series_probe._dicom_files

    def counted(folder):
        calls.append(folder)
        return original(folder)

    class Header:
        SeriesInstanceUID = "synthetic-series"
        SeriesNumber = 1
        Modality = "MR"

    monkeypatch.setattr(series_probe, "_dicom_files", counted)
    monkeypatch.setattr(series_probe, "_read_header", lambda _path: Header())

    candidates = series_probe.probe_study_series(study)

    assert len(candidates) == 1
    assert calls.count(series) == 1


def test_probe_snapshot_does_not_retain_live_widget_or_vtk_objects():
    from modules.ai_imaging.eagle_eye_lumbar.series_probe import (
        snapshot_widget_probe_inputs,
    )

    vtk_owned = object()

    class Widget:
        study_uid = "study-uid"
        import_folder_path = "study-path"
        lst_thumbnails_data = [
            {
                "vtk_image_data": vtk_owned,
                "metadata": {
                    "series": {"series_number": 4, "description": "private"},
                    "instances": [
                        {
                            "image_position_patient": [1, 2, 3],
                            "image_orientation_patient": [1, 0, 0, 0, 1, 0],
                            "private_payload": vtk_owned,
                        }
                    ],
                },
            }
        ]

    snapshot = snapshot_widget_probe_inputs(Widget())

    assert snapshot["study_uid"] == "study-uid"
    assert snapshot["import_folder_path"] == "study-path"
    assert snapshot["thumbnails_data"][0]["metadata"] == {
        "series": {"series_number": 4},
        "instances": (
            {
                "image_position_patient": (1, 2, 3),
                "image_orientation_patient": (1, 0, 0, 0, 1, 0),
            },
        ),
    }
    assert "vtk_image_data" not in snapshot["thumbnails_data"][0]


def test_workflow_worker_never_dereferences_the_live_patient_widget():
    from pathlib import Path

    source = Path(
        "modules/ai_imaging/eagle_eye_lumbar/workflow_coordinator.py"
    ).read_text(encoding="utf-8")
    worker = source.split("def _worker()", 1)[1].split("threading.Thread", 1)[0]

    assert "patient_widget" not in worker
    assert "build_candidates_from_snapshot(snapshot)" in worker
