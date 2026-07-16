"""
Guard tests for the lesion feature store + serialisable pattern descriptor.

Covers the "preserve + categorise" directive (2026-07-15):
  * describe_region extracts first-order + GLCM + microcalcification-constellation
    features from a box matrix (the "4 bright dots → 4 dots" fingerprint).
  * the per-lesion store round-trips atomically and aggregates by patient.
  * the applicability matrix maps the three comparison kinds to the correct feature
    subsets + geometry transforms (CC↔MLO cross-view vs R↔L mirror).

Sandbox-friendly: numpy + stdlib only, no Qt/VTK/pydicom.
"""

from __future__ import annotations

import numpy as np

from modules.ai_imaging.ai_module_ui.cursor_3d import appearance_similarity as app
from modules.ai_imaging.ai_module_ui.cursor_3d import lesion_feature_store as lfs
from modules.ai_imaging.ai_module_ui.cursor_3d import geometry as geom


# ─── describe_region (the pattern matrix) ────────────────────────────────────

def _image_with_dots(n_dots: int, size: int = 80) -> np.ndarray:
    """Flat mid-grey background with `n_dots` small bright 3×3 blobs."""
    img = np.full((size, size), 100.0, dtype="float64")
    # spread the dots so they are distinct connected components
    positions = [(20, 20), (20, 55), (55, 20), (55, 55), (38, 38)][:n_dots]
    for (cy, cx) in positions:
        img[cy - 1:cy + 2, cx - 1:cx + 2] = 1000.0
    return img


def test_describe_region_detects_microcalcification_constellation():
    img = _image_with_dots(4)
    d = app.describe_region(img, [5, 5, 75, 75], spacing_mm=(0.1, 0.1))
    assert d["ok"] is True
    mc = d["microcalc"]
    assert mc["detected"] is True
    # four planted dots → a small constellation (allow ±1 for thresholding).
    assert 3 <= mc["count"] <= 5
    assert d["lesion_type"] == "microcalc_like"
    # spacing/size come back in mm because spacing was supplied.
    assert mc["mean_area_mm2"] is not None
    assert mc["mean_nn_spacing_mm"] is not None


def test_describe_region_flat_region_has_no_constellation():
    img = np.full((80, 80), 100.0, dtype="float64")
    d = app.describe_region(img, [5, 5, 75, 75], spacing_mm=(0.1, 0.1))
    assert d["ok"] is True
    assert d["microcalc"]["detected"] is False
    assert d["lesion_type"] != "microcalc_like"


def test_describe_region_has_first_order_and_glcm_blocks():
    img = _image_with_dots(4)
    d = app.describe_region(img, [5, 5, 75, 75])
    fo = d["first_order"]
    for k in ("mean", "std", "skew", "kurtosis", "entropy", "high_density_fraction"):
        assert k in fo
    glcm = d["glcm"]
    assert glcm is not None
    for k in ("contrast", "homogeneity", "asm", "correlation", "entropy"):
        assert k in glcm


def test_describe_region_never_raises_on_bad_box():
    img = _image_with_dots(1)
    d = app.describe_region(img, [10, 10, 11, 11])   # sub-2px → empty
    assert d["ok"] is False


def test_describe_region_source_scoring_unchanged():
    """The new descriptor must not perturb the existing histogram scoring path."""
    img = _image_with_dots(4)
    feat = app.source_features(img, [5, 5, 75, 75])
    assert feat.ok is True
    # identical box in the same image → near-perfect self-similarity.
    s = app.candidate_appearance_score(feat, img, [5, 5, 75, 75])
    assert s > 0.9


# ─── the store round-trip ────────────────────────────────────────────────────

def _record(patient="P1", study="S1", lat="R", view="CC", uid=None):
    return lfs.LesionFeatureRecord(
        lesion_uid=uid or lfs.LesionFeatureRecord.new_uid(),
        patient_id=patient, study_uid=study, laterality=lat, view_position=view,
        box_px=[10.0, 10.0, 30.0, 30.0], origin="picked",
        geometry=lfs.LesionGeometryFeatures(
            radial_distance_mm=40.0, axial_depth_mm=30.0, height_mm=-5.0,
            pnl_length_mm=90.0, pnl_fractional_depth=0.333,
        ),
        appearance={"ok": True, "density_mean": 512.0, "lesion_type": "microcalc_like"},
    )


def test_store_round_trip_and_replace_by_uid(tmp_path):
    attach = str(tmp_path)
    rec = _record(uid="fixed-uid")
    path = lfs.save_lesion_feature(rec, attach)
    assert path is not None

    loaded = lfs.load_lesion_features("S1", attach)
    assert len(loaded) == 1
    assert loaded[0]["lesion_uid"] == "fixed-uid"
    assert loaded[0]["geometry"]["pnl_fractional_depth"] == 0.333

    # same uid replaces, does not duplicate
    rec2 = _record(uid="fixed-uid")
    rec2.score = 0.99
    lfs.save_lesion_feature(rec2, attach)
    loaded = lfs.load_lesion_features("S1", attach)
    assert len(loaded) == 1
    assert loaded[0]["score"] == 0.99


