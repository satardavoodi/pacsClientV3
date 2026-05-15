"""
tests/viewer/test_canonical_series_sort.py
==========================================
Unit tests for canonical_sort_instances() in image_io.py.

Root-cause context (2026-05-13 forensic):
  - First-open during active download used natsorted filename order.
  - Reopen from DB used ORDER BY instance_number (DICOM header value).
  - These two ordering authorities can be opposite or inconsistent.
  - The canonical sort function must produce identical order from both
    input representations.

Run:
    .venv\\Scripts\\python.exe -m pytest tests/viewer/test_canonical_series_sort.py -v
"""

import sys
import os

# Ensure project root is on sys.path regardless of how pytest is invoked.
_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pytest
import copy
import math
from pathlib import Path

from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

# ---------------------------------------------------------------------------
# Import the function under test.
# ---------------------------------------------------------------------------
from PacsClient.pacs.patient_tab.utils.image_io import (
    canonical_sort_instances,
    apply_advanced_display_convention,
    _compute_path_list_hash,
    _anatomical_label_from_ipp_delta,
    _plane_from_normal,
)
from PacsClient.pacs.patient_tab.utils.advanced_geometry_contract import (
    assert_advanced_order_contract,
    build_series_geometry_index,
    stamp_metadata_with_geometry_index,
)


# ---------------------------------------------------------------------------
# Helper: build a mock instance dict.
# ---------------------------------------------------------------------------
def _make_inst(
    filename: str,
    instance_number: int,
    ipp_z: float,           # z-component of IPP; IOP is axial (row=X, col=Y)
    sop_uid: str = "",
    iop=None,
):
    """Build a minimal instance dict as produced by both load paths."""
    if iop is None:
        # Standard axial IOP: row=X+, col=Y+
        iop = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    if not sop_uid:
        sop_uid = f"1.2.3.{abs(instance_number)}"
    return {
        "instance_path": f"/study/series/{filename}",
        "instance_number": instance_number,
        "sop_uid": sop_uid,
        "image_orientation_patient": list(iop),
        "image_position_patient": [0.0, 0.0, float(ipp_z)],
    }


def _write_test_dicom(
    path: Path,
    *,
    study_uid: str,
    series_uid: str,
    series_number: str,
    sop_uid: str,
    iop,
    ipp,
    modality: str = "CT",
    body_part: str = "ABDOMEN",
    laterality: str = "",
    patient_position: str = "HFS",
    instance_number: int = 1,
):
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
    ds.PixelData = (b"\0\0" * ds.Rows * ds.Columns)
    ds.save_as(str(path), write_like_original=False)
    return str(path)


# ---------------------------------------------------------------------------
# Test 1: Empty / single-item edge cases
# ---------------------------------------------------------------------------
class TestEdgeCases:
    def test_empty_list(self):
        result, method = canonical_sort_instances([])
        assert result == []
        assert method == "SINGLE_OR_EMPTY"

    def test_single_instance(self):
        inst = _make_inst("Instance_0001.dcm", 1, 0.0)
        result, method = canonical_sort_instances([inst])
        assert result == [inst]
        assert method == "SINGLE_OR_EMPTY"

    def test_does_not_mutate_input(self):
        insts = [
            _make_inst("Instance_0001.dcm", 3, 30.0),
            _make_inst("Instance_0002.dcm", 2, 20.0),
            _make_inst("Instance_0003.dcm", 1, 10.0),
        ]
        original_ids = [id(x) for x in insts]
        canonical_sort_instances(insts)
        # Input list must be unchanged
        assert [id(x) for x in insts] == original_ids
        assert insts[0]["instance_number"] == 3  # original order preserved


