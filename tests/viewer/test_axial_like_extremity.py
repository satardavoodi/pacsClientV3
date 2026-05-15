"""
tests/viewer/test_axial_like_extremity.py
==========================================
Unit tests for the AXIAL_LIKE_EXTREMITY classification added to
advanced_geometry_contract.py (v3.0.x).

Clinical motivation:
  Shoulder MRI (oblique-axial acquisitions) and wrist MRI have IOP vectors
  whose slice normal is oblique (dominance < 0.9), so _plane_from_normal
  returns "OBLIQUE".  Without the AXIAL_LIKE_EXTREMITY rule these series
  were displayed in Anterior→Posterior or Right→Left order instead of the
  anatomically correct Proximal→Distal.

Run:
    .venv\\Scripts\\python.exe -m pytest tests/viewer/test_axial_like_extremity.py -v
"""

import sys
import os
import math

_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pytest
from pathlib import Path
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from PacsClient.pacs.patient_tab.utils.advanced_geometry_contract import (
    build_series_geometry_index,
    _plane_from_normal,
    _normalize_body_part_canonical,
    _normalize_laterality,
    _matches_axial_keywords,
    _check_axial_like_extremity,
    _resolve_display_labels,
)

import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm_iop(row, col):
    """Return normalized row+col IOP list, 6 floats."""
    r = np.asarray(row, dtype=float)
    c = np.asarray(col, dtype=float)
    r = r / np.linalg.norm(r)
    c = c / np.linalg.norm(c)
    return list(r) + list(c)


def _write_test_dicom_ext(
    path: Path,
    *,
    study_uid: str,
    series_uid: str,
    series_number: str,
    sop_uid: str,
    iop,
    ipp,
    modality: str = "MR",
    body_part: str = "SHOULDER",
    laterality: str = "R",
    patient_position: str = "HFS",
    instance_number: int = 1,
    series_description: str = "",
    protocol_name: str = "",
):
    """Like test_canonical_series_sort._write_test_dicom but also sets
    SeriesDescription and ProtocolName."""
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = generate_uid()
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.SOPInstanceUID = sop_uid
    ds.SeriesNumber = str(series_number)
    ds.InstanceNumber = int(instance_number)
    ds.Modality = modality
    ds.BodyPartExamined = body_part
    if laterality:
        ds.Laterality = laterality
    ds.PatientPosition = patient_position
    ds.Rows = 16
    ds.Columns = 16
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 1
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelSpacing = [1.0, 1.0]
    ds.SliceThickness = 1.0
    ds.SpacingBetweenSlices = 1.0
    ds.ImageOrientationPatient = [float(v) for v in iop]
    ds.ImagePositionPatient = [float(v) for v in ipp]
    ds.WindowWidth = 400
    ds.WindowCenter = 40
    ds.PixelData = b"\0\0" * ds.Rows * ds.Columns
    if series_description:
        ds.SeriesDescription = series_description
    if protocol_name:
        ds.ProtocolName = protocol_name
    ds.save_as(str(path), write_like_original=False)
    return str(path)


def _build_oblique_y_dominant_series(
    tmp_path: Path,
    *,
    body_part: str,
    laterality: str = "R",
    series_description: str = "",
    protocol_name: str = "",
    n_slices: int = 5,
):
    """Build an OBLIQUE Y-dominant series (like clinical SHOULDER oblique-axial).

    IOP: row=[1,0,0], col=[0,0.6,0.8]  → normal = [0, -0.8, 0.6]
         abs_vec = [0, 0.8, 0.6]       → axis=1 (Y), dominance=0.8 < 0.9  → OBLIQUE

    Slices positioned along z-axis (inferior→superior) so Z-based reversal
    puts the first display slice at the proximal/superior end.
    """
    study_uid = generate_uid()
    series_uid = generate_uid()
    iop = [1.0, 0.0, 0.0, 0.0, 0.6, 0.8]  # row, col (not orthogonal but usable for test)
    paths = []
    for i in range(n_slices):
        sop = generate_uid()
        z = float(50 + i * 10)          # z=50,60,70,80,90 (inferior→superior)
        p = tmp_path / f"oblique_{body_part}_{i+1:03d}.dcm"
        _write_test_dicom_ext(
            p,
            study_uid=study_uid,
            series_uid=series_uid,
            series_number="4",
            sop_uid=sop,
            iop=iop,
            ipp=[0.0, 0.0, z],
            body_part=body_part,
            laterality=laterality,
            series_description=series_description,
            protocol_name=protocol_name,
            instance_number=i + 1,
        )
        paths.append(str(p))
    return paths, study_uid, series_uid


