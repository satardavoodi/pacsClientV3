"""Load and validate a radiologist reference read for one benchmark case.

Reference reads are the ground truth the bench scores against. They live
outside the repository, under ``user_data/ai/eagle_eye/_bench/ground_truth``
(gitignored), because they are tied to a real study; this module and every
other file in ``tools/eagle_eye_bench`` stay free of patient data.

A reference is written once, by a radiologist, from full-resolution DICOM -
never from a pipeline output. Scoring a model against a reference derived from
its own earlier answer measures nothing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from .scoring import LEVELS, MORPHOLOGY_ORDER, ROOT_EFFECT_ORDER, SEVERITY_ORDER

SCHEMA_VERSION = "1.0.0"

_STRUCTURES = ("lateral_recess", "central_canal", "neural_foramen")


def default_root() -> Path:
    """``user_data/ai/eagle_eye/_bench/ground_truth`` via the app data paths."""
    try:
        from PacsClient.utils.data_paths import AI_DIR
        base = Path(AI_DIR) / "eagle_eye"
    except Exception:
        base = Path(os.getcwd()) / "user_data" / "ai" / "eagle_eye"
    return base / "_bench" / "ground_truth"


def available(root: Path | None = None) -> List[str]:
    directory = Path(root) if root is not None else default_root()
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.json"))


def load(case_id: str, root: Path | None = None) -> Dict[str, Any]:
    directory = Path(root) if root is not None else default_root()
    path = directory / f"{case_id}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"No reference read for case '{case_id}' in {directory}. "
            f"Available: {', '.join(available(directory)) or 'none'}"
        )
    document = json.loads(path.read_text(encoding="utf-8"))
    problems = validate(document)
    if problems:
        raise ValueError(
            "Reference read is malformed:\n  - " + "\n  - ".join(problems)
        )
    return document


def validate(document: Dict[str, Any]) -> List[str]:
    """Structural problems that would make scoring meaningless."""
    problems: List[str] = []
    if not str(document.get("case_id", "")).strip():
        problems.append("case_id is missing")
    if str(document.get("schema_version", "")) != SCHEMA_VERSION:
        problems.append(
            f"schema_version must be {SCHEMA_VERSION}, got "
            f"{document.get('schema_version')!r}"
        )
    if not str(document.get("recorded_by", "")).strip():
        problems.append(
            "recorded_by is missing - a reference with no attributed reader "
            "cannot be trusted as ground truth"
        )

    levels = document.get("levels")
    if not isinstance(levels, dict) or not levels:
        problems.append("levels is missing or empty")
        return problems

    for level, entry in levels.items():
        if level not in LEVELS:
            problems.append(f"unknown level {level!r}")
            continue
        if not isinstance(entry, dict):
            problems.append(f"{level}: entry must be an object")
            continue
        if entry.get("normal"):
            continue
        disc = entry.get("disc") or {}
        if disc:
            morphology = disc.get("morphology")
            if morphology not in MORPHOLOGY_ORDER:
                problems.append(
                    f"{level}: disc.morphology must be one of {MORPHOLOGY_ORDER}, "
                    f"got {morphology!r}"
                )
            if disc.get("side") not in (None, "", "left", "right", "bilateral", "central"):
                problems.append(f"{level}: disc.side {disc.get('side')!r} is not a side")
        for structure in _STRUCTURES:
            want = entry.get(structure)
            if want is None:
                continue
            if not isinstance(want, dict):
                problems.append(f"{level}.{structure}: must be an object")
                continue
            if want.get("severity") and want["severity"] not in SEVERITY_ORDER:
                problems.append(
                    f"{level}.{structure}.severity must be one of {SEVERITY_ORDER}"
                )
        root = entry.get("root")
        if root is not None:
            if not isinstance(root, dict):
                problems.append(f"{level}.root: must be an object")
            elif root.get("effect") not in ROOT_EFFECT_ORDER:
                problems.append(
                    f"{level}.root.effect must be one of {ROOT_EFFECT_ORDER}"
                )

    for entry in (document.get("endplates") or []):
        if not entry.get("accept_levels"):
            problems.append(
                f"endplate {entry.get('vertebra')!r}: accept_levels is required - a "
                "vertebral endplate borders two disc levels and the report names "
                "levels, not vertebrae"
            )
    return problems


def critical_claims(document: Dict[str, Any]) -> List[str]:
    """Claim ids the reference marks as must-not-miss."""
    out: List[str] = []
    for level, entry in (document.get("levels") or {}).items():
        if (entry.get("disc") or {}).get("critical"):
            out.append(f"{level}/disc/morphology")
        for structure in _STRUCTURES:
            if (entry.get(structure) or {}).get("critical"):
                out.append(f"{level}/{structure}")
        if (entry.get("root") or {}).get("critical"):
            out.append(f"{level}/root")
    return out