# ---------------------------------------------------------------------------
# Test 2: Geometry sort (IPP_IOP_GEOMETRY)
# ---------------------------------------------------------------------------
class TestGeometrySort:
    def test_standard_axial_iop_sorts_inferior_first(self):
        """Standard axial IOP [row=X, col=Y]:
        cross(row,col) = [0,0,+1]  →  ascending z  →  Inferior first.
        """
        std_axial_iop = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        insts = [
            _make_inst("Instance_0001.dcm", 1, 10.0, iop=std_axial_iop),
            _make_inst("Instance_0002.dcm", 2, 20.0, iop=std_axial_iop),
            _make_inst("Instance_0003.dcm", 3, 30.0, iop=std_axial_iop),
        ]

        result, method = canonical_sort_instances(insts)
        assert method == "IPP_IOP_GEOMETRY"

        z_vals = [inst["image_position_patient"][2] for inst in result]
        assert z_vals == [10.0, 20.0, 30.0], (
            f"Expected Inferior-first (ascending z) with cross(row,col); got {z_vals}"
        )
        delta = [result[-1]["image_position_patient"][i] - result[0]["image_position_patient"][i] for i in range(3)]
        # last – first = [0,0,+20]  → Superior direction (going toward Superior)
        assert _anatomical_label_from_ipp_delta(delta) == "Superior"
        assert _anatomical_label_from_ipp_delta([-v for v in delta]) == "Inferior"

    def test_flipped_axial_iop_sorts_superior_first(self):
        """Flipped axial IOP [row=Y, col=X]:
        cross(row,col) = [0,0,-1]  →  descending z  →  Superior first.
        """
        flipped_axial_iop = [0.0, 1.0, 0.0, 1.0, 0.0, 0.0]
        insts = [
            _make_inst("Instance_0001.dcm", 1, 10.0, iop=flipped_axial_iop),
            _make_inst("Instance_0002.dcm", 2, 20.0, iop=flipped_axial_iop),
            _make_inst("Instance_0003.dcm", 3, 30.0, iop=flipped_axial_iop),
        ]

        result, method = canonical_sort_instances(insts)
        assert method == "IPP_IOP_GEOMETRY"
        z_vals = [inst["image_position_patient"][2] for inst in result]
        assert z_vals == [30.0, 20.0, 10.0], (
            f"Expected Superior-first (descending z) with cross(row,col) on flipped IOP; got {z_vals}"
        )

    def test_reversed_instance_number_correct_ipp(self):
        """
        Classic divergence scenario:
          filenames:       Instance_0001, 0002, 0003
          InstanceNumber:  3, 2, 1  (reversed in DICOM header)
          IPP z-values:    30, 20, 10  (also reversed, matching InstanceNumber)

        With cross(row,col) = [0,0,+1] for standard axial IOP, ascending z gives
        Inferior-first: expected z = [10, 20, 30].
        """
        insts = [
            _make_inst("Instance_0001.dcm", 3, 30.0),
            _make_inst("Instance_0002.dcm", 2, 20.0),
            _make_inst("Instance_0003.dcm", 1, 10.0),
        ]
        result, method = canonical_sort_instances(insts)
        assert method == "IPP_IOP_GEOMETRY"
        z_vals = [inst["image_position_patient"][2] for inst in result]
        assert z_vals == [10.0, 20.0, 30.0], (
            f"Expected Inferior-first (ascending z) with cross(row,col); got {z_vals}"
        )
        assert result[0]["image_position_patient"][2] == 10.0
        assert result[-1]["image_position_patient"][2] == 30.0

    def test_already_sorted_in_viewer_convention_unchanged(self):
        """If already in Inferior-first order (cross(row,col) convention), keep it."""
        # Viewer convention after revert: ascending z = Inferior first
        insts = [
            _make_inst("Instance_0001.dcm", 1, 10.0),
            _make_inst("Instance_0002.dcm", 2, 20.0),
            _make_inst("Instance_0003.dcm", 3, 30.0),
        ]
        result, method = canonical_sort_instances(insts)
        assert method == "IPP_IOP_GEOMETRY"
        z_vals = [inst["image_position_patient"][2] for inst in result]
        assert z_vals == [10.0, 20.0, 30.0]

    def test_filesystem_path_and_db_path_produce_identical_order(self):
        """
        Simulate the two divergent load paths:
          - DB path returns instances sorted by instance_number (3, 2, 1)
          - Filesystem path returns instances in natsorted filename order (1, 2, 3)
            where filenames encode the *network* sequence number, NOT anatomical
        Both must produce the same canonical IPP-geometry order.
        """
        # Anatomical order (IPP z ascending): 10, 20, 30
        # DICOM InstanceNumber:               3, 2, 1  (reversed vs anatomy)
        # natsorted filename order:           0001, 0002, 0003 = network seq = InstanceNum 3,2,1
        # So filename 0001 → InstanceNumber 3 → IPP z=30 (deepest anatomically)
        #    filename 0002 → InstanceNumber 2 → IPP z=20
        #    filename 0003 → InstanceNumber 1 → IPP z=10 (shallowest)

        # --- DB path: ordered by InstanceNumber (3, 2, 1) ---
        db_instances = [
            _make_inst("Instance_0001.dcm", 3, 30.0),  # InstanceNumber=3
            _make_inst("Instance_0002.dcm", 2, 20.0),  # InstanceNumber=2
            _make_inst("Instance_0003.dcm", 1, 10.0),  # InstanceNumber=1
        ]

        # --- Filesystem path: natsorted filename order (0001, 0002, 0003) ---
        fs_instances = [
            _make_inst("Instance_0001.dcm", 3, 30.0),
            _make_inst("Instance_0002.dcm", 2, 20.0),
            _make_inst("Instance_0003.dcm", 1, 10.0),
        ]

        db_sorted, db_method = canonical_sort_instances(db_instances)
        fs_sorted, fs_method = canonical_sort_instances(fs_instances)

        assert db_method == "IPP_IOP_GEOMETRY", f"DB method: {db_method}"
        assert fs_method == "IPP_IOP_GEOMETRY", f"FS method: {fs_method}"

        db_z = [inst["image_position_patient"][2] for inst in db_sorted]
        fs_z = [inst["image_position_patient"][2] for inst in fs_sorted]
        assert db_z == fs_z, f"DB path {db_z} != FS path {fs_z}"
        # cross(row,col) = [0,0,+1] for standard axial → ascending z = Inferior first
        assert db_z == [10.0, 20.0, 30.0], (
            f"Expected Inferior-first (ascending z); got {db_z}"
        )

    def test_reference_metadata_matches_pixel_order(self):
        """
        After canonical sort, metadata['instances'][i].instance_path must equal
        the i-th entry in the file list used for ITK (the canonical dicom_files).
        """
        insts = [
            _make_inst("Instance_0001.dcm", 5, 50.0),
            _make_inst("Instance_0002.dcm", 3, 30.0),
            _make_inst("Instance_0003.dcm", 1, 10.0),
        ]
        sorted_insts, _ = canonical_sort_instances(insts)
        canonical_files = [inst["instance_path"] for inst in sorted_insts]
        # Pixel volume order must match metadata order
        for i, (inst, fpath) in enumerate(zip(sorted_insts, canonical_files)):
            assert inst["instance_path"] == fpath, (
                f"Slice {i}: metadata path {inst['instance_path']!r} "
                f"!= file list path {fpath!r}"
            )


