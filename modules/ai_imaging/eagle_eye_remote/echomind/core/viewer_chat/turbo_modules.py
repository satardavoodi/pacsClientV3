# -*- coding: utf-8 -*-
"""The region-module registry — `(modality, region) -> package`.

WHY THIS FILE EXISTS. `turbo_region_modules.REGION_MODULES` was implicitly CT-only:
nothing in its name or its lookup said so, and the prompt builder gated on a literal
`== "CT"` a few files away. Adding MRI is the moment that has to become explicit,
because the alternative is two libraries with the same function names and a caller
that guesses.

This module is hand-written and deliberately tiny. The libraries themselves are
GENERATED (`tools/dev/gen_turbo_modules.py`, `tools/dev/gen_turbo_mri_modules.py`);
a registry that were also generated would have nowhere to record why a modality is
absent.

ABSENT MODALITIES ARE ABSENT ON PURPOSE. Mammography has no library yet, so
`modules_for()` returns `[]` for it and the prompt builder falls back to the full
shared prompt. That fallback is the contract: never a narrower prompt than the caller
would otherwise have sent.

THE SECOND AXIS. `subtypes_for()` selects study-type packages. Region is WHERE the
study looked; subtype is WHAT KIND of study it is. Obstetric ultrasound forced the
distinction and radiography needs it most: a hysterosalpingogram, a barium enema and
a colon transit study are all abdominopelvic and share nothing else, and a bone age,
a skeletal survey and a standing alignment film are all skeletal and share nothing
else.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


def _libraries() -> Dict[str, dict]:
    """Imported lazily so a syntax error in one generated library cannot stop the
    other from loading, and cannot break the Turbo button at import time."""
    out: Dict[str, dict] = {}
    try:
        from .turbo_region_modules import REGION_MODULES
        out["CT"] = REGION_MODULES
    except Exception as exc:                      # pragma: no cover - defensive
        logger.warning("[Turbo-modules] CT library unavailable: %s", exc)
    try:
        from .turbo_mri_modules import MRI_MODULES
        out["MRI"] = MRI_MODULES
    except Exception as exc:                      # pragma: no cover - defensive
        logger.warning("[Turbo-modules] MRI library unavailable: %s", exc)
    try:
        from .turbo_xr_modules import XR_MODULES
        out["RADIOLOGY"] = XR_MODULES
    except Exception as exc:                      # pragma: no cover - defensive
        logger.warning("[Turbo-modules] radiography library unavailable: %s", exc)
    try:
        from .turbo_us_modules import US_MODULES
        out["SONOGRAPHY"] = US_MODULES
    except Exception as exc:                      # pragma: no cover - defensive
        logger.warning("[Turbo-modules] ultrasound library unavailable: %s", exc)
    return out


def normalise_modality(modality) -> str:
    """The library key for a modality string, or ``""`` when there is no library."""
    m = str(modality or "").strip().upper()
    if m in ("MR", "MRI"):
        return "MRI"
    if m == "CT":
        return "CT"
    # The modality menu says RADIOLOGY; DICOM says CR, DX or DR; people say
    # X-ray. They are the same library.
    if m in ("RADIOLOGY", "RADIOGRAPHY", "CR", "DX", "DR", "XR", "X-RAY", "XRAY"):
        return "RADIOLOGY"
    if m in ("SONOGRAPHY", "ULTRASOUND", "US", "OBSTETRIC ULTRASOUND",
             "OB ULTRASOUND", "PREGNANCY ULTRASOUND", "FETAL ULTRASOUND"):
        return "SONOGRAPHY"
    return ""


def supported_modalities() -> Tuple[str, ...]:
    """Modalities that have a region-module library, in a stable order."""
    return tuple(sorted(_libraries()))


def library_for(modality) -> dict:
    """The `{region_key: package}` map for a modality, or an empty dict."""
    return _libraries().get(normalise_modality(modality), {})


def module_for(modality, region):
    """One package, or None."""
    return library_for(modality).get(str(region or "").strip().lower())


def modules_for(modality, regions) -> List[dict]:
    """Packages for these regions, in gate order, de-duplicated by title.

    De-duplication is by title rather than by key because two keys legitimately share
    one package — `pelvis` and `prostate` on CT, `head_neck` and `thyroid` on both.
    Emitting the same block twice would give the model two identical reporting orders
    and no reason to prefer either.
    """
    lib = library_for(modality)
    if not lib:
        return []
    out, seen = [], set()
    for r in regions or []:
        m = lib.get(str(r or "").strip().lower())
        if m and m["title"] not in seen:
            seen.add(m["title"])
            out.append(m)
    return out


def _subtype_libraries():
    out = {}
    try:
        from .turbo_us_modules import US_SUBTYPE_PACKAGES
        out["SONOGRAPHY"] = US_SUBTYPE_PACKAGES
    except Exception as exc:                      # pragma: no cover - defensive
        logger.warning("[Turbo-modules] ultrasound subtypes unavailable: %s", exc)
    try:
        from .turbo_xr_modules import XR_SUBTYPE_PACKAGES
        out["RADIOLOGY"] = XR_SUBTYPE_PACKAGES
    except Exception as exc:                      # pragma: no cover - defensive
        logger.warning("[Turbo-modules] radiography subtypes unavailable: %s", exc)
    return out


def subtypes_for(modality, subtypes) -> List[dict]:
    """Study-type packages for these subtypes, in order, de-duplicated by title.

    Empty for every modality but ultrasound, and for most ultrasound studies too — a
    subtype is an addition to the region context, never a replacement for it.
    """
    lib = _subtype_libraries().get(normalise_modality(modality), {})
    if not lib:
        return []
    out, seen = [], set()
    for s in subtypes or []:
        p = lib.get(str(s or "").strip().lower())
        if p and p["title"] not in seen:
            seen.add(p["title"])
            out.append(p)
    return out


def known_subtypes(modality) -> Tuple[str, ...]:
    return tuple(sorted(_subtype_libraries().get(normalise_modality(modality), {})))
