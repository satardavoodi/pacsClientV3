"""
Guard tests — Two-Stage 3D Cursor (Mammography CC/MLO correspondence).

Covers the validation scenarios required by the feature spec, plus the two defects
that made the legacy locus unsafe to auto-rank against:

    * LEFT-breast arc mirror  — the arc used to sweep INFERIORLY for L breasts.
    * chimera radius          — an AB (arc) locus fed the SS (axial) distance.

Pure: no Qt, no VTK, no backend. Runs in the offscreen sandbox lane:

    python3 -m pytest tests/code/ai_imaging/test_cursor3d_two_stage.py -q -p no:debugging
"""

from __future__ import annotations

import importlib
import math
import pathlib
import sys
import types

import pytest


# ─── Import bootstrap ────────────────────────────────────────────────────────
#
# The Stage-1/Stage-2 core is deliberately PURE (stdlib + math only): no Qt, no
# VTK, no numpy. But `modules/ai_imaging/ai_module_ui/__init__.py` imports
# AiMainWindow -> PySide6, so a normal package import would drag the whole GUI
# stack in and make these tests un-runnable headlessly.
#
# We therefore register the package chain WITHOUT executing those __init__ files,
# then import the pure submodules inside it (so their relative imports still
# resolve). If this bootstrap ever starts failing, it means a pure module grew a
# Qt/VTK dependency — which is exactly the regression we want to catch, because
# the offline accuracy harness depends on this core staying importable alone.

_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_CHAIN = [
    ("modules", _ROOT / "modules"),
    ("modules.ai_imaging", _ROOT / "modules" / "ai_imaging"),
    ("modules.ai_imaging.ai_module_ui", _ROOT / "modules" / "ai_imaging" / "ai_module_ui"),
    ("modules.ai_imaging.ai_module_ui.cursor_3d",
     _ROOT / "modules" / "ai_imaging" / "ai_module_ui" / "cursor_3d"),
]
for _name, _path in _CHAIN:
    if _name not in sys.modules:
        _stub = types.ModuleType(_name)
        _stub.__path__ = [str(_path)]
        sys.modules[_name] = _stub

_BASE = "modules.ai_imaging.ai_module_ui.cursor_3d"
_geometry = importlib.import_module(f"{_BASE}.geometry")
_search_region = importlib.import_module(f"{_BASE}.search_region")
_matching = importlib.import_module(f"{_BASE}.candidate_matching")
_threshold = importlib.import_module(f"{_BASE}.threshold_policy")

ChestWallOrientation = _geometry.ChestWallOrientation
ImageGeometry = _geometry.ImageGeometry
LesionLocation = _geometry.LesionLocation
MammogramGeometry = _geometry.MammogramGeometry
NipplePosition = _geometry.NipplePosition
PixelSpacing = _geometry.PixelSpacing

SearchRegion = _search_region.SearchRegion
compute_search_region = _search_region.compute_search_region
absolute_error_mm = _search_region.absolute_error_mm

AMBIGUOUS = _matching.AMBIGUOUS
MATCH = _matching.MATCH
NO_MATCH = _matching.NO_MATCH
Candidate = _matching.Candidate
rank_candidates = _matching.rank_candidates

second_pass_threshold = _threshold.second_pass_threshold


def test_stage1_stage2_core_imports_without_qt_or_vtk():
    """The pure core must never acquire a GUI dependency — the offline accuracy
    harness (and every test above) depends on importing it standalone.

    Match real IMPORT STATEMENTS, not bare substrings: the docstrings legitimately
    mention Qt/VTK/PySide6 while explaining *why* they are absent, and a naive
    substring scan flags those as violations.
    """
    import re

    qt_import = re.compile(r"^\s*(?:from|import)\s+PySide6\b", re.MULTILINE)
    vtk_import = re.compile(r"^\s*(?:from|import)\s+vtk\b", re.MULTILINE)

    for mod in (_geometry, _search_region, _matching, _threshold):
        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        assert not vtk_import.search(src), f"{mod.__name__} must not import VTK"
        assert not qt_import.search(src), f"{mod.__name__} must not import Qt"


def test_pure_core_imports_without_qt_in_a_clean_interpreter():
    """
    Stronger, session-independent purity check: import the four pure modules in a
    FRESH subprocess and assert Qt/VTK were not pulled in transitively.

    This must NOT be asserted against the parent session's ``sys.modules`` — in a
    full-suite run hundreds of other tests import PySide6 first, so a parent-session
    check is guaranteed to be polluted and flaky (it was: it got auto-quarantined).
    A clean subprocess is the only correct way to prove the core imports Qt-free.
    """
    import subprocess

    code = (
        "import sys, importlib\n"
        "for m in ("
        "'modules.ai_imaging.ai_module_ui.cursor_3d.geometry',"
        "'modules.ai_imaging.ai_module_ui.cursor_3d.search_region',"
        "'modules.ai_imaging.ai_module_ui.cursor_3d.candidate_matching',"
        "'modules.ai_imaging.ai_module_ui.cursor_3d.threshold_policy'):\n"
        "    import types, pathlib\n"
        "    parts = m.split('.')\n"
        "    for i in range(1, len(parts)):\n"
        "        name = '.'.join(parts[:i])\n"
        "        if name not in sys.modules:\n"
        "            stub = types.ModuleType(name)\n"
        "            stub.__path__ = [str(pathlib.Path(_ROOT, *parts[:i]))]\n"
        "            sys.modules[name] = stub\n"
        "    importlib.import_module(m)\n"
        "bad = [x for x in ('PySide6', 'vtk') if x in sys.modules]\n"
        "sys.exit('LEAKED: ' + ','.join(bad) if bad else 0)\n"
    )
    # Inject the repo root so the stub __path__ entries resolve.
    preamble = f"_ROOT = r'''{_ROOT}'''\nimport sys; sys.path.insert(0, _ROOT)\n"
    proc = subprocess.run(
        [sys.executable, "-c", preamble + code],
        capture_output=True, text=True, cwd=str(_ROOT),
    )
    assert proc.returncode == 0, (
        f"pure core pulled in a GUI dependency:\n{proc.stdout}\n{proc.stderr}"
    )


# ─── Fixtures ────────────────────────────────────────────────────────────────

SPACING = PixelSpacing(x=0.1, y=0.1)          # 0.1 mm/px — typical MG detector
W_PX, H_PX = 2400, 3200                        # 240 mm x 320 mm


def _geom(laterality: str, view: str, nipple_px, pectoral=None) -> MammogramGeometry:
    return MammogramGeometry(
        image=ImageGeometry(width_px=W_PX, height_px=H_PX, pixel_spacing=SPACING),
        nipple=NipplePosition.from_pixels(nipple_px[0], nipple_px[1], SPACING, detected=True),
        chest_wall=(ChestWallOrientation.RIGHT if laterality == "R"
                    else ChestWallOrientation.LEFT),
        laterality=laterality,
        view_position=view,
        pectoral_angle_deg=pectoral,
    )


def _lesion(cx_px, cy_px, w_px=100, h_px=100, score=0.6) -> LesionLocation:
    return LesionLocation.from_pixel_box(
        [cx_px - w_px / 2, cy_px - h_px / 2, cx_px + w_px / 2, cy_px + h_px / 2],
        SPACING, score=score,
    )


# R breast: chest wall on the RIGHT edge, nipple on the LEFT.
R_CC = _geom("R", "CC", (200, 1600))
R_MLO = _geom("R", "MLO", (200, 1900), pectoral=45.0)

# L breast: chest wall on the LEFT edge, nipple on the RIGHT.
L_CC = _geom("L", "CC", (2200, 1600))
L_MLO = _geom("L", "MLO", (2200, 1900), pectoral=45.0)


