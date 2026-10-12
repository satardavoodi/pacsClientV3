"""Durable, server-local files attached to an agent analysis.

The conversation database keeps small relational metadata.  Potentially large
results stay on disk below the configured clinical data root, outside the
application install and outside any web root.  Paths on disk are opaque ids;
human labels are metadata, so a patient name can never become a path segment.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .attachments import Attachment


JSON_MIME = "application/json"
CSV_MIME = "text/csv"
MAX_TABLE_DEPTH = 4

LABELS_FA = {
    "rows": "ردیف‌های نتیجه",
    "patients": "بیماران",
    "high_risk_receptions": "موارد پرریسک",
    "by_modality": "تفکیک نوع خدمت",
    "by_insurance": "تفکیک بیمه",
    "by_cashier": "تفکیک صندوق‌دار",
    "by_card": "تفکیک کارتخوان",
    "insurance_payments": "پرداخت‌های بیمه",
    "steps": "مراحل تحلیل",
    "cashier": "صندوق",
    "cashier_report": "گزارش صندوق",
    "service_report": "گزارش خدمات",
    "risk": "ریسک",
    "risk_report": "گزارش ریسک",
    "cashdesk_risk_analysis": "تحلیل ریسک صندوق",
    "daily-summary": "خلاصهٔ روزانه",
    "cashier-reconciliation": "مغایرت‌گیری صندوق",
    "risk-analysis": "تحلیل ریسک",
    "financial-analysis": "تحلیل مالی",
    "patient-list": "فهرست بیماران",
}


class AnalysisArtifactError(RuntimeError):
    """A durable analysis file could not be created safely."""


@dataclass(frozen=True)
class ArtifactFile:
    id: str
    kind: str
    display_name: str
    format: str
    relative_path: str
    mime_type: str
    size_bytes: int
    row_count: int | None
    sha256: str
    complete: bool
    managed: bool


def create_artifacts(
    data_root: Path,
    conversation_id: str,
    analysis_id: str,
    response: dict[str, Any],
    *,
    evidence: list[dict[str, Any]] | None = None,
    attachments: tuple[Attachment, ...] = (),
) -> list[ArtifactFile]:
    """Write the complete response plus useful row tables atomically.

    Existing raw snapshots are referenced, not copied.  They are the immutable
    audit trail and may be shared by more than one view; deleting a conversation
    must therefore remove only files marked ``managed``.
    """
    root = Path(data_root).resolve()
    analysis_root = _confined(root, root / "analyses")
    directory = _confined(
        analysis_root,
        analysis_root / _opaque(conversation_id, "conv") / _opaque(analysis_id, "analysis"),
    )
    created: list[ArtifactFile] = []
    directory_created = False
    try:
        directory.mkdir(parents=True, exist_ok=False)
        directory_created = True
        for attachment in attachments:
            artifact_id = _new_id("art")
            input_path = directory / f"{artifact_id}.{attachment.extension}"
            _write_bytes_atomic(input_path, attachment.data)
            created.append(
                _managed_file(
                    root,
                    input_path,
                    "input",
                    f"فایل ارسالی — {attachment.display_name}",
                    attachment.extension,
                    attachment.mime_type,
                    artifact_id=artifact_id,
                )
            )
        response_path = directory / "response.json"
        _write_json_atomic(response_path, response)
        created.append(
            _managed_file(root, response_path, "response", "پاسخ و دادهٔ اصلی", "json", JSON_MIME)
        )

        result = response.get("result")
        for label, rows in _tables(result):
            artifact_id = _new_id("art")
            csv_path = directory / f"{artifact_id}.csv"
            _write_csv_atomic(csv_path, rows)
            created.append(
                _managed_file(
                    root,
                    csv_path,
                    "table",
                    f"جزئیات {label}",
                    "csv",
                    CSV_MIME,
                    row_count=len(rows),
                    artifact_id=artifact_id,
                )
            )

        evidence = evidence if isinstance(evidence, list) else []
        if evidence:
            evidence_path = directory / "evidence.json"
            _write_json_atomic(evidence_path, evidence)
            created.append(
                _managed_file(
                    root,
                    evidence_path,
                    "evidence",
                    "همهٔ منابع تحلیل",
                    "json",
                    JSON_MIME,
                )
            )
            for index, source in enumerate(evidence, start=1):
                if not isinstance(source, dict):
                    continue
                source_data = source.get("data")
                # A single-tool primary result was already exported above.
                if source_data is result:
                    continue
                tool = _fa_label(source.get("tool") or f"منبع {index}")
                for label, rows in _tables(source_data):
                    artifact_id = _new_id("art")
                    csv_path = directory / f"{artifact_id}.csv"
                    _write_csv_atomic(csv_path, rows)
                    created.append(
                        _managed_file(
                            root,
                            csv_path,
                            "evidence_table",
                            f"جزئیات {tool} — {label}",
                            "csv",
                            CSV_MIME,
                            row_count=len(rows),
                            artifact_id=artifact_id,
                        )
                    )

        created.extend(_source_references(root, {"result": result, "evidence": evidence}))
        return created
    except Exception as exc:
        if directory_created:
            _remove_tree(analysis_root, directory)
        if isinstance(exc, AnalysisArtifactError):
            raise
        raise AnalysisArtifactError(f"Could not store analysis artifacts: {type(exc).__name__}") from exc


def remove_managed_files(data_root: Path, relative_paths: list[str]) -> list[str]:
    """Remove files owned by a deleted conversation; return failures.

    Every target is re-confined under ``<data_root>/analyses`` before unlinking.
    Raw source references are never passed here.
    """
    root = Path(data_root).resolve()
    analysis_root = _confined(root, root / "analyses")
    failures: list[str] = []
    parents: set[Path] = set()
    for relative in relative_paths:
        try:
            target = _confined(analysis_root, root / relative)
            if target.is_file():
                target.unlink()
            parents.add(target.parent)
        except OSError:
            failures.append(relative)
        except AnalysisArtifactError:
            failures.append(relative)

    for parent in sorted(parents, key=lambda p: len(p.parts), reverse=True):
        current = parent
        while current != analysis_root:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
    return failures


def _tables(value: Any, prefix: str = "داده", depth: int = 0) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    if depth > MAX_TABLE_DEPTH:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            label = _fa_label(key) or prefix
            if isinstance(child, list) and child and all(isinstance(row, dict) for row in child):
                yield label, child
            elif isinstance(child, (dict, list)):
                yield from _tables(child, label, depth + 1)
    elif isinstance(value, list):
        for child in value:
            if isinstance(child, (dict, list)):
                yield from _tables(child, prefix, depth + 1)


def _source_references(root: Path, value: Any) -> list[ArtifactFile]:
    found: dict[str, tuple[str, Path]] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            paths = node.get("source_paths")
            if isinstance(paths, dict):
                for label, raw in paths.items():
                    if not raw:
                        continue
                    try:
                        candidate = Path(str(raw))
                        path = _confined(root, candidate if candidate.is_absolute() else root / candidate)
                    except AnalysisArtifactError:
                        continue
                    if path.is_file():
                        found[str(path).lower()] = (str(label), path)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    references: list[ArtifactFile] = []
    for label, path in found.values():
        references.append(
            ArtifactFile(
                id=_new_id("art"),
                kind="source",
                display_name=f"دادهٔ خام {_fa_label(label)}",
                format=path.suffix.lower().lstrip(".") or "file",
                relative_path=path.relative_to(root).as_posix(),
                mime_type=JSON_MIME if path.suffix.lower() in {".json", ".jsonl"} else "application/octet-stream",
                size_bytes=path.stat().st_size,
                row_count=None,
                sha256="",
                complete=True,
                managed=False,
            )
        )
    return references


def _write_json_atomic(path: Path, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n"
    _write_text_atomic(path, payload, encoding="utf-8")


def _write_csv_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            name = str(key)
            if name not in seen:
                seen.add(name)
                fields.append(name)

    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({field: _csv_cell(field, row.get(field)) for field in fields})
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _csv_cell(field: str, value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, (dict, list, tuple)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value)
    lowered = field.lower().replace("_", "")
    text_field = any(token in lowered for token in ("phone", "mobile", "tel", "nationalcode", "nationalid"))
    if text_field or text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def _write_text_atomic(path: Path, text: str, *, encoding: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _managed_file(
    root: Path,
    path: Path,
    kind: str,
    display_name: str,
    format_name: str,
    mime_type: str,
    *,
    row_count: int | None = None,
    artifact_id: str | None = None,
) -> ArtifactFile:
    return ArtifactFile(
        id=artifact_id or _new_id("art"),
        kind=kind,
        display_name=display_name,
        format=format_name,
        relative_path=path.relative_to(root).as_posix(),
        mime_type=mime_type,
        size_bytes=path.stat().st_size,
        row_count=row_count,
        sha256=_sha256(path),
        complete=True,
        managed=True,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _opaque(value: str, prefix: str) -> str:
    text = str(value or "")
    marker = f"{prefix}_"
    suffix = text[len(marker) :] if text.startswith(marker) else ""
    if 4 < len(text) <= 80 and suffix and suffix.isascii() and suffix.isalnum():
        return text
    raise AnalysisArtifactError(f"Invalid {prefix} identifier")


def _confined(base: Path, target: Path) -> Path:
    base = Path(base).resolve()
    target = Path(target).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise AnalysisArtifactError("Artifact path escaped the clinical data root") from exc
    return target


def _remove_tree(base: Path, target: Path) -> None:
    try:
        confined = _confined(base, target)
    except AnalysisArtifactError:
        return
    if confined.exists():
        try:
            shutil.rmtree(confined)
        except OSError:
            return


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _fa_label(value: Any) -> str:
    text = str(value or "").strip()
    return LABELS_FA.get(text, text.replace("_", " "))
