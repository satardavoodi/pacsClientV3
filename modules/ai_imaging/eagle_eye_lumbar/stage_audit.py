"""Read-only inventory of model-facing Eagle Eye stage images.

The analysis pipeline writes immutable, session-relative artifacts.  This module
turns those files into a small presentation model without importing Qt and
without exposing source DICOM or external attachment paths.  The result panel
uses it to show exactly which derived images entered each model boundary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from modules.ai_imaging.eagle_eye.card_templates import list_card_templates


@dataclass(frozen=True)
class StageAuditImage:
    path: Path
    label: str
    details: str = ""


@dataclass(frozen=True)
class StageAuditSection:
    key: str
    title: str
    status: str
    summary: str
    images: tuple[StageAuditImage, ...] = ()


@dataclass(frozen=True)
class StageAudit:
    session_dir: Path
    sections: tuple[StageAuditSection, ...]


_SCREENING_BRANCHES = tuple(
    (f"screening_{template.key}", f"Screening - {template.display_name}")
    for template in list_card_templates(
        modality="mri", body_part="lumbar_spine", family="screening"
    )
)
_HISTORICAL_SCREENING_BRANCHES = (
    (
        "screening_foraminal_posterior_elements",
        "Historical screening - foramina and posterior elements",
    ),
)
_HISTORICAL_SCREENING_KEYS = frozenset(
    key for key, _title in _HISTORICAL_SCREENING_BRANCHES
)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _session_file(root: Path, value: Any) -> Path | None:
    """Resolve only regular files contained by the selected session."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        resolved_root = root.resolve()
        candidate = Path(text)
        if not candidate.is_absolute():
            candidate = resolved_root / candidate
        resolved = candidate.resolve()
        resolved.relative_to(resolved_root)
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def _image_records(document: dict[str, Any]) -> list[dict[str, Any]]:
    sent = document.get("sent")
    if isinstance(sent, dict) and isinstance(sent.get("images"), list):
        return [item for item in sent["images"] if isinstance(item, dict)]
    evidence = document.get("evidence")
    if isinstance(evidence, dict) and isinstance(evidence.get("images"), list):
        return [item for item in evidence["images"] if isinstance(item, dict)]
    return []


def _request_images(root: Path, document: dict[str, Any]) -> tuple[StageAuditImage, ...]:
    images = []
    for position, item in enumerate(_image_records(document), start=1):
        path = None
        for key in ("audit_file", "file", "source_file", "path"):
            path = _session_file(root, item.get(key))
            if path is not None:
                break
        if path is None:
            continue
        caption = str(item.get("caption") or "").strip()
        source_kind = str(item.get("source_kind") or "").strip()
        label = caption.split(";")[0].strip() if caption else ""
        if not label:
            label = source_kind.replace("_", " ").title() or f"Image {position}"
        details = caption
        images.append(StageAuditImage(path, label, details))
    return tuple(images)


def _deduplicate_images(images: Iterable[StageAuditImage]) -> tuple[StageAuditImage, ...]:
    output = []
    seen = set()
    for item in images:
        key = str(item.path).casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return tuple(output)


def _envelope_status(document: dict[str, Any]) -> str:
    if bool(document.get("truncated")):
        return "truncated"
    if bool(document.get("parsed")):
        return "ready"
    if document:
        return "unavailable"
    return "not run"


def _screening_summary(request: dict[str, Any], envelope: dict[str, Any]) -> str:
    records = _image_records(request)
    produced = int(envelope.get("completion_tokens") or 0)
    maximum = int(envelope.get("max_output_tokens") or 0)
    data = envelope.get("data")
    findings = data.get("findings") if isinstance(data, dict) else None
    parts = [f"Input images: {len(records)}"]
    if produced or maximum:
        parts.append(f"Output allowance used: {produced}/{maximum}")
    if isinstance(findings, list):
        parts.append(f"Abnormal attention records: {len(findings)}")
    elif envelope:
        parts.append("No usable structured findings")
    return " | ".join(parts)


def _anatomy_summary(stage1: dict[str, Any]) -> str:
    data = stage1.get("data")
    level_map = data.get("level_map") if isinstance(data, dict) else None
    if isinstance(level_map, list) and level_map:
        lines = [
            "Anatomical level assignment retained from the focused screening "
            "handoff. Each range identifies the axial capture frames assigned "
            "to that lumbar level."
        ]
        for row in level_map:
            if not isinstance(row, dict):
                continue
            level = str(row.get("level") or "unassigned")
            frames = row.get("axial_frames")
            if isinstance(frames, (list, tuple)) and len(frames) == 2:
                lines.append(f"{level}: axial frames {frames[0]}-{frames[1]}")
            else:
                lines.append(f"{level}: axial frames unavailable")
        return "\n".join(lines)
    templates = data.get("level_card_templates") if isinstance(data, dict) else None
    if not isinstance(templates, list) or not templates:
        return (
            "No dedicated anatomical-map result is stored for this session. "
            "The screening branches inferred their own level assignments."
        )
    lines = [
        "This map was derived from the screening handoff; it was not produced by "
        "a separate anatomy-only gate."
    ]
    for template in templates:
        if not isinstance(template, dict):
            continue
        level = str(template.get("level") or "unassigned")
        slots = template.get("slots")
        slot_values = []
        if isinstance(slots, dict):
            for role, raw in slots.items():
                item = raw if isinstance(raw, dict) else {}
                tile_id = str(item.get("tile_id") or "unassigned")
                slot_values.append(f"{role} = {tile_id}")
        lines.append(f"{level}: " + ("; ".join(slot_values) or "no mapped slots"))
    return "\n".join(lines)


