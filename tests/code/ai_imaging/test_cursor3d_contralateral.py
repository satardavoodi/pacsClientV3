"""
Guard tests for the contralateral (R↔L) symmetry matcher.

Verifies the "second clinical question" engine:
  * a symmetric contralateral pair (near-equal breast-relative geometry + similar
    appearance) scores high and is called SYMMETRIC;
  * a geometry-mismatched contralateral scores low and is flagged ASYMMETRIC;
  * a lesion with NO contralateral counterpart raises the asymmetry flag;
  * geometry-only records (no appearance stored) still score on position, weights
    renormalising cleanly;
  * only same-view / opposite-laterality records are considered.

Pure stdlib — sandbox-friendly.
"""

from __future__ import annotations

from modules.ai_imaging.ai_module_ui.cursor_3d import contralateral_matcher as cm


def _rec(lat, view, depth, radial, height, *, density=None, mc_count=None,
         lesion_type=None, origin="picked", uid="u"):
    geom = {
        "axial_depth_mm": depth,
        "radial_distance_mm": radial,
        "height_mm": height,
        "pnl_length_mm": 90.0,
    }
    appearance = None
    if density is not None:
        appearance = {
            "ok": True,
            "density_mean": density,
            "first_order": {"mean": density},
            "glcm": {"contrast": 10.0, "homogeneity": 0.5, "asm": 0.2,
                     "correlation": 0.3, "entropy": 2.0},
            "microcalc": ({"detected": True, "count": mc_count,
                           "mean_area_mm2": 0.1, "mean_nn_spacing_mm": 3.0}
                          if mc_count else {"detected": False, "count": 0}),
            "lesion_type": lesion_type or "dense_mass_like",
        }
    return {
        "lesion_uid": uid, "patient_id": "P", "laterality": lat,
        "view_position": view, "origin": origin, "box_px": [0, 0, 10, 10],
        "geometry": geom, "appearance": appearance,
    }


def test_symmetric_pair_scores_high():
    q = _rec("R", "CC", 30.0, 40.0, -5.0, density=500.0, uid="q")
    c = _rec("L", "CC", 31.0, 41.0, -4.0, density=505.0, uid="c")
    m = cm.score_symmetry(q, c)
    assert m.total >= cm.SYMMETRIC_FLOOR
    assert m.is_symmetric is True


def test_geometry_mismatch_scores_low():
    q = _rec("R", "CC", 30.0, 40.0, -5.0, density=500.0, uid="q")
    c = _rec("L", "CC", 85.0, 95.0, 45.0, density=500.0, uid="c")
    m = cm.score_symmetry(q, c)
    assert m.total < cm.SYMMETRIC_FLOOR
    assert m.is_symmetric is False


def test_match_flags_asymmetry_when_no_good_counterpart():
    q = _rec("R", "CC", 30.0, 40.0, -5.0, density=500.0, uid="q")
    far = _rec("L", "CC", 90.0, 100.0, 50.0, density=500.0, uid="c")
    res = cm.match_contralateral(q, [far])
    assert res.status == cm.ASYMMETRIC
    assert res.asymmetry_flag is True


def test_match_symmetric_when_counterpart_present():
    q = _rec("R", "MLO", 50.0, 60.0, 10.0, density=400.0, uid="q")
    good = _rec("L", "MLO", 49.0, 61.0, 11.0, density=402.0, uid="c")
    res = cm.match_contralateral(q, [good])
    assert res.status == cm.SYMMETRIC
    assert res.asymmetry_flag is False
    assert res.best is not None


def test_no_contralateral_candidate_is_insufficient_not_asymmetric():
    """Absence of DATA (other breast not analysed) must NOT be called an asymmetry."""
    q = _rec("R", "CC", 30.0, 40.0, -5.0, uid="q")
    res = cm.match_contralateral(q, [])
    assert res.status == cm.INSUFFICIENT
    assert res.asymmetry_flag is False
    assert res.best is None


def test_geometry_only_records_still_score():
    """No appearance stored → score on geometry alone, weights renormalise."""
    q = _rec("R", "CC", 30.0, 40.0, -5.0, density=None, uid="q")
    c = _rec("L", "CC", 30.5, 40.5, -5.5, density=None, uid="c")
    m = cm.score_symmetry(q, c)
    assert m.candidate is not None
    assert set(m.components) <= {"axial_depth_agree", "radial_agree", "height_agree"}
    assert m.total >= cm.SYMMETRIC_FLOOR   # near-identical geometry


def test_only_same_view_opposite_laterality_considered():
    q = _rec("R", "CC", 30.0, 40.0, -5.0, uid="q")
    same_lat = _rec("R", "CC", 30.0, 40.0, -5.0, uid="sl")      # same breast — excluded
    other_view = _rec("L", "MLO", 30.0, 40.0, -5.0, uid="ov")   # other view — excluded
    good = _rec("L", "CC", 30.0, 40.0, -5.0, uid="g")           # the only valid mirror
    res = cm.match_contralateral(q, cm._same_view_opposite_laterality(q, [same_lat, other_view, good]))
    assert res.status == cm.SYMMETRIC
    assert res.best.candidate["lesion_uid"] == "g"