# ---------------------------------------------------------------------------
# Test 3: Tie-breaker — duplicate slice positions
# ---------------------------------------------------------------------------
class TestTieBreakers:
    def test_duplicate_ipp_uses_instance_number(self):
        """Two slices at the same IPP z — tie broken by InstanceNumber."""
        insts = [
            _make_inst("Instance_0002.dcm", 2, 10.0, sop_uid="1.2.3.2"),
            _make_inst("Instance_0001.dcm", 1, 10.0, sop_uid="1.2.3.1"),
        ]
        result, method = canonical_sort_instances(insts)
        assert method == "IPP_IOP_GEOMETRY"
        assert result[0]["instance_number"] == 1
        assert result[1]["instance_number"] == 2

    def test_duplicate_ipp_and_instance_number_uses_sop_uid(self):
        """Tie broken by SOPInstanceUID when InstanceNumber is also the same."""
        insts = [
            _make_inst("Instance_0002.dcm", 1, 10.0, sop_uid="1.2.3.B"),
            _make_inst("Instance_0001.dcm", 1, 10.0, sop_uid="1.2.3.A"),
        ]
        result, method = canonical_sort_instances(insts)
        assert method == "IPP_IOP_GEOMETRY"
        assert result[0]["sop_uid"] == "1.2.3.A"
        assert result[1]["sop_uid"] == "1.2.3.B"


# ---------------------------------------------------------------------------
# Test 4: Fallback — missing IPP/IOP
# ---------------------------------------------------------------------------
class TestFallback:
    def test_instance_number_fallback_when_no_geometry(self):
        """When IPP/IOP are absent, fall back to InstanceNumber sort."""
        insts = [
            {"instance_path": "/s/Instance_0003.dcm", "instance_number": 3,
             "sop_uid": "1.1.3", "image_orientation_patient": None,
             "image_position_patient": None},
            {"instance_path": "/s/Instance_0001.dcm", "instance_number": 1,
             "sop_uid": "1.1.1", "image_orientation_patient": None,
             "image_position_patient": None},
            {"instance_path": "/s/Instance_0002.dcm", "instance_number": 2,
             "sop_uid": "1.1.2", "image_orientation_patient": None,
             "image_position_patient": None},
        ]
        result, method = canonical_sort_instances(insts)
        assert method == "INSTANCE_NUMBER_FALLBACK"
        nums = [inst["instance_number"] for inst in result]
        assert nums == [1, 2, 3]

    def test_partial_geometry_falls_back(self):
        """Only 1 out of 5 instances has valid IPP/IOP → below 50% → fallback."""
        insts = [
            _make_inst("Instance_0005.dcm", 5, 50.0),  # has geometry
        ] + [
            {
                "instance_path": f"/s/Instance_000{i}.dcm",
                "instance_number": i,
                "sop_uid": f"1.1.{i}",
                "image_orientation_patient": None,
                "image_position_patient": None,
            }
            for i in [4, 3, 2, 1]
        ]
        result, method = canonical_sort_instances(insts)
        assert method in ("INSTANCE_NUMBER_FALLBACK", "FILE_PATH_FALLBACK")
        nums = [inst["instance_number"] for inst in result]
        assert nums == sorted(nums)

    def test_file_path_fallback_when_no_instance_number(self):
        """No InstanceNumber and no IPP/IOP → FILE_PATH_FALLBACK."""
        insts = [
            {"instance_path": "/s/Instance_0003.dcm", "instance_number": None,
             "sop_uid": "1.1.3", "image_orientation_patient": None,
             "image_position_patient": None},
            {"instance_path": "/s/Instance_0001.dcm", "instance_number": None,
             "sop_uid": "1.1.1", "image_orientation_patient": None,
             "image_position_patient": None},
            {"instance_path": "/s/Instance_0002.dcm", "instance_number": None,
             "sop_uid": "1.1.2", "image_orientation_patient": None,
             "image_position_patient": None},
        ]
        result, method = canonical_sort_instances(insts)
        assert method == "FILE_PATH_FALLBACK"


