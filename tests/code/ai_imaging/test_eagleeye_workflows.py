import csv
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _load_module(relative_path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_rows(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def test_bone_age_feedback_preserves_ai_and_updates_human_review(tmp_path):
    schema = _load_module(
        "modules/ai_imaging/ai_module_ui/feedback_schema.py",
        "feedback_schema_for_bone_age_test",
    )

    schema.upsert_bone_age_feedback_csv(
        "study-ba",
        tmp_path,
        {"patient_id": "P1"},
        {"bone_age_years": 10, "bone_age_months": 120, "sex": "female"},
        corrected_data={"bone_age_years": "11", "bone_age_months": "132", "sex": "female"},
        review_metadata={"validation_status": "corrected", "reviewer_id": "r1"},
    )
    schema.upsert_bone_age_feedback_csv(
        "study-ba",
        tmp_path,
        {"patient_id": "P1"},
        {"bone_age_years": 10, "bone_age_months": 120, "sex": "female"},
        corrected_data={"bone_age_years": "12", "bone_age_months": "144", "sex": "male"},
        review_metadata={"validation_status": "confirmed", "reviewer_id": "r2"},
    )

    row = _read_rows(tmp_path / "bone_age_feedback.csv")[0]
    assert row["module_name"] == "bone_age"
    assert row["ai_bone_age_years"] == "10"
    assert row["ai_bone_age_months"] == "120"
    assert row["ai_sex"] == "female"
    assert row["corrected_bone_age_years"] == "12"
    assert row["corrected_bone_age_months"] == "144"
    assert row["corrected_sex"] == "male"
    assert row["validation_status"] == "confirmed"
    assert row["reviewer_id"] == "r2"


def test_mammography_feedback_uses_mg_specific_fields_and_updates_review(tmp_path):
    schema = _load_module(
        "modules/ai_imaging/ai_module_ui/feedback_schema.py",
        "feedback_schema_for_mg_test",
    )
    ai_row = {
        "patient_id": "P2",
        "dicom_full_path": "series/a.dcm",
        "labels_pred": "Mass",
        "scores": "0.91",
        "laterality": "Left",
        "view": "MLO",
    }

    schema.write_mg_feedback_csv(
        "study-mg",
        tmp_path,
        "updated_csv_with_boxes_0.45.csv",
        ai_row,
        selected_box=[1, 2, 3, 4],
        corrected_status="abnormal",
        corrected_classification=["Mass"],
        mammography_fields={
            "laterality": "Left",
            "view": "MLO",
            "lesion_type": "Mass",
            "quadrant": "UOQ",
            "birads_category": "4A",
            "human_action": "correct",
            "source_row_index": 2,
            "source_box_index": 0,
            "source_kind": "ai",
        },
        review_metadata={"validation_status": "corrected", "reviewer_id": "r1"},
    )
    schema.write_mg_feedback_csv(
        "study-mg",
        tmp_path,
        "updated_csv_with_boxes_0.45.csv",
        ai_row,
        selected_box=[1, 2, 3, 4],
        corrected_status="normal",
        corrected_classification=["No Finding"],
        mammography_fields={
            "laterality": "Right",
            "view": "CC",
            "lesion_type": "No Finding",
            "birads_category": "1",
            "human_action": "remove",
            "source_row_index": 2,
            "source_box_index": 0,
            "source_kind": "ai",
        },
        review_metadata={"validation_status": "confirmed", "reviewer_id": "r2"},
    )

    row = _read_rows(tmp_path / "mg_feedback.csv")[0]
    assert row["module_name"] == "mammography"
    assert row["ai_classification"] == "Mass"
    assert row["ai_confidence"] == "0.91"
    assert row["ai_laterality"] == "Left"
    assert row["ai_view"] == "MLO"
    assert row["corrected_status"] == "normal"
    assert row["corrected_classification"] == "No Finding"
    assert row["corrected_laterality"] == "Right"
    assert row["corrected_view"] == "CC"
    assert row["corrected_lesion_type"] == "No Finding"
    assert row["corrected_birads_category"] == "1"
    assert row["human_action"] == "remove"
    assert row["source_row_index"] == "2"
    assert row["source_box_index"] == "0"
    assert row["source_kind"] == "ai"
    assert row["validation_status"] == "confirmed"
    assert row["reviewer_id"] == "r2"


def test_csv_table_round_trip_for_eagleeye_csv_loading(tmp_path):
    csv_table = _load_module(
        "modules/ai_imaging/ai_module_ui/csv_table.py",
        "csv_table_for_eagleeye_test",
    )

    path = tmp_path / "updated_csv_with_boxes.csv"
    table = csv_table.CsvTable(
        rows=[{"dicom_full_path": "a.dcm", "box": "[[1,2,3,4]]", "scores": "[0.9]"}],
        columns=["dicom_full_path", "box", "scores"],
    )
    csv_table.write_csv_table(path, table)
    loaded = csv_table.read_csv_table(path)

    assert len(loaded) == 1
    assert loaded["dicom_full_path"][0] == "a.dcm"
    assert loaded["box"][0] == "[[1,2,3,4]]"


def test_ui_routing_and_bone_age_import_guards_are_explicit():
    ai_mainwindow = (ROOT / "modules/ai_imaging/ai_module_ui/ai_mainwindow.py").read_text(encoding="utf-8")
    imaging_tab = (ROOT / "modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py").read_text(encoding="utf-8")
    patient_widget = (ROOT / "modules/ai_imaging/ai_module_ui/overrides/patient_widget.py").read_text(encoding="utf-8")
    vtk_widget = (ROOT / "modules/ai_imaging/ai_module_ui/overrides/vtk_widget.py").read_text(encoding="utf-8")
    hp_modules = (ROOT / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_modules.py").read_text(encoding="utf-8")

    assert "eagle_eye_mode" in ai_mainwindow
    assert "eagle_eye_mode" in hp_modules
    assert 'self.eagle_eye_mode == "bone_age"' in imaging_tab
    assert 'initial_layout = (1, 1) if self.eagle_eye_mode == "bone_age" else (1, 2)' in patient_widget
    assert 'BACKEND_PYDICOM_QT if self.eagle_eye_mode == "bone_age" else BACKEND_VTK' in patient_widget
    assert 'if self.eagle_eye_mode == "bone_age":\n            return super().creator_vtk_widget()' in patient_widget
    assert 'if self.eagle_eye_mode == "bone_age":\n            return super().create_dummy_vtk_widget()' in patient_widget
    assert ".get('metadata', {})" in patient_widget
    assert 'modality == \'MG\'' in vtk_widget
    assert "metadata_fixed['study_uid']" not in vtk_widget
    assert "lst_node_viewers" not in patient_widget


def test_mammography_ui_has_mg_specific_controls():
    imaging_tab = (ROOT / "modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py").read_text(encoding="utf-8")
    vtk_widget = (ROOT / "modules/ai_imaging/ai_module_ui/overrides/vtk_widget.py").read_text(encoding="utf-8")
    viewer_2d = (ROOT / "modules/viewer/advanced/viewer_2d.py").read_text(encoding="utf-8")
    polygon_style = (ROOT / "modules/viewer/interactor_styles/segmentation_styles/polygon_interactorstyle.py").read_text(encoding="utf-8")

    for token in (
        "MGFindingEditorDialog",
        "confirm_finding_btn",
        "reject_finding_btn",
        "edit_finding_btn",
        "new_finding_btn",
        "_open_mg_finding_editor",
        "_on_mg_new_polygon_finished",
        "_bbox_from_polygon_ijk",
        "style.on_polygon_finished",
    ):
        assert token in imaging_tab

    for token in (
        "display_name",
        "source_row_key",
        "source_box_index",
        "finding_uid",
    ):
        assert token in vtk_widget
        assert token in viewer_2d

    assert "self.on_polygon_finished = on_polygon_finished" in polygon_style
    assert "callback(pts_world_out, ijk_list_3d, obj)" in polygon_style


def test_mammography_csv_contract_marks_server_fields_correctly():
    schema = _load_module(
        "modules/ai_imaging/ai_module_ui/mg_csv_schema.py",
        "mg_csv_schema_for_contract_test",
    )

    contract = schema.infer_mg_csv_contract(
        detection_columns=["dicom_full_path", "box", "scores", "coord_space"],
        classification_columns=["dicom_full_path", "xmin", "ymin", "xmax", "ymax", "labels_pred"],
    )

    mandatory = {spec.name for spec in contract["mandatory"]}
    automatic = {spec.name for spec in contract["automatic"]}
    optional = {spec.name for spec in contract["optional"]}

    assert {"dicom_full_path", "box", "xmin", "ymin", "xmax", "ymax", "labels_pred"} <= mandatory
    assert {"box", "xmin", "ymin", "xmax", "ymax", "coord_space"} & (mandatory | automatic)
    assert {"laterality", "view", "birads_category"} <= optional
    assert schema.normalize_mg_action("Reject") == "rejected"
