import importlib.util
import math
import sys
from pathlib import Path
import importlib


ROOT = Path(__file__).resolve().parents[3]


def _load_module(relative_path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _make_geometry_module():
    return importlib.import_module("modules.ai_imaging.ai_module_ui.cursor_3d.geometry")


def test_mlo_depth_uses_chestwall_perpendicular_normal():
    geom_mod = _make_geometry_module()

    spacing = geom_mod.PixelSpacing(x=1.0, y=1.0)
    image = geom_mod.ImageGeometry(width_px=600, height_px=600, pixel_spacing=spacing)
    nipple = geom_mod.NipplePosition.from_pixels(100.0, 100.0, spacing, detected=True)

    # 45 degree MLO: depth axis is diagonal, not pure horizontal.
    mlo_geom = geom_mod.MammogramGeometry(
        image=image,
        nipple=nipple,
        chest_wall=geom_mod.ChestWallOrientation.RIGHT,
        laterality="R",
        view_position="MLO",
        pectoral_angle_deg=45.0,
    )
    lesion = geom_mod.LesionLocation.from_pixel_box([190, 95, 210, 105], spacing)

    depth_mm = mlo_geom.compute_lesion_depth_mm(lesion)
    assert abs(depth_mm - (100.0 / math.sqrt(2.0))) < 1e-3


def test_mlo_max_depth_follows_tilted_normal_to_image_bounds():
    geom_mod = _make_geometry_module()

    spacing = geom_mod.PixelSpacing(x=1.0, y=1.0)
    image = geom_mod.ImageGeometry(width_px=500, height_px=300, pixel_spacing=spacing)
    # Nipple in the middle vertically so depth normal hits right edge first
    nipple = geom_mod.NipplePosition.from_pixels(100.0, 200.0, spacing, detected=True)

    # Right-MLO, 45 degree tilt.  Normal points UP-RIGHT: (cos(-45), sin(-45)) = (0.707, -0.707)
    mlo_geom = geom_mod.MammogramGeometry(
        image=image,
        nipple=nipple,
        chest_wall=geom_mod.ChestWallOrientation.RIGHT,
        laterality="R",
        view_position="MLO",
        pectoral_angle_deg=45.0,
    )

    # Normal = (0.707, -0.707)
    # To right edge: (500-100)/0.707 ~= 565.7
    # To top edge: (0-200)/(-0.707) = 200/0.707 ~= 282.8 (limiting)
    expected = 200.0 / math.sin(math.radians(45.0))
    assert abs(mlo_geom.max_available_depth_mm() - expected) < 1e-3


def test_correspondence_arc_best_point_is_on_valid_arc_samples():
    geom_mod = _make_geometry_module()
    arc_mod = importlib.import_module("modules.ai_imaging.ai_module_ui.cursor_3d.correspondence_arc")

    spacing = geom_mod.PixelSpacing(x=1.0, y=1.0)
    img = geom_mod.ImageGeometry(width_px=1000, height_px=1000, pixel_spacing=spacing)

    cc_geom = geom_mod.MammogramGeometry(
        image=img,
        nipple=geom_mod.NipplePosition.from_pixels(120.0, 500.0, spacing, detected=True),
        chest_wall=geom_mod.ChestWallOrientation.RIGHT,
        laterality="R",
        view_position="CC",
    )
    mlo_geom = geom_mod.MammogramGeometry(
        image=img,
        nipple=geom_mod.NipplePosition.from_pixels(130.0, 520.0, spacing, detected=True),
        chest_wall=geom_mod.ChestWallOrientation.RIGHT,
        laterality="R",
        view_position="MLO",
        pectoral_angle_deg=45.0,
    )

    lesion = geom_mod.LesionLocation.from_pixel_box([350, 480, 390, 520], spacing)
    arc = arc_mod.compute_correspondence_arc(
        source_lesion=lesion,
        source_geom=cc_geom,
        target_geom=mlo_geom,
        source_view="CC",
        target_view="MLO",
        pectoral_angle_deg=45.0,
    )

    assert arc.arc_points_px
    assert arc.best_point_px in arc.arc_points_px


def test_visualization_uses_validated_target_center_for_region_strip():
    """The target-view overlay must be driven by the VALIDATED target lesion.

    Guard intent: when the correlator produced a validated ``target_lesion``,
    the target-view rendering must derive its geometry from that lesion's
    ``center_px`` — never from a blind/unvalidated projection.

    This is pinned BEHAVIOURALLY (not by variable name) on purpose: the July-13
    3D-cursor rewrite (upstream ``1c01b3e4``) renamed the locals
    (``target_center_px`` -> ``lesion_center_px``) while keeping the guarantee.
    A name-only pin failed on a rewrite that was in fact correct, so assert the
    invariant instead of the spelling.
    """
    text = (ROOT / "modules/ai_imaging/ai_module_ui/cursor_3d/visualization.py").read_text(encoding="utf-8")

    # The validated target lesion's centre must be read at all.
    assert "match.target_lesion.center_px" in text, (
        "visualization.py no longer reads match.target_lesion.center_px — the "
        "target-view overlay may be using an unvalidated projection."
    )

    # It must be guarded by a presence check, so an unmatched lesion cannot
    # silently fall through to a raw projection.
    assert "if match.target_lesion" in text or "elif match.target_lesion" in text, (
        "the validated-target-lesion branch guard is missing from visualization.py"
    )

    # And it must actually feed the drawing call (whatever the kwarg is named).
    assert "lesion_center_px=match.target_lesion.center_px" in text or (
        "target_center_px=target_center_px" in text
    ), "the validated target centre is read but never passed to the draw call"