# ---------------------------------------------------------------------------
# Test 5: Non-axial (sagittal / coronal) IOP
# ---------------------------------------------------------------------------
class TestNonAxial:
    def test_sagittal_series_geometry_sort(self):
        """
        Sagittal IOP: row=Y+, col=Z+
        cross(row=[0,1,0], col=[0,0,1]) = [+1,0,0]  →  ascending x  →  Left first.
        """
        sagittal_iop = [0.0, 1.0, 0.0, 0.0, 0.0, 1.0]  # row=Y, col=Z → normal=+X
        insts = [
            {
                "instance_path": f"/s/Instance_000{i}.dcm",
                "instance_number": 4 - i,
                "sop_uid": f"1.1.{i}",
                "image_orientation_patient": sagittal_iop,
                "image_position_patient": [float(i * 5), 0.0, 0.0],
            }
            for i in [3, 2, 1]
        ]
        result, method = canonical_sort_instances(insts)
        assert method == "IPP_IOP_GEOMETRY"
        x_vals = [inst["image_position_patient"][0] for inst in result]
        assert x_vals == [5.0, 10.0, 15.0], (
            f"Expected Left-first (ascending x) with cross(row,col)=+X; got {x_vals}"
        )

    def test_sagittal_flipped_iop_sorts_right_first(self):
        """Flipped sagittal IOP: row=Z+, col=Y+
        cross(row=[0,0,1], col=[0,1,0]) = [-1,0,0]  →  descending x  →  Right first.
        """
        sagittal_iop = [0.0, 0.0, 1.0, 0.0, 1.0, 0.0]  # row=Z, col=Y → normal=-X
        insts = [
            {
                "instance_path": f"/s/Instance_000{i}.dcm",
                "instance_number": 4 - i,
                "sop_uid": f"1.1.{i}",
                "image_orientation_patient": sagittal_iop,
                "image_position_patient": [float(i * 5), 0.0, 0.0],
            }
            for i in [3, 2, 1]
        ]
        result, method = canonical_sort_instances(insts)
        assert method == "IPP_IOP_GEOMETRY"
        x_vals = [inst["image_position_patient"][0] for inst in result]
        assert x_vals == [15.0, 10.0, 5.0], (
            f"Expected Right-first (descending x) with cross(row,col)=-X; got {x_vals}"
        )

    def test_coronal_series_geometry_sort(self):
        """Coronal IOP: row=X+, col=Z+
        cross(row=[1,0,0], col=[0,0,1]) = [0,-1,0]  →  descending y  →  Posterior first.
        """
        coronal_iop = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0]  # row=X, col=Z → normal=-Y
        insts = [
            {
                "instance_path": f"/s/Instance_000{i}.dcm",
                "instance_number": 4 - i,
                "sop_uid": f"1.2.{i}",
                "image_orientation_patient": coronal_iop,
                "image_position_patient": [0.0, float(i * 5), 0.0],
            }
            for i in [3, 2, 1]
        ]
        result, method = canonical_sort_instances(insts)
        assert method == "IPP_IOP_GEOMETRY"
        y_vals = [inst["image_position_patient"][1] for inst in result]
        assert y_vals == [15.0, 10.0, 5.0], (
            f"Expected Posterior-first (descending y) with cross(row,col)=-Y; got {y_vals}"
        )

    def test_coronal_flipped_iop_sorts_anterior_first(self):
        """Flipped coronal IOP: row=Z+, col=X+
        cross(row=[0,0,1], col=[1,0,0]) = [0,+1,0]  →  ascending y  →  Anterior first.
        """
        coronal_iop = [0.0, 0.0, 1.0, 1.0, 0.0, 0.0]  # row=Z, col=X → normal=+Y
        insts = [
            {
                "instance_path": f"/s/Instance_000{i}.dcm",
                "instance_number": 4 - i,
                "sop_uid": f"1.2.{i}",
                "image_orientation_patient": coronal_iop,
                "image_position_patient": [0.0, float(i * 5), 0.0],
            }
            for i in [3, 2, 1]
        ]
        result, method = canonical_sort_instances(insts)
        assert method == "IPP_IOP_GEOMETRY"
        y_vals = [inst["image_position_patient"][1] for inst in result]
        assert y_vals == [5.0, 10.0, 15.0], (
            f"Expected Anterior-first (ascending y) with cross(row,col)=+Y; got {y_vals}"
        )

    def test_oblique_plane_classifies_as_oblique(self):
        normal = [0.60, 0.60, 0.53]
        plane, dominant_axis, dominant_sign = _plane_from_normal(normal)
        assert plane == "OBLIQUE"
        assert dominant_axis in {0, 1, 2}
        assert dominant_sign in {-1, 1}

    def test_oblique_series_is_deterministic(self):
        oblique_iop = [0.707, 0.0, 0.707, 0.0, 1.0, 0.0]
        insts = [
            {
                "instance_path": f"/s/Instance_000{i}.dcm",
                "instance_number": i,
                "sop_uid": f"1.3.{i}",
                "image_orientation_patient": oblique_iop,
                "image_position_patient": [float(i), float(i), float(i)],
            }
            for i in [3, 2, 1]
        ]
        result1, method1 = canonical_sort_instances(copy.deepcopy(insts))
        result2, method2 = canonical_sort_instances(copy.deepcopy(insts))
        assert method1 == method2 == "IPP_IOP_GEOMETRY"
        assert [x["instance_path"] for x in result1] == [x["instance_path"] for x in result2]