def _build_true_axial_extremity_series(
    tmp_path: Path,
    *,
    body_part: str = "KNEE",
    n_slices: int = 5,
):
    """Build a true AXIAL (Z-dominant) extremity series.

    IOP: row=[1,0,0], col=[0,1,0] → normal=[0,0,1] → AXIAL (dominance=1.0)
    """
    study_uid = generate_uid()
    series_uid = generate_uid()
    iop = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    paths = []
    for i in range(n_slices):
        sop = generate_uid()
        z = float(10 + i * 5)
        p = tmp_path / f"axial_{body_part}_{i+1:03d}.dcm"
        _write_test_dicom_ext(
            p,
            study_uid=study_uid,
            series_uid=series_uid,
            series_number="3",
            sop_uid=sop,
            iop=iop,
            ipp=[0.0, 0.0, z],
            body_part=body_part,
            instance_number=i + 1,
        )
        paths.append(str(p))
    return paths, study_uid, series_uid


def _build_coronal_extremity_series(tmp_path: Path, *, body_part: str = "KNEE"):
    """True CORONAL: row=[1,0,0], col=[0,0,1] → normal=[0,-1,0] → CORONAL."""
    study_uid = generate_uid()
    series_uid = generate_uid()
    # row=[1,0,0], col=[0,0,1] → normal = cross([1,0,0],[0,0,1]) = [0,-1,0] → CORONAL
    iop = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
    paths = []
    for i in range(4):
        sop = generate_uid()
        p = tmp_path / f"coronal_{body_part}_{i+1:03d}.dcm"
        _write_test_dicom_ext(
            p,
            study_uid=study_uid,
            series_uid=series_uid,
            series_number="2",
            sop_uid=sop,
            iop=iop,
            ipp=[0.0, float(i * 5), 0.0],
            body_part=body_part,
            instance_number=i + 1,
        )
        paths.append(str(p))
    return paths, study_uid, series_uid


