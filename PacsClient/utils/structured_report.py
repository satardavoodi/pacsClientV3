"""Read-only, bounded DICOM SR text projection. No image decoding or Qt state.

File reads belong on a worker. Values are displayed literally, never interpreted
as HTML or instructions. Unsupported spatial/reference content is identified.
"""
from pathlib import Path

import pydicom


SR_CLASSES = frozenset("1.2.840.10008.5.1.4.1.1.88." + suffix
                       for suffix in ("11", "22", "33", "34"))
MAX_FILES = 256
MAX_BYTES = 64 * 1024 * 1024
MAX_TEXT = 200000


def _text(value):
    value = "" if value is None else str(value)
    return value if len(value) <= 4096 else value[:4096] + " [truncated]"


def _code(sequence, unit=False):
    if not sequence:
        return ""
    item = sequence[0]
    return _text((getattr(item, "CodeValue", "") if unit else "")
                 or getattr(item, "CodeMeaning", "") or getattr(item, "CodeValue", ""))


def render_report(ds):
    if str(getattr(ds, "SOPClassUID", "")) not in SR_CLASSES:
        raise ValueError("Unsupported structured report type")
    lines = ["DICOM Structured Report", "Completion: " + _text(getattr(ds, "CompletionFlag", "Unknown")),
             "Verification: " + _text(getattr(ds, "VerificationFlag", "Unknown")), ""]
    stack = [(ds, 0)]
    count = size = 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > 2048 or size >= MAX_TEXT:
            lines.append("[Content truncated: display limit reached]")
            break
        kind = str(getattr(node, "ValueType", ""))
        name = _code(getattr(node, "ConceptNameCodeSequence", ())) or kind or "Content"
        if kind == "NUM":
            values = getattr(node, "MeasuredValueSequence", ())
            if values:
                item = values[0]
                value = _text(getattr(item, "NumericValue", getattr(item, "FloatingPointValue", "")))
                value += " " + _code(getattr(item, "MeasurementUnitsCodeSequence", ()), unit=True)
            else:
                value = _code(getattr(node, "NumericValueQualifierCodeSequence", ())) or "Value unavailable"
        elif kind == "CODE":
            value = _code(getattr(node, "ConceptCodeSequence", ()))
        elif kind in ("TEXT", "PNAME", "DATE", "TIME", "DATETIME", "UIDREF"):
            attribute = {"TEXT": "TextValue", "PNAME": "PersonName", "DATE": "Date",
                         "TIME": "Time", "DATETIME": "DateTime", "UIDREF": "UID"}[kind]
            value = _text(getattr(node, attribute, ""))
        elif kind == "CONTAINER":
            value = ""
        else:
            value = "[" + (kind or "Reference") + ": not rendered in text view]"
        line = "  " * depth + name + (": " + value if value else "")
        lines.append(line)
        size += len(line)
        children = getattr(node, "ContentSequence", ())
        if depth >= 24 and children:
            lines.append("[Content truncated: nesting limit reached]")
        else:
            stack.extend((child, depth + 1) for child in reversed(children[:2048]))
            if len(children) > 2048:
                lines.append("[Content truncated: item limit reached]")
    return "\n".join(lines)


def load_reports(directory, study_uid, series_uid, *, cancelled=lambda: False):
    """Return immutable (document label, plain text) pairs, failing closed on identity.

    Never infer a patient's directory or series from a number. Callers provide the
    canonical persisted path and both UIDs; no database or network is consulted.
    """
    if cancelled():
        return ()
    if not directory or not study_uid or not series_uid:
        raise ValueError("Report identity or local folder is unavailable")
    documents = []
    total = 0
    paths = []
    for path in Path(directory).iterdir():
        if cancelled():
            return ()
        if path.is_file():
            paths.append(path)
            if len(paths) > MAX_FILES:
                raise ValueError("Report folder exceeds the document limit")
    for path in sorted(paths):
        if cancelled():
            return ()
        if path.suffix.lower() not in (".dcm", ".dicom", ""):
            continue
        total += path.stat().st_size
        if total > MAX_BYTES:
            raise ValueError("Report folder exceeds the size limit")
        ds = pydicom.dcmread(path, stop_before_pixels=True)
        if (str(getattr(ds, "StudyInstanceUID", "")) != study_uid
                or str(getattr(ds, "SeriesInstanceUID", "")) != series_uid):
            raise ValueError("Report identity does not match the selected series")
        content = render_report(ds)
        label = "Document " + str(len(documents) + 1)
        title = _code(getattr(ds, "ConceptNameCodeSequence", ()))
        documents.append((label + (" - " + title if title else ""), content))
    if not documents:
        raise ValueError("No local structured reports found; download the series first")
    return tuple(documents)