# ---------------------------------------------------------------------------
# Test 6: Large series performance sanity (not a strict perf test)
# ---------------------------------------------------------------------------
class TestPerformance:
    def test_large_series_completes(self):
        """Canonical sort of 512 instances should finish without error."""
        import random
        random.seed(42)
        insts = [
            _make_inst(
                f"Instance_{i:04d}.dcm",
                # Scramble InstanceNumber vs IPP to simulate real divergence
                instance_number=random.randint(1, 512),
                ipp_z=float(i),
            )
            for i in range(512)
        ]
        result, method = canonical_sort_instances(insts)
        assert len(result) == 512
        assert method == "IPP_IOP_GEOMETRY"
        z_vals = [inst["image_position_patient"][2] for inst in result]
        assert z_vals == sorted(z_vals), (
            f"Expected Inferior-first (ascending z) with cross(row,col)=[0,0,+1]; "
            f"first 5 z={z_vals[:5]}"
        )


# ---------------------------------------------------------------------------
# Test 7: Convention + rl_sort_instances_by_ipp contract (requirement #9)
# ---------------------------------------------------------------------------
class TestConventionContract:
    """Verify the cross(row, col) convention is used consistently and that
    rl_sort_instances_by_ipp() is no longer a no-op."""

    def test_canonical_sort_normal_is_positive_z_for_standard_axial(self):
        """Requirement #9 – convention confirmation.

        For standard axial HFS IOP [row=X+, col=Y+]:
          cross(row=[1,0,0], col=[0,1,0]) = [0, 0, +1]

        The canonical sort uses ascending dot(IPP, normal), so ascending z
        means Inferior first.  This test pins the normal sign so any future
        accidental revert to cross(col,row) is caught immediately.
        """
        import numpy as np
        from PacsClient.pacs.patient_tab.utils.image_io import (
            _slice_normal_from_iop,
        )

        std_axial_iop = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        normal = _slice_normal_from_iop(std_axial_iop)
        assert normal is not None, "_slice_normal_from_iop returned None for valid IOP"

        # Must be [0, 0, +1]  (cross(row,col) convention)
        n = np.asarray(normal)
        assert abs(float(n[0])) < 1e-9, f"Expected nx≈0, got {n[0]}"
        assert abs(float(n[1])) < 1e-9, f"Expected ny≈0, got {n[1]}"
        assert float(n[2]) > 0.9, (
            f"Expected nz≈+1 (cross(row,col) = [0,0,+1] for axial HFS); "
            f"got nz={n[2]:.6f}.  "
            f"If nz≈-1 the sorter is using cross(col,row) — must revert."
        )

    def test_rl_sort_instances_is_not_a_noop_for_fast_order(self):
        """Requirement #9 – rl_sort_instances_by_ipp() must do a real IPP sort.

        FAST (pydicom_qt) delivers instances in InstanceNumber order.
        When InstanceNumber order ≠ IPP geometry order the function must
        reorder the list.  A no-op would return the unmodified input.
        """
        from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar.reference_line import (
            rl_sort_instances_by_ipp,
        )

        std_axial_iop = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        # Instance-number order is 1→2→3, but IPP z is REVERSED (30→20→10).
        insts = [
            {
                "instance_path": f"/s/Instance_000{i}.dcm",
                "instance_number": i,
                "sop_uid": f"1.4.{i}",
                "image_orientation_patient": std_axial_iop,
                "image_position_patient": [0.0, 0.0, float((4 - i) * 10)],
            }
            for i in [1, 2, 3]
        ]
        # Instance 1 → z=30 (Superior), 2 → z=20, 3 → z=10 (Inferior)
        original_paths = [inst["instance_path"] for inst in insts]
        result = rl_sort_instances_by_ipp(insts)

        result_paths = [inst["instance_path"] for inst in result]
        assert result_paths != original_paths, (
            "rl_sort_instances_by_ipp() returned input unchanged — it is still a no-op. "
            "Expected IPP geometry reorder (Inferior-first: z=10,20,30)."
        )
        z_vals = [inst["image_position_patient"][2] for inst in result]
        assert z_vals == [10.0, 20.0, 30.0], (
            f"Expected Inferior-first (ascending z); got {z_vals}"
        )

    def test_rl_sort_instances_is_idempotent(self):
        """Requirement #9 – applying rl_sort_instances_by_ipp() twice gives the
        same result as applying it once.
        """
        from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar.reference_line import (
            rl_sort_instances_by_ipp,
        )

        std_axial_iop = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        insts = [
            _make_inst(f"Instance_000{i}.dcm", i, float(i * 10))
            for i in [3, 1, 2]   # unsorted input
        ]
        once = rl_sort_instances_by_ipp(insts)
        twice = rl_sort_instances_by_ipp(once)

        z_once = [inst["image_position_patient"][2] for inst in once]
        z_twice = [inst["image_position_patient"][2] for inst in twice]
        assert z_once == z_twice, (
            f"rl_sort_instances_by_ipp() is not idempotent: "
            f"once={z_once}, twice={z_twice}"
        )
        # Both should be Inferior-first
        assert z_once == sorted(z_once), f"Not in ascending order after first sort: {z_once}"