def _build_sagittal_extremity_series(tmp_path: Path, *, body_part: str = "KNEE"):
    """True SAGITTAL: row=[0,1,0], col=[0,0,1] → normal=[1,0,0] → SAGITTAL."""
    study_uid = generate_uid()
    series_uid = generate_uid()
    iop = [0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    paths = []
    for i in range(4):
        sop = generate_uid()
        p = tmp_path / f"sagittal_{body_part}_{i+1:03d}.dcm"
        _write_test_dicom_ext(
            p,
            study_uid=study_uid,
            series_uid=series_uid,
            series_number="1",
            sop_uid=sop,
            iop=iop,
            ipp=[float(i * 5), 0.0, 0.0],
            body_part=body_part,
            instance_number=i + 1,
        )
        paths.append(str(p))
    return paths, study_uid, series_uid


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


class TestMatchesAxialKeywords:
    def test_ax_token_matches(self):
        assert _matches_axial_keywords("T2_AX") is True

    def test_axial_full_word_matches(self):
        assert _matches_axial_keywords("Axial") is True

    def test_tra_matches(self):
        assert _matches_axial_keywords("TRA") is True

    def test_transverse_matches(self):
        assert _matches_axial_keywords("TRANSVERSE") is True

    def test_trans_matches(self):
        assert _matches_axial_keywords("TRANS_SHOULDER") is True

    def test_compound_tse_ax_matches(self):
        assert _matches_axial_keywords("TSE_AX") is True

    def test_pd_ax_matches(self):
        assert _matches_axial_keywords("PD_AX_SHOULDER") is True

    def test_sagittal_no_match(self):
        assert _matches_axial_keywords("SAG") is False

    def test_coronal_no_match(self):
        assert _matches_axial_keywords("COR") is False

    def test_empty_no_match(self):
        assert _matches_axial_keywords("") is False

    def test_none_like_empty_no_match(self):
        assert _matches_axial_keywords(None) is False  # type: ignore[arg-type]


class TestNormalizeBodyPartCanonical:
    def test_shoulder_right(self):
        assert _normalize_body_part_canonical("SHOULDER RIGHT") == "SHOULDER"

    def test_wrist_left(self):
        assert _normalize_body_part_canonical("WRIST_LEFT") == "WRIST"

    def test_knee_bilateral(self):
        assert _normalize_body_part_canonical("KNEE BILATERAL") == "KNEE"

    def test_unknown_returns_stripped_upper(self):
        result = _normalize_body_part_canonical("BRAIN")
        assert "BRAIN" in result

    def test_empty_returns_unknown(self):
        assert _normalize_body_part_canonical("") == "UNKNOWN"


class TestNormalizeLaterality:
    def test_right_variants(self):
        for v in ("R", "RIGHT", "RT"):
            assert _normalize_laterality(v) == "R"

    def test_left_variants(self):
        for v in ("L", "LEFT", "LT"):
            assert _normalize_laterality(v) == "L"

    def test_bilateral_variants(self):
        for v in ("B", "BI", "BILATERAL", "BL"):
            assert _normalize_laterality(v) == "B"

    def test_empty(self):
        assert _normalize_laterality("") == ""


class TestCheckAxialLikeExtremity:
    """Unit tests for _check_axial_like_extremity."""

    def test_criterion_a_series_description_keyword(self):
        is_axial, reason, confidence = _check_axial_like_extremity(
            plane="OBLIQUE",
            body_part="SHOULDER",
            normalized_body_part="SHOULDER",
            dominant_axis=1,
            dominance_value=0.8,
            series_description="T2_AX",
            protocol_name="",
        )
        assert is_axial is True
        assert "series_description" in reason
        assert confidence == "HIGH"

    def test_criterion_a_protocol_name_keyword(self):
        is_axial, reason, confidence = _check_axial_like_extremity(
            plane="OBLIQUE",
            body_part="WRIST",
            normalized_body_part="WRIST",
            dominant_axis=0,
            dominance_value=0.78,
            series_description="",
            protocol_name="TRA",
        )
        assert is_axial is True
        assert "protocol_name" in reason
        assert confidence == "HIGH"

    def test_criterion_b_true_axial_plane(self):
        is_axial, reason, confidence = _check_axial_like_extremity(
            plane="AXIAL",
            body_part="KNEE",
            normalized_body_part="KNEE",
            dominant_axis=2,
            dominance_value=1.0,
            series_description="",
            protocol_name="",
        )
        assert is_axial is True
        assert reason == "true_axial_plane"
        assert confidence == "HIGH"

    def test_criterion_c_oblique_shoulder_heuristic(self):
        is_axial, reason, confidence = _check_axial_like_extremity(
            plane="OBLIQUE",
            body_part="SHOULDER",
            normalized_body_part="SHOULDER",
            dominant_axis=1,
            dominance_value=0.79,
            series_description="",
            protocol_name="",
        )
        assert is_axial is True
        assert reason == "oblique_extremity_heuristic"
        assert confidence == "MEDIUM"

    def test_non_extremity_not_axial_like(self):
        is_axial, reason, confidence = _check_axial_like_extremity(
            plane="OBLIQUE",
            body_part="ABDOMEN",
            normalized_body_part="ABDOMEN",
            dominant_axis=1,
            dominance_value=0.8,
            series_description="AX",
            protocol_name="",
        )
        assert is_axial is False

    def test_coronal_knee_no_keywords_not_axial_like(self):
        """CORONAL KNEE without axial keywords → NOT axial-like."""
        is_axial, reason, _ = _check_axial_like_extremity(
            plane="CORONAL",
            body_part="KNEE",
            normalized_body_part="KNEE",
            dominant_axis=1,
            dominance_value=0.99,
            series_description="",
            protocol_name="",
        )
        assert is_axial is False

    def test_sagittal_knee_no_keywords_not_axial_like(self):
        is_axial, _, _ = _check_axial_like_extremity(
            plane="SAGITTAL",
            body_part="KNEE",
            normalized_body_part="KNEE",
            dominant_axis=0,
            dominance_value=0.99,
            series_description="",
            protocol_name="",
        )
        assert is_axial is False


class TestResolveLabelSignature:
    """Smoke test for the 6-tuple return signature of _resolve_display_labels."""

    def test_returns_six_tuple(self):
        result = _resolve_display_labels(
            plane="AXIAL",
            body_part="ABDOMEN",
            patient_position="HFS",
            geometry_first_label="Inferior",
            geometry_last_label="Superior",
            dominant_axis=2,
            dominance_value=1.0,
            series_description="",
            protocol_name="",
        )
        assert len(result) == 6

    def test_axial_non_extremity_convention(self):
        first_lbl, last_lbl, sort_tgt, conv, unresolved, axial_like = _resolve_display_labels(
            plane="AXIAL",
            body_part="ABDOMEN",
            patient_position="HFS",
            geometry_first_label="Inferior",
            geometry_last_label="Superior",
            dominant_axis=2,
            dominance_value=1.0,
            series_description="",
            protocol_name="",
        )
        assert conv == "AXIAL_SUPERIOR_TO_INFERIOR"
        assert axial_like[0] is False

    def test_oblique_shoulder_no_keywords_axial_like_extremity(self):
        first_lbl, last_lbl, sort_tgt, conv, unresolved, axial_like = _resolve_display_labels(
            plane="OBLIQUE",
            body_part="SHOULDER",
            patient_position="HFS",
            geometry_first_label="Anterior",
            geometry_last_label="Posterior",
            dominant_axis=1,
            dominance_value=0.8,
            series_description="",
            protocol_name="",
        )
        assert conv == "AXIAL_LIKE_EXTREMITY"
        assert first_lbl == "Proximal"
        assert last_lbl == "Distal"
        assert axial_like[0] is True
        assert axial_like[2] == "MEDIUM"

    def test_oblique_shoulder_keyword_high_confidence(self):
        first_lbl, last_lbl, sort_tgt, conv, unresolved, axial_like = _resolve_display_labels(
            plane="OBLIQUE",
            body_part="SHOULDER",
            patient_position="HFS",
            geometry_first_label="Anterior",
            geometry_last_label="Posterior",
            dominant_axis=1,
            dominance_value=0.8,
            series_description="T2_AX",
            protocol_name="",
        )
        assert conv == "AXIAL_LIKE_EXTREMITY"
        assert axial_like[2] == "HIGH"


# ---------------------------------------------------------------------------
# Integration tests with real DICOM files
# ---------------------------------------------------------------------------


class TestBuildSeriesGeometryIndexAxialLike:
    """Full integration: build_series_geometry_index on clinical-like DICOM sets."""

    def test_shoulder_oblique_keyword_axial_description(self, tmp_path):
        """Criterion A: SHOULDER OBLIQUE + SeriesDescription contains 'AX' token.

        Expected: display_convention='AXIAL_LIKE_EXTREMITY',
                  first_display_label='Proximal', last_display_label='Distal'.
        """
        paths, study_uid, series_uid = _build_oblique_y_dominant_series(
            tmp_path,
            body_part="SHOULDER",
            laterality="R",
            series_description="T2_AX",
        )
        idx, error_flag = build_series_geometry_index(
            paths,
            patient_code="test_patient",
            study_uid_hint=study_uid,
            series_uid_hint=series_uid,
        )
        assert error_flag is False
        assert idx.display_convention == "AXIAL_LIKE_EXTREMITY", (
            f"Expected AXIAL_LIKE_EXTREMITY, got {idx.display_convention}"
        )
        assert idx.first_display_label == "Proximal"
        assert idx.last_display_label == "Distal"

    def test_wrist_oblique_keyword_tra_protocol(self, tmp_path):
        """Criterion A: WRIST OBLIQUE + ProtocolName contains 'TRA'."""
        paths, study_uid, series_uid = _build_oblique_y_dominant_series(
            tmp_path,
            body_part="WRIST",
            laterality="L",
            protocol_name="TRA",
        )
        idx, _ = build_series_geometry_index(
            paths, patient_code="test_patient",
            study_uid_hint=study_uid, series_uid_hint=series_uid,
        )
        assert idx.display_convention == "AXIAL_LIKE_EXTREMITY"
        assert idx.first_display_label == "Proximal"
        assert idx.last_display_label == "Distal"

    def test_knee_true_axial_criterion_b(self, tmp_path):
        """Criterion B: KNEE + true AXIAL plane (Z-dominant ≥ 0.9)."""
        paths, study_uid, series_uid = _build_true_axial_extremity_series(
            tmp_path, body_part="KNEE"
        )
        idx, _ = build_series_geometry_index(
            paths, patient_code="test_patient",
            study_uid_hint=study_uid, series_uid_hint=series_uid,
        )
        assert idx.display_convention == "AXIAL_LIKE_EXTREMITY"
        assert idx.first_display_label == "Proximal"
        assert idx.last_display_label == "Distal"

    def test_knee_coronal_no_keywords_stays_coronal(self, tmp_path):
        """KNEE CORONAL without axial keywords must NOT become AXIAL_LIKE_EXTREMITY."""
        paths, study_uid, series_uid = _build_coronal_extremity_series(
            tmp_path, body_part="KNEE"
        )
        idx, _ = build_series_geometry_index(
            paths, patient_code="test_patient",
            study_uid_hint=study_uid, series_uid_hint=series_uid,
        )
        assert idx.display_convention == "CORONAL_ANTERIOR_TO_POSTERIOR"
        assert idx.first_display_label != "Proximal"

    def test_knee_sagittal_no_keywords_stays_sagittal(self, tmp_path):
        """KNEE SAGITTAL without axial keywords must NOT become AXIAL_LIKE_EXTREMITY."""
        paths, study_uid, series_uid = _build_sagittal_extremity_series(
            tmp_path, body_part="KNEE"
        )
        idx, _ = build_series_geometry_index(
            paths, patient_code="test_patient",
            study_uid_hint=study_uid, series_uid_hint=series_uid,
        )
        assert idx.display_convention == "SAGITTAL_RIGHT_TO_LEFT"
        assert idx.first_display_label != "Proximal"

    def test_abdomen_oblique_not_axial_like(self, tmp_path):
        """Non-extremity body part (ABDOMEN) with 'AX' keyword → NOT AXIAL_LIKE_EXTREMITY.

        Keywords only trigger AXIAL_LIKE if body part is an extremity/joint.
        """
        paths, study_uid, series_uid = _build_oblique_y_dominant_series(
            tmp_path,
            body_part="ABDOMEN",
            laterality="",
            series_description="T2_AX",
        )
        idx, _ = build_series_geometry_index(
            paths, patient_code="test_patient",
            study_uid_hint=study_uid, series_uid_hint=series_uid,
        )
        assert idx.display_convention != "AXIAL_LIKE_EXTREMITY"
        assert idx.first_display_label not in ("Proximal", "Distal")

    def test_shoulder_oblique_criterion_c_heuristic_no_keywords(self, tmp_path):
        """Criterion C: SHOULDER OBLIQUE, no keywords → AXIAL_LIKE via heuristic (MEDIUM)."""
        paths, study_uid, series_uid = _build_oblique_y_dominant_series(
            tmp_path,
            body_part="SHOULDER",
            laterality="R",
            series_description="",   # no keywords
            protocol_name="",
        )
        idx, _ = build_series_geometry_index(
            paths, patient_code="test_patient",
            study_uid_hint=study_uid, series_uid_hint=series_uid,
        )
        assert idx.display_convention == "AXIAL_LIKE_EXTREMITY"
        assert idx.first_display_label == "Proximal"
        assert idx.last_display_label == "Distal"

    def test_display_order_hash_stable_on_identical_files(self, tmp_path):
        """Building the same DICOM set twice must produce identical hashes."""
        paths, study_uid, series_uid = _build_oblique_y_dominant_series(
            tmp_path,
            body_part="SHOULDER",
            series_description="T2_AX",
        )
        idx1, _ = build_series_geometry_index(
            paths, patient_code="p1",
            study_uid_hint=study_uid, series_uid_hint=series_uid,
        )
        idx2, _ = build_series_geometry_index(
            paths, patient_code="p1",
            study_uid_hint=study_uid, series_uid_hint=series_uid,
        )
        assert idx1.display_order_hash == idx2.display_order_hash
        assert idx1.geometry_order_hash == idx2.geometry_order_hash

    def test_display_instances_metadata_paths_match_hash(self, tmp_path):
        """display_order_hash must be consistent with display_instances_order paths."""
        from PacsClient.pacs.patient_tab.utils.advanced_geometry_contract import _hash_paths
        paths, study_uid, series_uid = _build_oblique_y_dominant_series(
            tmp_path,
            body_part="SHOULDER",
            series_description="AX",
        )
        idx, _ = build_series_geometry_index(
            paths, patient_code="p",
            study_uid_hint=study_uid, series_uid_hint=series_uid,
        )
        expected_hash = _hash_paths([inst.instance_path for inst in idx.display_instances_order])
        assert idx.display_order_hash == expected_hash

    def test_sorted_instances_geometry_order_unchanged(self, tmp_path):
        """sorted_instances_geometry_order must never change (canonical sort invariant).

        For AXIAL_LIKE_EXTREMITY, only display_instances_order is reordered.
        """
        paths, study_uid, series_uid = _build_oblique_y_dominant_series(
            tmp_path,
            body_part="SHOULDER",
            series_description="T2_AX",
        )
        idx, _ = build_series_geometry_index(
            paths, patient_code="p",
            study_uid_hint=study_uid, series_uid_hint=series_uid,
        )
        # Geometry order is sorted by slice_pos ascending (smallest = most distal).
        geo_z_values = [
            inst.image_position_patient[2]
            for inst in idx.sorted_instances_geometry_order
            if inst.image_position_patient
        ]
        assert geo_z_values == sorted(geo_z_values), (
            "sorted_instances_geometry_order Z-values must be ascending (geometry invariant)"
        )
        # Display order for proximal-first should be descending Z for this test series.
        disp_z_values = [
            inst.image_position_patient[2]
            for inst in idx.display_instances_order
            if inst.image_position_patient
        ]
        assert disp_z_values == sorted(disp_z_values, reverse=True), (
            "display_instances_order Z-values should be descending (proximal=superior first)"
        )

    def test_plane_from_normal_returns_three_tuple(self):
        """_plane_from_normal must return a 3-tuple (plane, axis, dominance)."""
        result = _plane_from_normal([1.0, 0.0, 0.0])
        assert len(result) == 3
        plane, axis, dominance = result
        assert plane == "SAGITTAL"
        assert axis == 0
        assert math.isclose(dominance, 1.0, abs_tol=1e-6)

    def test_plane_from_normal_oblique_returns_dominance(self):
        # Normal [0, -0.8, 0.6] is OBLIQUE Y-dominant with dominance 0.8
        normal = [0.0, -0.8, 0.6]
        plane, axis, dominance = _plane_from_normal(normal)
        assert plane == "OBLIQUE"
        assert axis == 1  # Y-dominant
        assert math.isclose(dominance, 0.8, abs_tol=0.01)