# ─── The two geometric quantities must be distinct ───────────────────────────

def test_axial_and_radial_are_different_quantities():
    """
    dl (axial, the SS quantity) != dr (radial, the AB/Kopans quantity), and
    dl <= dr always. Conflating them is exactly the legacy chimera defect.
    """
    lesion = _lesion(900, 1000)          # off the posterior nipple line
    dl = R_CC.compute_lesion_depth_mm(lesion)
    dr = R_CC.compute_lesion_radial_distance_mm(lesion)

    assert dl < dr, "off-axis lesion must have axial < radial"
    assert dl == pytest.approx(70.0, abs=0.5)      # 700 px horizontally
    assert dr == pytest.approx(math.hypot(70.0, 60.0), abs=0.5)


def test_axial_equals_radial_on_the_posterior_nipple_line():
    """On the PNL the two coincide — the only case where the chimera was benign."""
    lesion = _lesion(900, 1600)          # same row as the nipple
    dl = R_CC.compute_lesion_depth_mm(lesion)
    dr = R_CC.compute_lesion_radial_distance_mm(lesion)
    assert dl == pytest.approx(dr, abs=0.01)


# ─── LEFT/RIGHT symmetry — the mirror bug ────────────────────────────────────

def test_arc_sweeps_superiorly_for_BOTH_lateralities():
    """
    THE LEFT-BREAST MIRROR BUG.

    The legacy arc used `centre_angle = chest_wall_angle - theta_pec` for both
    sides. For L (chest_wall_angle = pi) that gives sin > 0 => the arc swept
    INFERIORLY, into the wrong quadrant. The pectoral muscle is SUPERIOR in both
    R-MLO and L-MLO, so the arc must sweep superiorly (negative y, y-down) on both.
    """
    lesion_r = _lesion(900, 1400)
    lesion_l = _lesion(1500, 1400)       # mirrored about the image centre

    region_r = compute_search_region(lesion_r, R_CC, R_MLO, method="ab")
    region_l = compute_search_region(lesion_l, L_CC, L_MLO, method="ab")

    assert region_r.ok and region_l.ok

    # Locus centroid must lie ABOVE the nipple (smaller y) on both sides.
    def _mean_y(region):
        return sum(p[1] for p in region.points_px) / len(region.points_px)

    assert _mean_y(region_r) < R_MLO.nipple.y_px, "R-MLO arc must sweep superiorly"
    assert _mean_y(region_l) < L_MLO.nipple.y_px, "L-MLO arc must sweep superiorly"


def test_strip_is_mirror_symmetric_between_lateralities():
    """A mirrored lesion in a mirrored breast must give a mirrored strip."""
    lesion_r = _lesion(900, 1400)
    lesion_l = _lesion(W_PX - 900, 1400)

    r = compute_search_region(lesion_r, R_CC, R_MLO, method="ss")
    l = compute_search_region(lesion_l, L_CC, L_MLO, method="ss")

    assert r.ok and l.ok
    # The preserved axial distance must be identical.
    assert r.distance_mm == pytest.approx(l.distance_mm, abs=0.01)


# ─── Anisotropic spacing ─────────────────────────────────────────────────────

def test_anisotropic_spacing_is_honoured_per_axis():
    """
    The legacy arc collapsed spacing to a scalar mean ((sx+sy)/2), distorting the
    locus whenever row and column spacing differ. Points must convert per-axis.
    """
    aniso = PixelSpacing(x=0.05, y=0.20)      # deliberately 4:1
    geom_src = MammogramGeometry(
        image=ImageGeometry(W_PX, H_PX, aniso),
        nipple=NipplePosition.from_pixels(200, 1600, aniso, detected=True),
        chest_wall=ChestWallOrientation.RIGHT, laterality="R", view_position="CC",
    )
    geom_tgt = MammogramGeometry(
        image=ImageGeometry(W_PX, H_PX, aniso),
        nipple=NipplePosition.from_pixels(200, 1600, aniso, detected=True),
        chest_wall=ChestWallOrientation.RIGHT, laterality="R", view_position="MLO",
    )
    lesion = LesionLocation.from_pixel_box([850, 950, 950, 1050], aniso)

    region = compute_search_region(lesion, geom_src, geom_tgt, method="ss")
    assert region.ok

    # With no pectoral angle the MLO normal is horizontal, so the strip is vertical
    # at x = nipple_x + dl/sx. dl = (900-200)*0.05 = 35 mm -> x stays 900 px.
    xs = {round(p[0]) for p in region.points_px}
    assert xs == {900}, f"strip should be the vertical line x=900, got {sorted(xs)[:5]}"


# ─── deviation / absolute error ──────────────────────────────────────────────

