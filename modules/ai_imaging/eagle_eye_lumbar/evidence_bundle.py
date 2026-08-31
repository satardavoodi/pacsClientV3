"""Build focused Eagle Eye evidence images without changing source captures.

The source capture is a complete workstation layout because its localizer
lines are valuable spatial context. Sending that layout unchanged, however,
spends many of the available pixels on sidebar and viewer chrome. Focused V1
uses measured viewport rectangles from the capture manifest to create one
standardized evidence sheet per source frame:

* panes marked for evaluation receive most of the canvas;
* every localizer pane remains visible in a smaller context column;
* source order and image count are unchanged, so request behavior is bounded;
* the derived files are generated in the analysis worker and never overwrite
  the clinical source captures.

The feature is an explicit A/B switch. ``layout`` is the safe default and does
no image I/O. ``focused-v1`` is accepted only when every source frame carries
measured viewport bounds; legacy sessions fail clearly instead of guessing by
splitting a screenshot into thirds. ``focused-v2`` is deferred until screening
and context finish, then a separate service composes verification-only evidence
directly from immutable DICOM volumes.
"""

from __future__ import annotations

import os
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from .llm_package import AnalysisPackage, PackagedImage

logger = logging.getLogger(__name__)

ENV_EVIDENCE_MODE = "AIPACS_EAGLE_EYE_EVIDENCE_MODE"
MODE_LAYOUT = "layout"
MODE_FOCUSED_V1 = "focused-v1"
MODE_FOCUSED_V2 = "focused-v2"
# V3 is V2's geometry with the pixel budget spent on the lesion instead of the
# whole field of view: every tile is cropped to a physical box around the spine
# before it is scaled, and focus tiles are larger. See focus_evidence.
MODE_FOCUSED_V3 = "focused-v3"
MODE_FOCUSED_V3_PARASAGITTAL = "focused-v3-parasagittal"
VERIFICATION_ONLY_MODES = frozenset(
    (MODE_FOCUSED_V2, MODE_FOCUSED_V3, MODE_FOCUSED_V3_PARASAGITTAL)
)
SUPPORTED_MODES = frozenset(
    (MODE_LAYOUT, MODE_FOCUSED_V1, *VERIFICATION_ONLY_MODES)
)

MAX_CANVAS_WIDTH = 2048
MAX_CANVAS_HEIGHT = 1280

_BACKGROUND = (12, 15, 20)
_CELL_BACKGROUND = (4, 6, 9)
_BORDER = (78, 88, 102)
_TEXT = (238, 242, 247)
_DIAGNOSTIC = (63, 183, 116)
_LOCALIZER = (92, 143, 224)
_PADDING = 20
_GAP = 16
_LABEL_HEIGHT = 48


class EvidenceBundleError(RuntimeError):
    """The requested derivative cannot be built without guessing."""


def resolve_mode() -> str:
    """Resolve the strict evidence A/B switch from the runtime environment."""
    mode = (os.environ.get(ENV_EVIDENCE_MODE) or MODE_LAYOUT).strip().lower()
    if mode not in SUPPORTED_MODES:
        allowed = ", ".join(sorted(SUPPORTED_MODES))
        raise EvidenceBundleError(
            f"unsupported evidence mode '{mode}'; expected one of: {allowed}"
        )
    return mode


def normalized_bounds(x: float, y: float, width: float, height: float,
                      container_width: float,
                      container_height: float) -> Dict[str, float]:
    """Clip one widget rectangle and express it in capture-relative units."""
    try:
        cw = float(container_width)
        ch = float(container_height)
        left = max(0.0, min(cw, float(x)))
        top = max(0.0, min(ch, float(y)))
        right = max(0.0, min(cw, float(x) + float(width)))
        bottom = max(0.0, min(ch, float(y) + float(height)))
    except (TypeError, ValueError):
        return {}
    if cw <= 0 or ch <= 0 or right <= left or bottom <= top:
        return {}
    return {
        "x": round(left / cw, 8),
        "y": round(top / ch, 8),
        "width": round((right - left) / cw, 8),
        "height": round((bottom - top) / ch, 8),
    }