def _anatomy_gate_summary(envelope: dict[str, Any]) -> str:
    data = envelope.get("data") if isinstance(envelope, dict) else None
    levels = data.get("axial_levels") if isinstance(data, dict) else None
    sagittal = data.get("sagittal_planes") if isinstance(data, dict) else None
    parts = []
    if isinstance(levels, list):
        parts.append(f"Mapped axial levels: {len(levels)}")
        for row in levels:
            if not isinstance(row, dict):
                continue
            frames = row.get("axial_frames")
            if isinstance(frames, (list, tuple)) and len(frames) == 2:
                parts.append(
                    f"{row.get('level') or 'unassigned'}: axial frames {frames[0]}-{frames[1]}"
                )
    if isinstance(sagittal, dict):
        parts.append(f"Mapped sagittal sequences: {len(sagittal)}")
    if envelope:
        parts.append(f"Status: {_envelope_status(envelope)}")
    return " | ".join(parts) or "No dedicated anatomy-only map is stored."


def _anatomy_card_images(root: Path) -> tuple[tuple[StageAuditImage, ...], dict[str, Any]]:
    manifest_path = root / ".evidence" / "anatomy-gate-v4" / "anatomy_manifest.json"
    if not manifest_path.is_file():
        # Historical sessions remain inspectable; runtime construction never
        # falls back to a superseded anatomy gate.
        for historical_mode in (
            "anatomy-gate-v3", "anatomy-gate-v2", "anatomy-gate-v1"
        ):
            historical = root / ".evidence" / historical_mode / "anatomy_manifest.json"
            if historical.is_file():
                manifest_path = historical
                break
    manifest = _read_json(manifest_path)
    images = []
    for record in manifest.get("cards") or ():
        if not isinstance(record, dict):
            continue
        path = _session_file(root, manifest_path.parent / str(record.get("image_file") or ""))
        if path is None:
            continue
        request_key = str(record.get("request_key") or "unassigned")
        images.append(StageAuditImage(
            path,
            request_key.replace("_", " ").title(),
            f"Anatomy-only card | Tiles: {record.get('tile_count', 0)} | Normality not assessed",
        ))
    return tuple(images), manifest


def _find_card_manifest(root: Path) -> Path | None:
    candidates = sorted((root / ".evidence").glob("*/evidence_manifest.json"))
    for path in candidates:
        document = _read_json(path)
        if isinstance(document.get("card_bindings"), list):
            return path
    return None


def _card_images(root: Path) -> tuple[tuple[StageAuditImage, ...], dict[str, Any]]:
    manifest_path = _find_card_manifest(root)
    if manifest_path is None:
        return (), {}
    manifest = _read_json(manifest_path)
    images = []
    for binding in manifest.get("card_bindings") or ():
        if not isinstance(binding, dict):
            continue
        sidecar_name = binding.get("card_json_file")
        sidecar = _session_file(root, manifest_path.parent / str(sidecar_name or ""))
        sidecar_document = _read_json(sidecar) if sidecar is not None else {}
        image_name = sidecar_document.get("image_file")
        image_path = _session_file(root, manifest_path.parent / str(image_name or ""))
        if image_path is None:
            focus_id = str(binding.get("focus_id") or "")
            matches = sorted(manifest_path.parent.glob(f"{focus_id}_*.png")) if focus_id else []
            image_path = matches[0].resolve() if matches else None
        if image_path is None:
            continue
        index = binding.get("image_index")
        level = str(binding.get("subject_level") or "unassigned")
        group = str(binding.get("structure_group") or "unassigned").replace("_", " ")
        frames = [str(value) for value in binding.get("allowed_axial_frames") or ()]
        details = f"Subject level: {level} | Structure group: {group}"
        if frames:
            details += " | Axial frames " + ", ".join(frames)
        attention = [str(value) for value in binding.get("attention_ids") or ()]
        if attention:
            details += " | Attention: " + ", ".join(attention)
        images.append(StageAuditImage(
            image_path,
            f"Card {index} - {level} - {group}",
            details,
        ))
    return tuple(images), manifest