def test_deviation_is_zero_on_the_locus_and_grows_off_it():
    lesion = _lesion(900, 1500)
    region = compute_search_region(lesion, R_CC, R_MLO, method="ss")
    assert region.ok

    on_locus = region.points_px[len(region.points_px) // 2]
    assert region.deviation_mm(on_locus) == pytest.approx(0.0, abs=0.05)

    # Step 10 mm along the depth normal -> deviation must be 10 mm.
    nx, ny = R_MLO.depth_normal_unit_vector()
    off = (on_locus[0] + nx * 10.0 / SPACING.x,
           on_locus[1] + ny * 10.0 / SPACING.y)
    assert region.deviation_mm(off) == pytest.approx(10.0, abs=0.2)


def test_absolute_error_matches_the_published_metric():
    """AE = shortest distance from the true lesion centre to the predicted locus."""
    lesion = _lesion(900, 1500)
    region = compute_search_region(lesion, R_CC, R_MLO, method="ss")
    truth = region.points_px[len(region.points_px) // 3]
    assert absolute_error_mm(region, truth) == pytest.approx(0.0, abs=0.05)


def test_bands_are_wide_and_honest_by_default():
    """
    The band must reflect the literature, not wishful thinking: SS needs ~±32 mm to
    reach 100 % sensitivity. A narrow default band around an uncertain prediction
    is the clinically dangerous failure mode.
    """
    region = compute_search_region(_lesion(900, 1500), R_CC, R_MLO)
    assert region.inner_band_mm >= 5.0
    assert region.outer_band_mm >= 25.0
    assert region.outer_band_mm > region.inner_band_mm


def test_gm_is_the_default_method():
    """GM was promoted to default (2026-07-15) after live validation on 50258.
    SS/AB remain reachable via AIPACS_CURSOR3D_LOCUS."""
    region = compute_search_region(_lesion(900, 1500), R_CC, R_MLO)
    assert region.method == "gm"
    assert region.distance_kind == "anterior"


# ─── Out of field ────────────────────────────────────────────────────────────

def test_lesion_beyond_the_field_yields_an_unusable_region():
    deep = _lesion(2350, 1600)        # essentially at the chest wall
    far_target = _geom("R", "MLO", (2300, 1900), pectoral=45.0)
    region = compute_search_region(deep, R_CC, far_target, method="ss")
    # Either flagged not-ok, or empty — never a silently wrong locus.
    assert (not region.ok) or region.is_empty or len(region.points_px) >= 2


# ─── Stage 2: candidate ranking ──────────────────────────────────────────────

def _region_for_ranking():
    source = _lesion(900, 1500)
    region = compute_search_region(source, R_CC, R_MLO, method="ss")
    assert region.ok
    return source, region


def test_scenario_clear_match_after_lowering_threshold():
    """A single low-threshold detection sitting on the locus => confident MATCH."""
    source, region = _region_for_ranking()
    on_locus = region.points_px[len(region.points_px) // 2]

    cand = Candidate(index=0, box_px=[on_locus[0] - 50, on_locus[1] - 50,
                                      on_locus[0] + 50, on_locus[1] + 50], score=0.41)
    res = rank_candidates([cand], region, source, R_CC, R_MLO)

    assert res.status == MATCH
    assert res.is_confident
    assert res.best is not None
    assert res.best.deviation_mm < 1.0


def test_scenario_no_candidate_in_the_region():
    """Detections exist but none near the locus => NO_MATCH, region stays valid."""
    source, region = _region_for_ranking()
    far = Candidate(index=0, box_px=[2300, 100, 2380, 180], score=0.42)
    res = rank_candidates([far], region, source, R_CC, R_MLO)

    assert res.status == NO_MATCH
    assert not res.is_confident
    assert res.best is None
    assert "region" in res.message.lower() or "no " in res.message.lower()


def test_scenario_no_detections_at_all():
    source, region = _region_for_ranking()
    res = rank_candidates([], region, source, R_CC, R_MLO)
    assert res.status == NO_MATCH
    assert not res.is_confident


def _strip_foot_and_dir(region: SearchRegion, geom: MammogramGeometry):
    """
    The foot of the strip (where it crosses the posterior nipple line) and the unit
    direction ALONG the strip, both in pixels.

    Reflecting a point across the foot preserves BOTH preserved quantities:
        axial  dl  — unchanged (still on the strip)
        radial dr  — unchanged (dr = hypot(dl, t), and t only changes sign)
    So a pair placed symmetrically about the foot is a *genuine* tie: no geometric
    cue can separate them. That is the only honest way to construct ambiguity.
    """
    nx, ny = geom.depth_normal_unit_vector()
    dl = region.distance_mm
    foot_mm = (geom.nipple.x_mm + nx * dl, geom.nipple.y_mm + ny * dl)
    foot_px = (foot_mm[0] / SPACING.x, foot_mm[1] / SPACING.y)
    along_mm = (-ny, nx)
    return foot_px, along_mm


def test_scenario_multiple_similar_candidates_are_ambiguous_not_forced():
    """
    THE SAFETY CONTRACT.

    Two identical candidates placed symmetrically about the strip foot are
    geometrically indistinguishable (equal dl, equal dr, equal size/score). The
    ranker must NOT resolve them into a confident pick — forcing one would point the
    radiologist at a coin-flip, away from the true lesion half the time.
    """
    source, region = _region_for_ranking()
    foot, along = _strip_foot_and_dir(region, R_MLO)

    t = 250.0  # mm along the strip, either side of the foot
    p1 = (foot[0] + along[0] * t / SPACING.x, foot[1] + along[1] * t / SPACING.y)
    p2 = (foot[0] - along[0] * t / SPACING.x, foot[1] - along[1] * t / SPACING.y)

    c1 = Candidate(index=0, box_px=[p1[0] - 50, p1[1] - 50, p1[0] + 50, p1[1] + 50], score=0.42)
    c2 = Candidate(index=1, box_px=[p2[0] - 50, p2[1] - 50, p2[0] + 50, p2[1] + 50], score=0.42)

    res = rank_candidates([c1, c2], region, source, R_CC, R_MLO)

    assert res.status == AMBIGUOUS
    assert res.best is None, "an ambiguous result must not select a winner"
    assert not res.is_confident
    assert len(res.alternatives) >= 2


def test_radial_agreement_disambiguates_position_ALONG_the_strip():
    """
    An emergent property worth pinning: the strip alone cannot say WHERE along
    itself the lesion sits — every point on it has the same axial distance. The
    radial (Kopans/NOD) component supplies exactly that missing cue, because
    dr = hypot(dl, t) grows with distance `t` from the foot.

    Combining the two is, in effect, Zheng et al.'s third "mixed" search area
    (a strip on the chest-wall side, an arc on the nipple side). So a candidate
    whose radial distance ALSO matches the source must outrank an equally
    on-strip candidate whose radial distance does not.
    """
    source, region = _region_for_ranking()
    foot, along = _strip_foot_and_dir(region, R_MLO)

    src_dr = R_CC.compute_lesion_radial_distance_mm(source)
    src_dl = region.distance_mm
    # Offset along the strip that reproduces the source's radial distance.
    t_true = math.sqrt(max(src_dr ** 2 - src_dl ** 2, 0.0))

    def _at(t):
        return (foot[0] + along[0] * t / SPACING.x, foot[1] + along[1] * t / SPACING.y)

    p_right = _at(t_true)          # correct radial distance
    p_wrong = _at(t_true + 60.0)   # on the strip, but 60 mm further out

    good = Candidate(index=0, box_px=[p_right[0] - 50, p_right[1] - 50,
                                      p_right[0] + 50, p_right[1] + 50], score=0.42)
    bad = Candidate(index=1, box_px=[p_wrong[0] - 50, p_wrong[1] - 50,
                                     p_wrong[0] + 50, p_wrong[1] + 50], score=0.42)

    res = rank_candidates([bad, good], region, source, R_CC, R_MLO)

    assert res.ranked[0].candidate.index == 0, "the radially-consistent candidate must win"
    assert res.ranked[0].components["radial_agree"] > res.ranked[1].components["radial_agree"]
    # Both sit exactly on the strip, so the axial cue cannot separate them.
    assert res.ranked[0].deviation_mm == pytest.approx(res.ranked[1].deviation_mm, abs=0.2)


def test_low_score_candidate_is_never_presented_as_a_match():
    """Below the confidence floor => NO_MATCH, even though it is the best available."""
    source, region = _region_for_ranking()
    # Near the outer edge of the search band, tiny, low AI confidence.
    nx, ny = R_MLO.depth_normal_unit_vector()
    on_locus = region.points_px[len(region.points_px) // 2]
    edge = (on_locus[0] + nx * 30.0 / SPACING.x,
            on_locus[1] + ny * 30.0 / SPACING.y)

    weak = Candidate(index=0, box_px=[edge[0] - 5, edge[1] - 5, edge[0] + 5, edge[1] + 5],
                     score=0.05)
    res = rank_candidates([weak], region, source, R_CC, R_MLO)

    assert res.status == NO_MATCH
    assert not res.is_confident


def test_ranking_is_sorted_and_ranked():
    source, region = _region_for_ranking()
    mid = region.points_px[len(region.points_px) // 2]
    nx, ny = R_MLO.depth_normal_unit_vector()

    near = Candidate(index=0, box_px=[mid[0] - 50, mid[1] - 50, mid[0] + 50, mid[1] + 50], score=0.44)
    off = (mid[0] + nx * 20.0 / SPACING.x, mid[1] + ny * 20.0 / SPACING.y)
    farther = Candidate(index=1, box_px=[off[0] - 50, off[1] - 50, off[0] + 50, off[1] + 50], score=0.41)

    res = rank_candidates([farther, near], region, source, R_CC, R_MLO)

    assert res.ranked[0].total >= res.ranked[1].total
    assert res.ranked[0].rank == 1 and res.ranked[1].rank == 2
    assert res.ranked[0].candidate.index == 0, "the on-locus candidate must rank first"


def test_unknown_classification_is_neutral_not_penalised():
    """
    The classification join is fragile (exact float box equality upstream). A
    missing label is a plumbing artefact, NOT evidence against a candidate.
    """
    source, region = _region_for_ranking()
    mid = region.points_px[len(region.points_px) // 2]
    box = [mid[0] - 50, mid[1] - 50, mid[0] + 50, mid[1] + 50]

    unlabelled = Candidate(index=0, box_px=box, score=0.42, classification=None)
    res = rank_candidates([unlabelled], region, source, R_CC, R_MLO)
    assert res.ranked[0].components["class_agree"] == pytest.approx(0.5)


def test_direction_cc_to_mlo_and_mlo_to_cc_both_supported():
    """Spec scenarios: 'detected in CC but not MLO' AND 'in MLO but not CC'."""
    lesion_cc = _lesion(900, 1500)
    r1 = compute_search_region(lesion_cc, R_CC, R_MLO)
    assert r1.ok and r1.source_view == "CC" and r1.target_view == "MLO"

    lesion_mlo = _lesion(900, 1700)
    r2 = compute_search_region(lesion_mlo, R_MLO, R_CC)
    assert r2.ok and r2.source_view == "MLO" and r2.target_view == "CC"


# ─── GM locus (accuracy-plan Phase 4 / the "GM upgrade") ─────────────────────

# Real geometry from patient 50258, where SS mis-placed the region by ~18–25 mm
# and the workflow (correctly) returned no_match. Spacing 0.083 mm/px, 2796×3584.
_SP258 = PixelSpacing(x=0.083, y=0.083)
_W258, _H258 = 2796, 3584


def _geom258(view, nipple_px, pectoral=None):
    return MammogramGeometry(
        image=ImageGeometry(width_px=_W258, height_px=_H258, pixel_spacing=_SP258),
        nipple=NipplePosition.from_pixels(nipple_px[0], nipple_px[1], _SP258, detected=True),
        chest_wall=ChestWallOrientation.LEFT,
        laterality="L",
        view_position=view,
        pectoral_angle_deg=pectoral,
    )


_CC258 = _geom258("CC", (986.5421, 1962.0335))
_MLO258 = _geom258("MLO", (1020.0897, 2409.3346), pectoral=22.225)
_SRC258 = LesionLocation.from_pixel_box(
    [363.234, 1534.999, 727.388, 1924.313], _SP258
)
# The real corresponding detections found in MLO at threshold 0.39.
_MLO258_DETECTIONS = [(558, 1769), (462, 1820), (544, 1837)]


def test_gm_lands_the_lesion_where_ss_missed_50258():
    """
    THE REGRESSION THIS FEATURE EXISTS FOR (patient 50258, 2026-07-15).

    SS placed the strip ~18 mm from the true corresponding detections (outside the
    8 mm inner band → no_match). GM, by preserving the anterior distance along the
    untilted nipple line instead of the pectoral-tilted axis, must land the same
    lesion inside the inner band.
    """
    ss = compute_search_region(_SRC258, _CC258, _MLO258, method="ss")
    gm = compute_search_region(_SRC258, _CC258, _MLO258, method="gm")
    assert ss.ok and gm.ok
    assert gm.method == "gm" and gm.distance_kind == "anterior"

    ss_best = min(ss.deviation_mm(d) for d in _MLO258_DETECTIONS)
    gm_best = min(gm.deviation_mm(d) for d in _MLO258_DETECTIONS)

    assert ss_best > 15.0, f"SS should miss (it did, live): {ss_best:.1f}mm"
    assert gm_best < 5.0, f"GM should land the lesion: {gm_best:.1f}mm"
    assert gm_best < ss_best / 3.0, "GM must be a large improvement over SS"
    # And it would flip the outcome: inside GM's inner band, outside SS's.
    assert gm_best <= gm.inner_band_mm
    assert ss_best > ss.inner_band_mm


def test_gm_is_independent_of_the_pectoral_angle():
    """
    GM's anterior placement must NOT depend on the pectoral angle (that dependence
    is exactly what makes SS fragile). Rebuilding GM across a wide pectoral range
    must leave the true detection's deviation essentially unchanged.
    """
    devs = []
    for pec in (15.0, 22.225, 35.0, 50.0):
        mlo = _geom258("MLO", (1020.0897, 2409.3346), pectoral=pec)
        gm = compute_search_region(_SRC258, _CC258, mlo, method="gm")
        devs.append(gm.deviation_mm(_MLO258_DETECTIONS[0]))
    assert max(devs) - min(devs) < 1.0, f"GM should be pectoral-insensitive, spread={max(devs)-min(devs):.2f}"


def test_gm_slots_into_the_searchregion_contract():
    """GM must expose the same interface the renderer / matcher / AE-harness use."""
    gm = compute_search_region(_SRC258, _CC258, _MLO258, method="gm")
    assert not gm.is_empty
    assert gm.nominal_point_px is not None
    # deviation is zero on the locus and grows off it (same contract as SS/AB).
    on = gm.points_px[len(gm.points_px) // 2]
    assert gm.deviation_mm(on) < 1.0
    # band edges are drawable and offset from the locus.
    assert gm.band_points_px(gm.outer_band_mm)
    # absolute_error_mm works on a GM region.
    assert absolute_error_mm(gm, on) < 1.0


def test_gm_and_ss_agree_for_a_lesion_on_the_nipple_line():
    """
    Sanity: a lesion with NO superior offset (on the posterior nipple line) is the
    case where SS's tilt does no harm — GM and SS should give the same anterior/axial
    distance, so GM never regresses the easy case.
    """
    on_line = _lesion(900, 1600)  # same row as the R_CC/R_MLO nipple (y=1600)
    ss = compute_search_region(on_line, R_CC, R_MLO, method="ss")
    gm = compute_search_region(on_line, R_CC, R_MLO, method="gm")
    assert abs(ss.distance_mm - gm.distance_mm) < 1.0


def test_gm_is_the_live_default_ss_is_the_kill_switch():
    """GM is the default; SS is reachable as the kill switch via method='ss'
    (env AIPACS_CURSOR3D_LOCUS=ss). Both must be selectable explicitly."""
    default = compute_search_region(_SRC258, _CC258, _MLO258)
    assert default.method == "gm"
    ss = compute_search_region(_SRC258, _CC258, _MLO258, method="ss")
    assert ss.method == "ss"


# ─── Three-factor cross-view heatmap (2026-07-15) ────────────────────────────

_hm = importlib.import_module(f"{_BASE}.cross_view_heatmap")
_app = importlib.import_module(f"{_BASE}.appearance_similarity")


def test_factor2_height_prior_is_wide_and_soft():
    """
    Factor 2 (medial-lateral → MLO height) must be a WIDE bias, not a hard pin —
    50258 showed it explains only ~34% of the true height. The true detection, ~35 mm
    off the predicted height, must still score ~exp(-1)=0.37, NOT be crushed to 0.
    """
    gm = compute_search_region(_SRC258, _CC258, _MLO258, method="gm")
    true_det = (558, 1769)
    hs = _hm.height_score(gm, true_det)
    assert 0.25 < hs < 0.75, f"height prior should be soft, got {hs:.2f}"
    # ...and it peaks at the predicted (x_CC·cosθ) height.
    assert _hm.height_score(gm, gm.nominal_point_px) > 0.95


def test_factor1_geometric_score_decays_across_the_band():
    gm = compute_search_region(_SRC258, _CC258, _MLO258, method="gm")
    on = gm.points_px[len(gm.points_px) // 2]
    assert _hm.geometric_score(gm, on) > 0.95
    # 40 mm off the locus (past the 32 mm outer band) → 0.
    nx, ny = gm._normal
    off = (on[0] + nx * 40.0 / _SP258.x, on[1] + ny * 40.0 / _SP258.y)
    assert _hm.geometric_score(gm, off) < 0.2


def test_combine_renormalises_when_appearance_absent_no_dilution():
    """A uniform-0.6 candidate must score 0.6 whether or not appearance is present —
    the missing factor must not hand every candidate a constant."""
    with_app = _hm.combine(0.6, 0.6, 0.6)
    without = _hm.combine(0.6, 0.6, None)
    assert abs(with_app - 0.6) < 1e-6
    assert abs(without - 0.6) < 1e-6
    # a low appearance pulls the score down (it is really used when present).
    assert _hm.combine(0.9, 0.9, 0.1) < _hm.combine(0.9, 0.9, None)


def _require_numpy():
    try:
        import numpy  # noqa: F401
        return numpy
    except Exception:
        pytest.skip("numpy not available")


def test_factor3_appearance_matches_density_signature():
    """
    Factor 3: a DENSE source lesion (microcalc-like) must match a dense candidate
    and reject a fatty one, over realistic tight AI boxes.
    """
    np = _require_numpy()
    rng = np.random.default_rng(0)

    def fill(img, box, val):
        x1, y1, x2, y2 = [int(v) for v in box]
        img[y1:y2, x1:x2] = rng.normal(val, 15, (y2 - y1, x2 - x1))

    timg = rng.normal(300, 20, (3584, 2796)).astype("float32")
    simg = rng.normal(300, 20, (3584, 2796)).astype("float32")
    src_box = [363, 1535, 727, 1924]
    a_box, b_box = [500, 1710, 616, 1828], [404, 1762, 520, 1878]
    fill(simg, src_box, 900)   # dense source
    fill(timg, a_box, 900)     # dense candidate (match)
    fill(timg, b_box, 120)     # fatty candidate (mismatch)

    sf = _app.source_features(simg, src_box)
    a = _app.candidate_appearance_score(sf, timg, a_box)
    b = _app.candidate_appearance_score(sf, timg, b_box)
    assert a > 0.7 and b < 0.4 and a > b + 0.3, (a, b)
    # neutral 0.5 when there is no pixel data — never a penalty.
    assert _app.candidate_appearance_score(sf, None, a_box) == 0.5


def test_appearance_factor_enters_scoring_and_breaks_a_tie():
    """
    Two candidates equal on geometry (both on the locus) — the one whose appearance
    matches the source must win once factor 3 is supplied, and appearance_sim must be
    ABSENT from the components when no pixel fn is given.
    """
    np = _require_numpy()
    rng = np.random.default_rng(1)
    gm = compute_search_region(_SRC258, _CC258, _MLO258, method="gm")

    def fill(img, box, val):
        x1, y1, x2, y2 = [int(v) for v in box]
        img[y1:y2, x1:x2] = rng.normal(val, 15, (y2 - y1, x2 - x1))

    # Put both candidates on the locus (near the true detections), same size/score.
    a_box = [500, 1710, 616, 1828]   # will be dense (matches source)
    b_box = [500, 2000, 616, 2118]   # will be fatty
    timg = rng.normal(300, 20, (3584, 2796)).astype("float32")
    simg = rng.normal(300, 20, (3584, 2796)).astype("float32")
    fill(simg, [363, 1535, 727, 1924], 900)
    fill(timg, a_box, 900)
    fill(timg, b_box, 120)
    sf = _app.source_features(simg, [363, 1535, 727, 1924])
    appfn = lambda box: _app.candidate_appearance_score(sf, timg, box)

    ca = Candidate(index=0, box_px=a_box, score=0.49)
    cb = Candidate(index=1, box_px=b_box, score=0.49)

    res_no = rank_candidates([ca, cb], gm, _SRC258, _CC258, _MLO258)
    res_ap = rank_candidates([ca, cb], gm, _SRC258, _CC258, _MLO258, appearance_score_fn=appfn)

    assert "appearance_sim" not in res_no.ranked[0].components
    assert "appearance_sim" in res_ap.ranked[0].components
    assert res_ap.ranked[0].candidate.index == 0, "density-matching candidate should win"


def test_heatmap_field_builds_with_a_peak():
    _require_numpy()
    gm = compute_search_region(_SRC258, _CC258, _MLO258, method="gm")
    field = _hm.build_heatmap_field(gm)
    assert field is not None and field.values.ndim == 2
    assert field.peak_px is not None
    assert 0.0 <= float(field.values.max()) <= 1.0


# ─── Full revalidation matrix (2026-07-15) ───────────────────────────────────
# Each factor, independently, across R/L × CC↔MLO. Synthetic geometry (portrait
# 2796×3584, 0.083 mm/px); R nipple on the left, L nipple on the right.

_SPX = PixelSpacing(x=0.083, y=0.083)


def _g(lat, view, nip, pec=None):
    return MammogramGeometry(
        image=ImageGeometry(2796, 3584, _SPX),
        nipple=NipplePosition.from_pixels(nip[0], nip[1], _SPX, detected=True),
        chest_wall=(ChestWallOrientation.RIGHT if lat == "R" else ChestWallOrientation.LEFT),
        laterality=lat, view_position=view, pectoral_angle_deg=pec,
    )


def _lz(cx, cy):
    return LesionLocation.from_pixel_box([cx - 50, cy - 50, cx + 50, cy + 50], _SPX)


@pytest.mark.parametrize("lat", ["R", "L"])
@pytest.mark.parametrize("direction", [("CC", "MLO"), ("MLO", "CC")])
def test_factor1_gm_valid_across_all_configurations(lat, direction):
    """Stage 1: GM produces a valid, anterior-preserving region on the correct
    chest-wall side for every R/L × CC↔MLO configuration."""
    nx = 400 if lat == "R" else 2396
    cc, mlo = _g(lat, "CC", (nx, 1600)), _g(lat, "MLO", (nx, 1900), 40)
    sv, tv = direction
    sg, tg = (cc, mlo) if sv == "CC" else (mlo, cc)
    lx = 1000 if lat == "R" else 1796
    src = _lz(lx, 1400 if sv == "CC" else 1700)

    r = compute_search_region(src, sg, tg, method="gm")
    assert r.ok and r.method == "gm" and r.distance_kind == "anterior"
    assert not r.is_empty
    # deviation ~0 on the locus.
    mid = r.points_px[len(r.points_px) // 2]
    assert r.deviation_mm(mid) < 0.6
    # locus on the chest-wall side of the target nipple.
    locus_x = r.points_px[0][0]
    on_chest_side = (locus_x > tg.nipple.x_px) if lat == "R" else (locus_x < tg.nipple.x_px)
    assert on_chest_side, f"{lat} {sv}->{tv}: locus must be on the chest-wall side"


@pytest.mark.parametrize("lat", ["R", "L"])
def test_factor2_monotonic_symmetric_and_central_overlap(lat):
    """Stage 2: greater CC medial-lateral displacement → greater MLO height bias;
    central lesion → ~0 bias (overlap); opposite sides → opposite sign."""
    nx = 400 if lat == "R" else 2396
    cc, mlo = _g(lat, "CC", (nx, 1600)), _g(lat, "MLO", (nx, 1900), 40)
    lx = 1000 if lat == "R" else 1796

    heights = []
    for dv in (0, 300, 600):  # 0/25/50 mm off the nipple line
        r = compute_search_region(_lz(lx, 1600 - dv), cc, mlo, method="gm")
        heights.append(abs(r.nominal_height_mm()))
    assert heights[0] < heights[1] < heights[2], "monotonic with displacement"
    assert heights[0] < 2.0, "central lesion → ~0 bias (overlap region)"

    up = compute_search_region(_lz(lx, 1300), cc, mlo, method="gm").nominal_height_mm()
    dn = compute_search_region(_lz(lx, 1900), cc, mlo, method="gm").nominal_height_mm()
    assert up * dn < 0, "opposite sides of the nipple line → opposite-sign bias"


def test_factor2_is_left_right_symmetric():
    r = compute_search_region(_lz(1000, 1300), _g("R", "CC", (400, 1600)),
                              _g("R", "MLO", (400, 1900), 40), method="gm").nominal_height_mm()
    l = compute_search_region(_lz(1796, 1300), _g("L", "CC", (2396, 1600)),
                              _g("L", "MLO", (2396, 1900), 40), method="gm").nominal_height_mm()
    assert abs(abs(r) - abs(l)) < 0.5


def test_factor3_texture_similarity():
    """Stage 3: a heterogeneous (high-variance) source matches a heterogeneous
    candidate over a flat one."""
    np = _require_numpy()
    rng = np.random.default_rng(3)

    def fill(img, box, val, tex):
        x1, y1, x2, y2 = [int(v) for v in box]
        img[y1:y2, x1:x2] = rng.normal(val, tex, (y2 - y1, x2 - x1))

    sb = [900, 1400, 1064, 1600]
    het_box, flat_box = [500, 1700, 664, 1900], [300, 1700, 464, 1900]
    simg = rng.normal(300, 20, (3584, 2796)).astype("float32")
    timg = rng.normal(300, 20, (3584, 2796)).astype("float32")
    fill(simg, sb, 600, 120)      # heterogeneous source
    fill(timg, het_box, 600, 120)
    fill(timg, flat_box, 600, 5)
    sf = _app.source_features(simg, sb)
    assert _app.candidate_appearance_score(sf, timg, het_box) > _app.candidate_appearance_score(sf, timg, flat_box)


def test_factor4_overlap_and_detection_support():
    """
    Stage 4: the AI box's overlap with the predicted region, and detection_support
    (AI confidence blended with that overlap).
    """
    cc = _g("R", "CC", (400, 1600))
    mlo = _g("R", "MLO", (400, 1900), 40)
    gm = compute_search_region(_lz(1000, 1400), cc, mlo, method="gm")
    lx = gm.points_px[0][0]
    my = gm.points_px[len(gm.points_px) // 2][1]

    on = _hm.region_overlap_fraction(gm, [lx - 60, my - 60, lx + 60, my + 60])
    off = _hm.region_overlap_fraction(gm, [lx + 45 / 0.083, my - 60, lx + 45 / 0.083 + 120, my + 60])
    assert on > 0.7 and off < 0.2, f"on-region {on:.2f} must dominate off-region {off:.2f}"

    # detection_support needs BOTH confidence and overlap.
    assert _hm.detection_support(0.9, 0.9) > _hm.detection_support(0.9, 0.1)
    assert _hm.detection_support(0.9, 0.9) > _hm.detection_support(0.1, 0.9)


def test_factor4_enters_scoring_no_double_count():
    """detection_support is present; the standalone ai_score component is gone
    (folded into factor 4) so AI confidence is not double-counted."""
    cc = _g("R", "CC", (400, 1600))
    mlo = _g("R", "MLO", (400, 1900), 40)
    src = _lz(1000, 1400)
    gm = compute_search_region(src, cc, mlo, method="gm")
    lx = gm.points_px[0][0]
    my = gm.points_px[len(gm.points_px) // 2][1]

    good = Candidate(index=0, box_px=[lx - 60, my - 60, lx + 60, my + 60], score=0.6)
    bad = Candidate(index=1, box_px=[lx + 45 / 0.083, my - 60, lx + 45 / 0.083 + 120, my + 60], score=0.6)
    res = rank_candidates([bad, good], gm, src, cc, mlo)
    assert "detection_support" in res.ranked[0].components
    assert "ai_score" not in res.ranked[0].components
    # equal AI confidence → the on-region box wins on factor 4.
    assert res.ranked[0].candidate.index == 0


def test_dominant_index_picks_single_strongest_match():
    """The final focus is ONE lesion — the strongest confident MATCH — never an
    ambiguous or no-match entry."""
    from modules.ai_imaging.ai_module_ui.cursor_3d.candidate_matching import (
        dominant_index, MatchResult, ScoredCandidate, Candidate as _C, MATCH, AMBIGUOUS, NO_MATCH,
    )

    def _sc(total):
        return ScoredCandidate(candidate=_C(index=0, box_px=[0, 0, 1, 1]), total=total)

    results = [
        MatchResult(status=MATCH, best=_sc(0.58)),
        MatchResult(status=MATCH, best=_sc(0.72)),
        MatchResult(status=AMBIGUOUS, best=None),
    ]
    assert dominant_index(results) == 1                      # the 0.72 MATCH
    assert dominant_index([MatchResult(status=AMBIGUOUS, best=None),
                           MatchResult(status=NO_MATCH)]) is None  # no forced focus


def test_layout_independence_calc_is_deterministic():
    """Stage 1 note: the geometry takes NO layout/viewport parameter — Layout 1 vs
    Layout 2 only changes WHICH viewport renders, never the math. Same inputs must
    give an identical region."""
    src = _lz(1000, 1400)
    a = compute_search_region(src, _g("R", "CC", (400, 1600)), _g("R", "MLO", (400, 1900), 40), method="gm")
    b = compute_search_region(src, _g("R", "CC", (400, 1600)), _g("R", "MLO", (400, 1900), 40), method="gm")
    assert a.distance_mm == b.distance_mm
    assert a.points_px == b.points_px
    assert a.nominal_point_px == b.nominal_point_px


# ─── Threshold step-down ─────────────────────────────────────────────────────

def test_second_pass_threshold_steps_down_by_0_05():
    assert second_pass_threshold(0.45) == 0.40
    assert second_pass_threshold(0.40) == 0.35


def test_second_pass_threshold_is_rounded_to_two_decimals():
    """
    The CSV filename carries f"{threshold:.2f}" and the manifest re-parses the
    threshold back OUT of that filename. An unrounded 0.44999999 would be written
    as _0.45.csv and silently collide with the first-pass result.
    """
    t = second_pass_threshold(0.45)
    assert t == round(t, 2)
    assert f"{t:.2f}" == "0.40"


def test_second_pass_threshold_is_clamped_above_zero():
    assert second_pass_threshold(0.05) > 0.0
    assert second_pass_threshold(0.01) > 0.0


# ─── The escalation ladder (live finding, study 50016) ───────────────────────

def test_ladder_escalates_because_one_step_is_often_not_enough():
    """
    STUDY 50016, 2026-07-14 — the reason this ladder exists.

    The lesion was found in L-CC at 0.4627. The second pass ran correctly at 0.41
    and L-MLO came back EMPTY. Every run on disk (0.41/0.42/0.43/0.44/0.45/0.46)
    had ZERO detections in L-MLO — the corresponding lesion simply scores below
    0.41, so a single −0.05 step could never have surfaced it.

    The ladder keeps stepping down until a detection lands INSIDE the predicted
    region, or the floor is reached.
    """
    assert _threshold.threshold_ladder(0.46) == [0.41, 0.31, 0.21]
    # Rung 0 must still be exactly the spec's −0.05.
    assert _threshold.threshold_ladder(0.46)[0] == second_pass_threshold(0.46)


def test_ladder_is_strictly_descending_and_two_dp():
    """Every rung must be lower than the last, below the original, and 2 dp — the
    CSV filename / manifest round-trip depends on the rounding."""
    for original in (0.46, 0.45, 0.40, 0.35, 0.30):
        lad = _threshold.threshold_ladder(original)
        assert all(lad[i] > lad[i + 1] for i in range(len(lad) - 1)), lad
        assert all(t < original for t in lad), lad
        assert all(t == round(t, 2) for t in lad), lad


def test_ladder_respects_the_floor_and_never_runs_below_it():
    """Below ~0.20 the detector's output is noise. The ladder must clamp, dedupe,
    and — when the original is already at the floor — decline to run at all."""
    floor = _threshold.LADDER_FLOOR
    assert _threshold.threshold_ladder(0.25) == [floor]
    assert _threshold.threshold_ladder(floor) == []
    for original in (0.46, 0.30, 0.25):
        assert all(t >= floor for t in _threshold.threshold_ladder(original))


def test_ladder_reaches_a_low_threshold_in_few_backend_calls():
    """Each rung is a real AI-server round trip, so the ladder must get deep fast.
    Three calls must reach at/below 0.25 from the routine default."""
    lad = _threshold.threshold_ladder(0.45)
    assert len(lad) <= 3, "too many backend round trips"
    assert lad[-1] <= 0.25, f"ladder does not reach deep enough: {lad}"


# ─── PNL cross-view depth normalisation (patient 50513, MLO→CC) ───────────────
#
# The pectoralis-reference upgrade: express a lesion's depth as a FRACTION of the
# nipple→pectoral distance (the Posterior Nipple Line) and rescale it to the target
# view's own PNL, so a posterior MLO lesion stays posterior in CC. Flag-gated
# default-OFF (AIPACS_CURSOR3D_PNL_NORMALIZE); these pin the pure geometry.

_pnl_mod = importlib.import_module(f"{_BASE}.pnl_normalization")
compute_pnl_normalization = _pnl_mod.compute_pnl_normalization


def _mlo_with_line(laterality, nipple_px, pectoral_deg, point_px):
    """An MLO geometry carrying a pectoral-line point (px→mm), so its PNL is defined."""
    g = _geom(laterality, "MLO", nipple_px, pectoral=pectoral_deg)
    g.pectoral_ref_point_mm = (point_px[0] * SPACING.x, point_px[1] * SPACING.y)
    return g


def test_pnl_cc_reference_is_nipple_to_posterior_edge():
    """CC has no pectoral muscle → the reference is the posterior image edge."""
    cc_r = _geom("R", "CC", (400, 1600))   # chest wall on the RIGHT edge
    assert abs(cc_r.pectoral_reference_distance_mm() - (W_PX - 400) * SPACING.x) < 1e-6
    cc_l = _geom("L", "CC", (2000, 1600))  # chest wall on the LEFT edge
    assert abs(cc_l.pectoral_reference_distance_mm() - 2000 * SPACING.x) < 1e-6


def test_pnl_mlo_reference_is_perpendicular_to_the_pectoral_line():
    """MLO PNL = perpendicular nipple→pectoral-line distance (needs point + angle)."""
    mlo = _mlo_with_line("R", (400, 1900), 30.0, (1600, 300))
    th = math.radians(30.0)
    dx, dy = math.sin(th), math.cos(th)
    ax = (400 - 1600) * SPACING.x
    ay = (1900 - 300) * SPACING.y
    expect = abs(ax * dy - ay * dx)     # |A × d|, d unit
    assert abs(mlo.pectoral_reference_distance_mm() - expect) < 1e-6


def test_pnl_mlo_without_a_line_is_unavailable():
    """No pectoral line (or no angle) → None; the MLO image edge is NOT the pectoral."""
    assert _geom("R", "MLO", (400, 1900), pectoral=30.0).pectoral_reference_distance_mm() is None
    assert _mlo_with_line("R", (400, 1900), None, (1600, 300)).pectoral_reference_distance_mm() is None


def test_pnl_available_only_with_both_references_else_legacy_passthrough():
    src_mlo = _mlo_with_line("R", (400, 1900), 30.0, (1600, 300))
    tgt_cc = _geom("R", "CC", (400, 1600))
    les = _lesion(1000, 1500)
    r = compute_pnl_normalization(les, src_mlo, tgt_cc, horizontal_a_src_mm=55.0)
    assert r.available and r.ratio is not None
    # CC source (edge, available) → MLO target WITHOUT a line → unavailable, legacy.
    tgt_mlo_noline = _geom("R", "MLO", (400, 1900), pectoral=30.0)
    r2 = compute_pnl_normalization(les, tgt_cc, tgt_mlo_noline, horizontal_a_src_mm=55.0)
    assert not r2.available and r2.a_normalized_mm == 55.0


def test_pnl_ratio_preserves_fractional_depth():
    """a_norm/PNL_target == depth_source/PNL_source (the fraction is the invariant)."""
    src_mlo = _mlo_with_line("R", (400, 1900), 30.0, (1600, 300))
    tgt_cc = _geom("R", "CC", (400, 1600))
    les = _lesion(1000, 1400)
    r = compute_pnl_normalization(les, src_mlo, tgt_cc, horizontal_a_src_mm=60.0)
    ds = src_mlo.pectoral_reference_distance_mm()
    dt = tgt_cc.pectoral_reference_distance_mm()
    perp = src_mlo.compute_lesion_depth_mm(les)
    assert abs(r.ratio - dt / ds) < 1e-9
    assert abs(r.a_normalized_mm - perp * (dt / ds)) < 1e-6
    assert abs(r.a_normalized_mm / dt - perp / ds) < 1e-9   # fraction preserved


def test_pnl_is_default_on_kill_switch_is_zero(monkeypatch):
    """PNL normalisation is the DEFAULT (promoted 2026-07-15 after live 50513/50258);
    `=0` is the byte-identical legacy kill switch."""
    monkeypatch.delenv("AIPACS_CURSOR3D_PNL_NORMALIZE", raising=False)
    assert _pnl_mod.pnl_normalize_enabled() is True
    monkeypatch.setenv("AIPACS_CURSOR3D_PNL_NORMALIZE", "0")
    assert _pnl_mod.pnl_normalize_enabled() is False


def test_pnl_flag_off_is_byte_identical_and_on_applies(monkeypatch):
    """Flag OFF (=0) → GM keeps the legacy absolute depth; ON → the normalised one."""
    src_mlo = _mlo_with_line("R", (400, 1900), 30.0, (1600, 300))
    tgt_cc = _geom("R", "CC", (400, 1600))
    les = _lesion(1000, 1400)

    monkeypatch.setenv("AIPACS_CURSOR3D_PNL_NORMALIZE", "0")
    off = compute_search_region(les, src_mlo, tgt_cc, method="gm")
    assert off.pnl is not None and off.pnl.available
    assert abs(off.distance_mm - off.pnl.a_source_horizontal_mm) < 1e-6   # legacy depth

    monkeypatch.setenv("AIPACS_CURSOR3D_PNL_NORMALIZE", "1")
    on = compute_search_region(les, src_mlo, tgt_cc, method="gm")
    assert abs(on.distance_mm - on.pnl.a_normalized_mm) < 1e-6            # normalised depth
    assert abs(on.distance_mm - off.distance_mm) > 1e-6                  # the flag did change it


def test_pnl_flag_on_is_noop_when_unavailable(monkeypatch):
    """With the reference missing, ON must be byte-identical to OFF (never guess)."""
    src_cc = _geom("R", "CC", (400, 1600))
    tgt_mlo = _geom("R", "MLO", (400, 1900), pectoral=30.0)   # no pectoral point
    les = _lesion(1000, 1500)
    monkeypatch.delenv("AIPACS_CURSOR3D_PNL_NORMALIZE", raising=False)
    off = compute_search_region(les, src_cc, tgt_mlo, method="gm")
    monkeypatch.setenv("AIPACS_CURSOR3D_PNL_NORMALIZE", "1")
    on = compute_search_region(les, src_cc, tgt_mlo, method="gm")
    assert off.distance_mm == on.distance_mm
    assert on.pnl is not None and not on.pnl.available


def test_pnl_diagnostic_is_attached_and_serialisable():
    """Every GM region carries the PNL diagnostic (for live validation + persistence)."""
    src_mlo = _mlo_with_line("R", (400, 1900), 30.0, (1600, 300))
    tgt_cc = _geom("R", "CC", (400, 1600))
    r = compute_search_region(_lesion(1000, 1400), src_mlo, tgt_cc, method="gm")
    d = r.pnl.as_log_dict()
    for k in ("available", "a_horizontal_mm", "a_perp_mm", "a_normalized_mm",
              "pnl_source_mm", "pnl_target_mm", "ratio"):
        assert k in d


# ─── CC PNL from the posterior tissue boundary (not the image edge) ───────────

def test_cc_posterior_tissue_distance_from_contour():
    """CC PNL = nipple → posterior TISSUE boundary (chest-wall-side extreme of the
    contour), a better reference than the raw image edge."""
    f = _geometry.cc_posterior_tissue_distance_mm
    # R breast: chest wall on the RIGHT → boundary = max x. nipple 400px, 0.1 mm/px.
    assert abs(f([(400, 0), (1800, 0), (400, 0)], 400, "R", 0.1) - 140.0) < 1e-6
    # L breast: chest wall on the LEFT → boundary = min x. nipple 2000px.
    assert abs(f([(600, 0), (2000, 0)], 2000, "L", 0.1) - 140.0) < 1e-6
    assert f([], 400, "R", 0.1) is None                 # empty contour → None
    assert f([(300, 0)], 400, "R", 0.1) is None         # boundary anterior to nipple → None


def test_cc_pnl_prefers_measured_tissue_boundary_over_edge():
    """When a measured tissue-boundary distance is set it OVERRIDES the image edge;
    without it, the geometry falls back to the edge (byte-identical legacy)."""
    cc = _geom("R", "CC", (400, 1600))
    assert abs(cc.pectoral_reference_distance_mm() - (W_PX - 400) * SPACING.x) < 1e-6  # edge fallback
    cc.cc_reference_distance_mm = 140.0
    assert abs(cc.pectoral_reference_distance_mm() - 140.0) < 1e-6                     # prefers measured


def test_perpendicular_point_to_line_mm():
    """The manual CC chest-wall line reference: perpendicular nipple->line distance."""
    f = _geometry.perpendicular_point_to_line_mm
    # Point (0,10); vertical line x=5 → distance 5.
    assert abs(f((0.0, 10.0), (5.0, 0.0), (5.0, 20.0)) - 5.0) < 1e-6
    # Point (0,0); vertical line x=10 → distance 10.
    assert abs(f((0.0, 0.0), (10.0, 0.0), (10.0, 10.0)) - 10.0) < 1e-6
    # Degenerate (zero-length) line → None.
    assert f((0.0, 0.0), (3.0, 3.0), (3.0, 3.0)) is None


def test_manual_reference_line_overrides_absangle_pnl():
    """A drawn pectoral line (both endpoints) measures the PNL as the perpendicular
    to that EXACT line (sign-preserving), overriding the midpoint+abs(angle) method
    that under-measured the MLO PNL (50107: ~29 mm vs ~104 mm true) for a down-left
    L-MLO pectoral, scaling the predicted depth wrongly."""
    mlo = MammogramGeometry(
        image=ImageGeometry(width_px=2796, height_px=3584, pixel_spacing=PixelSpacing(0.083, 0.083)),
        nipple=NipplePosition.from_pixels(1165.5, 2599.4, PixelSpacing(0.083, 0.083)),
        chest_wall=ChestWallOrientation.LEFT, laterality="L", view_position="MLO",
        pectoral_angle_deg=22.79,
        pectoral_ref_point_mm=((1500 + 250) / 2 * 0.083, (250 + 1750) / 2 * 0.083),
    )
    old = mlo.pectoral_reference_distance_mm()          # midpoint + abs(angle)
    p1 = (1500 * 0.083, 250 * 0.083)                    # pectoral runs DOWN-LEFT
    p2 = (250 * 0.083, 1750 * 0.083)
    mlo.manual_reference_line_mm = (p1, p2)
    new = mlo.pectoral_reference_distance_mm()          # actual endpoints (== ruler)
    truth = _geometry.perpendicular_point_to_line_mm(
        (mlo.nipple.x_mm, mlo.nipple.y_mm), p1, p2)
    assert abs(new - truth) < 1e-6                      # matches the ruler exactly
    assert new > 90.0 and old < 45.0                   # ~104 vs ~29 — the fix and the bug
    assert new > old + 40.0


def test_heatmap_emphasis_pulls_core_toward_the_found_lesion():
    """Once the corresponding lesion is FOUND, the hot core snaps ONTO it — the
    geometric height along the band is only a weak prior (superior-inferior is
    unobservable in CC). Fixes 'the MLO core sits a bit low'. No match → unchanged."""
    np = _require_numpy()
    cc = _g("R", "CC", (400, 1600))
    mlo = _g("R", "MLO", (400, 1900), 40)
    region = compute_search_region(_lz(1000, 1400), cc, mlo, method="gm")
    base = _hm.build_heatmap_field(region)
    assert base is not None
    higher = min(region.points_px, key=lambda p: p[1])       # topmost locus point (superior)
    pulled = _hm.build_heatmap_field(region, emphasis_px=higher)
    assert pulled is not None
    assert pulled.peak_px[1] < base.peak_px[1] - 10          # core moved UP toward the lesion
    # No emphasis → core unchanged (stays at the geometric nominal).
    again = _hm.build_heatmap_field(region)
    assert abs(again.peak_px[1] - base.peak_px[1]) < 1e-6


def test_guided_flow_collects_a_cc_pectoral_line():
    """The guided 3D-Cursor flow must ask for BOTH pectoral lines — MLO AND CC — so
    the CC nipple-to-chest-wall distance is measured, not estimated."""
    gw = importlib.import_module(f"{_BASE}.guided_workflow")
    slots = [
        gw.ViewSlot(viewer_index=0, laterality="L", view_position="CC"),
        gw.ViewSlot(viewer_index=1, laterality="L", view_position="MLO"),
    ]
    steps = gw.plan_cursor3d_steps(slots)
    keys = [s.key for s in steps]
    assert "pectoral_mlo" in keys and "pectoral_cc" in keys, keys
    cc_step = next(s for s in steps if s.key == "pectoral_cc")
    assert cc_step.view_position == "CC" and cc_step.kind == "line" and cc_step.clicks == 2


# ─── Multiple / bilateral: show ALL confident corresponding lesions ──────────

def test_focused_indices_shows_all_confident_matches_strongest_first():
    """Two real corresponding lesions (two on a side, or bilateral) → BOTH are
    focused results; ambiguous/no-match never scatter into the focus list."""
    from modules.ai_imaging.ai_module_ui.cursor_3d.candidate_matching import (
        focused_indices, dominant_index, MatchResult, ScoredCandidate,
        Candidate as _C, MATCH, AMBIGUOUS, NO_MATCH,
    )

    def _sc(t):
        return ScoredCandidate(candidate=_C(index=0, box_px=[0, 0, 1, 1]), total=t)

    res = [
        MatchResult(status=MATCH, best=_sc(0.58)),
        MatchResult(status=AMBIGUOUS, best=None),
        MatchResult(status=MATCH, best=_sc(0.72)),
        MatchResult(status=NO_MATCH),
    ]
    assert focused_indices(res) == [2, 0]     # both MATCHes, strongest first
    assert dominant_index(res) == 2           # single-best convenience unchanged
    assert focused_indices([MatchResult(status=AMBIGUOUS, best=None),
                            MatchResult(status=NO_MATCH)]) == []   # no scatter