def prepare_package(package: AnalysisPackage, mode: str = "") -> AnalysisPackage:
    """Return the source package or a focused worker-side derivative."""
    selected = (mode or resolve_mode()).strip().lower()
    if selected not in SUPPORTED_MODES:
        raise EvidenceBundleError(f"unsupported evidence mode '{selected}'")
    if selected == MODE_LAYOUT or selected in VERIFICATION_ONLY_MODES:
        # V2 and V3 are candidate-directed. Screening and context must finish
        # before their verification-only package can be composed by
        # focus_evidence.
        return package

    output_root = package.session_dir / ".evidence" / MODE_FOCUSED_V1
    neighbors = _neighbor_indices(package.images)
    prepared: List[PackagedImage] = []

    for item in package.images:
        capture = item.capture or {}
        bounds = capture.get("viewport_bounds") or {}
        panes = capture.get("panes") or {}
        missing = [role for role in panes if role not in bounds]
        if not panes or missing:
            detail = ", ".join(missing) if missing else "all panes"
            raise EvidenceBundleError(
                f"{item.session} frame {item.index} has no measured viewport bounds "
                f"for {detail}; recapture it before using {MODE_FOCUSED_V1}"
            )

        session_dir = output_root / _safe_segment(item.session)
        destination = session_dir / f"{item.path.stem}_focused.png"
        _render_focused_image(item.path, destination, capture)

        previous_index, next_index = neighbors[(item.session, item.index)]
        adjacency = (
            "FOCUSED EVIDENCE V1; diagnostic panes enlarged; localizers retained; "
            f"previous source frame: {previous_index if previous_index is not None else 'none'}; "
            f"next source frame: {next_index if next_index is not None else 'none'}"
        )
        prepared.append(PackagedImage(
            path=destination,
            caption=f"[{adjacency}] {item.caption}",
            session=item.session,
            index=item.index,
            capture=capture,
            source_path=item.path,
            evidence_mode=MODE_FOCUSED_V1,
        ))

    header = (
        f"{package.header}\n"
        "  EVIDENCE MODE: FOCUSED V1. Each image is a deterministic derivative "
        "of exactly one source frame. Diagnostic panes are enlarged and all "
        "localizer panes are retained. Image count and capture order are unchanged."
    )
    logger.info(
        "[EAGLE-EYE-LLM] prepared %d focused evidence image(s) for dispatch",
        len(prepared),
    )
    return AnalysisPackage(
        session_dir=package.session_dir,
        session_id=package.session_id,
        protocol_id=package.protocol_id,
        analysis=package.analysis,
        header=header,
        images=prepared,
        study_instance_uid=package.study_instance_uid,
        source_series=package.source_series,
    )


def _neighbor_indices(images: Sequence[PackagedImage]) -> Dict[Tuple[str, int], Tuple[Any, Any]]:
    by_session: Dict[str, List[int]] = {}
    for item in images:
        by_session.setdefault(item.session, []).append(item.index)

    result: Dict[Tuple[str, int], Tuple[Any, Any]] = {}
    for session, indices in by_session.items():
        for position, index in enumerate(indices):
            previous_index = indices[position - 1] if position > 0 else None
            next_index = indices[position + 1] if position + 1 < len(indices) else None
            result[(session, index)] = (previous_index, next_index)
    return result


def _safe_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "session")).strip("._")
    return cleaned or "session"


def _pixel_box(bounds: Dict[str, Any], width: int, height: int) -> Tuple[int, int, int, int]:
    try:
        left = round(float(bounds["x"]) * width)
        top = round(float(bounds["y"]) * height)
        right = round((float(bounds["x"]) + float(bounds["width"])) * width)
        bottom = round((float(bounds["y"]) + float(bounds["height"])) * height)
    except (KeyError, TypeError, ValueError) as exc:
        raise EvidenceBundleError("invalid measured viewport bounds") from exc
    left = max(0, min(width, left))
    top = max(0, min(height, top))
    right = max(0, min(width, right))
    bottom = max(0, min(height, bottom))
    if right <= left or bottom <= top:
        raise EvidenceBundleError("measured viewport bounds resolve to an empty crop")
    return left, top, right, bottom


