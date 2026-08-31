"""Guards for focused-v3: the same slices, with the pixels spent on the spine.

V2 letterboxes the whole acquired field into a 256 px tile, which puts a 200 mm
lumbar axial at 0.78 mm/px and a 300 mm sagittal at 1.17 - so the 1-3 mm
base-versus-dome difference that separates a bulge from a protrusion is one to
three pixels. V3 crops each tile to a physical box around the spine first.

These guards exist so that improvement cannot be silently undone, and so V2
stays byte-identical while both modes are being compared.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from modules.ai_imaging.evidence_core import (  # noqa: E402
    DicomSlice,
    DicomSliceStack,
    SeriesVolume,
)
from modules.ai_imaging.eagle_eye_lumbar import (  # noqa: E402
    evidence_bundle,
    focus_evidence,
    llm_package,
    protocols,
)

V2 = evidence_bundle.MODE_FOCUSED_V2
V3 = evidence_bundle.MODE_FOCUSED_V3

_SCREENING = """LEVEL MAP
  L4-L5: axial frames 1-6

CANDIDATE FINDINGS
```json
{"findings": [{"level": "L4-L5", "candidate": "disc_extrusion",
"laterality": "right", "confidence": "high", "evidence": ["sagittal_t2", "axial_t2"],
"key_frames": {"axial": [3, 2, 4], "sagittal": [4]},
"note": "focal displaced material"}]}
```
"""


def _volume(plane: str, offset: float = 0.0) -> SeriesVolume:
    z, y, x = np.indices((9, 128, 128), dtype=np.float32)
    pixels = offset + z * 11.0 + x * 0.8 + y * 0.4
    return SeriesVolume(
        pixels=pixels,
        origin=(0.0, 0.0, 0.0),
        spacing=(1.0, 1.0, 1.0),
        direction=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
        plane=plane,
    )


def _axial_slice_stack() -> DicomSliceStack:
    slices = []
    for ordinal in range(1, 10):
        y, x = np.indices((128, 128), dtype=np.float32)
        slices.append(
            DicomSlice(
                pixels=ordinal * 11.0 + x * 0.8 + y * 0.4,
                position_lps=(0.0, 0.0, float(ordinal - 1)),
                orientation_lps=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
                pixel_spacing=(1.0, 1.0),
                source_ordinal=ordinal,
            )
        )
    return DicomSliceStack(tuple(slices), plane="axial")


def _source(role: str, path: Path, index: int) -> dict:
    path.mkdir(parents=True, exist_ok=True)
    return {
        "index": index,
        "series_uid": f"1.2.840.test.{index}",
        "series_number": index,
        "series_description": role,
        "protocol_name": role,
        "modality": "MR",
        "plane": "axial" if role == "axial_t2" else "sagittal",
        "slice_count": 9,
        "series_path": str(path),
    }


def _package(tmp_path: Path) -> llm_package.AnalysisPackage:
    root = tmp_path / "session"
    layout_dir = root / "Axial"
    layout_dir.mkdir(parents=True)
    images = []
    for frame in range(1, 7):
        path = layout_dir / f"axial_{frame:03d}.png"
        Image.fromarray(np.full((80, 80), frame * 20, dtype=np.uint8)).save(path)
        images.append(
            llm_package.PackagedImage(
                path=path,
                caption=f"[axial] frame {frame} of 6",
                session="axial",
                index=frame,
                capture={
                    "panes": {
                        "axial_t2": {
                            "slice_index": frame + 1,
                            "position": [0.0, 0.0, float(9 - frame)],
                        }
                    }
                },
            )
        )
    protocol = protocols.get_protocol("lumbar_mri")
    return llm_package.AnalysisPackage(
        session_dir=root,
        session_id="focused-v3-test",
        protocol_id=protocol.id,
        analysis=protocol.analysis,
        header=(
            "TEST CAPTURE PACKAGE\n"
            "  6 images follow, in capture order, each preceded by its caption."
        ),
        images=images,
        study_instance_uid="1.2.3",
        source_series={
            "sagittal_t2": _source("sagittal_t2", tmp_path / "private" / "sag-t2", 1),
            "sagittal_t1": _source("sagittal_t1", tmp_path / "private" / "sag-t1", 2),
            "axial_t2": _source("axial_t2", tmp_path / "private" / "ax-t2", 3),
        },
    )


@pytest.fixture()
def patched_volumes(monkeypatch):
    def load(candidate):
        if candidate.series_description == "sagittal_t1":
            return _volume("sagittal", 30.0)
        return _volume("sagittal", 10.0)

    monkeypatch.setattr(focus_evidence, "load_series_volume", load)
    monkeypatch.setattr(
        focus_evidence, "load_dicom_slice_stack", lambda _c: _axial_slice_stack()
    )


def _manifest(session_dir: Path, mode: str) -> dict:
    path = session_dir / ".evidence" / mode / focus_evidence.MANIFEST_NAME
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ profile --

def test_the_mode_selects_the_render_profile_and_nothing_else():
    v2 = focus_evidence._RenderProfile.for_mode(V2)
    v3 = focus_evidence._RenderProfile.for_mode(V3)
    assert v2.crop_to_spine is False
    assert v2.focus_tile == focus_evidence.TILE_SIZE
    assert v3.crop_to_spine is True
    assert v3.focus_tile == focus_evidence.FOCUS_TILE_SIZE_V3
    assert v3.focus_tile[0] > v2.focus_tile[0]
    # An unknown mode must fall back to V2 rather than crop by accident.
    assert focus_evidence._RenderProfile.for_mode("nonsense").mode == V2


def test_evidence_bundle_accepts_v3_and_leaves_the_package_for_verification():
    assert V3 in evidence_bundle.SUPPORTED_MODES
    assert V3 in evidence_bundle.VERIFICATION_ONLY_MODES
    package = object()
    assert evidence_bundle.prepare_package(package, mode=V3) is package


# --------------------------------------------------------------------- crop --

def test_the_crop_box_stays_inside_the_image_and_keeps_a_usable_minimum():
    box = focus_evidence._clamped_box(100, 100, 5.0, 5.0, 80, 80)
    assert box == (0, 0, 80, 80)
    box = focus_evidence._clamped_box(100, 100, 95.0, 95.0, 80, 80)
    assert box == (20, 20, 100, 100)
    # A request larger than the image degrades to the whole image - and the
    # image wins over the readable minimum, which would otherwise push the box
    # outside a slice smaller than MIN_ROI_PIXELS.
    assert focus_evidence._clamped_box(40, 40, 20.0, 20.0, 900, 900) == (0, 0, 40, 40)
    assert focus_evidence._clamped_box(20, 20, 10.0, 10.0, 4, 4) == (0, 0, 20, 20)
    # A tiny request never collapses below a readable tile.
    left, top, right, bottom = focus_evidence._clamped_box(200, 200, 100.0, 100.0, 2, 2)
    assert right - left >= focus_evidence.MIN_ROI_PIXELS
    assert bottom - top >= focus_evidence.MIN_ROI_PIXELS


@pytest.mark.parametrize("posterior_is_down, expect_below_centre", [(True, True), (False, False)])
def test_the_axial_crop_biases_posteriorly_using_the_direction_cosines(
    posterior_is_down, expect_below_centre
):
    """Bias must follow patient space, not an assumed array orientation."""
    column = (0.0, 1.0, 0.0) if posterior_is_down else (0.0, -1.0, 0.0)
    image_slice = DicomSlice(
        pixels=np.random.default_rng(0).random((500, 640)).astype(np.float32),
        position_lps=(0.0, 0.0, 0.0),
        orientation_lps=(1.0, 0.0, 0.0, *column),
        pixel_spacing=(0.3125, 0.3125),
        source_ordinal=1,
    )
    array = np.asarray(image_slice.pixels)
    cropped, box, spacing = focus_evidence._axial_roi(array, image_slice)
    centre_of_box = (box[1] + box[3]) / 2.0
    if expect_below_centre:
        assert centre_of_box > array.shape[0] / 2.0
    else:
        assert centre_of_box < array.shape[0] / 2.0
    # The box is the requested physical size, in pixels.
    assert cropped.shape[1] == pytest.approx(
        focus_evidence.AXIAL_ROI_MM[0] / 0.3125, abs=1)
    assert cropped.shape[0] == pytest.approx(
        focus_evidence.AXIAL_ROI_MM[1] / 0.3125, abs=1)
    assert spacing == (0.3125, 0.3125)


def test_the_crop_is_what_buys_the_resolution_back():
    """The real numbers from the 2026-08-30 case: 640x500 at 0.3125 mm/px."""
    whole_field = focus_evidence._effective_mm_per_pixel(
        (0, 0, 640, 500), (0.3125, 0.3125), focus_evidence.TILE_SIZE)
    assert whole_field == (0.7812, 0.7812)

    cropped = focus_evidence._effective_mm_per_pixel(
        (166, 82, 473, 415), (0.3125, 0.3125), focus_evidence.FOCUS_TILE_SIZE_V3)
    assert cropped == (0.3125, 0.3125)          # native - fit_grayscale never upscales
    assert cropped[0] < whole_field[0] / 2.0    # and better than twice as sharp


def test_a_sagittal_crop_centres_on_the_projected_point():
    volume = _volume("sagittal")
    array = np.asarray(volume.pixels[4])
    _cropped, box, spacing = focus_evidence._sagittal_roi(
        array, volume, (30.0, 90.0, 4.0), (40.0, 40.0))
    assert spacing == (1.0, 1.0)
    assert (box[0] + box[2]) / 2.0 == pytest.approx(30.0, abs=1.0)
    assert (box[1] + box[3]) / 2.0 == pytest.approx(90.0, abs=1.0)


# ---------------------------------------------------------------- end to end --

def test_v3_writes_its_own_evidence_folder_with_larger_audited_tiles(
    tmp_path, patched_volumes
):
    package = focus_evidence.prepare_verification_package(
        _package(tmp_path), _SCREENING,
        json.loads(_SCREENING.split("```json")[1].split("```")[0]),
        None, mode=V3,
    )
    session_dir = package.images[0].path.parents[2]
    assert (session_dir / ".evidence" / V3).is_dir()
    assert all(item.evidence_mode == V3 for item in package.images)

    manifest = _manifest(session_dir, V3)
    assert manifest["evidence_mode"] == V3
    profile = manifest["render_profile"]
    assert profile["crop_to_spine"] is True
    assert profile["focus_tile"] == list(focus_evidence.FOCUS_TILE_SIZE_V3)
    assert profile["axial_roi_mm"] == list(focus_evidence.AXIAL_ROI_MM)
    # The sagittal overview crop is tall and narrow; a square tile would let
    # the height set the scale and give the crop back almost nothing.
    assert profile["sagittal_overview_tile"] == list(
        focus_evidence.SAGITTAL_OVERVIEW_TILE_V3)
    assert profile["sagittal_overview_tile"][1] > profile["sagittal_overview_tile"][0]

    focus = manifest["focuses"][0]
    assert focus["tile_size"] == list(focus_evidence.FOCUS_TILE_SIZE_V3)
    # Every tile records the crop used and what one tile pixel is worth, so a
    # bad centre or a silent downscale is auditable after the fact.
    for tile in focus["sampling"]["axial"]:
        assert len(tile["crop_box"]) == 4
        assert len(tile["mm_per_pixel"]) == 2
    assert focus["sampling"]["sagittal"]
    assert manifest["overview_sampling"]["axial_overview"]


def test_the_v3_header_tells_the_model_the_field_was_cropped(tmp_path, patched_volumes):
    package = focus_evidence.prepare_verification_package(
        _package(tmp_path), _SCREENING,
        json.loads(_SCREENING.split("```json")[1].split("```")[0]),
        None, mode=V3,
    )
    assert "FOCUSED V3" in package.header
    assert "cropped to a fixed physical box" in package.header
    assert "not assessable" in package.header


def test_v2_is_untouched_by_the_v3_work(tmp_path, patched_volumes):
    package = focus_evidence.prepare_verification_package(
        _package(tmp_path), _SCREENING,
        json.loads(_SCREENING.split("```json")[1].split("```")[0]),
        None, mode=V2,
    )
    session_dir = package.images[0].path.parents[2]
    assert (session_dir / ".evidence" / V2).is_dir()
    assert not (session_dir / ".evidence" / V3).exists()
    assert all(item.evidence_mode == V2 for item in package.images)
    assert "FOCUSED V2" in package.header
    assert "cropped to a fixed physical box" not in package.header

    manifest = _manifest(session_dir, V2)
    assert manifest["render_profile"]["crop_to_spine"] is False
    assert manifest["render_profile"]["axial_roi_mm"] is None
    assert manifest["focuses"][0]["tile_size"] == list(focus_evidence.TILE_SIZE)

    sheet = Image.open(session_dir / ".evidence" / V2 / "sagittal_overview.png")
    assert sheet.width % focus_evidence.TILE_SIZE[0] == 0


def test_v3_defaults_off_so_the_switch_is_deliberate(monkeypatch):
    monkeypatch.delenv(evidence_bundle.ENV_EVIDENCE_MODE, raising=False)
    assert evidence_bundle.resolve_mode() == evidence_bundle.MODE_LAYOUT
    monkeypatch.setenv(evidence_bundle.ENV_EVIDENCE_MODE, V3)
    assert evidence_bundle.resolve_mode() == V3