def test_load_features_for_patient_aggregates_across_studies(tmp_path):
    attach = str(tmp_path)
    lfs.save_lesion_feature(_record(study="S1", view="CC"), attach)
    lfs.save_lesion_feature(_record(study="S2", view="MLO"), attach)
    lfs.save_lesion_feature(_record(patient="OTHER", study="S3"), attach)

    mine = lfs.load_features_for_patient("P1", attach)
    assert len(mine) == 2
    views = sorted(r["view_position"] for r in mine)
    assert views == ["CC", "MLO"]


def test_save_never_raises_without_attachments_path():
    assert lfs.save_lesion_feature(_record(), "") is None


# ─── the applicability matrix (the categorisation) ───────────────────────────

def test_all_three_comparison_kinds_present():
    assert set(lfs.COMPARISON_KINDS) == set(lfs.COMPARISON_FEATURE_APPLICABILITY)
    assert len(lfs.COMPARISON_KINDS) == 3


def test_cross_view_uses_pnl_transform_contralateral_uses_mirror():
    assert lfs.geometry_transform_for(lfs.CMP_CC_MLO_SAME_BREAST) == lfs.GEOM_CROSS_VIEW_PNL
    assert lfs.geometry_transform_for(lfs.CMP_RCC_LCC) == lfs.GEOM_MIRROR_SAME_VIEW
    assert lfs.geometry_transform_for(lfs.CMP_RMLO_LMLO) == lfs.GEOM_MIRROR_SAME_VIEW


def test_pnl_fractional_depth_is_primary_cross_view_but_absolute_wins_contralateral():
    cross = lfs.COMPARISON_FEATURE_APPLICABILITY[lfs.CMP_CC_MLO_SAME_BREAST]["features"]
    contra = lfs.COMPARISON_FEATURE_APPLICABILITY[lfs.CMP_RCC_LCC]["features"]
    # cross-view leans on the PNL fraction; same-view mirror leans on absolute depth
    assert cross["pnl_fractional_depth"] == lfs.PRIMARY
    assert contra["axial_depth_mm"] == lfs.PRIMARY


def test_pectoral_angle_invalid_for_cc_contralateral_but_used_for_mlo():
    cc = lfs.COMPARISON_FEATURE_APPLICABILITY[lfs.CMP_RCC_LCC]["features"]
    mlo = lfs.COMPARISON_FEATURE_APPLICABILITY[lfs.CMP_RMLO_LMLO]["features"]
    assert cc["pectoral_angle_deg"] == lfs.INVALID
    assert mlo["pectoral_angle_deg"] in (lfs.USEFUL, lfs.PRIMARY)
    # invalid features are excluded from the selector
    assert "pectoral_angle_deg" not in lfs.features_for_comparison(lfs.CMP_RCC_LCC)


def test_box_shape_is_weak_cross_view_but_useful_contralateral():
    """Shape rotates between CC/MLO (weak) but survives a same-view mirror (useful)."""
    cross = lfs.COMPARISON_FEATURE_APPLICABILITY[lfs.CMP_CC_MLO_SAME_BREAST]["features"]
    contra = lfs.COMPARISON_FEATURE_APPLICABILITY[lfs.CMP_RCC_LCC]["features"]
    assert cross["box_shape_aspect"] == lfs.WEAK
    assert contra["box_shape_aspect"] in (lfs.USEFUL, lfs.PRIMARY)


def test_features_for_comparison_primary_only_filter():
    prim = lfs.features_for_comparison(lfs.CMP_RMLO_LMLO, roles=(lfs.PRIMARY,))
    assert "microcalc_count" in prim
    assert all(
        lfs.COMPARISON_FEATURE_APPLICABILITY[lfs.CMP_RMLO_LMLO]["features"][f] == lfs.PRIMARY
        for f in prim
    )


def test_contralateral_pair_kind_and_mirror():
    assert lfs.contralateral_pair_kind("CC") == lfs.CMP_RCC_LCC
    assert lfs.contralateral_pair_kind("MLO") == lfs.CMP_RMLO_LMLO
    assert lfs.contralateral_pair_kind("XX") is None
    assert lfs.mirror_x_px(10.0, 100.0) == 90.0


# ─── DICOM Positioner Primary Angle → pectoral angle ─────────────────────────

def test_positioner_angle_folds_to_pectoral_magnitude():
    f = geom.pectoral_angle_from_positioner_angle
    assert f(45.0) == 45.0
    assert f(-45.0) == 45.0          # sign dropped — laterality supplies direction
    assert f(135.0) == 45.0          # reflected across 90
    assert f(60.0) == 60.0
    assert f(200.0) == 20.0          # 200 mod 180 = 20, in-band


def test_positioner_angle_rejects_implausible_values():
    f = geom.pectoral_angle_from_positioner_angle
    assert f(0.0) is None            # a CC / straight → not an MLO tilt
    assert f(90.0) is None           # ~lateral → above the plausible band
    assert f(5.0) is None            # below the plausible band
    assert f(None) is None
    assert f("bad") is None
    assert f(float("nan")) is None


def test_geometry_record_carries_dicom_fields():
    g = lfs.LesionGeometryFeatures(
        positioner_primary_angle_deg=45.0, body_part_thickness_mm=58.0
    )
    d = lfs.LesionFeatureRecord(
        lesion_uid="u", patient_id="P", study_uid="S", laterality="R",
        view_position="MLO", box_px=[0, 0, 1, 1], geometry=g,
    ).to_dict()
    assert d["geometry"]["positioner_primary_angle_deg"] == 45.0
    assert d["geometry"]["body_part_thickness_mm"] == 58.0
