"""Bound untrusted model attention hints into a deterministic evidence plan."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional


SCHEMA_VERSION = "1.0.0"
ALLOWED_LEVELS = (
    "T12-L1",
    "L1-L2",
    "L2-L3",
    "L3-L4",
    "L4-L5",
    "L5-S1",
)
_LEVEL_RANK = {level: index for index, level in enumerate(ALLOWED_LEVELS)}
_LEVEL_PATTERN = re.compile(
    r"\b(T12\s*[-–—/]\s*L1|L[1-4]\s*[-–—/]\s*L[2-5]|L5\s*[-–—/]\s*S1)\b",
    re.IGNORECASE,
)
_LEVEL_MAP_LINE = re.compile(
    r"^\s*(T12\s*[-–—/]\s*L1|L[1-4]\s*[-–—/]\s*L[2-5]|L5\s*[-–—/]\s*S1)"
    r"\s*:\s*axial\s+frames?\s+(\d+)\s*(?:[-–—]\s*(\d+))?",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class EvidenceFocus:
    """One allowlisted anatomical focus, independent of model wording."""

    focus_id: str
    level: str
    family: str
    confidence: str
    sources: tuple[str, ...]
    questions: tuple[str, ...]
    key_axial_frames: tuple[int, ...]


@dataclass(frozen=True)
class EvidencePlan:
    """Versioned local execution plan for focused-v2 composition."""

    schema_version: str
    focuses: tuple[EvidenceFocus, ...]
    level_frames: Dict[str, tuple[int, int]]
    warnings: tuple[str, ...]


def normalize_level(value: Any) -> str:
    match = _LEVEL_PATTERN.search(str(value or ""))
    if not match:
        return ""
    return re.sub(r"\s*[-–—/]\s*", "-", match.group(1).upper())


def parse_level_map(screening_text: str) -> Dict[str, tuple[int, int]]:
    """Parse only the explicit level-map grammar emitted by the screening stage."""
    result: Dict[str, tuple[int, int]] = {}
    for match in _LEVEL_MAP_LINE.finditer(str(screening_text or "")):
        level = normalize_level(match.group(1))
        first = max(1, int(match.group(2)))
        last = max(first, int(match.group(3) or first))
        if level and level not in result:
            result[level] = (first, last)
    return result


def _text(value: Any, limit: int = 180) -> str:
    return " ".join(str(value or "").split())[:limit]


def _confidence(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in {"high", "moderate", "low"} else "low"


def _family(candidate: Any, context_type: Any = "") -> str:
    token = str(candidate or "").strip().lower()
    if any(part in token for part in ("disc", "bulge", "protrusion", "extrusion")):
        return "disc_displacement"
    if any(part in token for part in ("canal", "recess", "foramin", "root", "cauda")):
        return "neural_compromise"
    if any(part in token for part in ("marrow", "modic", "endplate", "vertebral", "osteophyte")):
        return "osseous_endplate"
    if any(part in token for part in ("facet", "ligament", "synovial")):
        return "posterior_element"
    if any(part in token for part in ("listhesis", "alignment", "scoliosis")):
        return "alignment"
    context = str(context_type or "").strip().lower()
    if context in {"traumatic", "neoplastic", "postoperative", "inflammatory_or_infectious"}:
        return context
    if context in {"degenerative", "discogenic"}:
        return "degenerative"
    return "other"


def _screening_rows(structured: Optional[Dict[str, Any]]) -> Iterable[dict]:
    findings = (structured or {}).get("findings")
    if not isinstance(findings, list):
        return ()
    return (item for item in findings[:64] if isinstance(item, dict))


def _positive_frames(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    result = []
    for item in value[:5]:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in result:
            result.append(number)
    return tuple(result)


def _context_rows(structured: Optional[Dict[str, Any]]) -> Iterable[dict]:
    rows = (structured or {}).get("context_attention_foci")
    if not isinstance(rows, list):
        return ()
    return (
        item
        for item in rows[:8]
        if isinstance(item, dict)
        and str(item.get("scope") or "").strip().lower() in {"regional", "level_specific"}
    )


def build_evidence_plan(
    screening_text: str,
    screening_structured: Optional[Dict[str, Any]],
    context_structured: Optional[Dict[str, Any]],
    *,
    max_focuses: int = 4,
) -> EvidencePlan:
    """Merge screening and context attention without accepting executable orders."""
    grouped: Dict[str, dict] = {}
    warnings = []

    for row in _screening_rows(screening_structured):
        level = normalize_level(row.get("level"))
        if not level:
            warnings.append("screening_focus_without_allowlisted_level")
            continue
        entry = grouped.setdefault(
            level,
            {"families": [], "confidences": [], "sources": [], "questions": []},
        )
        entry["families"].append(_family(row.get("candidate")))
        entry["confidences"].append(_confidence(row.get("confidence")))
        entry["sources"].append("screening_candidate")
        note = _text(row.get("note"))
        if note:
            entry["questions"].append(note)
        key_frames = row.get("key_frames")
        if isinstance(key_frames, dict):
            entry.setdefault("key_axial_frames", []).extend(
                _positive_frames(key_frames.get("axial"))
            )

    for row in _context_rows(context_structured):
        level = normalize_level(row.get("anatomic_focus"))
        if not level:
            warnings.append("context_focus_without_allowlisted_level")
            continue
        entry = grouped.setdefault(
            level,
            {"families": [], "confidences": [], "sources": [], "questions": []},
        )
        entry["families"].append(_family("", row.get("context_type")))
        entry["confidences"].append(_confidence(row.get("confidence")))
        entry["sources"].append("context_attention_focus")
        questions = row.get("verification_questions")
        if isinstance(questions, list):
            entry["questions"].extend(_text(item) for item in questions[:4] if _text(item))

    confidence_rank = {"high": 0, "moderate": 1, "low": 2}
    family_rank = {
        "neoplastic": 0,
        "traumatic": 1,
        "inflammatory_or_infectious": 2,
        "disc_displacement": 3,
        "neural_compromise": 4,
        "postoperative": 5,
    }

    def priority(item: tuple[str, dict]) -> tuple[int, int, int]:
        level, entry = item
        confidence = min(entry["confidences"], key=lambda value: confidence_rank[value])
        family = min(entry["families"], key=lambda value: family_rank.get(value, 9))
        return confidence_rank[confidence], family_rank.get(family, 9), _LEVEL_RANK[level]

    focuses = []
    for ordinal, (level, entry) in enumerate(
        sorted(grouped.items(), key=priority)[: max(0, int(max_focuses))], start=1
    ):
        confidence = min(entry["confidences"], key=lambda value: confidence_rank[value])
        family = min(entry["families"], key=lambda value: family_rank.get(value, 9))
        focuses.append(
            EvidenceFocus(
                focus_id=f"focus-{ordinal:02d}",
                level=level,
                family=family,
                confidence=confidence,
                sources=tuple(dict.fromkeys(entry["sources"])),
                questions=tuple(dict.fromkeys(entry["questions"]))[:4],
                key_axial_frames=tuple(
                    dict.fromkeys(entry.get("key_axial_frames", ()))
                )[:5],
            )
        )

    if len(grouped) > len(focuses):
        warnings.append("focus_limit_applied")
    return EvidencePlan(
        schema_version=SCHEMA_VERSION,
        focuses=tuple(focuses),
        level_frames=parse_level_map(screening_text),
        warnings=tuple(dict.fromkeys(warnings)),
    )
