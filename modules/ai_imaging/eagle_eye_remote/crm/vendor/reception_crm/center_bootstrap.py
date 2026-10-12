"""Discover and maintain one installation's centre/service vocabulary.

The installer can be built once, but departments and service names are policy
owned by each centre.  This module turns the reception software on *this*
machine into durable, reviewable configuration without ever writing to the
vendor database.

There are deliberately two trust levels:

* ``center_config.json`` is deterministic evidence read from the local CRM.
* ``service_concepts.candidates.json`` is an LLM proposal and is NEVER active
  until an administrator promotes named concepts.  A plausible synonym can
  widen a clinical cohort, so model output is not configuration authority.
"""

from __future__ import annotations

import hashlib
import csv
import io
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .lexicon.normalize import fold
from .runtime import config_root

CENTER_CONFIG_FILENAME = "center_config.json"
ACTIVE_CONCEPTS_FILENAME = "service_concepts.json"
CANDIDATE_CONCEPTS_FILENAME = "service_concepts.candidates.json"
BOOTSTRAP_MANIFEST_FILENAME = "center_bootstrap.json"
CENTER_PROFILE_FILENAME = "center_profile.md"
SERVICE_CATALOG_CSV_FILENAME = "service_catalog.csv"

MAX_CONCEPTS = 120
MAX_ALIASES_PER_CONCEPT = 24
MAX_MATCH_TERMS_PER_CONCEPT = 16
MAX_EVIDENCE_SERVICES = 24
MAX_LLM_CATALOG_CHARS = 120_000
SAFE_SHORT_ALIASES = frozenset({"ct", "mr", "us", "xr"})

_CONCEPT_ID = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


class CenterBootstrapError(RuntimeError):
    """The deterministic centre bootstrap could not be completed safely."""


