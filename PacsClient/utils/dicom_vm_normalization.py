"""Repair server-collapsed standard DICOM multi-value text elements.

The socket server can encode a pydicom ``MultiValue`` as one Python-list
representation, for example ``"['ORIGINAL', 'PRIMARY', 'P']"``. This module is
the single normalization authority used at download ingestion and media export.
It deliberately ignores private elements and standard VM=1 elements.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import pydicom
from pydicom.datadict import dictionary_VM
from pydicom.dataset import Dataset
from pydicom.tag import BaseTag


_TEXT_VRS = frozenset(
    {"AE", "AS", "CS", "DA", "DT", "LO", "LT", "PN", "SH", "ST", "TM", "UC", "UI", "UR", "UT"}
)


@dataclass(frozen=True)
class DicomVmNormalizationResult:
    """Outcome of a byte-level normalization attempt."""

    payload: bytes
    normalized_tags: tuple[BaseTag, ...] = ()
    error_type: str | None = None

    @property
    def changed(self) -> bool:
        return bool(self.normalized_tags)


class _NormalizationValidationError(ValueError):
    pass


def _vr_code(value: Any) -> str:
    return str(getattr(value, "value", value))


def _standard_tag_allows_multiple_values(tag: BaseTag) -> bool:
    if tag.is_private:
        return False
    try:
        return dictionary_VM(tag) != "1"
    except KeyError:
        return False


def _parse_collapsed_string_list(value: Any) -> list[str] | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) < 4 or not (text.startswith("[") and text.endswith("]")):
        return None
    try:
        parsed = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return None
    if not isinstance(parsed, list) or not parsed:
        return None
    if not all(isinstance(item, str) for item in parsed):
        return None
    return parsed


def normalize_collapsed_multivalue_dataset(ds: Dataset) -> tuple[BaseTag, ...]:
    """Restore malformed list-repr values for standard text tags with VM > 1.

    The dataset is mutated in place. Private elements and standard VM=1 values
    are never changed, even when their text resembles a Python list.
    """

    normalized: list[BaseTag] = []
    for element in ds.iterall():
        if _vr_code(element.VR) not in _TEXT_VRS:
            continue
        if not _standard_tag_allows_multiple_values(element.tag):
            continue
        parsed = _parse_collapsed_string_list(element.value)
        if parsed is None:
            continue
        element.value = parsed
        normalized.append(element.tag)
    return tuple(normalized)


def _identity_snapshot(ds: Dataset) -> dict[str, str]:
    return {
        keyword: str(ds.get(keyword) or "")
        for keyword in (
            "SOPInstanceUID",
            "StudyInstanceUID",
            "SeriesInstanceUID",
            "FrameOfReferenceUID",
        )
    }


def _transfer_syntax(ds: Dataset) -> str:
    file_meta = getattr(ds, "file_meta", None)
    return str(getattr(file_meta, "TransferSyntaxUID", "") or "")


def _is_recognizable_dicom(ds: Dataset) -> bool:
    file_meta = getattr(ds, "file_meta", None)
    return bool(
        ds.get("SOPClassUID")
        or getattr(file_meta, "MediaStorageSOPClassUID", None)
    )


def _normalized_tags_persisted(ds: Dataset, normalized_tags: tuple[BaseTag, ...]) -> bool:
    expected = set(normalized_tags)
    observed: dict[BaseTag, list[Any]] = {tag: [] for tag in expected}
    for element in ds.iterall():
        if element.tag in observed:
            observed[element.tag].append(element)
    return all(
        elements and all(element.VM > 1 for element in elements)
        for elements in observed.values()
    )


def normalize_dicom_bytes(payload: bytes) -> DicomVmNormalizationResult:
    """Normalize one Part-10 payload, failing open to the exact received bytes.

    Clean payloads are returned as the original ``bytes`` object. Parse, write,
    or validation failure returns the exact original bytes plus a non-sensitive
    exception type so download can continue without dropping clinical data.
    """

    try:
        ds = pydicom.dcmread(BytesIO(payload), force=True)
        if not _is_recognizable_dicom(ds):
            raise _NormalizationValidationError("unrecognized DICOM object")

        identity_before = _identity_snapshot(ds)
        transfer_syntax_before = _transfer_syntax(ds)
        normalized_tags = normalize_collapsed_multivalue_dataset(ds)
        if not normalized_tags:
            return DicomVmNormalizationResult(payload=payload)

        output = BytesIO()
        ds.save_as(output, write_like_original=True)
        normalized_payload = output.getvalue()

        check = pydicom.dcmread(BytesIO(normalized_payload), stop_before_pixels=True, force=True)
        if _identity_snapshot(check) != identity_before:
            raise _NormalizationValidationError("identity changed during normalization")
        if _transfer_syntax(check) != transfer_syntax_before:
            raise _NormalizationValidationError("transfer syntax changed during normalization")
        if not _normalized_tags_persisted(check, normalized_tags):
            raise _NormalizationValidationError("multi-value restoration did not persist")

        return DicomVmNormalizationResult(
            payload=normalized_payload,
            normalized_tags=normalized_tags,
        )
    except Exception as exc:
        return DicomVmNormalizationResult(
            payload=payload,
            error_type=type(exc).__name__,
        )
