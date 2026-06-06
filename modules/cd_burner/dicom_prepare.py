"""DICOM preparation for CD export: anonymization + transfer-syntax conversion.

Pure python/pydicom — no Qt. Used by the burn worker BEFORE DICOMDIR
creation: study folders are transformed into a prepared staging tree and
the existing DicomDirBuilder then runs on the prepared files unchanged.

Clinical-safety rules:
* A transcode failure NEVER drops image data — the file falls back to its
  previous (anonymized-if-requested, original-syntax) form with a warning.
* An anonymization failure NEVER leaks an identified file — the file is
  excluded from the export with a warning.
* Every converted file is validated by re-reading and decoding its pixel
  data before it is accepted.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from pydicom import dcmread
from pydicom.uid import (
    ExplicitVRLittleEndian,
    JPEG2000,
    JPEG2000Lossless,
    RLELossless,
    generate_uid,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output format choices (UI ↔ backend contract)
# ---------------------------------------------------------------------------

FORMAT_ORIGINAL = "original"          # keep transfer syntax as-is
FORMAT_UNCOMPRESSED = "uncompressed"  # Explicit VR Little Endian
FORMAT_LOSSLESS = "lossless"          # RLE Lossless
FORMAT_LOSSY = "lossy"                # JPEG 2000 (lossy, ~10:1)
FORMAT_JPEG2000 = "jpeg2000"          # JPEG 2000 Lossless

FORMAT_CHOICES = (
    (FORMAT_ORIGINAL, "Original"),
    (FORMAT_UNCOMPRESSED, "Uncompressed"),
    (FORMAT_LOSSLESS, "Lossless (RLE)"),
    (FORMAT_LOSSY, "Lossy (JPEG 2000)"),
    (FORMAT_JPEG2000, "JPEG 2000 (lossless)"),
)

LOSSY_COMPRESSION_RATIO = 10.0

# ---------------------------------------------------------------------------
# Anonymization policy (pragmatic basic-profile subset)
# ---------------------------------------------------------------------------

# Keywords blanked when present (identifying, not needed for viewing).
_BLANK_KEYWORDS = (
    "PatientBirthDate",
    "PatientBirthTime",
    "PatientAddress",
    "PatientTelephoneNumbers",
    "OtherPatientIDs",
    "OtherPatientNames",
    "PatientMotherBirthName",
    "MilitaryRank",
    "EthnicGroup",
    "PatientComments",
    "ReferringPhysicianName",
    "PerformingPhysicianName",
    "OperatorsName",
    "PhysiciansOfRecord",
    "RequestingPhysician",
    "InstitutionName",
    "InstitutionAddress",
    "InstitutionalDepartmentName",
    "StationName",
    "DeviceSerialNumber",
)

# UID keywords remapped consistently across the whole export.
_REMAP_UID_KEYWORDS = {
    "StudyInstanceUID",
    "SeriesInstanceUID",
    "SOPInstanceUID",
    "FrameOfReferenceUID",
    "ReferencedSOPInstanceUID",
    "ReferencedFrameOfReferenceUID",
    "SynchronizationFrameOfReferenceUID",
}


@dataclass
class PrepareResult:
    prepared_folders: List[str] = field(default_factory=list)
    passthrough: bool = False          # True → no work was needed (use originals)
    total_files: int = 0
    converted_files: int = 0
    fallback_files: int = 0            # transcode failed → previous form kept
    skipped_files: int = 0             # anonymization failed → excluded
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.total_files > 0 or self.passthrough


def _is_dicom_file(path: Path) -> bool:
    if path.suffix.lower() in (".dcm", ".dicom"):
        return True
    if path.suffix:
        return False
    try:
        dcmread(str(path), stop_before_pixels=True)
        return True
    except Exception:
        return False


def _iter_dicom_files(folder: Path):
    for root, _dirs, files in os.walk(str(folder)):
        for name in files:
            path = Path(root) / name
            if _is_dicom_file(path):
                yield path


class DicomPreparer:
    """Anonymize and/or transcode study folders into a prepared tree."""

    def __init__(
        self,
        anonymize: bool = False,
        seed: int = 1,
        dicom_format: str = FORMAT_ORIGINAL,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ):
        self.anonymize = bool(anonymize)
        self.seed = int(seed) if seed else 1
        self.dicom_format = dicom_format if dicom_format else FORMAT_ORIGINAL
        self.progress_callback = progress_callback
        self._uid_map: Dict[str, str] = {}
        self._cancelled = False

    # -- public ---------------------------------------------------------------

    def cancel(self):
        self._cancelled = True

    @property
    def needs_processing(self) -> bool:
        return self.anonymize or self.dicom_format != FORMAT_ORIGINAL

    def prepare(self, study_folders: List[str], output_root: str) -> PrepareResult:
        result = PrepareResult()

        if not self.needs_processing:
            result.prepared_folders = list(study_folders)
            result.passthrough = True
            return result

        out_root = Path(output_root)
        out_root.mkdir(parents=True, exist_ok=True)

        all_files: List[tuple] = []  # (src, dst)
        for index, folder in enumerate(study_folders):
            src_folder = Path(folder)
            dst_folder = out_root / f"STUDY{index:02d}"
            for src in _iter_dicom_files(src_folder):
                rel = src.relative_to(src_folder)
                all_files.append((src, dst_folder / rel))
            result.prepared_folders.append(str(dst_folder))

        total = len(all_files)
        for n, (src, dst) in enumerate(all_files):
            if self._cancelled:
                result.warnings.append("Preparation cancelled")
                break
            self._report(n, total, src.name)
            outcome = self._process_file(src, dst, result)
            if outcome:
                result.total_files += 1

        self._report(total, total, "done")
        return result

    # -- internals --------------------------------------------------------------

    def _report(self, n: int, total: int, name: str):
        if self.progress_callback and total:
            percent = int(n * 100 / total)
            self.progress_callback(percent, f"Preparing DICOM {n}/{total}: {name}")

    def _process_file(self, src: Path, dst: Path, result: PrepareResult) -> bool:
        """Returns True if a file was written for the export."""
        dst.parent.mkdir(parents=True, exist_ok=True)

        try:
            ds = dcmread(str(src))
        except Exception as exc:
            result.skipped_files += 1
            result.warnings.append(f"Unreadable DICOM skipped: {src.name} ({exc})")
            return False

        if self.anonymize:
            try:
                self._anonymize(ds)
            except Exception as exc:
                # NEVER fall back to the identified file.
                result.skipped_files += 1
                result.warnings.append(
                    f"Anonymization failed — file excluded: {src.name} ({exc})"
                )
                return False

        try:
            converted = self._transcode(ds)
            ds.save_as(str(dst), write_like_original=False)
            self._validate(dst)
            if converted:
                result.converted_files += 1
            return True
        except Exception as exc:
            logger.warning("Transcode failed for %s: %s — keeping previous form", src.name, exc)
            result.fallback_files += 1
            result.warnings.append(f"Format conversion failed, original syntax kept: {src.name}")
            return self._write_fallback(src, dst, result)

    def _write_fallback(self, src: Path, dst: Path, result: PrepareResult) -> bool:
        """Write the file without transcoding (re-anonymizing if required)."""
        try:
            if not self.anonymize:
                shutil.copy2(str(src), str(dst))
                return True
            ds = dcmread(str(src))
            self._anonymize(ds)  # uid map cached → consistent with the rest
            ds.save_as(str(dst), write_like_original=False)
            return True
        except Exception as exc:
            result.skipped_files += 1
            result.warnings.append(f"File excluded from export: {src.name} ({exc})")
            try:
                if dst.exists():
                    dst.unlink()
            except OSError:
                pass
            return False

    # -- anonymization ----------------------------------------------------------

    def _mapped_uid(self, original: str) -> str:
        new = self._uid_map.get(original)
        if new is None:
            new = generate_uid()
            self._uid_map[original] = new
        return new

    def _anonymize(self, ds):
        ds.PatientName = f"ANONYMOUS^{self.seed}"
        ds.PatientID = f"ANON{self.seed:04d}"
        if "AccessionNumber" in ds:
            ds.AccessionNumber = f"ANON{self.seed:04d}"

        for keyword in _BLANK_KEYWORDS:
            if keyword in ds:
                try:
                    setattr(ds, keyword, "")
                except Exception:
                    del ds[keyword]

        # Consistent UID remap (walks sequences too).
        for elem in ds.iterall():
            if elem.VR != "UI" or elem.keyword not in _REMAP_UID_KEYWORDS:
                continue
            value = elem.value
            if value is None or value == "":
                continue
            if isinstance(value, (list, tuple)) or value.__class__.__name__ == "MultiValue":
                elem.value = [self._mapped_uid(str(v)) for v in value]
            else:
                elem.value = self._mapped_uid(str(value))

        # file_meta must follow the dataset SOPInstanceUID
        try:
            ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
        except Exception:
            pass

    # -- transfer-syntax conversion ----------------------------------------------

    def _current_syntax(self, ds):
        try:
            return ds.file_meta.TransferSyntaxUID
        except Exception:
            return None

    def _ensure_uncompressed(self, ds) -> bool:
        syntax = self._current_syntax(ds)
        if syntax is None or not syntax.is_compressed:
            return False
        ds.decompress()
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        return True

    def _transcode(self, ds) -> bool:
        """Convert in place. Returns True if the syntax was changed."""
        fmt = self.dicom_format
        if fmt == FORMAT_ORIGINAL:
            return False

        if "PixelData" not in ds:
            return False  # SR/PR etc. — nothing to convert

        if fmt == FORMAT_UNCOMPRESSED:
            return self._ensure_uncompressed(ds)

        if fmt == FORMAT_LOSSLESS:
            syntax = self._current_syntax(ds)
            if syntax == RLELossless:
                return False
            self._ensure_uncompressed(ds)
            ds.compress(RLELossless)
            return True

        if fmt in (FORMAT_JPEG2000, FORMAT_LOSSY):
            return self._to_jpeg2000(ds, lossy=(fmt == FORMAT_LOSSY))

        raise ValueError(f"Unknown DICOM format option: {fmt}")

    def _to_jpeg2000(self, ds, lossy: bool) -> bool:
        from openjpeg.utils import encode_array
        from pydicom.encaps import encapsulate

        syntax = self._current_syntax(ds)
        if not lossy and syntax == JPEG2000Lossless:
            return False

        self._ensure_uncompressed(ds)
        arr = ds.pixel_array

        samples = int(getattr(ds, "SamplesPerPixel", 1) or 1)
        frames = int(getattr(ds, "NumberOfFrames", 1) or 1)
        photometric = 1 if samples >= 3 else 2  # sRGB / greyscale
        ratios = [LOSSY_COMPRESSION_RATIO] if lossy else None
        bits_stored = int(getattr(ds, "BitsStored", 0) or 0) or None

        if frames > 1:
            frame_list = [arr[i] for i in range(frames)]
        else:
            frame_list = [arr]

        encoded = [
            encode_array(
                frame,
                bits_stored=bits_stored,
                photometric_interpretation=photometric,
                compression_ratios=ratios,
            )
            for frame in frame_list
        ]

        ds.PixelData = encapsulate(encoded)
        ds["PixelData"].is_undefined_length = True
        ds.file_meta.TransferSyntaxUID = JPEG2000 if lossy else JPEG2000Lossless

        if samples >= 3:
            # J2K with MCT — keep RGB photometric; readers handle the MCT flag.
            ds.PlanarConfiguration = 0

        if lossy:
            ds.LossyImageCompression = "01"
            ds.LossyImageCompressionRatio = LOSSY_COMPRESSION_RATIO
            ds.LossyImageCompressionMethod = "ISO_15444_1"
        return True

    # -- validation -----------------------------------------------------------------

    def _validate(self, path: Path):
        check = dcmread(str(path))
        if "PixelData" in check:
            _ = check.pixel_array  # raises if the written file cannot decode