# ---------------------------------------------------------------------------
# Test 8: Advanced display-convention layer (post-canonical shared order)
# ---------------------------------------------------------------------------
class TestAdvancedDisplayConvention:
    def test_canonical_geometry_order_remains_stable(self):
        """Canonical order stays geometry-stable; display convention is a separate layer."""
        insts = [
            _make_inst("Instance_0001.dcm", 3, 30.0),
            _make_inst("Instance_0002.dcm", 2, 20.0),
            _make_inst("Instance_0003.dcm", 1, 10.0),
        ]
        canonical, method = canonical_sort_instances(insts)
        assert method == "IPP_IOP_GEOMETRY"
        z_canonical = [i["image_position_patient"][2] for i in canonical]
        assert z_canonical == [10.0, 20.0, 30.0]

        # Display convention can reverse without mutating canonical list.
        display = apply_advanced_display_convention(
            canonical,
            plane="AXIAL",
            patient_position="HFS",
            body_part="ABDOMEN",
            laterality="",
            series_uid="1.2.3.4",
        )
        z_display = [i["image_position_patient"][2] for i in display]
        assert z_display == [30.0, 20.0, 10.0]
        assert z_canonical == [10.0, 20.0, 30.0], "canonical list was mutated"

    def test_display_layer_reverses_shared_instance_list(self):
        """AXIAL canonical Inferior-first becomes Superior-first display list."""
        canonical = [
            _make_inst("Instance_0001.dcm", 1, 10.0),
            _make_inst("Instance_0002.dcm", 2, 20.0),
            _make_inst("Instance_0003.dcm", 3, 30.0),
        ]
        display = apply_advanced_display_convention(
            canonical,
            plane="AXIAL",
            patient_position="HFS",
            body_part="ABDOMEN",
            laterality="",
            series_uid="1.2.3",
        )
        assert [x["image_position_patient"][2] for x in display] == [30.0, 20.0, 10.0]

    def test_shared_order_alignment_after_display_layer(self):
        """After display convention, SITK file list == metadata order == reference order."""
        canonical = [
            _make_inst("Instance_0001.dcm", 1, 10.0),
            _make_inst("Instance_0002.dcm", 2, 20.0),
            _make_inst("Instance_0003.dcm", 3, 30.0),
        ]
        display = apply_advanced_display_convention(
            canonical,
            plane="AXIAL",
            patient_position="HFS",
            body_part="ABDOMEN",
            laterality="",
            series_uid="1.2.840",
        )

        sitk_files = [inst["instance_path"] for inst in display]
        metadata_instances = list(display)
        reference_instances = list(display)

        sitk_hash = _compute_path_list_hash(sitk_files)
        meta_hash = _compute_path_list_hash([inst["instance_path"] for inst in metadata_instances])
        ref_hash = _compute_path_list_hash([inst["instance_path"] for inst in reference_instances])

        assert sitk_hash == meta_hash == ref_hash

    def test_sagittal_convention_starts_from_expected_side(self):
        """Sagittal canonical left-first should become right-first display convention."""
        sagittal_iop = [0.0, 1.0, 0.0, 0.0, 0.0, 1.0]  # normal +X
        canonical = [
            {
                "instance_path": f"/s/Instance_000{i}.dcm",
                "instance_number": i,
                "sop_uid": f"1.9.{i}",
                "image_orientation_patient": sagittal_iop,
                "image_position_patient": [float(x), 0.0, 0.0],
            }
            for i, x in enumerate([5.0, 10.0, 15.0], 1)
        ]
        display = apply_advanced_display_convention(
            canonical,
            plane="SAGITTAL",
            patient_position="HFS",
            body_part="BRAIN",
            laterality="",
            series_uid="1.9",
        )
        assert [inst["image_position_patient"][0] for inst in display] == [15.0, 10.0, 5.0]

    def test_first_open_reopen_hash_remains_identical(self):
        """First-open and reopen paths converge to the same display_order_hash."""
        # First-open (filesystem-like) and reopen (db-like) represent the same
        # slices but arrive in different incoming order.
        fs_like = [
            _make_inst("Instance_0001.dcm", 3, 30.0),
            _make_inst("Instance_0002.dcm", 2, 20.0),
            _make_inst("Instance_0003.dcm", 1, 10.0),
        ]
        db_like = [
            _make_inst("Instance_0003.dcm", 1, 10.0),
            _make_inst("Instance_0002.dcm", 2, 20.0),
            _make_inst("Instance_0001.dcm", 3, 30.0),
        ]

        fs_canonical, _ = canonical_sort_instances(fs_like)
        db_canonical, _ = canonical_sort_instances(db_like)

        fs_display = apply_advanced_display_convention(
            fs_canonical,
            plane="AXIAL",
            patient_position="HFS",
            body_part="ABDOMEN",
            laterality="",
            series_uid="1.2.3",
        )
        db_display = apply_advanced_display_convention(
            db_canonical,
            plane="AXIAL",
            patient_position="HFS",
            body_part="ABDOMEN",
            laterality="",
            series_uid="1.2.3",
        )

        fs_hash = _compute_path_list_hash([x["instance_path"] for x in fs_display])
        db_hash = _compute_path_list_hash([x["instance_path"] for x in db_display])
        assert fs_hash == db_hash