def _atomic_diagnostic_inputs(
    root: Path,
) -> tuple[tuple[StageAuditImage, ...], str, str]:
    directory = root / ".atomic_analysis" / "stage3"
    requests = sorted(directory.glob("*_request.json"))
    if not requests:
        return (), "not run", ""
    images = []
    statuses = []
    for request_path in requests:
        key = request_path.name.removesuffix("_request.json")
        request = _read_json(request_path)
        envelope = _read_json(directory / f"{key}_structured.json")
        status = _envelope_status(envelope)
        statuses.append(status)
        for item in _request_images(root, request):
            details = f"Atomic request: {key} | Status: {status}"
            if item.details:
                details += f"\n{item.details}"
            images.append(StageAuditImage(item.path, f"{key} - {item.label}", details))
    if "truncated" in statuses:
        overall = "truncated"
    elif all(status == "ready" for status in statuses):
        overall = "ready"
    else:
        overall = "unavailable"
    ready = sum(status == "ready" for status in statuses)
    truncated = sum(status == "truncated" for status in statuses)
    summary = (
        f"Atomic diagnostic requests: {len(requests)} | Exact input images: "
        f"{len(images)} | Structured responses: {ready}"
    )
    if truncated:
        summary += f" | Truncated responses: {truncated}"
    return tuple(images), overall, summary


def build_stage_audit(session_dir: str | Path) -> StageAudit:
    """Build a safe, deterministic stage inventory for one stored session."""
    root = Path(session_dir).resolve()
    atomic_root = root / ".atomic_analysis" / "stage1"
    anatomy_request = _read_json(atomic_root / "anatomy_mapping_request.json")
    anatomy_envelope = _read_json(atomic_root / "anatomy_mapping_structured.json")
    anatomy_source_images = _request_images(root, anatomy_request)
    screening_sections = []
    atlas_images = []
    for key, title in (*_SCREENING_BRANCHES, *_HISTORICAL_SCREENING_BRANCHES):
        request = _read_json(atomic_root / f"{key}_request.json")
        envelope = _read_json(atomic_root / f"{key}_structured.json")
        if key in _HISTORICAL_SCREENING_KEYS and not (request or envelope):
            continue
        images = _request_images(root, request)
        atlas_images.extend(images)
        screening_sections.append(StageAuditSection(
            key,
            title,
            _envelope_status(envelope),
            _screening_summary(request, envelope),
            images,
        ))

    stage1 = _read_json(root / "llm_stage1_structured.json")
    stage1_data = stage1.get("data") or {}
    anatomy_status = (
        "derived"
        if stage1_data.get("level_map") or stage1_data.get("level_card_templates")
        else "unavailable"
    )
    anatomy = StageAuditSection(
        "anatomy_map",
        "Gate 1 - anatomy mapping input and map",
        _envelope_status(anatomy_envelope) if anatomy_envelope else anatomy_status,
        (
            _anatomy_gate_summary(anatomy_envelope)
            if anatomy_envelope else _anatomy_summary(stage1)
        ),
        anatomy_source_images or _deduplicate_images(atlas_images),
    )

    anatomy_card_images, _anatomy_card_manifest = _anatomy_card_images(root)
    anatomy_cards = StageAuditSection(
        "anatomy_cards",
        "Gate 1 to Gate 2 - anatomical cards",
        "ready" if anatomy_card_images else "unavailable",
        (
            f"Anatomy-only cards built: {len(anatomy_card_images)} | "
            "Pathology and normality were not assessed during card construction."
        ),
        anatomy_card_images,
    )

    context_request = _read_json(root / "llm_stage2_request.json")
    context_envelope = _read_json(root / "llm_stage2_structured.json")
    context_images = _request_images(root, context_request)
    context = StageAuditSection(
        "clinical_context",
        "Clinical-context inputs",
        _envelope_status(context_envelope),
        f"Input images available for audit: {len(context_images)}",
        context_images,
    )

    cards, manifest = _card_images(root)
    warnings = [str(value) for value in manifest.get("warnings") or ()]
    budget = manifest.get("budget") if isinstance(manifest.get("budget"), dict) else {}
    card_summary = f"Diagnostic cards built: {len(cards)}"
    if budget:
        card_summary += (
            f" | Package images: {budget.get('image_count', 0)}/"
            f"{budget.get('max_images', 0)}"
        )
    if warnings:
        card_summary += " | Warnings: " + ", ".join(warnings)
    cards_section = StageAuditSection(
        "diagnostic_cards",
        "Gated diagnostic cards",
        "ready" if cards else "unavailable",
        card_summary,
        cards,
    )

    atomic_images, atomic_status, atomic_summary = _atomic_diagnostic_inputs(root)
    verification_request = _read_json(root / "llm_stage3_request.json")
    verification_envelope = _read_json(root / "llm_stage3_structured.json")
    verification_images = (
        atomic_images or _request_images(root, verification_request) or cards
    )
    verification_status = (
        atomic_status if atomic_images else _envelope_status(verification_envelope)
    )
    verification_summary = atomic_summary or (
        f"Images sent in the diagnostic request: {len(verification_images)} | "
        f"Structured decisions available: "
        f"{len(((verification_envelope.get('data') or {}).get('verifications') or []))}"
    )
    verification = StageAuditSection(
        "diagnostic_model_input",
        "Diagnostic-model input",
        verification_status,
        verification_summary,
        verification_images,
    )

    return StageAudit(
        root,
        (
            anatomy,
            anatomy_cards,
            *screening_sections,
            context,
            cards_section,
            verification,
        ),
    )
