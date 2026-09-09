"""Offline, hash-bound snapshots of SAVED stage-three inputs, not model replay.

Never import the runtime backend here. Preserve the historical prompt and sent
metadata verbatim as JSON values; resolve images by their ordered request entries.
This is integrity checking, not de-identification, DICOM/anatomical validation,
or an attestation of what a remote provider actually received.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PureWindowsPath

SCHEMA_VERSION = "1.0.0"
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_IMAGE_BYTES = 256 * 1024 * 1024
MAX_IMAGES = 64
INPUT_KEYS = ("model", "backend", "pipeline", "prompt", "sent")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


class SnapshotError(ValueError):
    """A safe, non-patient-bearing error for local snapshot operations."""


def _encoded(document):
    try:
        return json.dumps(document, sort_keys=True, ensure_ascii=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, RecursionError):
        raise SnapshotError("Snapshot JSON cannot be encoded safely.") from None


def _digest(payload):
    return hashlib.sha256(payload).hexdigest()


def _read(root, name, limit):
    if (not isinstance(name, str) or not name or "\\" in name
            or PureWindowsPath(name).drive or name.startswith("/")
            or any(p in ("", ".", "..") or ":" in p or p.endswith((" ", "."))
                   for p in name.split("/"))):
        raise SnapshotError("Invalid relative artifact path.")
    path = root
    for part in name.split("/"):
        path = path / part
        if path.is_symlink() or path.is_junction():
            raise SnapshotError("Linked artifact paths are not accepted.")
    try:
        path.resolve().relative_to(root)
        with path.open("rb") as handle:
            payload = handle.read(limit + 1)
    except (OSError, ValueError):
        raise SnapshotError("Required local artifact cannot be read.") from None
    if not payload or len(payload) > limit:
        raise SnapshotError("Artifact is empty or exceeds the local snapshot limit.")
    return payload


def _document(payload):
    def reject_constant(value):
        raise ValueError("Non-finite JSON value")
    try:
        document = json.loads(payload, parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise SnapshotError("Invalid snapshot JSON.") from None
    if not isinstance(document, dict):
        raise SnapshotError("Snapshot JSON must be an object.")
    return document


def _images(document):
    if any(k not in document for k in INPUT_KEYS):
        raise SnapshotError("Saved request lacks required input fields.")
    if (not isinstance(document["pipeline"], dict)
            or not isinstance(document["prompt"], dict)
            or not isinstance(document["prompt"].get("text"), str)
            or not document["prompt"]["text"]
            or any(not isinstance(document[k], str) or not document[k]
                   for k in ("model", "backend"))):
        raise SnapshotError("Saved prompt or model metadata is incomplete.")
    sent = document["sent"]
    if not isinstance(sent, dict):
        raise SnapshotError("Saved sent block is invalid.")
    images = sent.get("images")
    if (not isinstance(images, list) or not 1 <= len(images) <= MAX_IMAGES
            or type(sent.get("image_count")) is not int
            or sent["image_count"] != len(images)
            or any(not isinstance(sent.get(k), str) for k in ("header", "context"))):
        raise SnapshotError("Saved image count or context is invalid.")
    for item in images:
        if (not isinstance(item, dict) or not isinstance(item.get("file"), str)
                or Path(item["file"]).suffix.lower() not in IMAGE_SUFFIXES
                or not isinstance(item.get("caption"), str)):
            raise SnapshotError("Saved image entry is invalid.")
    return images


def _image_name(index, entry):
    return f"images/{index:03d}{Path(entry['file']).suffix.lower()}"


def freeze(session, destination):
    """Write a new snapshot; never overwrite or write inside the source session."""
    root = Path(session).resolve()
    target = Path(destination).resolve()
    if target.exists() or target.is_relative_to(root):
        raise SnapshotError("Choose a new destination outside the source session.")
    saved = _document(_read(root, "llm_stage3_request.json", MAX_DOCUMENT_BYTES))
    entries = _images(saved)
    inputs = {k: saved[k] for k in INPUT_KEYS}
    input_bytes = _encoded(inputs)
    if len(input_bytes) > MAX_DOCUMENT_BYTES:
        raise SnapshotError("Encoded input exceeds the local document limit.")
    payloads = [("input.json", input_bytes)]
    remaining = MAX_IMAGE_BYTES
    for index, entry in enumerate(entries, 1):
        data = _read(root, entry["file"], remaining)
        remaining -= len(data)
        payloads.append((_image_name(index, entry), data))
    manifest = {"schema_version": SCHEMA_VERSION, "files": [
        {"file": name, "sha256": _digest(data), "bytes": len(data)}
        for name, data in payloads
    ]}
    manifest["snapshot_id"] = _digest(_encoded(manifest))
    try:
        target.mkdir(parents=True, exist_ok=False)
        (target / "images").mkdir()
        for name, data in payloads:
            with (target / name).open("xb") as handle:
                handle.write(data)
        # Completeness marker is last. A partial write cannot pass check().
        with (target / "manifest.json").open("xb") as handle:
            handle.write(_encoded(manifest))
    except OSError:
        raise SnapshotError("Snapshot write failed; retain any partial output for inspection.") from None
    return manifest["snapshot_id"]


def check(snapshot, expected_id=""):
    """Verify exact saved text/order/bytes; optional external identity pins a run."""
    root = Path(snapshot).resolve()
    manifest = _document(_read(root, "manifest.json", MAX_DOCUMENT_BYTES))
    if (set(manifest) != {"schema_version", "files", "snapshot_id"}
            or manifest["schema_version"] != SCHEMA_VERSION):
        raise SnapshotError("Unsupported or incomplete snapshot manifest.")
    identity = _digest(_encoded({k: manifest[k] for k in ("schema_version", "files")}))
    if identity != manifest["snapshot_id"] or (expected_id and identity != expected_id):
        raise SnapshotError("Snapshot identity mismatch.")
    input_bytes = _read(root, "input.json", MAX_DOCUMENT_BYTES)
    inputs = _document(input_bytes)
    entries = _images(inputs)
    expected_names = ["input.json"] + [_image_name(i, entry) for i, entry in enumerate(entries, 1)]
    files = manifest["files"]
    if (not isinstance(files, list) or len(files) != len(expected_names)
            or any(not isinstance(item, dict) for item in files)):
        raise SnapshotError("Snapshot file list is incomplete.")
    remaining = MAX_IMAGE_BYTES
    for index, (item, name) in enumerate(zip(files, expected_names)):
        if item.get("file") != name:
            raise SnapshotError("Snapshot image order mismatch.")
        data = input_bytes if index == 0 else _read(root, name, remaining)
        if item.get("sha256") != _digest(data) or item.get("bytes") != len(data):
            raise SnapshotError("Snapshot artifact digest mismatch.")
        if index:
            remaining -= len(data)
    return identity
