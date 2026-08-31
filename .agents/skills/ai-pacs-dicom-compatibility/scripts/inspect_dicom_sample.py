#!/usr/bin/env python3
"""Create a PHI-minimized structural inventory of explicitly selected DICOM data.

The report omits paths and patient attributes. Study, series, instance, and
concatenation UIDs are represented by run-local salted labels so that objects can
be grouped within one report without disclosing their raw identifiers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pydicom
from pydicom import config
from pydicom.dataset import Dataset
from pydicom.tag import Tag
from pydicom.uid import UID


PIXEL_DATA = Tag(0x7FE0, 0x0010)
FLOAT_PIXEL_DATA = Tag(0x7FE0, 0x0008)
DOUBLE_FLOAT_PIXEL_DATA = Tag(0x7FE0, 0x0009)
WAVEFORM_SEQUENCE = Tag(0x5400, 0x0100)
ENCAPSULATED_DOCUMENT = Tag(0x0042, 0x0011)

PAYLOAD_TAGS = {
    PIXEL_DATA: "pixel_data",
    FLOAT_PIXEL_DATA: "float_pixel_data",
    DOUBLE_FLOAT_PIXEL_DATA: "double_float_pixel_data",
    WAVEFORM_SEQUENCE: "waveform_sequence",
    ENCAPSULATED_DOCUMENT: "encapsulated_document",
}

HEADER_KEYWORDS = [
    "SOPClassUID",
    "SOPInstanceUID",
    "StudyInstanceUID",
    "SeriesInstanceUID",
    "Modality",
    "TransferSyntaxUID",
    "Rows",
    "Columns",
    "NumberOfFrames",
    "SamplesPerPixel",
    "PhotometricInterpretation",
    "PlanarConfiguration",
    "BitsAllocated",
    "BitsStored",
    "HighBit",
    "PixelRepresentation",
    "FrameTime",
    "FrameTimeVector",
    "CineRate",
    "RecommendedDisplayFrameRate",
    "FrameIncrementPointer",
    "SharedFunctionalGroupsSequence",
    "PerFrameFunctionalGroupsSequence",
    "DimensionOrganizationSequence",
    "DimensionIndexSequence",
    "ConcatenationUID",
    "InConcatenationNumber",
    "InConcatenationTotalNumber",
    "SequenceOfUltrasoundRegions",
    "WaveformSequence",
    "EncapsulatedDocument",
]

SAFE_SCALAR_KEYWORDS = [
    "Modality",
    "Rows",
    "Columns",
    "NumberOfFrames",
    "SamplesPerPixel",
    "PhotometricInterpretation",
    "PlanarConfiguration",
    "BitsAllocated",
    "BitsStored",
    "HighBit",
    "PixelRepresentation",
    "InConcatenationNumber",
    "InConcatenationTotalNumber",
]

PRESENCE_KEYWORDS = [
    "FrameTime",
    "FrameTimeVector",
    "CineRate",
    "RecommendedDisplayFrameRate",
    "FrameIncrementPointer",
    "SharedFunctionalGroupsSequence",
    "PerFrameFunctionalGroupsSequence",
    "DimensionOrganizationSequence",
    "DimensionIndexSequence",
    "SequenceOfUltrasoundRegions",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect an explicitly selected DICOM file or directory without "
            "reporting paths or patient attributes."
        )
    )
    parser.add_argument("input", type=Path, help="Explicit local file or directory")
    parser.add_argument(
        "--max-files",
        type=positive_int,
        default=1000,
        help="Maximum candidate files to inspect (default: 1000)",
    )
    parser.add_argument(
        "--decode",
        action="store_true",
        help="Attempt bounded pixel/waveform decoding",
    )
    parser.add_argument(
        "--max-decode-files",
        type=non_negative_int,
        default=3,
        help="Maximum payload-bearing files to decode (default: 3)",
    )
    parser.add_argument(
        "--max-decode-bytes",
        type=positive_int,
        default=256 * 1024 * 1024,
        help="Skip decoding candidates larger than this many bytes",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional local JSON output file; stdout is used otherwise",
    )
    return parser.parse_args()


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must not be negative")
    return parsed


def candidate_files(root: Path, limit: int) -> tuple[list[Path], bool]:
    if root.is_file():
        return ([root] if root.name.upper() != "DICOMDIR" else []), False
    if not root.is_dir():
        raise FileNotFoundError

    files: list[Path] = []
    truncated = False
    for path in root.rglob("*"):
        if not path.is_file() or path.name.upper() == "DICOMDIR":
            continue
        if len(files) >= limit:
            truncated = True
            break
        files.append(path)
    return files, truncated


def uid_label(value: Any, salt: bytes, prefix: str) -> str | None:
    if value in (None, ""):
        return None
    digest = hashlib.sha256(salt + str(value).encode("utf-8", "replace")).hexdigest()
    return f"{prefix}-{digest[:12]}"


def safe_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    text = str(value)
    if len(text) > 128:
        return {"present": True, "item_count": len(value) if hasattr(value, "__len__") else None}
    return text


def transfer_syntax(ds: Dataset) -> str | None:
    file_meta = getattr(ds, "file_meta", None)
    value = getattr(file_meta, "TransferSyntaxUID", None) if file_meta else None
    return str(value) if value else None


def transfer_syntax_details(value: str | None) -> dict[str, Any]:
    if not value:
        return {"uid": None, "name": None, "is_compressed": None}
    uid = UID(value)
    try:
        compressed = uid.is_compressed
    except ValueError:
        compressed = None
    return {
        "uid": str(uid),
        "name": uid.name,
        "is_compressed": compressed,
    }


def sop_class_details(ds: Dataset) -> tuple[str | None, str | None]:
    value = ds.get("SOPClassUID")
    if not value:
        file_meta = getattr(ds, "file_meta", None)
        value = getattr(file_meta, "MediaStorageSOPClassUID", None) if file_meta else None
    if not value:
        return None, None
    return str(value), getattr(value, "name", None) or None


def read_header(path: Path) -> Dataset:
    tags = [Tag(keyword) for keyword in HEADER_KEYWORDS]
    tags.extend(PAYLOAD_TAGS)
    return pydicom.dcmread(
        path,
        force=True,
        defer_size=1024,
        specific_tags=tags,
    )


def payload_kinds(ds: Dataset) -> list[str]:
    return [name for tag, name in PAYLOAD_TAGS.items() if tag in ds]


def handler_capability(uid: str) -> list[dict[str, Any]]:
    capabilities: list[dict[str, Any]] = []
    for handler in config.pixel_data_handlers:
        available = False
        supports = False
        try:
            available = bool(handler.is_available())
        except Exception:
            pass
        try:
            supports = bool(handler.supports_transfer_syntax(uid))
        except Exception:
            pass
        capabilities.append(
            {
                "handler": handler.__name__.rsplit(".", 1)[-1],
                "available": available,
                "supports_transfer_syntax": supports,
                "usable_for_transfer_syntax": available and supports,
            }
        )
    return capabilities


def array_summary(array: np.ndarray) -> dict[str, Any]:
    contiguous = np.ascontiguousarray(array)
    result: dict[str, Any] = {
        "shape": list(contiguous.shape),
        "dtype": str(contiguous.dtype),
        "byte_count": int(contiguous.nbytes),
        "sha256": hashlib.sha256(contiguous.tobytes()).hexdigest(),
    }
    if contiguous.size:
        try:
            result["minimum"] = safe_scalar(np.nanmin(contiguous).item())
            result["maximum"] = safe_scalar(np.nanmax(contiguous).item())
        except (TypeError, ValueError):
            result["range_available"] = False
    return result


def decode_summary(path: Path, kinds: list[str], max_bytes: int) -> dict[str, Any]:
    try:
        file_size = path.stat().st_size
    except OSError as exc:
        return {"status": "error", "error_type": type(exc).__name__}
    if file_size > max_bytes:
        return {"status": "skipped_file_size_limit", "file_size": file_size}

    try:
        ds = pydicom.dcmread(path, force=True)
        if any(kind.endswith("pixel_data") for kind in kinds):
            return {"status": "decoded", "kind": "pixel_array", **array_summary(ds.pixel_array)}
        if "waveform_sequence" in kinds:
            return {
                "status": "decoded",
                "kind": "waveform_array",
                **array_summary(ds.waveform_array(0)),
            }
        return {"status": "not_decodable_by_this_tool"}
    except Exception as exc:
        return {"status": "error", "error_type": type(exc).__name__}


def inspect_file(path: Path, salt: bytes) -> tuple[dict[str, Any] | None, str | None]:
    try:
        ds = read_header(path)
    except Exception as exc:
        return None, type(exc).__name__

    kinds = payload_kinds(ds)
    recognizable = bool(
        kinds
        or ds.get("SOPClassUID")
        or ds.get("StudyInstanceUID")
        or ds.get("SeriesInstanceUID")
        or ds.get("Modality")
        or getattr(getattr(ds, "file_meta", None), "MediaStorageSOPClassUID", None)
    )
    if not recognizable:
        return None, "UnrecognizedDICOM"

    sop_uid, sop_name = sop_class_details(ds)
    syntax = transfer_syntax_details(transfer_syntax(ds))
    record: dict[str, Any] = {
        "object_index": None,
        "study": uid_label(ds.get("StudyInstanceUID"), salt, "study"),
        "series": uid_label(ds.get("SeriesInstanceUID"), salt, "series"),
        "instance": uid_label(ds.get("SOPInstanceUID"), salt, "instance"),
        "sop_class_uid": sop_uid,
        "sop_class_name": sop_name,
        "transfer_syntax_uid": syntax["uid"],
        "transfer_syntax_name": syntax["name"],
        "transfer_syntax_is_compressed": syntax["is_compressed"],
        "payload_kinds": kinds,
        "attributes": {
            keyword: safe_scalar(ds.get(keyword))
            for keyword in SAFE_SCALAR_KEYWORDS
            if keyword in ds
        },
        "structures_present": [keyword for keyword in PRESENCE_KEYWORDS if keyword in ds],
        "concatenation": uid_label(ds.get("ConcatenationUID"), salt, "concat"),
    }
    return record, None


def grouped_summary(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str | None, str | None], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[(record["study"], record["series"])].append(record)

    result = []
    for (study, series), items in groups.items():
        payloads = sorted({kind for item in items for kind in item["payload_kinds"]})
        syntaxes = sorted({item["transfer_syntax_uid"] for item in items if item["transfer_syntax_uid"]})
        result.append(
            {
                "study": study,
                "series": series,
                "object_count": len(items),
                "payload_kinds": payloads,
                "transfer_syntax_uids": syntaxes,
            }
        )
    return sorted(result, key=lambda item: (item["study"] or "", item["series"] or ""))


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    salt = secrets.token_bytes(32)
    files, truncated = candidate_files(args.input.resolve(), args.max_files)
    records: list[dict[str, Any]] = []
    rejected_errors: Counter[str] = Counter()
    decode_budget = args.max_decode_files

    for path in files:
        record, error_type = inspect_file(path, salt)
        if record is None:
            rejected_errors[error_type or "UnknownError"] += 1
            continue
        record["object_index"] = len(records) + 1
        if args.decode and record["payload_kinds"] and decode_budget > 0:
            record["decode"] = decode_summary(path, record["payload_kinds"], args.max_decode_bytes)
            decode_budget -= 1
        records.append(record)

    syntaxes = sorted({record["transfer_syntax_uid"] for record in records if record["transfer_syntax_uid"]})
    return {
        "schema_version": 1,
        "privacy": {
            "paths_omitted": True,
            "patient_attributes_omitted": True,
            "identity_uids_replaced_by_run_local_salted_labels": True,
            "decode_summaries_may_contain_content_digests": args.decode,
        },
        "runtime": {
            "python": sys.version.split()[0],
            "pydicom": pydicom.__version__,
            "numpy": np.__version__,
        },
        "scan": {
            "input_kind": "file" if args.input.is_file() else "directory",
            "candidate_file_count": len(files),
            "dicom_object_count": len(records),
            "rejected_file_count": sum(rejected_errors.values()),
            "rejected_error_types": dict(sorted(rejected_errors.items())),
            "truncated_by_max_files": truncated,
            "decode_requested": args.decode,
            "decode_limit": args.max_decode_files,
            "decode_file_size_limit": args.max_decode_bytes,
        },
        "transfer_syntax_capabilities": {
            uid: handler_capability(uid) for uid in syntaxes
        },
        "series": grouped_summary(records),
        "objects": records,
    }


def main() -> int:
    args = parse_args()
    try:
        report = build_report(args)
    except (FileNotFoundError, PermissionError) as exc:
        error = {
            "status": "error",
            "error_type": type(exc).__name__,
            "paths_omitted": True,
        }
        print(json.dumps(error, indent=2), file=sys.stderr)
        return 2

    rendered = json.dumps(report, indent=2 if args.pretty else None, sort_keys=args.pretty)
    if args.output:
        args.output.write_text(rendered + os.linesep, encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
