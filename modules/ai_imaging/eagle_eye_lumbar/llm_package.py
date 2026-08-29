"""Turn a finished Eagle Eye capture session into an ordered LLM request.

The model must receive the session STRUCTURE, not a bag of screenshots: which
sweep each frame belongs to, where it sits in that sweep, which pane is being
evaluated and which is only a localiser. All of that is already recorded in the
manifests, so this module reads them rather than the folder listing - a package
built from a glob would look identical and prove nothing about ordering.

WHAT THIS MODULE REFUSES TO DO
------------------------------
It will not build a package from an incomplete session. The manifest's
``capture_count`` is compared against the frames actually on disk, and a short
session raises. This is the same rule the capture side already learned the hard
way: a partial sweep is made of individually valid frames, so nothing but the
COUNT reveals it, and a partial study analysed as if it were whole produces a
confident report about anatomy nobody looked at.

Pure python: no Qt, no network, no model knowledge.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .constants import EAGLE_EYE_VERSION, MANIFEST_JSON, SESSION_JSON

logger = logging.getLogger(__name__)

# The patient identity sent with the request. The screenshots carry whatever the
# workstation burns into them; this is about the STRUCTURED metadata, which
# needs no identity at all for the model to read the images.
ANONYMOUS_PATIENT_ID = "PID 0"

_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


class PackageError(RuntimeError):
    """The session on disk cannot be turned into a valid request."""


def mime_for(path: Path) -> str:
    """MIME type from the file suffix.

    The pre-existing single-image helpers in EchoMind hardcode
    ``data:image/jpeg`` regardless of the file. Eagle Eye writes PNG, so that
    would mislabel every frame; derive it instead.
    """
    return _MIME_BY_SUFFIX.get(path.suffix.lower(), "application/octet-stream")


class PackagedImage:
    """One screenshot plus the caption that tells the model what it is."""

    __slots__ = ("path", "caption", "session", "index", "capture",
                 "source_path", "evidence_mode")

    def __init__(self, path: Path, caption: str, session: str, index: int,
                 capture: Optional[Dict[str, Any]] = None,
                 source_path: Optional[Path] = None,
                 evidence_mode: str = "layout"):
        self.path = Path(path)
        self.caption = str(caption)
        self.session = str(session)
        self.index = int(index)
        # Plain manifest data only. It lets the worker derive a focused image
        # without re-reading the manifests that the GUI-side fail-fast package
        # builder has already validated.
        self.capture = dict(capture or {})
        self.source_path = Path(source_path) if source_path is not None else self.path
        self.evidence_mode = str(evidence_mode or "layout")

    @property
    def mime(self) -> str:
        return mime_for(self.path)

    def as_dict(self, root: Optional[Path] = None) -> Dict[str, Any]:
        try:
            name = str(self.path.relative_to(root)) if root else self.path.name
        except ValueError:
            name = self.path.name
        document = {
            "session": self.session,
            "index": self.index,
            "file": name.replace("\\", "/"),
            "caption": self.caption,
        }
        if self.evidence_mode != "layout" or self.source_path != self.path:
            try:
                source = (str(self.source_path.relative_to(root)) if root
                          else self.source_path.name)
            except ValueError:
                source = self.source_path.name
            document["evidence_mode"] = self.evidence_mode
            document["source_file"] = source.replace("\\", "/")
        return document


class AnalysisPackage:
    """Everything one analysis request needs, in the order it must be sent."""

    __slots__ = ("session_dir", "session_id", "protocol_id", "analysis",
                 "header", "images", "study_instance_uid")

    def __init__(self, session_dir: Path, session_id: str, protocol_id: str,
                 analysis, header: str, images: Sequence[PackagedImage],
                 study_instance_uid: str = ""):
        self.session_dir = Path(session_dir)
        self.session_id = str(session_id)
        self.protocol_id = str(protocol_id)
        # An `analysis_prompt.AnalysisPipeline` - the ordered passes. The
        # package itself is stage-agnostic: the same images and captions go to
        # every stage, and only the system prompt and the carried-over context
        # differ.
        self.analysis = analysis
        self.header = str(header)
        self.images = list(images)
        self.study_instance_uid = str(study_instance_uid or "")

    @property
    def image_count(self) -> int:
        return len(self.images)

    def request_document(self, stage, model: str = "", backend: str = "",
                         context: str = "") -> Dict[str, Any]:
        """What ONE stage sends, written beside the captures.

        Split deliberately into what was SENT and local provenance. The sent
        half is the reproducible input - prompt text, header, every caption,
        and for a later stage the context carried in from the previous one.
        Provenance holds the real study UID so a stored result can be traced
        back to the study; it is not part of the request.
        """
        return {
            "eagle_eye_version": EAGLE_EYE_VERSION,
            "created_at": _utc_now_iso(),
            "session_id": self.session_id,
            "protocol_id": self.protocol_id,
            "model": str(model or ""),
            "backend": str(backend or ""),
            "pipeline": self.analysis.as_dict(),
            "prompt": dict(stage.as_dict(), text=stage.text),
            "patient": {"patient_id": ANONYMOUS_PATIENT_ID},
            "sent": {
                "header": self.header,
                "context": str(context or ""),
                "image_count": self.image_count,
                "images": [img.as_dict(self.session_dir) for img in self.images],
            },
            "local_provenance": {
                "study_instance_uid": self.study_instance_uid,
                "session_dir": str(self.session_dir),
            },
        }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise PackageError(f"{path.name} is missing from the session") from exc
    except (OSError, ValueError) as exc:
        raise PackageError(f"{path.name} could not be read: {exc}") from exc


def _fmt(value: Any, digits: int = 1) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "?"


def _pane_phrase(role: str, pane: Dict[str, Any], clean: bool) -> str:
    """One pane of one frame, described the way the model must read it."""
    label = pane.get("label") or role
    notes = ["EVALUATE - no reference line"] if clean else ["localiser - reference line drawn"]

    if pane.get("parked"):
        notes.append("parked for the whole sweep")

    match = pane.get("match") or {}
    if pane.get("role") == "synced" and match:
        notes.append(f"position-matched to {_fmt(match.get('distance_mm'), 2)} mm")

    return f"{label} slice #{pane.get('slice_index')} ({', '.join(notes)})"


_ESTIMATE_CAVEAT = ("GEOMETRY ESTIMATE of where the SLICE lies, "
                    "not a zone assignment for any finding")


def _slice_position_phrase(spatial: Dict[str, Any]) -> str:
    """Where this sagittal slice sits, said in a way that cannot be misread.

    The stored `side` is already 'midline' inside the central band, so
    "midline of midline" is what a naive format produces; and the signed offset
    beside the word "right" reads as a contradiction. Say the distance from the
    midline, unsigned, with the side named once.
    """
    side = str(spatial.get("side") or "").strip()
    distance = _fmt(abs(float(spatial.get("offset_mm") or 0.0)), 1)
    if side in ("", "midline"):
        where = f"slice position at the midline ({distance} mm off centre)"
    else:
        where = f"slice position {distance} mm {side} of the midline"
    return f"{where} - {_ESTIMATE_CAVEAT}"


def _caption_for(manifest: Dict[str, Any], capture: Dict[str, Any],
                 total: int) -> str:
    """The text that travels with one image."""
    order = manifest.get("capture_order") or {}
    session_label = str(manifest.get("session_type") or order.get("session") or "session")
    driving = capture.get("driving_pane")
    clean = set(capture.get("reference_lines_hidden_on") or [])
    panes = capture.get("panes") or {}

    # Driving pane first, then the rest in manifest order - the model should
    # read the sentence in the same priority the sweep had.
    ordering = ([driving] if driving in panes else []) + [k for k in panes if k != driving]
    pane_text = " | ".join(_pane_phrase(role, panes[role], role in clean)
                           for role in ordering)

    bits = [f"[{session_label}] frame {capture.get('index')} of {total}",
            f"sweep direction {order.get('direction') or 'unknown'}",
            pane_text]

    spatial = capture.get("spatial_context") or {}
    if spatial:
        bits.append(_slice_position_phrase(spatial))

    axial = capture.get("axial_context") or {}
    if axial:
        bits.append("axial z = {} mm ({} mm below the top of the axial stack)".format(
            _fmt(axial.get("z_lps"), 1), _fmt(axial.get("mm_below_top"), 1)))

    return "; ".join(bits)


#: A gap this many times the typical within-slab step marks a slab boundary.
#: Measured separation on a real `t2_tse_tra_msma` study is wide: 4.3-5.3 mm
#: inside a slab against 9.5-41.6 mm between them, so 1.5x sits in open space on
#: both sides. Raising it risks merging two levels; lowering it risks splitting
#: one - and a wrong boundary is worse than none, which is why a stack with no
#: clear gaps produces NO slab line at all rather than an invented structure.
_SLAB_GAP_FACTOR = 1.5


def _axial_slabs(captures) -> List[Tuple[int, int]]:
    """Group axial frames into acquisition slabs, from the DICOM z-positions.

    THE MODELS MUST NOT SOLVE THIS BY EYE. An angled multi-slab lumbar axial is
    a run of closely spaced slices at one disc, then a jump to the next - and
    the jump is a measured number sitting in the header, not something to infer
    from a few-hundred-pixel screenshot. Two models asked to find the boundaries
    visually returned two different answers on the same study
    (session 20260826T205136Z), which is how a finding ends up reported one
    level off.

    Returns inclusive 1-based ``(first_frame, last_frame)`` ranges in the SAME
    numbering the captions use, or ``[]`` when the stack has no clear slab
    structure (a uniformly spaced series) - in which case nothing is claimed.
    """
    ordered: List[Tuple[int, float]] = []
    for capture in captures or []:
        axial = capture.get("axial_context") or {}
        z = axial.get("z_lps")
        index = capture.get("index")
        if z is None or index is None:
            return []
        try:
            ordered.append((int(index), float(z)))
        except (TypeError, ValueError):
            return []

    if len(ordered) < 4:
        return []
    ordered.sort(key=lambda pair: pair[0])

    gaps = [abs(ordered[i][1] - ordered[i - 1][1]) for i in range(1, len(ordered))]
    steps = sorted(gaps)
    typical = steps[len(steps) // 2]
    if typical <= 0:
        return []

    slabs: List[Tuple[int, int]] = []
    start = ordered[0][0]
    for position, gap in enumerate(gaps, start=1):
        if gap > typical * _SLAB_GAP_FACTOR:
            slabs.append((start, ordered[position - 1][0]))
            start = ordered[position][0]
    slabs.append((start, ordered[-1][0]))

    # One group is not a structure: a uniformly spaced stack tells the model
    # nothing it could not see, and printing "1 slab" invites it to treat the
    # whole study as one level.
    return slabs if len(slabs) > 1 else []


def _slab_lines(slabs: List[Tuple[int, int]]) -> List[str]:
    """The header block that hands the measured structure to every stage."""
    if not slabs:
        return []
    ranges = " | ".join(f"{first}-{last}" if first != last else str(first)
                        for first, last in slabs)
    return [
        f"  AXIAL SLAB STRUCTURE (measured from the DICOM slice positions):",
        f"    {len(slabs)} slabs, by frame number as used in the captions below:",
        f"    {ranges}",
        "    These boundaries are MEASURED, not estimated. Use them as given and",
        "    do not re-derive them by eye. Angled multi-slab lumbar axials are",
        "    prescribed one slab per disc level, so treat each group as one level",
        "    unless the images clearly contradict it. Assigning the LEVEL NAMES",
        "    is still yours; the grouping is not.",
    ]


def _session_header(manifest: Dict[str, Any], directory: str) -> str:
    order = manifest.get("capture_order") or {}
    clean = ", ".join(order.get("reference_lines_hidden_on") or []) or "none"
    reference = ", ".join(order.get("reference_slots") or []) or "none"
    synced = ", ".join(order.get("synced_slots") or []) or "none"
    return (
        f"  {directory}: {manifest.get('capture_count')} frames, "
        f"driven by {order.get('driving_slot')}, "
        f"direction {order.get('direction')} along {order.get('axis')}.\n"
        f"    evaluate (no reference line): {clean}\n"
        f"    synced to the driving pane: {synced}\n"
        f"    localisers (reference line drawn): {reference}"
    )


def _layout_line(session_doc: Dict[str, Any]) -> str:
    layout = session_doc.get("layout") or {}
    viewports = layout.get("viewports") or []
    if not viewports:
        return "  layout: unknown"
    panes = ", ".join(f"panel {v.get('position')} = {v.get('slot')}" for v in viewports)
    return (f"  layout: {layout.get('rows')} x {layout.get('columns')} - {panes}")


def build_package(session_dir, protocol=None) -> AnalysisPackage:
    """Read a finished session directory into an ordered, captioned package.

    ``protocol`` supplies the prompt. When omitted it is resolved from the
    session's own ``protocol_id``, so a package can be rebuilt later from the
    directory alone - which is what a retry does.
    """
    root = Path(session_dir)
    session_doc = _load_json(root / SESSION_JSON)

    protocol_id = str(session_doc.get("protocol_id") or session_doc.get("session_kind") or "")
    if protocol is None:
        from .protocols import get_protocol
        protocol = get_protocol(protocol_id)
    if protocol is None:
        raise PackageError(f"no protocol registered for '{protocol_id}'")
    if protocol.analysis is None:
        raise PackageError(f"protocol '{protocol.id}' has no analysis prompt")

    passes = session_doc.get("passes") or {}
    if not passes:
        raise PackageError("the session records no capture passes")

    header_lines: List[str] = [
        f"EAGLE EYE CAPTURE PACKAGE - {protocol.name} ({protocol.modality})",
        f"  patient: {ANONYMOUS_PATIENT_ID}",
        f"  session: {session_doc.get('session_id')}",
        _layout_line(session_doc),
        "  sessions, in the order their images follow:",
    ]
    images: List[PackagedImage] = []

    for name, spec in passes.items():
        directory = str(spec.get("directory") or name.title())
        manifest = _load_json(root / directory / MANIFEST_JSON)
        captures = manifest.get("captures") or []

        declared = int(manifest.get("capture_count") or 0)
        if declared != len(captures):
            raise PackageError(
                f"{directory}: manifest declares {declared} captures but lists "
                f"{len(captures)}; refusing to analyse an inconsistent session")

        header_lines.append(_session_header(manifest, directory))

        # Only the sweep that MOVES through the axial stack has a slab
        # structure. The sagittal sweep parks the axial pane on one slice, so
        # every one of its captures carries the same z and `_axial_slabs`
        # correctly finds no structure there.
        header_lines.extend(_slab_lines(_axial_slabs(captures)))

        total = len(captures)
        for capture in captures:
            path = root / directory / str(capture.get("image") or "")
            if not path.is_file():
                raise PackageError(
                    f"{directory}/{capture.get('image')} is listed in the manifest "
                    f"but missing on disk; refusing to analyse a partial session")
            images.append(PackagedImage(
                path=path,
                caption=_caption_for(manifest, capture, total),
                session=name,
                index=int(capture.get("index") or 0),
                capture=capture,
            ))

    if not images:
        raise PackageError("the session contains no captured frames")

    header_lines.append(
        f"  {len(images)} images follow, in capture order, each preceded by its caption.")

    package = AnalysisPackage(
        session_dir=root,
        session_id=str(session_doc.get("session_id") or ""),
        protocol_id=protocol.id,
        analysis=protocol.analysis,
        header="\n".join(header_lines),
        images=images,
        study_instance_uid=str(session_doc.get("study_instance_uid") or ""),
    )
    logger.info("[EAGLE-EYE-LLM] packaged %d image(s) from %s",
                package.image_count, package.session_id)
    return package
