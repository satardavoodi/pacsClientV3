"""
Lesion Feature Store — durable, categorised per-lesion descriptors.

WHY THIS EXISTS (the radiologist's directive, 2026-07-15)
────────────────────────────────────────────────────────────────────────────────
Everything the 3D Cursor measures about a lesion — its GEOMETRY (nipple distance,
depth, the PNL/pectoral scale, height, pixel spacing) and its APPEARANCE (density
signature, texture, microcalcification constellation) — is currently computed to
solve ONE problem: matching the CC and MLO views of the SAME breast. Then it is
thrown away.

That is wasteful, because the SAME measurements answer a SECOND, independent
clinical question: is a finding real, judged by comparing one breast against the
CONTRALATERAL breast in the SAME view —

        Right-CC  vs  Left-CC          (same projection, opposite breast)
        Right-MLO vs  Left-MLO

A true lesion often has NO symmetric counterpart (an asymmetry), while benign
tissue usually does. So a lesion's stored descriptor lets us later ask "does the
mirror location in the other breast look similar?" — using geometry to find the
mirror location and appearance to judge similarity.

This module is the SINGLE PLACE those descriptors are preserved, so the data is
available for BOTH comparison families without recomputation.

WHAT IS STORED — one self-describing record per lesion
────────────────────────────────────────────────────────────────────────────────
Each `LesionFeatureRecord` carries its own identity (patient / study / series /
laterality / view / box), so a future consumer can pull every lesion for a patient
and pair them however it likes (CC↔MLO, or R↔L). The record is intentionally
OVER-complete: it stores raw geometry AND raw appearance, because which SUBSET is
valid depends on the comparison (see COMPARISON_FEATURE_APPLICABILITY below).

THE KEY INSIGHT — a feature's validity depends on the comparison
────────────────────────────────────────────────────────────────────────────────
  • CC↔MLO (same breast) is a ROTATION + non-rigid COMPRESSION change of view.
    Geometry must be transformed (PNL fractional depth); appearance must be
    ROTATION-INVARIANT (density, histogram, microcalc COUNT/size — not raw shape
    or spicule orientation, which rotate).

  • R↔L SAME-VIEW is a MIRROR. Both breasts are imaged the SAME way (same angle,
    same compression), so — after flipping the medial-lateral axis — geometry is
    DIRECTLY comparable (absolute nipple distance, not PNL-normalised) and
    appearance transfers ALMOST FULLY, INCLUDING shape and near-pixel texture that
    are unreliable cross-view. This is the EASIER appearance match.

So the same stored descriptor is consumed through two different feature masks.
COMPARISON_FEATURE_APPLICABILITY is that mask, made explicit and testable.

Purity: stdlib only (json, os, tempfile, uuid, dataclasses, datetime). No Qt, VTK,
numpy, pydicom. The appearance descriptor is passed in as a plain dict (computed by
`appearance_similarity.describe_region`, the numpy tier), so this store stays
headless-testable and never couples to the pixel layer.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


FEATURE_FILENAME = "mg_lesion_features.json"
SCHEMA_VERSION = 1


# ─── Comparison kinds ────────────────────────────────────────────────────────

CMP_CC_MLO_SAME_BREAST = "cc_mlo_same_breast"   # R-CC ↔ R-MLO (or L↔L): cross-view
CMP_RCC_LCC = "rcc_lcc_contralateral"           # R-CC ↔ L-CC: same view, mirror
CMP_RMLO_LMLO = "rmlo_lmlo_contralateral"       # R-MLO ↔ L-MLO: same view, mirror

COMPARISON_KINDS = (CMP_CC_MLO_SAME_BREAST, CMP_RCC_LCC, CMP_RMLO_LMLO)


# ─── Feature roles ───────────────────────────────────────────────────────────
# How much weight a given stored feature should carry for a given comparison.
PRIMARY = "primary"     # strong, first-class signal — drive the match with it
USEFUL = "useful"       # genuine independent signal — include it
WEAK = "weak"           # low reliability — use only as a tie-breaker
INVALID = "invalid"     # do NOT use — it does not transfer for this comparison


# ─── Geometry transforms ─────────────────────────────────────────────────────
# How the two lesions' GEOMETRY must be related before their features are compared.
GEOM_CROSS_VIEW_PNL = "cross_view_pnl"   # uncompress/rotate; depth via PNL fraction
GEOM_MIRROR_SAME_VIEW = "mirror_same_view"  # flip medial-lateral; absolute geometry


# ─── The applicability matrix — the categorisation the directive asked for ────
#
# For each comparison kind: the geometry transform, and the ROLE of every stored
# feature. This is the single source of truth for "which subset of the data is
# useful for which comparison", and it is asserted by the guard tests so it cannot
# silently drift.
#
# Rationale is attached per kind so the reasoning travels with the data.
COMPARISON_FEATURE_APPLICABILITY: Dict[str, Dict[str, Any]] = {

    # ── CC ↔ MLO, SAME breast (what the 3D Cursor does today) ────────────────
    CMP_CC_MLO_SAME_BREAST: {
        "geometry_transform": GEOM_CROSS_VIEW_PNL,
        "laterality": "same",
        "rationale": (
            "A rotation + non-rigid compression change of view. Depth must be "
            "renormalised by the PNL (fractional depth), radial nipple distance is "
            "approximately preserved, and superior-inferior height is largely "
            "UNOBSERVABLE from a single CC — so it is only a weak prior. Appearance "
            "must be rotation-invariant: density level, histogram shape and the "
            "microcalcification COUNT/size transfer; raw box shape and spicule "
            "orientation do NOT (they rotate/deform between views)."
        ),
        "features": {
            # geometry
            "pnl_fractional_depth": PRIMARY,   # depth / PNL — the view-stable scale
            "radial_distance_mm": PRIMARY,     # Kopans NOD, ~preserved
            "axial_depth_mm": USEFUL,          # SS component (used via PNL ratio)
            "pnl_length_mm": USEFUL,           # the per-view depth scale itself
            "height_mm": WEAK,                 # S-I unobservable in CC → weak prior
            "pectoral_angle_deg": WEAK,        # only defined in MLO
            # appearance
            "density_mean": PRIMARY,           # hyper/iso/hypo axis — rotation-free
            "histogram_shape": USEFUL,         # texture/heterogeneity — rotation-free
            "microcalc_count": PRIMARY,        # "4 dots → 4 dots" — very view-stable
            "microcalc_size_mm": USEFUL,       # calcification size — view-stable
            "microcalc_spacing_mm": USEFUL,    # cluster tightness — mostly stable
            "glcm_texture": USEFUL,            # rotation-AVERAGED Haralick only
            "first_order_skew_kurtosis": USEFUL,
            "box_shape_aspect": WEAK,          # compression differs per view
            "physical_size_mm2": USEFUL,       # size preserved better than shape
        },
    },

    # ── Right-CC ↔ Left-CC, CONTRALATERAL (same projection, mirror) ──────────
    CMP_RCC_LCC: {
        "geometry_transform": GEOM_MIRROR_SAME_VIEW,
        "laterality": "opposite",
        "rationale": (
            "A pure MIRROR: both breasts are imaged in the SAME CC projection, so "
            "after flipping the medial-lateral (x) axis the geometry is DIRECTLY "
            "comparable in ABSOLUTE terms — no PNL renormalisation. A true lesion "
            "typically has NO symmetric counterpart (asymmetry); benign tissue "
            "usually does. Because the projection is identical, appearance transfers "
            "ALMOST FULLY — including box shape and near-pixel texture that are "
            "unreliable cross-view — after exposure normalisation."
        ),
        "features": {
            # geometry — absolute, after mirroring x
            "radial_distance_mm": PRIMARY,     # same-view → directly comparable
            "axial_depth_mm": PRIMARY,         # absolute depth, not PNL-normalised
            "height_mm": PRIMARY,              # medial-lateral, mirrored → comparable
            "pnl_fractional_depth": USEFUL,    # still valid, but absolute is preferred
            "pnl_length_mm": USEFUL,           # symmetry check of the breast scale
            "pectoral_angle_deg": INVALID,     # pectoral not imaged in CC
            # appearance — same projection → nearly everything is valid
            "density_mean": PRIMARY,
            "histogram_shape": PRIMARY,
            "microcalc_count": PRIMARY,
            "microcalc_size_mm": PRIMARY,
            "microcalc_spacing_mm": PRIMARY,
            "glcm_texture": PRIMARY,           # same projection → full texture valid
            "first_order_skew_kurtosis": USEFUL,
            "box_shape_aspect": USEFUL,        # valid here (unlike cross-view)
            "physical_size_mm2": PRIMARY,
        },
    },

    # ── Right-MLO ↔ Left-MLO, CONTRALATERAL (same projection, mirror) ────────
    CMP_RMLO_LMLO: {
        "geometry_transform": GEOM_MIRROR_SAME_VIEW,
        "laterality": "opposite",
        "rationale": (
            "As R-CC↔L-CC, a MIRROR of the same (MLO) projection — but the pectoral "
            "muscle IS imaged, so the pectoral line / PNL and the superior-inferior "
            "height are BOTH directly comparable between the two MLOs (unlike "
            "CC↔MLO, where S-I is unobservable). The pectoral angle should be "
            "mirror-symmetric between a normal R and L MLO; a marked asymmetry there "
            "is itself a positioning/anatomy signal. Appearance transfers fully."
        ),
        "features": {
            # geometry — absolute, after mirroring x; MLO adds pectoral/height
            "radial_distance_mm": PRIMARY,
            "axial_depth_mm": PRIMARY,
            "height_mm": PRIMARY,              # superior-inferior, comparable in MLO↔MLO
            "pnl_length_mm": PRIMARY,          # pectoral-referenced, comparable
            "pectoral_angle_deg": USEFUL,      # should mirror between R and L MLO
            "pnl_fractional_depth": USEFUL,
            # appearance — same projection → nearly everything is valid
            "density_mean": PRIMARY,
            "histogram_shape": PRIMARY,
            "microcalc_count": PRIMARY,
            "microcalc_size_mm": PRIMARY,
            "microcalc_spacing_mm": PRIMARY,
            "glcm_texture": PRIMARY,
            "first_order_skew_kurtosis": USEFUL,
            "box_shape_aspect": USEFUL,
            "physical_size_mm2": PRIMARY,
        },
    },
}


def features_for_comparison(kind: str, *, roles: Optional[Tuple[str, ...]] = None) -> List[str]:
    """
    The stored-feature names that apply to a comparison `kind`, optionally filtered
    to a set of roles (e.g. `(PRIMARY,)` for the strong signals only).

    Excludes INVALID features always. Raises KeyError on an unknown kind — a typo
    must fail loudly, not silently return nothing.
    """
    spec = COMPARISON_FEATURE_APPLICABILITY[kind]["features"]
    wanted = roles if roles is not None else (PRIMARY, USEFUL, WEAK)
    return [name for name, role in spec.items() if role != INVALID and role in wanted]


def geometry_transform_for(kind: str) -> str:
    """The geometry transform ('cross_view_pnl' | 'mirror_same_view') for a kind."""
    return COMPARISON_FEATURE_APPLICABILITY[kind]["geometry_transform"]


# ─── The stored record ───────────────────────────────────────────────────────

@dataclass
class LesionGeometryFeatures:
    """
    All the mm-space quantities the geometry pipeline already computes for a lesion.

    Stored RAW (per-view, un-normalised) so any consumer can apply whichever
    transform its comparison needs — cross-view PNL normalisation OR same-view
    mirroring. `pnl_fractional_depth` is the one derived convenience (depth / PNL),
    because it is the single most reused cross-view quantity.
    """
    center_px: Optional[Tuple[float, float]] = None
    nipple_px: Optional[Tuple[float, float]] = None
    pixel_spacing_mm: Optional[Tuple[float, float]] = None
    radial_distance_mm: Optional[float] = None      # nipple→lesion straight line (Kopans)
    axial_depth_mm: Optional[float] = None          # perpendicular (chest-wall-normal) depth
    height_mm: Optional[float] = None               # signed along chest wall (CC:med-lat, MLO:sup-inf)
    pnl_length_mm: Optional[float] = None           # nipple→pectoral/chest-wall (the depth scale)
    pnl_fractional_depth: Optional[float] = None     # axial_depth / pnl_length (view-stable)
    pectoral_angle_deg: Optional[float] = None
    # DICOM positioning metadata — reserved (the near-optimal geometry refinement
    # from step 1/2). None until wired; stored here so the schema is future-proof.
    positioner_primary_angle_deg: Optional[float] = None
    body_part_thickness_mm: Optional[float] = None
    physical_size_mm2: Optional[float] = None
    box_shape_aspect: Optional[float] = None


@dataclass
class LesionFeatureRecord:
    """
    One lesion, fully described and self-identifying.

    Identity is complete on purpose: a future contralateral pass loads EVERY record
    for `patient_id`, groups by `view_position`, and pairs `laterality` R with L —
    none of which is possible if the record only knew its study.
    """
    lesion_uid: str
    patient_id: str
    study_uid: str
    laterality: str                 # 'R' | 'L'
    view_position: str              # 'CC' | 'MLO'
    box_px: List[float]             # [x1, y1, x2, y2] — the lesion bounding box
    origin: str = "picked"          # 'picked' (source) | 'predicted' | 'candidate'
    score: float = 0.5              # AI/detector confidence when available
    classification: Optional[str] = None
    series_uid: Optional[str] = None

    geometry: LesionGeometryFeatures = field(default_factory=LesionGeometryFeatures)
    # The appearance/pattern descriptor dict from appearance_similarity.describe_region
    # (first-order, GLCM texture, microcalc constellation, lesion-type). None when
    # pixels were not available at persist time (geometry is still stored).
    appearance: Optional[Dict[str, Any]] = None

    schema_version: int = SCHEMA_VERSION
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @staticmethod
    def new_uid() -> str:
        return uuid.uuid4().hex[:12]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─── Persistence (per study, atomic, never fatal) ────────────────────────────

def features_path(study_uid: str, attachments_path: str) -> str:
    return os.path.join(str(attachments_path), str(study_uid), FEATURE_FILENAME)


def load_lesion_features(study_uid: str, attachments_path: str) -> List[Dict[str, Any]]:
    """Return the raw lesion-feature dicts for a study. Never raises."""
    path = features_path(study_uid, attachments_path)
    try:
        if not os.path.isfile(path):
            return []
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        recs = data.get("lesions", [])
        return recs if isinstance(recs, list) else []
    except Exception:
        return []


def save_lesion_feature(record: LesionFeatureRecord, attachments_path: str) -> Optional[str]:
    """
    Append (or replace-by-lesion_uid) one lesion record. Atomic write; NEVER raises.

    Persistence failure must never break the clinical workflow — the correspondence
    result is already on screen; losing a descriptor is a lost future data point, not
    a danger. Returns the file path on success, None on failure.
    """
    try:
        if not attachments_path:
            return None
        path = features_path(record.study_uid, attachments_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)

        existing = load_lesion_features(record.study_uid, attachments_path)
        payload = record.to_dict()
        replaced = False
        for i, r in enumerate(existing):
            if r.get("lesion_uid") == record.lesion_uid:
                existing[i] = payload
                replaced = True
                break
        if not replaced:
            existing.append(payload)

        doc = {"schema_version": SCHEMA_VERSION, "lesions": existing}
        directory = os.path.dirname(path)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass
        return path
    except Exception as exc:  # noqa: BLE001 — persistence must never be fatal
        print(f"[3D-Cursor][FEATURES] save failed (non-fatal): {exc}")
        return None


def load_features_for_patient(
    patient_id: str,
    attachments_path: str,
) -> List[Dict[str, Any]]:
    """
    Every stored lesion for a patient, across all their studies — the entry point
    for a future contralateral (R↔L) or prior-exam comparison. Scans the per-study
    files under `attachments_path` and filters by `patient_id`. Never raises.

    This is deliberately a plain scan (no index): the store is small (a handful of
    lesions per study) and correctness/robustness matter more than speed here.
    """
    out: List[Dict[str, Any]] = []
    try:
        root = str(attachments_path)
        if not os.path.isdir(root):
            return out
        for entry in os.listdir(root):
            study_dir = os.path.join(root, entry)
            if not os.path.isdir(study_dir):
                continue
            for rec in load_lesion_features(entry, attachments_path):
                if str(rec.get("patient_id", "")) == str(patient_id):
                    out.append(rec)
    except Exception:
        return out
    return out


# ─── Same-view mirror helper (for the future R↔L consumer) ───────────────────

def mirror_x_px(x_px: float, image_width_px: float) -> float:
    """
    Reflect an x pixel coordinate across the image's vertical centre line.

    A Right and a Left mammogram of the same view are mirror images: the chest wall
    is on opposite edges. To compare a lesion's position between them, one view's x
    is reflected so both are expressed in the same medial-lateral frame. Pure.
    """
    return float(image_width_px) - float(x_px)


def contralateral_pair_kind(view_position: str) -> Optional[str]:
    """
    The comparison kind for a same-view R↔L pairing of `view_position`, or None if
    the view is not one we mirror. Small mapping so callers don't hard-code strings.
    """
    v = (view_position or "").upper()
    if v == "CC":
        return CMP_RCC_LCC
    if v == "MLO":
        return CMP_RMLO_LMLO
    return None