class ConceptProposalError(CenterBootstrapError):
    """The LLM proposal did not satisfy the candidate schema/evidence rules."""


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise CenterBootstrapError(f"cannot read {path}: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise CenterBootstrapError(f"{path} must contain a JSON object")
    return payload


def _atomic_write(path: Path, text: str) -> None:
    """Replace one derived/config artifact without exposing a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _clean_strings(
    values: Any,
    *,
    maximum: int,
    field: str,
    max_length: int = 120,
    allowed_short: frozenset[str] = frozenset(),
) -> list[str]:
    if not isinstance(values, list):
        raise CenterBootstrapError(f"{field} must be a list")
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        key = fold(value)
        if (len(key) < 3 and key not in allowed_short) or len(value) > max_length:
            raise CenterBootstrapError(f"{field} contains an unsafe value: {value!r}")
        if key not in seen:
            seen.add(key)
            output.append(value)
    if not output or len(output) > maximum:
        raise CenterBootstrapError(f"{field} must contain 1..{maximum} unique values")
    return output


def validate_active_concepts(payload: Any, *, center: str = "") -> list[dict[str, Any]]:
    """Validate configuration that is allowed to affect clinical queries."""
    if isinstance(payload, dict):
        configured_center = str(payload.get("center") or "").strip()
        if center and configured_center and configured_center.casefold() != center.casefold():
            raise CenterBootstrapError(
                f"service concepts belong to {configured_center!r}, not {center!r}"
            )
        raw_concepts = payload.get("concepts")
    else:
        raw_concepts = payload
    if raw_concepts is None:
        raw_concepts = []
    if not isinstance(raw_concepts, list) or len(raw_concepts) > MAX_CONCEPTS:
        raise CenterBootstrapError(f"concepts must be a list of at most {MAX_CONCEPTS}")

    concepts: list[dict[str, Any]] = []
    ids: set[str] = set()
    alias_owners: dict[str, str] = {}
    for index, raw in enumerate(raw_concepts):
        if not isinstance(raw, dict):
            raise CenterBootstrapError(f"concepts[{index}] must be an object")
        concept_id = str(raw.get("id") or "").strip()
        if not _CONCEPT_ID.fullmatch(concept_id) or concept_id in ids:
            raise CenterBootstrapError(f"invalid or duplicate concept id: {concept_id!r}")
        label_fa = str(raw.get("label_fa") or "").strip()
        if not label_fa or len(label_fa) > 120:
            raise CenterBootstrapError(f"concept {concept_id!r} needs a short label_fa")
        aliases = _clean_strings(
            raw.get("aliases"), maximum=MAX_ALIASES_PER_CONCEPT,
            field=f"concept {concept_id}.aliases",
            allowed_short=SAFE_SHORT_ALIASES,
        )
        match_terms = _clean_strings(
            raw.get("match_terms"), maximum=MAX_MATCH_TERMS_PER_CONCEPT,
            field=f"concept {concept_id}.match_terms",
        )
        for alias in aliases:
            key = fold(alias)
            owner = alias_owners.get(key)
            if owner and owner != concept_id:
                raise CenterBootstrapError(
                    f"alias {alias!r} is assigned to both {owner!r} and {concept_id!r}"
                )
            alias_owners[key] = concept_id
        ids.add(concept_id)
        concepts.append({
            "id": concept_id,
            "label_fa": label_fa,
            "aliases": aliases,
            "match_terms": match_terms,
        })
    return concepts


def discover_center_config(
    database: Any,
    *,
    center: str,
    database_name: str,
    service_concepts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Read departments/groups/services from a local Mongo database.

    ``database`` may be the project's read-only facade or a raw pymongo
    database used by the standalone generation script.  Only find operations
    are performed in either case.
    """
    center_name = str(center or "").strip()
    if not center_name:
        raise CenterBootstrapError("center name is required")

    departments = []
    for row in database["Modality"].find({}):
        departments.append({
            "code": str(row.get("_id")),
            "short": row.get("Modality"),
            "name_en": row.get("FullName"),
            "name_fa": row.get("PerFullName"),
            "disabled": bool(row.get("Disabled")),
            "requires_scheduling": bool(row.get("RequiresScheduling")),
        })
    if not departments:
        raise CenterBootstrapError("the local Modality catalogue is empty")
    known_departments = {row["code"] for row in departments}

    groups = []
    for row in database["ServicesGroupInfo"].find({}):
        groups.append({
            "id": str(row.get("_id")),
            "department": str(row.get("Modality")),
            "name": row.get("Name"),
        })

    services = []
    for row in database["ServicesInfo"].find({}):
        name = str(row.get("Service") or "").strip()
        if not name:
            continue
        services.append({
            "id": str(row.get("_id")),
            "name": name,
            "department": str(row.get("Modality")),
            "group_id": str(row.get("Group")) if row.get("Group") else None,
            "group_name": row.get("ServiceGroup"),
            "internal_name": row.get("internalName") or None,
            "internal_code": row.get("internalCode") or None,
        })
    if not services:
        raise CenterBootstrapError("the local ServicesInfo catalogue is empty")

    referenced = {
        row["department"] for row in services
    } | {row["department"] for row in groups}
    orphan_departments = sorted(referenced - known_departments - {"None"})
    services_per_department: dict[str, int] = {}
    for service in services:
        code = service["department"]
        services_per_department[code] = services_per_department.get(code, 0) + 1

    return {
        "_about": (
            "Generated from this installation's local reception database. "
            "Departments are centre policy; services are the work performed."
        ),
        "schema_version": 2,
        "center": center_name,
        "database": database_name,
        "generated_at": _now(),
        "service_concepts": service_concepts,
        "departments": sorted(
            departments, key=lambda row: (not row["code"].isdigit(), row["code"])
        ),
        "service_groups": sorted(
            groups, key=lambda row: (row["department"], str(row.get("name") or ""))
        ),
        "services": sorted(
            services, key=lambda row: (row["department"], row["name"])
        ),
        "orphan_departments": orphan_departments,
        "counts": {
            "departments": len(departments),
            "disabled_departments": sum(1 for row in departments if row["disabled"]),
            "service_groups": len(groups),
            "services": len(services),
            "service_concepts": len(service_concepts),
            "services_per_department": services_per_department,
            "orphan_departments": len(orphan_departments),
        },
    }


def catalog_fingerprint(config: dict[str, Any]) -> str:
    evidence = {
        "center": config.get("center"),
        "departments": config.get("departments") or [],
        "service_groups": config.get("service_groups") or [],
        "services": config.get("services") or [],
    }
    encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _candidate_messages(config: dict[str, Any]) -> list[dict[str, str]]:
    compact = [
        {
            "service": row.get("name"),
            "department": row.get("department"),
            "group": row.get("group_name"),
            "internal_name": row.get("internal_name"),
        }
        for row in (config.get("services") or [])
    ]
    catalogue_json = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    if len(catalogue_json) > MAX_LLM_CATALOG_CHARS:
        raise ConceptProposalError(
            f"service catalogue is {len(catalogue_json)} characters; maximum for one "
            f"bounded proposal is {MAX_LLM_CATALOG_CHARS}. No partial proposal was sent."
        )
    system = (
        "You prepare REVIEW-ONLY service synonym candidates for medical reception software. "
        "The supplied catalogue contains service names, departments and groups, never patient "
        "data. Do not diagnose, invent a service, merge different anatomy, or treat a department "
        "as a service. Return one JSON object with key concepts. Each concept must contain: "
        "id (lowercase snake_case), label_fa, aliases (how Persian/English users may ask), "
        "match_terms (literal fragments that occur in at least one supplied service name), "
        "evidence_services (exact supplied service names), confidence (0..1), and reason_fa. "
        "Prefer no candidate over an uncertain clinical equivalence. Output JSON only."
    )
    user = (
        f"Center: {config.get('center')}\n"
        "Identify only high-confidence alternate naming families that are useful for search.\n"
        f"CATALOGUE_DATA={catalogue_json}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def validate_candidate_concepts(
    payload: Any, *, service_names: list[str]
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("concepts"), list):
        raise ConceptProposalError("LLM reply must be an object containing a concepts list")
    raw_concepts = payload["concepts"]
    if len(raw_concepts) > MAX_CONCEPTS:
        raise ConceptProposalError(f"LLM proposed more than {MAX_CONCEPTS} concepts")

    known = {name: fold(name) for name in service_names}
    output: list[dict[str, Any]] = []
    ids: set[str] = set()
    alias_owners: dict[str, str] = {}
    for index, raw in enumerate(raw_concepts):
        if not isinstance(raw, dict):
            raise ConceptProposalError(f"concepts[{index}] is not an object")
        concept_id = str(raw.get("id") or "").strip()
        if not _CONCEPT_ID.fullmatch(concept_id) or concept_id in ids:
            raise ConceptProposalError(f"invalid or duplicate candidate id: {concept_id!r}")
        try:
            aliases = _clean_strings(
                raw.get("aliases"), maximum=MAX_ALIASES_PER_CONCEPT,
                field=f"candidate {concept_id}.aliases",
                allowed_short=SAFE_SHORT_ALIASES,
            )
            match_terms = _clean_strings(
                raw.get("match_terms"), maximum=MAX_MATCH_TERMS_PER_CONCEPT,
                field=f"candidate {concept_id}.match_terms",
            )
            evidence = _clean_strings(
                raw.get("evidence_services"), maximum=MAX_EVIDENCE_SERVICES,
                field=f"candidate {concept_id}.evidence_services", max_length=500,
            )
        except CenterBootstrapError as exc:
            raise ConceptProposalError(str(exc)) from exc
        unknown_evidence = [name for name in evidence if name not in known]
        if unknown_evidence:
            raise ConceptProposalError(
                f"candidate {concept_id!r} invented evidence service {unknown_evidence[0]!r}"
            )
        for term in match_terms:
            needle = fold(term)
            if not any(needle in folded for folded in known.values()):
                raise ConceptProposalError(
                    f"candidate {concept_id!r} match term {term!r} occurs in no service"
                )
        for alias in aliases:
            key = fold(alias)
            owner = alias_owners.get(key)
            if owner and owner != concept_id:
                raise ConceptProposalError(
                    f"candidate alias {alias!r} conflicts between {owner!r} and {concept_id!r}"
                )
            alias_owners[key] = concept_id
        label_fa = str(raw.get("label_fa") or "").strip()
        reason_fa = str(raw.get("reason_fa") or "").strip()
        confidence_raw = raw.get("confidence")
        if not isinstance(confidence_raw, (int, float, str)):
            raise ConceptProposalError(
                f"candidate {concept_id!r} has invalid confidence"
            )
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError) as exc:
            raise ConceptProposalError(
                f"candidate {concept_id!r} has invalid confidence"
            ) from exc
        if not label_fa or len(label_fa) > 120 or not reason_fa or not (0 <= confidence <= 1):
            raise ConceptProposalError(f"candidate {concept_id!r} has invalid metadata")
        ids.add(concept_id)
        output.append({
            "id": concept_id,
            "label_fa": label_fa,
            "aliases": aliases,
            "match_terms": match_terms,
            "evidence_services": evidence,
            "confidence": confidence,
            "reason_fa": reason_fa,
        })
    return output