def _render_focused_image(source: Path, destination: Path,
                           capture: Dict[str, Any]) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
    except ImportError as exc:
        raise EvidenceBundleError("Pillow is unavailable for focused evidence") from exc

    panes = capture.get("panes") or {}
    bounds = capture.get("viewport_bounds") or {}
    evaluate = list(capture.get("reference_lines_hidden_on") or [])
    diagnostic_roles = [role for role in panes if role in evaluate]
    if not diagnostic_roles:
        driving = capture.get("driving_pane")
        diagnostic_roles = [driving] if driving in panes else [next(iter(panes))]
    localizer_roles = [role for role in panes if role not in diagnostic_roles]

    try:
        with Image.open(source) as opened:
            original = opened.convert("RGB")
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise EvidenceBundleError(f"could not read source image {source.name}: {exc}") from exc

    canvas = Image.new("RGB", (MAX_CANVAS_WIDTH, MAX_CANVAS_HEIGHT), _BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    try:
        label_font = ImageFont.load_default(size=20)
    except TypeError:
        label_font = ImageFont.load_default()
    cells = _layout_cells(len(diagnostic_roles), len(localizer_roles))
    temporary = None
    try:
        for role, cell in zip(diagnostic_roles, cells[0]):
            crop = original.crop(_pixel_box(bounds[role], original.width, original.height))
            try:
                _paste_cell(canvas, draw, crop, cell, panes.get(role) or {}, True,
                            label_font, ImageOps, Image)
            finally:
                crop.close()
        for role, cell in zip(localizer_roles, cells[1]):
            crop = original.crop(_pixel_box(bounds[role], original.width, original.height))
            try:
                _paste_cell(canvas, draw, crop, cell, panes.get(role) or {}, False,
                            label_font, ImageOps, Image)
            finally:
                crop.close()

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(
            f".{destination.name}.{uuid.uuid4().hex}.tmp")
        canvas.save(temporary, "PNG", optimize=True)
        os.replace(str(temporary), str(destination))
    except OSError as exc:
        raise EvidenceBundleError(f"could not write focused evidence {destination.name}: {exc}") from exc
    finally:
        original.close()
        canvas.close()
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _layout_cells(diagnostic_count: int, localizer_count: int):
    usable_left = _PADDING
    usable_top = _PADDING
    usable_right = MAX_CANVAS_WIDTH - _PADDING
    usable_bottom = MAX_CANVAS_HEIGHT - _PADDING

    if localizer_count:
        split = usable_left + round((usable_right - usable_left) * 0.78)
        diagnostic_area = (usable_left, usable_top, split - _GAP, usable_bottom)
        localizer_area = (split, usable_top, usable_right, usable_bottom)
    else:
        diagnostic_area = (usable_left, usable_top, usable_right, usable_bottom)
        localizer_area = (usable_right, usable_top, usable_right, usable_bottom)

    diagnostic_cells = _split_horizontally(diagnostic_area, diagnostic_count)
    localizer_cells = _split_vertically(localizer_area, localizer_count)
    return diagnostic_cells, localizer_cells


def _split_horizontally(area, count: int):
    if count <= 0:
        return []
    left, top, right, bottom = area
    available = (right - left) - _GAP * (count - 1)
    width = available / count
    return [
        (round(left + i * (width + _GAP)), top,
         round(left + i * (width + _GAP) + width), bottom)
        for i in range(count)
    ]


def _split_vertically(area, count: int):
    if count <= 0:
        return []
    left, top, right, bottom = area
    available = (bottom - top) - _GAP * (count - 1)
    height = available / count
    return [
        (left, round(top + i * (height + _GAP)), right,
         round(top + i * (height + _GAP) + height))
        for i in range(count)
    ]


def _paste_cell(canvas, draw, crop, cell, pane, diagnostic, label_font,
                image_ops, image_module):
    left, top, right, bottom = cell
    draw.rectangle(cell, fill=_CELL_BACKGROUND, outline=_BORDER, width=2)
    label = str(pane.get("label") or "Viewport")
    kind = "DIAGNOSTIC" if diagnostic else "LOCALIZER"
    color = _DIAGNOSTIC if diagnostic else _LOCALIZER
    draw.rectangle((left + 2, top + 2, right - 2, top + _LABEL_HEIGHT), fill=color)
    draw.text((left + 10, top + 13), f"{kind} - {label}",
              fill=_TEXT, font=label_font)

    image_box = (left + 4, top + _LABEL_HEIGHT + 4, right - 4, bottom - 4)
    target = (max(1, image_box[2] - image_box[0]),
              max(1, image_box[3] - image_box[1]))
    fitted = image_ops.contain(crop, target, method=image_module.Resampling.LANCZOS)
    try:
        x = image_box[0] + (target[0] - fitted.width) // 2
        y = image_box[1] + (target[1] - fitted.height) // 2
        canvas.paste(fitted, (x, y))
    finally:
        fitted.close()