def test_analyze_records_distinguishes_asymmetry_from_missing_data():
    recs = [
        _rec("R", "CC", 30.0, 40.0, -5.0, density=500.0, uid="r"),
        _rec("L", "CC", 31.0, 41.0, -4.0, density=505.0, uid="l"),        # symmetric partner for r
        _rec("R", "MLO", 55.0, 65.0, 20.0, density=500.0, uid="lonely"),  # no L-MLO at all
        _rec("R", "CC", 82.0, 92.0, 46.0, density=500.0, uid="odd"),      # L-CC exists but far
    ]
    results = cm.analyze_records(recs)
    by = {r.query["lesion_uid"]: r for r in results}
    # a matched mirror → symmetric
    assert by["r"].status == cm.SYMMETRIC
    # counterpart exists but does not match → a REAL asymmetry (flagged)
    assert by["odd"].status == cm.ASYMMETRIC
    assert by["odd"].asymmetry_flag is True
    # the other breast has no finding in this view → insufficient data, NOT flagged
    assert by["lonely"].status == cm.INSUFFICIENT
    assert by["lonely"].asymmetry_flag is False


def test_microcalc_presence_mismatch_lowers_symmetry():
    # identical geometry, but one has a calc cluster and the other does not
    q = _rec("R", "CC", 30.0, 40.0, -5.0, density=500.0, mc_count=4,
             lesion_type="microcalc_like", uid="q")
    c = _rec("L", "CC", 30.0, 40.0, -5.0, density=500.0, mc_count=None,
             lesion_type="dense_mass_like", uid="c")
    with_mismatch = cm.score_symmetry(q, c).total
    c2 = _rec("L", "CC", 30.0, 40.0, -5.0, density=500.0, mc_count=4,
              lesion_type="microcalc_like", uid="c2")
    with_match = cm.score_symmetry(q, c2).total
    assert with_match > with_mismatch


def test_analyze_from_store_end_to_end(tmp_path):
    """Persist real records, then run the store-backed patient analysis."""
    from modules.ai_imaging.ai_module_ui.cursor_3d import lesion_feature_store as lfs
    attach = str(tmp_path)

    def save(lat, view, depth, radial, height, uid, study="S1"):
        rec = lfs.LesionFeatureRecord(
            lesion_uid=uid, patient_id="P9", study_uid=study, laterality=lat,
            view_position=view, box_px=[0, 0, 10, 10], origin="picked",
            geometry=lfs.LesionGeometryFeatures(
                axial_depth_mm=depth, radial_distance_mm=radial,
                height_mm=height, pnl_length_mm=90.0),
        )
        lfs.save_lesion_feature(rec, attach)

    save("R", "CC", 30.0, 40.0, -5.0, "r")
    save("L", "CC", 31.0, 41.0, -4.0, "l")        # symmetric partner for r
    save("R", "MLO", 55.0, 65.0, 20.0, "lonely")  # no L-MLO partner

    results = cm.analyze_patient_symmetry_from_store("P9", attach)
    by = {r.query["lesion_uid"]: r for r in results}
    assert by["r"].status == cm.SYMMETRIC
    assert by["lonely"].asymmetry_flag is True


def test_contralateral_enabled_default_on(monkeypatch):
    """Promoted to default-ON 2026-07-15; `=0` remains the kill switch."""
    monkeypatch.delenv("AIPACS_CURSOR3D_CONTRALATERAL", raising=False)
    assert cm.contralateral_enabled() is True
    monkeypatch.setenv("AIPACS_CURSOR3D_CONTRALATERAL", "0")
    assert cm.contralateral_enabled() is False
    monkeypatch.setenv("AIPACS_CURSOR3D_CONTRALATERAL", "on")
    assert cm.contralateral_enabled() is True


def test_controller_defaults_appearance_and_heatmap_on():
    """Source-pin: the two controller flags default ON (promoted 2026-07-15)."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[3]
    text = (root / "modules" / "ai_imaging" / "ai_module_ui" / "cursor_3d"
            / "two_stage_controller.py").read_text(encoding="utf-8")
    assert 'os.getenv("AIPACS_CURSOR3D_APPEARANCE", "1")' in text
    assert 'os.getenv("AIPACS_CURSOR3D_HEATMAP", "1")' in text


def test_controller_wires_the_contralateral_pass():
    """Source-pin: the controller imports the matcher, runs it after persist, and
    surfaces the note (asserted without importing Qt)."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[3]
    text = (root / "modules" / "ai_imaging" / "ai_module_ui" / "cursor_3d"
            / "two_stage_controller.py").read_text(encoding="utf-8")
    assert "import contralateral_matcher as _cxl" in text
    assert "_run_contralateral_analysis(scored)" in text
    assert "def _run_contralateral_analysis" in text
    assert "_symmetry_note" in text