class TestSeriesGeometryIndexContract:
    def _build_axial_series(self, tmp_path: Path, *, body_part: str = "ABDOMEN"):
        study_uid = generate_uid()
        series_uid = generate_uid()
        iop = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        files = []
        for instance_number, z in [(3, 30.0), (1, 10.0), (2, 20.0)]:
            path = tmp_path / f"Instance_{instance_number:04d}.dcm"
            files.append(
                _write_test_dicom(
                    path,
                    study_uid=study_uid,
                    series_uid=series_uid,
                    series_number="4",
                    sop_uid=generate_uid(),
                    iop=iop,
                    ipp=[0.0, 0.0, z],
                    body_part=body_part,
                    patient_position="HFS",
                    instance_number=instance_number,
                )
            )
        return files, study_uid, series_uid

    def test_same_series_from_filesystem_and_db_produces_identical_geometry_index(self, tmp_path):
        files, study_uid, series_uid = self._build_axial_series(tmp_path)
        fs_index, _ = build_series_geometry_index(files, study_uid_hint=study_uid, series_uid_hint=series_uid, source="fresh_files")
        db_index, _ = build_series_geometry_index(list(reversed(files)), study_uid_hint=study_uid, series_uid_hint=series_uid, source="db")
        assert fs_index.geometry_order_hash == db_index.geometry_order_hash
        assert fs_index.display_order_hash == db_index.display_order_hash
        assert fs_index.sop_uid_by_display_index == db_index.sop_uid_by_display_index

    def test_reopen_produces_identical_display_order_hash(self, tmp_path):
        files, study_uid, series_uid = self._build_axial_series(tmp_path)
        index1, _ = build_series_geometry_index(files, study_uid_hint=study_uid, series_uid_hint=series_uid, source="fresh_files")
        index2, _ = build_series_geometry_index(files, study_uid_hint=study_uid, series_uid_hint=series_uid, source="reopen")
        assert index1.display_order_hash == index2.display_order_hash

    def test_axial_abdomen_first_display_label_is_superior(self, tmp_path):
        files, study_uid, series_uid = self._build_axial_series(tmp_path, body_part="ABDOMEN")
        index, _ = build_series_geometry_index(files, study_uid_hint=study_uid, series_uid_hint=series_uid, source="fresh_files")
        assert index.plane == "AXIAL"
        assert index.first_display_label == "Superior"

    def test_axial_joint_first_display_label_is_proximal_when_detectable(self, tmp_path):
        files, study_uid, series_uid = self._build_axial_series(tmp_path, body_part="KNEE")
        index, _ = build_series_geometry_index(files, study_uid_hint=study_uid, series_uid_hint=series_uid, source="fresh_files")
        assert index.first_display_label == "Proximal"
        assert index.last_display_label == "Distal"

    def test_sagittal_display_starts_right_side(self, tmp_path):
        study_uid = generate_uid()
        series_uid = generate_uid()
        iop = [0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
        files = []
        for instance_number, x in [(3, 15.0), (1, 5.0), (2, 10.0)]:
            files.append(
                _write_test_dicom(
                    tmp_path / f"Sag_{instance_number:04d}.dcm",
                    study_uid=study_uid,
                    series_uid=series_uid,
                    series_number="8",
                    sop_uid=generate_uid(),
                    iop=iop,
                    ipp=[x, 0.0, 0.0],
                    body_part="BRAIN",
                    instance_number=instance_number,
                )
            )
        index, _ = build_series_geometry_index(files, study_uid_hint=study_uid, series_uid_hint=series_uid, source="fresh_files")
        assert index.plane == "SAGITTAL"
        assert index.first_display_label == "Right"
        assert [ipp[0] for ipp in index.ipp_by_display_index] == [5.0, 10.0, 15.0]

    def test_sitk_file_order_equals_display_instances_order(self, tmp_path):
        files, study_uid, series_uid = self._build_axial_series(tmp_path)
        index, _ = build_series_geometry_index(files, study_uid_hint=study_uid, series_uid_hint=series_uid, source="fresh_files")
        assert list(index.dicom_files_for_itk) == [inst.instance_path for inst in index.display_instances_order]

    def test_metadata_instances_equal_display_instances_order(self, tmp_path):
        files, study_uid, series_uid = self._build_axial_series(tmp_path)
        index, _ = build_series_geometry_index(files, study_uid_hint=study_uid, series_uid_hint=series_uid, source="fresh_files")
        metadata = {"series": {"series_number": "4"}, "instances": []}
        stamp_metadata_with_geometry_index(metadata, index)
        assert [inst["instance_path"] for inst in metadata["instances"]] == [inst.instance_path for inst in index.display_instances_order]
        assert metadata["instances"][0]["sop_uid"] == index.sop_uid_by_display_index[0]

    def test_mixed_series_uid_raises(self, tmp_path):
        files, study_uid, series_uid = self._build_axial_series(tmp_path)
        mixed_file = _write_test_dicom(
            tmp_path / "mixed_series.dcm",
            study_uid=study_uid,
            series_uid=generate_uid(),
            series_number="4",
            sop_uid=generate_uid(),
            iop=[1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
            ipp=[0.0, 0.0, 40.0],
            instance_number=4,
        )
        with pytest.raises(ValueError):
            build_series_geometry_index(files + [mixed_file], study_uid_hint=study_uid, source="fresh_files")

    def test_mixed_plane_logs_warning(self, tmp_path, caplog):
        study_uid = generate_uid()
        series_uid = generate_uid()
        axial = _write_test_dicom(
            tmp_path / "axial.dcm",
            study_uid=study_uid,
            series_uid=series_uid,
            series_number="4",
            sop_uid=generate_uid(),
            iop=[1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
            ipp=[0.0, 0.0, 10.0],
            instance_number=1,
        )
        sagittal = _write_test_dicom(
            tmp_path / "sagittal.dcm",
            study_uid=study_uid,
            series_uid=series_uid,
            series_number="4",
            sop_uid=generate_uid(),
            iop=[0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
            ipp=[10.0, 0.0, 0.0],
            instance_number=2,
        )
        with caplog.at_level("WARNING"):
            build_series_geometry_index([axial, sagittal], study_uid_hint=study_uid, series_uid_hint=series_uid, source="fresh_files")
        assert any("[ADVANCED_SERIES_GEOMETRY_WARNING]" in record.message for record in caplog.records)

    def test_attempt_to_mutate_finalized_metadata_raises_contract_error(self, tmp_path):
        files, study_uid, series_uid = self._build_axial_series(tmp_path)
        index, _ = build_series_geometry_index(files, study_uid_hint=study_uid, series_uid_hint=series_uid, source="fresh_files")
        metadata = {"series": {"series_number": "4"}, "instances": []}
        stamp_metadata_with_geometry_index(metadata, index)
        metadata["instances"] = list(reversed(metadata["instances"]))
        with pytest.raises(RuntimeError, match="ADVANCED_ORDER_CONTRACT_ERROR"):
            assert_advanced_order_contract(metadata, caller="test_contract")