def validate_candidate_concepts_partial(
    payload: Any, *, service_names: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep valid review candidates while rejecting invalid siblings safely."""
    if not isinstance(payload, dict) or not isinstance(payload.get("concepts"), list):
        raise ConceptProposalError("LLM reply must be an object containing a concepts list")
    raw_concepts = payload["concepts"]
    if len(raw_concepts) > MAX_CONCEPTS:
        raise ConceptProposalError(f"LLM proposed more than {MAX_CONCEPTS} concepts")

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_concepts):
        concept_id = ""
        if isinstance(raw, dict):
            concept_id = str(raw.get("id") or "").strip()[:64]
        try:
            accepted = validate_candidate_concepts(
                {"concepts": [*accepted, raw]}, service_names=service_names,
            )
        except ConceptProposalError as exc:
            rejected.append({
                "index": index,
                "id": concept_id,
                "reason": str(exc)[:500],
            })
    return accepted, rejected


def propose_service_concepts(
    config: dict[str, Any], *, chat: Callable[..., dict[str, Any]] | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Ask the configured LLM for evidence-anchored, inactive candidates."""
    if chat is None:
        from .llm import client

        chat = client.chat_completion
    reply = chat(
        _candidate_messages(config),
        response_format_json=True,
        max_tokens=4000,
        temperature=0.0,
        timeout=120,
    )
    try:
        payload = json.loads(str(reply.get("content") or ""))
    except json.JSONDecodeError as exc:
        raise ConceptProposalError("LLM candidate reply was not valid JSON") from exc
    names = [str(row.get("name")) for row in (config.get("services") or []) if row.get("name")]
    candidates, rejected = validate_candidate_concepts_partial(
        payload, service_names=names,
    )
    usage_raw = reply.get("usage")
    usage: dict[str, Any] = usage_raw if isinstance(usage_raw, dict) else {}
    return candidates, {
        "provider": reply.get("provider"),
        "model": usage.get("model"),
        "usage": usage,
        "_rejected_candidates": rejected,
    }


def _bundled_seed() -> dict[str, Any]:
    path = Path(__file__).resolve().parent / CENTER_CONFIG_FILENAME
    return _read_json(path)


def _load_or_create_active_concepts(root: Path, center: str) -> list[dict[str, Any]]:
    path = root / ACTIVE_CONCEPTS_FILENAME
    if path.exists():
        return validate_active_concepts(_read_json(path), center=center)

    seed = _bundled_seed()
    seed_center = str(seed.get("center") or "").strip()
    raw = seed.get("service_concepts") if seed_center.casefold() == center.casefold() else []
    concepts = validate_active_concepts(raw, center=center)
    _write_json(path, {
        "_about": (
            "Reviewed service aliases active for this centre. LLM candidates are stored "
            "separately and never become active without explicit promotion."
        ),
        "schema_version": 1,
        "center": center,
        "concepts": concepts,
    })
    return concepts


def _service_catalog_csv(config: dict[str, Any]) -> str:
    departments = {
        str(row.get("code")): row
        for row in (config.get("departments") or [])
        if isinstance(row, dict)
    }
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([
        "service_id", "service_name", "department_code", "department_name_fa",
        "department_name_en", "group_name", "internal_name", "internal_code",
    ])
    for row in config.get("services") or []:
        department = departments.get(str(row.get("department")), {})
        writer.writerow([
            row.get("id"), row.get("name"), row.get("department"),
            department.get("name_fa"), department.get("name_en"),
            row.get("group_name"), row.get("internal_name"), row.get("internal_code"),
        ])
    # UTF-8 BOM makes Persian text open correctly in Windows Excel while
    # remaining valid UTF-8 for scripts.
    return "\ufeff" + output.getvalue()


def _profile(
    config: dict[str, Any], manifest: dict[str, Any], candidate_payload: dict[str, Any]
) -> str:
    counts = config.get("counts") or {}
    lines = [
        f"# Center profile — {config.get('center')}",
        "",
        f"Generated: `{config.get('generated_at')}`",
        "",
        "This file is generated from the local reception catalogue. It contains no patient data.",
        "",
        "## Inventory",
        "",
        f"- Departments: {counts.get('departments', 0)} ({counts.get('disabled_departments', 0)} disabled)",
        f"- Service groups: {counts.get('service_groups', 0)}",
        f"- Services: {counts.get('services', 0)}",
        f"- Active reviewed service concepts: {counts.get('service_concepts', 0)}",
        f"- Orphan department codes: {', '.join(config.get('orphan_departments') or []) or 'none'}",
        f"- Complete service catalogue: `{SERVICE_CATALOG_CSV_FILENAME}`",
        "",
        "## Departments",
        "",
        "| Code | Persian name | English/short | State | Services |",
        "|---|---|---|---|---:|",
    ]
    per_department = counts.get("services_per_department") or {}
    for row in config.get("departments") or []:
        state = "disabled" if row.get("disabled") else "active"
        lines.append(
            f"| {row.get('code')} | {row.get('name_fa') or ''} | "
            f"{row.get('name_en') or row.get('short') or ''} | {state} | "
            f"{per_department.get(str(row.get('code')), 0)} |"
        )
    llm = manifest.get("llm") or {}
    lines.extend([
        "",
        "## Service lexicon lifecycle",
        "",
        f"- Catalogue fingerprint: `{manifest.get('catalog_fingerprint')}`",
        f"- LLM proposal status: `{llm.get('status', 'not_run')}`",
        f"- Candidate concepts: {llm.get('candidate_count', 0)}",
        "- Candidate aliases are inactive until explicitly promoted.",
        "- Re-run bootstrap after the reception vendor changes services or departments.",
        "",
    ])
    lines.extend(["## Active reviewed concepts", ""])
    active = config.get("service_concepts") or []
    if active:
        lines.extend([
            "| Id | Label | User aliases | Stored-name match terms |",
            "|---|---|---|---|",
        ])
        for concept in active:
            lines.append(
                f"| `{concept.get('id')}` | {concept.get('label_fa')} | "
                f"{'، '.join(concept.get('aliases') or [])} | "
                f"{'، '.join(concept.get('match_terms') or [])} |"
            )
    else:
        lines.append("No reviewed service concepts are active.")
    lines.extend(["", "## LLM candidates awaiting review", ""])
    candidates = candidate_payload.get("concepts") or []
    if candidates:
        lines.extend([
            "| Id | Label | Confidence | Evidence services |",
            "|---|---|---:|---|",
        ])
        for concept in candidates:
            lines.append(
                f"| `{concept.get('id')}` | {concept.get('label_fa')} | "
                f"{concept.get('confidence')} | "
                f"{'؛ '.join(concept.get('evidence_services') or [])} |"
            )
    else:
        lines.append("No candidate concepts are currently stored.")
    lines.append("")
    return "\n".join(lines)


def bootstrap_center(
    *,
    center: str,
    database: Any,
    database_name: str,
    output_root: Path | None = None,
    with_llm: bool = True,
    chat: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run deterministic discovery, then optionally create LLM candidates."""
    root = output_root or config_root()
    root.mkdir(parents=True, exist_ok=True)
    concepts = _load_or_create_active_concepts(root, center)

    # Build completely in memory before replacing the last known-good map. A
    # database outage during an upgrade therefore leaves the prior map intact.
    config = discover_center_config(
        database,
        center=center,
        database_name=database_name,
        service_concepts=concepts,
    )
    fingerprint = catalog_fingerprint(config)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "center": center,
        "generated_at": _now(),
        "catalog_fingerprint": fingerprint,
        "counts": config["counts"],
        "artifacts": {
            "center_config": str(root / CENTER_CONFIG_FILENAME),
            "active_concepts": str(root / ACTIVE_CONCEPTS_FILENAME),
            "candidate_concepts": str(root / CANDIDATE_CONCEPTS_FILENAME),
            "profile": str(root / CENTER_PROFILE_FILENAME),
            "service_catalog_csv": str(root / SERVICE_CATALOG_CSV_FILENAME),
        },
        "llm": {"status": "disabled" if not with_llm else "not_configured", "candidate_count": 0},
    }

    _write_json(root / CENTER_CONFIG_FILENAME, config)

    candidate_path = root / CANDIDATE_CONCEPTS_FILENAME
    previous_candidates = _read_json(candidate_path) if candidate_path.exists() else {}
    if with_llm:
        from .llm import client

        if previous_candidates.get("catalog_fingerprint") == fingerprint:
            previous = previous_candidates.get("concepts") or []
            previous_rejected = previous_candidates.get("rejected_candidates") or []
            manifest["llm"] = {
                "status": "unchanged",
                "candidate_count": len(previous) if isinstance(previous, list) else 0,
                "rejected_count": (
                    len(previous_rejected) if isinstance(previous_rejected, list) else 0
                ),
            }
        elif not client.is_configured() and chat is None:
            manifest["llm"] = {"status": "not_configured", "candidate_count": 0}
        else:
            try:
                candidates, model_meta = propose_service_concepts(config, chat=chat)
                rejected_candidates = model_meta.pop("_rejected_candidates", [])
                proposal_status = "review_required" if candidates else "no_valid_candidates"
                candidate_payload = {
                    "_about": (
                        "LLM-generated REVIEW CANDIDATES. These do not affect searches until "
                        "an administrator explicitly promotes selected concept ids."
                    ),
                    "schema_version": 1,
                    "status": proposal_status,
                    "center": center,
                    "generated_at": _now(),
                    "catalog_fingerprint": fingerprint,
                    "model": model_meta,
                    "concepts": candidates,
                    "rejected_candidates": rejected_candidates,
                }
                _write_json(candidate_path, candidate_payload)
                manifest["llm"] = {
                    "status": proposal_status,
                    "candidate_count": len(candidates),
                    "rejected_count": len(rejected_candidates),
                    "provider": model_meta.get("provider"),
                    "model": model_meta.get("model"),
                }
            except Exception as exc:  # deterministic discovery must still complete
                manifest["llm"] = {
                    "status": "error",
                    "candidate_count": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                }

    _write_json(root / BOOTSTRAP_MANIFEST_FILENAME, manifest)
    _atomic_write(root / SERVICE_CATALOG_CSV_FILENAME, _service_catalog_csv(config))
    final_candidates = _read_json(candidate_path) if candidate_path.exists() else {}
    _atomic_write(
        root / CENTER_PROFILE_FILENAME,
        _profile(config, manifest, final_candidates),
    )
    return manifest


def promote_candidate_concepts(
    concept_ids: list[str], *, output_root: Path | None = None, center: str
) -> dict[str, Any]:
    """Promote explicitly selected, evidence-anchored candidate ids."""
    root = output_root or config_root()
    requested = {str(value).strip() for value in concept_ids if str(value).strip()}
    if not requested:
        raise CenterBootstrapError("at least one candidate concept id is required")
    candidate_payload = _read_json(root / CANDIDATE_CONCEPTS_FILENAME)
    if str(candidate_payload.get("center") or "").casefold() != center.casefold():
        raise CenterBootstrapError("candidate file belongs to another centre")

    center_path = root / CENTER_CONFIG_FILENAME
    config = _read_json(center_path)
    if str(config.get("center") or "").casefold() != center.casefold():
        raise CenterBootstrapError("generated center_config belongs to another centre")
    current_fingerprint = catalog_fingerprint(config)
    if candidate_payload.get("catalog_fingerprint") != current_fingerprint:
        raise CenterBootstrapError(
            "candidate file was generated for a different catalogue; run bootstrap-center again"
        )
    service_names = [
        str(row.get("name"))
        for row in (config.get("services") or [])
        if isinstance(row, dict) and row.get("name")
    ]
    validated_candidates = validate_candidate_concepts(
        candidate_payload, service_names=service_names
    )
    by_id = {row["id"]: row for row in validated_candidates}
    missing = sorted(requested - set(by_id))
    if missing:
        raise CenterBootstrapError(f"unknown candidate concept ids: {', '.join(missing)}")

    active_path = root / ACTIVE_CONCEPTS_FILENAME
    active = validate_active_concepts(_read_json(active_path), center=center)
    merged = {row["id"]: row for row in active}
    for concept_id in requested:
        candidate = by_id[concept_id]
        merged[concept_id] = {
            "id": concept_id,
            "label_fa": candidate.get("label_fa"),
            "aliases": candidate.get("aliases"),
            "match_terms": candidate.get("match_terms"),
        }
    validated = validate_active_concepts(list(merged.values()), center=center)
    config["service_concepts"] = validated
    counts_raw = config.get("counts")
    counts: dict[str, Any] = dict(counts_raw) if isinstance(counts_raw, dict) else {}
    counts["service_concepts"] = len(validated)
    config["counts"] = counts
    config["updated_at"] = _now()
    _write_json(center_path, config)
    _write_json(active_path, {
        "_about": "Reviewed service aliases active for this centre.",
        "schema_version": 1,
        "center": center,
        "updated_at": _now(),
        "concepts": validated,
    })
    return {
        "center": center,
        "promoted": sorted(requested),
        "active_concept_count": len(validated),
        "active_concepts": str(active_path),
        "center_config": str(center_path),
    }
